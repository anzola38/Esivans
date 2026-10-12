"""Versioned rules: only the coordinator changes a threshold, each change is a new version that keeps
the previous one, the next evaluation uses it and stores the version, and old alerts keep theirs."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text

from app.timeutil import now

from .helpers import (COORD, FINANCE, SUPPORT, TECH, alerts, audit_items, detail, imported, in_review, play, put_rule,
                      rule, sample_csv)


def _catalog(client, headers: dict = COORD) -> dict:
    response = client.get("/api/rules", headers=headers)
    assert response.status_code == 200
    return response.json()


# ----------------------------------------------------------------------------- catalog

def test_catalog_lists_the_24_rules_in_version_1(fresh):
    catalog = _catalog(fresh)
    assert catalog["rules_version"] == "v1"
    items = catalog["items"]
    assert [r["code"] for r in items] == ([f"R{n:02d}" for n in range(1, 15)] + ["C01", "C02"]
                                          + [f"V{n:02d}" for n in range(1, 9)])
    assert all(r["version"] == 1 and len(r["history"]) == 1 for r in items)
    assert all(r["author"] == "Calibración inicial (análisis de 90 días)" for r in items)
    assert all(r["history"][0]["change_reason"] == "Umbral inicial de la hoja Reglas y umbrales" for r in items)
    stages = {r["code"]: r["stage"] for r in items}
    assert all(stages[f"R{n:02d}"] == "before_authorization" for n in range(1, 11))
    assert all(stages[code] == "reconciliation" for code in ("R11", "R12", "R13", "R14", "C01", "C02"))
    assert all(stages[f"V{n:02d}"] == "vehicle" for n in range(1, 9))


def test_catalog_item_describes_threshold_points_and_treatment(fresh):
    r05 = rule(fresh, "R05")
    assert r05["name"] == "Recarga sin recorrido" and r05["points"] == 3
    assert r05["threshold"] == {"min_km": 30, "load_fraction": 0.5}
    assert r05["param_labels"] == {"min_km": "Recorrido mínimo (km)", "load_fraction": "Fracción de la carga típica"}
    assert r05["threshold_text"] == "Menos de 30 km desde la carga del mismo combustible y 50 % o más de su carga típica"
    assert r05["stage_label"] == "Antes de autorizar" and r05["treatment"] == "review" and r05["treatment_label"] == "Revisión"
    r13 = rule(fresh, "R13")
    assert r13["threshold"] == {"amount_cop": 2000} and r13["treatment"] == "automatic" and r13["stage_label"] == "Al conciliar"
    assert rule(fresh, "R01")["threshold"] == {} and rule(fresh, "V06")["threshold"] == {}


@pytest.mark.parametrize("headers, can_edit", [(COORD, True), (TECH, False), (FINANCE, False), (SUPPORT, False)])
def test_only_the_coordinator_sees_the_catalog_as_editable(fresh, headers, can_edit):
    catalog = _catalog(fresh, headers)
    assert catalog["can_edit"] is can_edit and len(catalog["items"]) == 24


# ----------------------------------------------------------------------------- PUT as coordinator

def test_coordinator_change_creates_version_2_and_keeps_version_1(fresh, db):
    response = put_rule(fresh, "R05", threshold={"min_km": 25}, reason="Ajuste del comité")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rules_version"] == "v2"
    changed = body["rule"]
    assert changed["code"] == "R05" and changed["version"] == 2 and changed["points"] == 3
    assert changed["threshold"] == {"min_km": 25, "load_fraction": 0.5}        # the other parameter is carried over
    assert changed["author"] == "Andres Molina"
    assert abs((now() - datetime.fromisoformat(changed["valid_from"])).total_seconds()) < 60
    assert [(h["version"], h["threshold"]["min_km"], h["author"], h["change_reason"]) for h in changed["history"]] == [
        (2, 25, "Andres Molina", "Ajuste del comité"),
        (1, 30, "Calibración inicial (análisis de 90 días)", "Umbral inicial de la hoja Reglas y umbrales")]
    # Both rows exist in the table: nothing was updated in place.
    rows = db.execute(text("SELECT version, threshold->>'min_km' FROM rule_version WHERE code = 'R05' ORDER BY version")).all()
    assert [tuple(r) for r in rows] == [(1, "30"), (2, "25")]
    assert db.scalar(text("SELECT count(*) FROM rule_version")) == 25
    assert fresh.get("/api/health").json()["rules_version"] == "v2"
    assert rule(fresh, "R05") == changed and rule(fresh, "R06")["version"] == 1


def test_points_can_change_without_touching_the_threshold(fresh):
    body = put_rule(fresh, "R08", points=3, reason="Pesa más en el piloto").json()
    assert body["rule"]["version"] == 2 and body["rule"]["points"] == 3
    assert body["rule"]["threshold"] == {"window_h": 24} and body["rule"]["history"][1]["points"] == 2


def test_each_change_adds_one_to_the_catalog_version(fresh):
    assert put_rule(fresh, "R05", threshold={"min_km": 25}).json()["rules_version"] == "v2"
    assert put_rule(fresh, "R05", threshold={"min_km": 20}).json()["rule"]["version"] == 3
    third = put_rule(fresh, "R13", threshold={"amount_cop": 3000}).json()
    assert third["rules_version"] == "v4" and third["rule"]["version"] == 2
    assert [h["threshold"]["min_km"] for h in rule(fresh, "R05")["history"]] == [20, 25, 30]


def test_rule_code_is_case_insensitive(fresh):
    assert put_rule(fresh, "r05", threshold={"min_km": 25}).json()["rule"]["code"] == "R05"


# ----------------------------------------------------------------------------- validation

def test_unknown_rule_is_a_404(fresh):
    response = put_rule(fresh, "R99", threshold={"x": 1})
    assert response.status_code == 404
    assert response.json() == {"detail": "La regla R99 no existe.", "code": "rule_not_found"}
    assert _catalog(fresh)["rules_version"] == "v1"


@pytest.mark.parametrize("body, code", [
    ({"threshold": {"min_meters": 25}}, "unknown_param"),
    ({"threshold": {"min_km": -1}}, "invalid_param"),
    ({"points": 6}, "invalid_points"),
    ({"points": -1}, "invalid_points"),
    ({"threshold": {"min_km": 30}}, "no_changes"),
    ({"threshold": {"min_km": 30, "load_fraction": 0.5}, "points": 3}, "no_changes"),
    ({}, "no_changes"),
    ({"reason": "Solo el motivo"}, "no_changes"),
    ({"threshold": {"min_km": "treinta"}}, "validation_error"),
])
def test_invalid_changes_are_rejected_and_create_no_version(fresh, body, code):
    response = put_rule(fresh, "R05", **body)
    assert response.status_code == 422 and response.json()["code"] == code
    current = rule(fresh, "R05")
    assert current["version"] == 1 and current["threshold"] == {"min_km": 30, "load_fraction": 0.5}
    assert _catalog(fresh)["rules_version"] == "v1"
    assert audit_items(fresh, "action=rule.updated") == []


def test_unknown_parameter_error_lists_the_allowed_ones(fresh):
    body = put_rule(fresh, "R09", threshold={"hours": 2}).json()
    assert body["detail"] == "La regla R09 no tiene el parámetro 'hours'."
    assert body["allowed_params"] == ["night_start_h", "night_end_h", "window_h"]


# ----------------------------------------------------------------------------- other roles

@pytest.mark.parametrize("headers, label", [(TECH, "Técnico de Control y Monitoreo"),
                                            (FINANCE, "Administración y finanzas"), (SUPPORT, "Soporte")])
def test_other_roles_get_403_and_the_attempt_stays_in_the_audit_log(fresh, headers, label):
    response = put_rule(fresh, "R05", headers, threshold={"min_km": 25}, reason="Prueba")
    assert response.status_code == 403
    assert response.json() == {
        "detail": f"Tu rol ({label}) no puede hacer esta acción. Roles permitidos: Coordinador.",
        "code": "forbidden", "allowed_roles": ["coordinator"]}
    assert rule(fresh, "R05")["version"] == 1 and _catalog(fresh)["rules_version"] == "v1"
    denied = audit_items(fresh, "action=access.denied")
    assert len(denied) == 1
    assert denied[0]["actor"] == headers["X-Demo-User"] and denied[0]["role"] == headers["X-Demo-Role"]
    assert denied[0]["summary"] == f"{label} intentó PUT /api/rules/R05 sin permiso"
    assert denied[0]["after"] == {"method": "PUT", "path": "/api/rules/R05", "allowed_roles": ["coordinator"]}
    assert audit_items(fresh, "action=rule.updated") == []


# ----------------------------------------------------------------------------- the next evaluation uses the new threshold

def test_next_evaluation_uses_the_new_threshold_and_stores_the_version(fresh):
    put_rule(fresh, "R05", threshold={"min_km": 20}, reason="22 km ya cuenta como recorrido")
    request = detail(fresh, play(fresh, "VEH199")["request"]["id"])
    # 22 km is no longer under the threshold: R05 stops firing and the 7 points become 4.
    assert request["rule_codes"] == ["R08", "R09"] and request["points"] == 4 and request["traffic_light"] == "red"
    assert request["evaluation"]["rules_version"] == "v2"
    checks = {c["code"]: c for c in request["evaluation"]["checks"]}
    assert checks["R05"]["triggered"] is False and checks["R05"]["version"] == 2 and checks["R08"]["version"] == 1
    evaluated = next(a for a in request["audit"] if a["action"] == "request.evaluated")
    assert evaluated["after"]["rules_version"] == "v2" and evaluated["summary"].endswith("reglas v2")


def test_request_evaluated_before_the_change_keeps_its_version_and_result(fresh):
    before = in_review(fresh, "VEH199")
    assert before["evaluation"]["rules_version"] == "v1" and before["points"] == 7
    put_rule(fresh, "R05", threshold={"min_km": 20}, reason="22 km ya cuenta como recorrido")
    after = detail(fresh, before["id"])
    assert after["evaluation"] == before["evaluation"]
    assert after["rule_codes"] == ["R05", "R08", "R09"] and after["points"] == 7
    assert next(c for c in after["evaluation"]["checks"] if c["code"] == "R05")["version"] == 1


def test_new_points_change_the_traffic_light_of_the_next_request(fresh):
    put_rule(fresh, "R02", points=4, reason="Prueba de puntos")
    request = in_review(fresh, "VEH015")
    assert request["rule_codes"] == ["R02"] and request["points"] == 4 and request["traffic_light"] == "red"
    assert request["evaluation"]["reasons"][0]["version"] == 2 and request["evaluation"]["rules_version"] == "v2"


def test_wider_night_band_reaches_the_green_case(fresh):
    put_rule(fresh, "R09", threshold={"night_start_h": 9, "window_h": 0}, reason="Prueba de la franja")
    request = in_review(fresh, "GREEN")
    assert request["rule_codes"] == ["R09"] and request["points"] == 2 and request["traffic_light"] == "yellow"
    assert request["evaluation"]["reasons"][0]["explanation"] == "tanqueo a las 09:40 sin servicios cercanos"


def test_odometer_tolerance_of_r03_is_read_when_the_photo_arrives(fresh):
    # With 40 km per day the 142 km of the green case are no longer possible in 16 hours.
    put_rule(fresh, "R03", threshold={"max_km_per_day": 40}, reason="Prueba del odómetro")
    chat = play(fresh, "GREEN", steps=3)
    evidence = detail(fresh, chat["request"]["id"])["evidence"]
    assert evidence["odometer_read"] == 48352 and evidence["error_type"] is not None


# ----------------------------------------------------------------------------- old alerts keep their version

def test_old_alerts_keep_v1_and_new_ones_carry_the_new_version(fresh):
    seed_alerts = {a["id"]: a for a in alerts(fresh)["items"]}
    put_rule(fresh, "R13", threshold={"amount_cop": 5000}, reason="Ajuste del comité")
    put_rule(fresh, "V01", points=1, reason="Prueba")
    after = {a["id"]: a for a in alerts(fresh)["items"]}
    for alert_id, alert in seed_alerts.items():
        assert after[alert_id]["rules_version"] == "v1"
        assert after[alert_id]["points"] == alert["points"] and after[alert_id]["reasons"] == alert["reasons"]
        assert after[alert_id]["priority"] == alert["priority"]

    result = imported(fresh, sample_csv(fresh))
    assert result["rules_version"] == "v3"
    assert {d["rules_version"] for d in result["deviations"]} == {"v3"}
    everything = alerts(fresh)["items"]
    assert {a["rules_version"] for a in everything if a["kind"] != "reconciliation"} == {"v1"}
    assert {a["rules_version"] for a in everything if a["kind"] == "reconciliation"} == {"v3"}


def test_reset_brings_the_rules_back_to_version_1(fresh):
    put_rule(fresh, "R05", threshold={"min_km": 25}, reason="Ajuste del comité")
    put_rule(fresh, "R08", points=3)
    assert fresh.post("/api/dev/reset").status_code == 200
    catalog = _catalog(fresh)
    assert catalog["rules_version"] == "v1"
    assert all(r["version"] == 1 and len(r["history"]) == 1 for r in catalog["items"])
    assert rule(fresh, "R05")["threshold"] == {"min_km": 30, "load_fraction": 0.5} and rule(fresh, "R08")["points"] == 2
