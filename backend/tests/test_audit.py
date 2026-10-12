"""Audit log: every sensitive action leaves who, what, before, after and the rules version, and the
PostgreSQL trigger rejects UPDATE and DELETE on `audit_log` (checked with direct SQL on the test database)."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import AuditLog
from app.timeutil import now

from .helpers import (COORD, FINANCE, SUPPORT, TECH, audit_items, authorized_green, decide, import_csv, in_review,
                      put_rule, review, sample_csv, vehicle_alert)


def _rows(db) -> list[tuple]:
    return [tuple(r) for r in db.execute(text("SELECT id, actor, action, summary FROM audit_log ORDER BY id")).all()]


# ----------------------------------------------------------------------------- append-only trigger

def test_trigger_rejects_update_of_one_row(fresh, db):
    before = _rows(db)
    assert len(before) >= 2
    with pytest.raises(DBAPIError) as error:
        db.execute(text("UPDATE audit_log SET actor = 'otro', summary = 'editado' WHERE id = 1"))
    db.rollback()
    assert "audit_log es de solo insercion: UPDATE no esta permitido" in str(error.value)
    assert _rows(db) == before


def test_trigger_rejects_update_of_every_column_of_every_row(fresh, db):
    before = _rows(db)
    for statement in ("UPDATE audit_log SET action = 'x'", "UPDATE audit_log SET before = NULL, after = NULL",
                      "UPDATE audit_log SET created_at = now() - interval '1 year'"):
        with pytest.raises(DBAPIError) as error:
            db.execute(text(statement))
        db.rollback()
        assert "solo insercion" in str(error.value)
    assert _rows(db) == before


def test_trigger_rejects_delete(fresh, db):
    before = _rows(db)
    for statement in ("DELETE FROM audit_log WHERE id = 1", "DELETE FROM audit_log"):
        with pytest.raises(DBAPIError) as error:
            db.execute(text(statement))
        db.rollback()
        assert "audit_log es de solo insercion: DELETE no esta permitido" in str(error.value)
    assert _rows(db) == before


def test_trigger_rejects_changes_made_through_the_orm(fresh, db):
    row = db.scalars(select(AuditLog).order_by(AuditLog.id)).first()
    row_id, original = row.id, row.summary
    row.summary = "reescrito"
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()
    assert db.scalar(text("SELECT summary FROM audit_log WHERE id = :id"), {"id": row_id}) == original
    db.delete(db.get(AuditLog, row_id))
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()
    assert db.scalar(text("SELECT count(*) FROM audit_log WHERE id = :id"), {"id": row_id}) == 1


def test_update_that_matches_no_row_does_not_fail_and_changes_nothing(fresh, db):
    before = _rows(db)
    result = db.execute(text("UPDATE audit_log SET actor = 'otro' WHERE id = -1"))
    db.commit()
    assert result.rowcount == 0 and _rows(db) == before


def test_insert_is_still_allowed(fresh, db):
    count = len(_rows(db))
    db.execute(text("INSERT INTO audit_log (actor, action, entity, created_at) "
                    "VALUES ('prueba', 'test.insert', 'test', now())"))
    db.commit()
    rows = _rows(db)
    assert len(rows) == count + 1 and rows[-1][1:3] == ("prueba", "test.insert")


def test_trigger_is_defined_for_update_and_delete_on_each_row(fresh, db):
    events = db.execute(text(
        "SELECT event_manipulation, action_timing, action_orientation FROM information_schema.triggers "
        "WHERE event_object_table = 'audit_log' AND trigger_name = 'audit_log_no_update_delete' "
        "ORDER BY event_manipulation")).all()
    assert [tuple(e) for e in events] == [("DELETE", "BEFORE", "ROW"), ("UPDATE", "BEFORE", "ROW")]


def test_api_reports_the_log_as_append_only_and_has_no_route_to_change_it(fresh):
    assert fresh.get("/api/audit", headers=TECH).json()["append_only"] is True
    for method in (fresh.put, fresh.patch, fresh.delete, fresh.post):
        assert method("/api/audit", headers=COORD).status_code == 405
    assert fresh.delete("/api/audit/1", headers=COORD).status_code == 404


# ----------------------------------------------------------------------------- every sensitive action is recorded

def test_full_flow_leaves_the_trace_of_each_step_in_order(fresh):
    body = authorized_green(fresh, "TER-TRAZA-1")
    trail = body["audit"]
    assert [a["action"] for a in trail] == ["request.received", "evidence.read", "request.evaluated",
                                            "decision.approve", "authorization.enabled"]
    assert [a["actor"] for a in trail] == ["asistente", "asistente", "sistema", "Laura Gomez", "Laura Gomez"]
    assert [a["role"] for a in trail] == [None, None, None, "technician", "technician"]
    assert all(a["request_id"] == body["id"] for a in trail)
    assert [a["id"] for a in trail] == sorted(a["id"] for a in trail)
    for entry in trail:
        assert abs((now() - datetime.fromisoformat(entry["created_at"])).total_seconds()) < 60


def test_evidence_and_evaluation_entries_keep_what_was_read_and_the_rules_version(fresh):
    trail = {a["action"]: a for a in in_review(fresh, "VEH199")["audit"]}
    read = trail["evidence.read"]
    assert read["summary"] == "Foto del tablero leída: 195.406 km, nivel ¼ de tanque (25 %)"
    assert read["after"]["odometer_read"] == 195406 and read["after"]["fuel_level"] == 0.25
    assert read["after"]["confidence"] == {"odometer_km": 0.96, "fuel_level": 0.88} and len(read["after"]["photo_hash"]) == 64
    evaluated = trail["request.evaluated"]
    assert evaluated["summary"] == "Semáforo rojo con 7 puntos (R05, R08, R09); valor sugerido $10.000; reglas v1"
    assert evaluated["after"] == {"traffic_light": "red", "points": 7, "rules": ["R05", "R08", "R09"],
                                  "suggested_amount": 10000, "rules_version": "v1"}
    assert trail["request.received"]["summary"] == "Solicitud de Wilson Darío Hoyos para VEH199 (ZZA199) recibida por WhatsApp"


def test_one_click_approval_entry_has_actor_before_after_and_rules_version(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    entry = audit_items(fresh, f"request_id={request['id']}&action=decision")[0]
    assert entry["actor"] == "Laura Gomez" and entry["role"] == "technician"
    assert entry["role_label"] == "Técnico de Control y Monitoreo"
    assert entry["action"] == "decision.approve" and entry["entity"] == "decision" and entry["entity_id"] == "1"
    assert entry["summary"] == "Laura Gomez aprobó la solicitud por $90.000 en un clic"
    assert entry["before"] == {"suggested_amount": 90000, "traffic_light": "green", "points": 0, "rules_version": "v1"}
    assert entry["after"] == {"action": "approve", "amount": 90000, "reason": None, "one_click": True}


def test_rejection_entry_keeps_the_reason(fresh):
    request = in_review(fresh, "VEH015")
    decide(fresh, request["id"], action="reject", reason="Sin servicio que lo respalde", headers=COORD)
    entry = audit_items(fresh, "action=decision.reject")[0]
    assert entry["actor"] == "Andres Molina" and entry["role"] == "coordinator"
    assert entry["summary"] == "Andres Molina rechazó la solicitud. Motivo: Sin servicio que lo respalde"
    assert entry["before"]["traffic_light"] == "yellow" and entry["before"]["rules_version"] == "v1"
    assert entry["after"] == {"action": "reject", "amount": None, "reason": "Sin servicio que lo respalde",
                              "one_click": False}


def test_alert_review_entry_has_before_and_after(fresh):
    alert = vehicle_alert(fresh, "VEH129")
    review(fresh, alert["id"], "confirmed", "Se envía a revisión mecánica.")
    entry = audit_items(fresh, "action=alert.reviewed")[0]
    assert entry["actor"] == "Andres Molina" and entry["role"] == "coordinator"
    assert entry["entity"] == "alert" and entry["entity_id"] == str(alert["id"])
    assert entry["before"] == {"status": "open", "review_result": None, "review_comment": None, "reviewed_by": None}
    assert entry["after"] == {"status": "reviewed", "review_result": "confirmed",
                              "review_comment": "Se envía a revisión mecánica."}
    assert entry["summary"] == ("Andres Molina revisó la alerta V01, V05, V08 de VEH129: Confirmado. "
                                "Se envía a revisión mecánica.")


def test_rule_change_entry_has_both_versions(fresh):
    put_rule(fresh, "R05", threshold={"min_km": 25}, reason="Ajuste del comité")
    entry = audit_items(fresh, "action=rule.updated")[0]
    assert entry["actor"] == "Andres Molina" and entry["role"] == "coordinator" and entry["entity"] == "rule_version"
    assert entry["before"] == {"version": 1, "threshold": {"min_km": 30, "load_fraction": 0.5}, "points": 3}
    assert entry["after"] == {"version": 2, "threshold": {"min_km": 25, "load_fraction": 0.5}, "points": 3}
    assert entry["summary"] == "R05 Recarga sin recorrido: versión 2. Motivo: Ajuste del comité"


def test_import_entry_has_the_counts(fresh):
    import_csv(fresh, sample_csv(fresh), FINANCE, filename="terpel_ejemplo.csv")
    entry = audit_items(fresh, "action=import.executed")[0]
    assert entry["actor"] == "Paola Ruiz" and entry["role"] == "finance" and entry["entity"] == "import_batch"
    assert entry["after"] == {"rows": 10, "imported": 10, "duplicates": 0, "rejected": 0, "alerts": 5}
    assert entry["summary"] == ("Paola Ruiz cargó terpel_ejemplo.csv de Terpel: 10 nuevas, 0 duplicadas, "
                                "0 rechazadas, 5 alertas")


def test_denied_attempts_are_recorded_even_though_the_call_fails(fresh):
    request = in_review(fresh, "GREEN")
    alert = vehicle_alert(fresh, "VEH129")
    assert decide(fresh, request["id"], headers=SUPPORT, action="approve").status_code == 403
    assert review(fresh, alert["id"], headers=FINANCE).status_code == 403
    assert put_rule(fresh, "R08", TECH, threshold={"window_h": 12}).status_code == 403
    assert import_csv(fresh, sample_csv(fresh), SUPPORT).status_code == 403
    denied = audit_items(fresh, "action=access.denied")
    assert [(d["actor"], d["role"], d["after"]["method"], d["after"]["path"]) for d in reversed(denied)] == [
        ("Soporte TI", "support", "POST", f"/api/requests/{request['id']}/decision"),
        ("Paola Ruiz", "finance", "PATCH", f"/api/alerts/{alert['id']}"),
        ("Laura Gomez", "technician", "PUT", "/api/rules/R08"),
        ("Soporte TI", "support", "POST", "/api/integrations/terpel/imports"),
    ]
    assert denied[1]["after"]["allowed_roles"] == ["coordinator"]
    assert denied[1]["summary"] == "Técnico de Control y Monitoreo intentó PUT /api/rules/R08 sin permiso"
    assert all(d["entity"] == "endpoint" and d["before"] is None for d in denied)


def test_reset_and_seed_load_are_recorded(fresh):
    items = audit_items(fresh)
    assert [i["action"] for i in items] == ["demo.reset", "seed.loaded"]
    seed = items[1]
    assert seed["actor"] == "sistema" and seed["role"] is None and seed["role_label"] is None
    assert seed["after"]["vehicles"] == 24 and seed["after"]["transactions"] == 878
    assert seed["after"]["eom_services"] == 1534 and seed["after"]["alerts"] == 19 and seed["after"]["rules"] == 24


# ----------------------------------------------------------------------------- reading the log

def test_log_is_listed_from_newest_to_oldest_and_can_be_filtered(fresh):
    body = authorized_green(fresh)
    everything = audit_items(fresh)
    assert [i["id"] for i in everything] == sorted((i["id"] for i in everything), reverse=True)
    of_request = audit_items(fresh, f"request_id={body['id']}")
    assert len(of_request) == 5 and all(i["request_id"] == body["id"] for i in of_request)
    assert [i["action"] for i in audit_items(fresh, "action=decision")] == ["decision.approve"]
    assert [i["action"] for i in audit_items(fresh, "entity=authorization")] == ["authorization.enabled"]
    assert len(audit_items(fresh, "limit=2")) == 2
    assert audit_items(fresh, "request_id=999") == []


def test_log_limit_is_validated(fresh):
    for value in (0, 1001):
        response = fresh.get(f"/api/audit?limit={value}", headers=COORD)
        assert response.status_code == 422 and response.json()["code"] == "validation_error"


@pytest.mark.parametrize("headers", [TECH, COORD, FINANCE, SUPPORT])
def test_every_role_can_read_the_log(fresh, headers):
    response = fresh.get("/api/audit", headers=headers)
    assert response.status_code == 200 and len(response.json()["items"]) == 2
