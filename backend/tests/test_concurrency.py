"""Real races: two people acting on the same request at the same instant (not one after the other).

Each call runs in its own thread and both are released together by a barrier, so the two
transactions really overlap in PostgreSQL. Exactly one must win.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select

from app.models import Authorization, Decision, InboundMessage

from .helpers import COORD, TECH, WA, audit_items, authorize, conversation, decide, detail, in_review, outbox, post_webhook

ROUNDS = 3


def race(*calls):
    """Runs the calls at the same time and returns their responses in the order given."""
    barrier = Barrier(len(calls))

    def run(call):
        barrier.wait(timeout=10)
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=30) for future in futures]


@pytest.mark.parametrize("attempt", range(ROUNDS))
def test_two_technicians_deciding_at_the_same_time_leave_a_single_decision(fresh, db, attempt):
    request = in_review(fresh, "GREEN")
    responses = race(
        lambda: decide(fresh, request["id"], action="approve", headers=TECH),
        lambda: decide(fresh, request["id"], action="reject", reason="Otro criterio", headers=COORD),
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()["decision"]
    loser = next(r for r in responses if r.status_code == 409).json()
    assert loser["code"] == "already_decided"
    assert loser["decision"]["id"] == winner["id"] and loser["decision"]["decided_by"] == winner["decided_by"]
    assert winner["decided_by"] in loser["detail"]

    assert db.scalar(select(func.count()).select_from(Decision)) == 1
    after = detail(fresh, request["id"])
    assert after["decision"]["id"] == winner["id"] and after["decision"]["action"] == winner["action"]
    assert after["status"] == ("rejected" if winner["action"] == "reject" else "in_review")
    assert len(audit_items(fresh, f"request_id={request['id']}&action=decision")) == 1
    assert [e["event_type"] for e in outbox(fresh)].count("DecisionRecorded") == 1
    # The driver is told about a rejection only if the rejection won.
    kinds = [m["kind"] for m in conversation(fresh, WA["GREEN"])["messages"]]
    assert kinds.count("rejection") == (1 if winner["action"] == "reject" else 0)


@pytest.mark.parametrize("attempt", range(ROUNDS))
def test_two_enablements_at_the_same_time_authorize_only_once(fresh, db, attempt):
    request = in_review(fresh, "GREEN")
    assert decide(fresh, request["id"], action="approve").status_code == 200
    responses = race(
        lambda: authorize(fresh, request["id"], "TER-CARRERA-A", headers=TECH),
        lambda: authorize(fresh, request["id"], "TER-CARRERA-B", headers=COORD),
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r for r in responses if r.status_code == 200).json()["authorization"]
    assert next(r for r in responses if r.status_code == 409).json()["code"] == "already_authorized"

    assert db.scalar(select(func.count()).select_from(Authorization)) == 1
    assert detail(fresh, request["id"])["authorization"]["reference"] == winner["reference"]
    messages = [m for m in conversation(fresh, WA["GREEN"])["messages"] if m["kind"] == "authorization"]
    assert len(messages) == 1 and winner["reference"] in messages[0]["text"]
    assert len(audit_items(fresh, "action=authorization")) == 1


@pytest.mark.parametrize("attempt", range(ROUNDS))
def test_same_whatsapp_message_delivered_twice_at_once_is_stored_once(fresh, db, attempt):
    payload = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"field": "messages", "value": {
        "messages": [{"from": WA["GREEN"], "id": f"wamid.RACE{attempt}", "timestamp": "1791729600", "type": "text",
                      "text": {"body": "Hola, necesito tanquear"}}]}}]}]}
    responses = race(lambda: post_webhook(fresh, payload), lambda: post_webhook(fresh, payload))
    assert [r.status_code for r in responses] == [200, 200]
    assert sorted((r.json()["received"], r.json()["duplicates"]) for r in responses) == [(0, 1), (1, 0)]
    assert db.scalar(select(func.count()).select_from(InboundMessage)) == 1
    chat = conversation(fresh, WA["GREEN"])
    assert [m["kind"] for m in chat["messages"]].count("greeting") == 1
    assert [e["event_type"] for e in outbox(fresh)].count("RequestReceived") == 1

