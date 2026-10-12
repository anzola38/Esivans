"""Single ledger per vehicle (VEH160: Terpel + GoPass) and the pilot dashboard with its 9 indicators,
their baseline and target, and how the values change with the activity of the demo."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.timeutil import at, now, today

from .helpers import (COORD, FINANCE, SUPPORT, TECH, authorize, authorized_green, decide, imported, in_review, plain,
                      play, queue, review, sample_csv, vehicle_alert)

KEYS = ["attention_time", "one_click", "complete_first_try", "reconciliation", "high_priority_alerts", "integrations",
        "technician_load", "assistant_usage", "continuity"]


def _ledger(client, ref: str = "VEH160", headers: dict = TECH) -> dict:
    response = client.get(f"/api/vehicles/{ref}/ledger", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _normalized(value):
    """Texts come with non-breaking spaces before % and units; compare them with normal spaces."""
    if isinstance(value, str):
        return plain(value)
    if isinstance(value, list):
        return [_normalized(v) for v in value]
    if isinstance(value, dict):
        return {k: _normalized(v) for k, v in value.items()}
    return value


def _board(client, headers: dict = COORD) -> dict:
    response = client.get("/api/dashboard", headers=headers)
    assert response.status_code == 200, response.text
    return _normalized(response.json())


def _indicators(client) -> dict:
    return {i["key"]: i for i in _board(client)["indicators"]}


# ----------------------------------------------------------------------------- single ledger: VEH160

def test_veh160_gopass_alone_computes_783_km_per_gallon(fresh):
    comparison = _ledger(fresh)["comparison"]
    assert comparison["km"] == 4803
    assert comparison["gopass_only"] == {"gallons": 6.135, "efficiency": 782.9, "unit": "km/gal"}
    assert round(comparison["gopass_only"]["efficiency"]) == 783
    assert comparison["hidden_loads"] == 34 and comparison["hidden_cng_loads"] == 34
    assert comparison["single_ledger"] == {"gallons": 6.135, "cng_m3": 313.6, "gallon_equivalent": 65.3,
                                           "efficiency": 73.5, "unit": "km/gal-eq", "cng_m3_per_gallon": 5.3}
    assert comparison["explanation"] == (
        "GoPass solo calcula 4.803 km ÷ 6,135 gal = 783 km por galón, porque no ve sus 34 cargas de gas en Terpel "
        "(313,6 m³). En el libro único son 73,5 km por galón equivalente.")
    assert comparison["from"] == at(today() - timedelta(days=80), "07:10").isoformat()
    assert comparison["to"] == at(today() - timedelta(days=6), "10:33").isoformat()


def test_veh160_comparison_matches_its_own_entries(fresh):
    ledger = _ledger(fresh)
    entries = list(reversed(ledger["entries"]))          # oldest first
    gopass = [e for e in entries if e["provider"] == "gopass"]
    assert [e["quantity"] for e in gopass] == [6.0, 6.135] and [e["odometer"] for e in gopass] == [28930, 33733]
    assert gopass[1]["odometer"] - gopass[0]["odometer"] == 4803
    between = [e for e in entries if gopass[0]["timestamp"] < e["timestamp"] < gopass[1]["timestamp"]]
    assert len(between) == 34 and {e["provider"] for e in between} == {"terpel"} and {e["product"] for e in between} == {"GNV"}
    assert round(sum(e["quantity"] for e in between), 1) == 313.6
    assert round(4803 / 6.135) == 783


def test_veh160_ledger_joins_both_providers_newest_first(fresh):
    ledger = _ledger(fresh)
    assert ledger["vehicle"]["code"] == "VEH160" and ledger["vehicle"]["plate"] == "ZZA160"
    assert ledger["vehicle"]["provider"] == "gopass" and ledger["vehicle"]["payment_method"] == "tarjeta"
    assert ledger["vehicle"]["flags"] == ["V06"]
    assert ledger["flags"] == [{"code": "V06", "name": "Usa los dos proveedores", "points": 1, "version": 1,
                                "explanation": "Carga con Terpel y con GoPass: ningún proveedor ve todo su consumo"}]
    summary = ledger["summary"]
    assert summary["refuels"] == 41 == len(ledger["entries"]) and summary["amount"] == 1345244
    assert summary["providers"] == [
        {"provider": "terpel", "provider_label": "Terpel", "refuels": 39, "amount": 1150720},
        {"provider": "gopass", "provider_label": "GoPass", "refuels": 2, "amount": 194524}]
    assert summary["amount"] == sum(e["amount"] for e in ledger["entries"])
    timestamps = [e["timestamp"] for e in ledger["entries"]]
    assert timestamps == sorted(timestamps, reverse=True)
    newest = ledger["entries"][0]
    assert newest["provider"] == "terpel" and newest["odometer"] == 33998 and newest["km_since_previous"] == 145
    assert newest["timestamp"] == at(today() - timedelta(days=2), "17:05").isoformat()
    assert ledger["stats"]["providers"] == ["gopass", "terpel"] and ledger["stats"]["refuels_90d"] == 41
    assert ledger["efficiency"]["value"] == 49.8 and ledger["efficiency"]["status"] == "normal"


def test_vehicle_can_be_found_by_code_plate_id_or_public_id(fresh):
    by_code = _ledger(fresh, "VEH160")
    vehicle = by_code["vehicle"]
    for ref in ("veh160", "ZZA160", str(vehicle["id"]), vehicle["public_id"]):
        assert _ledger(fresh, ref)["vehicle"]["code"] == "VEH160", ref


def test_unknown_vehicle_is_a_404(fresh):
    response = fresh.get("/api/vehicles/VEH000/ledger", headers=TECH)
    assert response.status_code == 404
    assert response.json() == {"detail": "No existe el vehículo VEH000.", "code": "vehicle_not_found"}


def test_vehicle_with_a_single_provider_has_no_comparison(fresh):
    ledger = _ledger(fresh, "VEH901")
    assert ledger["comparison"] is None
    assert [p["provider"] for p in ledger["summary"]["providers"]] == ["terpel"]
    assert ledger["summary"]["refuels"] == 31 and ledger["entries"][0]["odometer"] == 48210


def test_ledger_km_between_refuels_skips_readings_without_odometer(fresh):
    entries = _ledger(fresh, "VEH905")["entries"]
    without = [e for e in entries if e["odometer"] is None]
    assert len(without) == 1 and without[0]["km_since_previous"] is None
    assert all(e["km_since_previous"] is None or e["km_since_previous"] >= 0 for e in entries)


@pytest.mark.parametrize("headers", [TECH, COORD, FINANCE, SUPPORT])
def test_every_role_can_read_vehicles_and_ledgers(fresh, headers):
    vehicles = fresh.get("/api/vehicles", headers=headers)
    assert vehicles.status_code == 200 and len(vehicles.json()["items"]) == 24
    assert _ledger(fresh, "VEH160", headers)["comparison"]["km"] == 4803


# ----------------------------------------------------------------------------- dashboard: structure

def test_dashboard_has_the_nine_indicators_in_order_with_baseline_and_target(fresh):
    board = _board(fresh)
    indicators = board["indicators"]
    assert [i["key"] for i in indicators] == KEYS
    assert [i["name"] for i in indicators] == [
        "Tiempo de atención", "Resueltas en un clic", "Completas al primer intento", "Conciliación con el proveedor",
        "Alertas de prioridad alta", "Integraciones", "Carga del técnico", "Uso del asistente", "Continuidad"]
    assert [i["baseline"] for i in indicators] == [
        "2 semanas de marcas de tiempo de WhatsApp; referencia del caso: 3 a 20 min",
        "Hoy 0 %: todo es manual",
        "Muestra de 100 conversaciones etiquetadas",
        "Hoy no es medible: no hay registro de lo autorizado",
        "Prueba con datos históricos: 1.682 tanqueos con alerta en 90 días, 53 de prioridad alta",
        "Se mide desde el día 1", "Solicitudes por hora pico y espera en cola", "Se mide desde el día 1",
        "Se mide desde el día 1"]
    assert [i["target"] for i in indicators] == [
        "Mediana de 3 min o menos y 9 de cada 10 en 10 min o menos",
        "60 % o más; sin intervención desde la etapa 3, con la autoaprobación",
        "90 % o más",
        "100 % conciliado en 24 h; diferencia de 5 % o menos en el 95 % de los casos",
        "Revisadas en 48 h; precisión de 50 % o más",
        "Flujo de 99,5 % o más", "Espera en pico menor a 5 min", "80 % o más de las solicitudes",
        "Cero vehículos sin combustible por causa del sistema"]
    assert [i["target_value"] for i in indicators] == [3, 0.6, 0.9, 1.0, 0.5, 0.995, 5, 0.8, 0]
    assert [i["higher_is_better"] for i in indicators] == [False, True, True, True, True, True, False, True, False]
    assert [i["unit"] for i in indicators] == ["min", "%", "%", "%", "%", "%", "min", "%", "incidentes"]
    for indicator in indicators:
        assert indicator["source"] in ("demo", "illustrative") and indicator["note"]
        assert indicator["source_label"] == {"demo": "Calculado con la actividad de la demo",
                                             "illustrative": "Valor ilustrativo"}[indicator["source"]]
        assert indicator["status_label"] == {"met": "Cumple la meta", "at_risk": "Cerca de la meta",
                                             "not_met": "No cumple", "no_data": "Sin datos todavía"}[indicator["status"]]
    assert abs((now() - datetime.fromisoformat(board["generated_at"])).total_seconds()) < 60
    assert board["seed_date"] == today().isoformat()


def test_dashboard_right_after_the_reset_shows_illustrative_values(fresh):
    board = _board(fresh)
    assert board["activity"] == {"requests": 0, "decisions": 0, "authorizations": 0, "alerts_open": 11,
                                 "alerts_reviewed": 8}
    values = {i["key"]: (i["current_value"], plain(i["current_display"]), i["source"], i["status"])
              for i in board["indicators"]}
    assert values == {
        "attention_time": (2.6, "2,6 min", "illustrative", "met"),
        "one_click": (0.64, "64 %", "illustrative", "met"),
        "complete_first_try": (0.92, "92 %", "illustrative", "met"),
        "reconciliation": (None, "Sin autorizaciones", "demo", "no_data"),
        "high_priority_alerts": (0.5, "Precisión 50 %", "demo", "at_risk"),
        "integrations": (0.997, "99,7 %", "illustrative", "met"),
        "technician_load": (3.4, "3,4 min", "illustrative", "met"),
        "assistant_usage": (0.84, "84 %", "illustrative", "met"),
        "continuity": (0, "0 incidentes", "illustrative", "met"),
    }
    alerts_note = next(i for i in board["indicators"] if i["key"] == "high_priority_alerts")["note"]
    assert alerts_note == "4 confirmadas de 8 revisadas. Prioridad alta: 6 en total, 2 revisadas a tiempo y 2 vencidas."


def test_dashboard_context_goes_from_66_7_to_10_hours(fresh):
    context = _board(fresh)["context"]
    assert context["requests_per_day"] == 200 and context["minutes_per_request_today"] == 20
    assert context["hours_today"] == 66.7 == round(200 * 20 / 60, 1)
    assert context["minutes_per_request_target"] == 3 and context["hours_target"] == 10 == 200 * 3 / 60
    assert context["shift_hours"] == 24
    assert context["title"] == "De 66,7 a 10 horas de gestión al día"
    assert context["text"] == ("Hoy, con 200 solicitudes al día de 20 minutos, la gestión suma 66,7 horas diarias frente "
                               "a 24 horas de turnos; con 3 minutos por solicitud bajaría a 10 horas.")


def test_dashboard_pilot_figures_and_the_decision_at_the_end_of_the_six_weeks(fresh):
    board = _board(fresh)
    assert board["pilot"]["zone"] == "Córdoba (CARIBE COR)" and board["pilot"]["vehicles"] == 59
    assert board["pilot"]["refuels_per_day"] == 66 and board["pilot"]["services_per_day"] == 467
    assert board["pilot"]["weeks"] == 6
    decision = board["decision"]
    assert decision["title"] == "Decisión al cierre de las 6 semanas"
    assert [(o["key"], o["label"]) for o in decision["options"]] == [("expand", "Ampliar"), ("adjust", "Ajustar"),
                                                                     ("stop", "Detener")]
    expand, adjust, stop = (o["text"] for o in decision["options"])
    assert expand == ("Mediana de 3 min o menos, 90 % o más de solicitudes completas, 60 % o más en un clic, 80 % o más "
                      "por el asistente, precisión de alertas de 50 % o más y ningún vehículo sin combustible.")
    assert "mediana entre 3 y 6 min" in adjust and "se corrige y se extiende 4 semanas" in adjust
    assert "vehículo sin combustible atribuible al sistema" in stop and "adopción menor al 50 %" in stop
    assert decision["note"] == ("Los indicadores se leen juntos: de nada sirve bajar el tiempo si aparecen vehículos "
                                "sin combustible.")


@pytest.mark.parametrize("headers", [TECH, COORD, FINANCE, SUPPORT])
def test_every_role_can_read_the_dashboard(fresh, headers):
    assert [i["key"] for i in _board(fresh, headers)["indicators"]] == KEYS


# ----------------------------------------------------------------------------- dashboard: it moves with the activity

def test_first_one_click_approval_turns_the_indicators_into_demo_values(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    board = _board(fresh)
    assert board["activity"]["requests"] == 1 and board["activity"]["decisions"] == 1
    assert board["activity"]["authorizations"] == 0
    indicators = {i["key"]: i for i in board["indicators"]}
    assert indicators["one_click"]["source"] == "demo" and indicators["one_click"]["current_value"] == 1.0
    assert plain(indicators["one_click"]["current_display"]) == "100 %" and indicators["one_click"]["status"] == "met"
    assert indicators["one_click"]["note"] == "1 de 1 decisiones de la demo."
    assert indicators["attention_time"]["source"] == "demo" and indicators["attention_time"]["status"] == "met"
    assert 0 <= indicators["attention_time"]["current_value"] < 1
    assert plain(indicators["attention_time"]["note"]) == ("Mediana de 1 solicitudes decididas en la demo; "
                                                           "100 % en 10 min o menos.")
    assert indicators["complete_first_try"]["current_value"] == 1.0
    assert indicators["complete_first_try"]["note"] == "1 de 1 solicitudes llegaron completas al técnico."
    assert indicators["technician_load"]["source"] == "demo" and indicators["technician_load"]["status"] == "met"
    assert indicators["assistant_usage"]["source"] == "demo" and indicators["assistant_usage"]["current_value"] == 1.0
    assert indicators["reconciliation"]["status"] == "no_data"          # approved, but nothing enabled yet
    # These two are never measured by the prototype.
    assert indicators["integrations"]["source"] == "illustrative" and indicators["continuity"]["source"] == "illustrative"


def test_one_click_share_drops_as_decisions_need_a_reason(fresh):
    green = in_review(fresh, "GREEN")
    decide(fresh, green["id"], action="approve")
    assert _indicators(fresh)["one_click"]["current_value"] == 1.0

    yellow = in_review(fresh, "VEH015")
    decide(fresh, yellow["id"], action="approve", reason="Kilometraje corregido y confirmado")
    one_click = _indicators(fresh)["one_click"]
    assert one_click["current_value"] == 0.5 and plain(one_click["current_display"]) == "50 %"
    assert one_click["status"] == "at_risk" and one_click["note"] == "1 de 2 decisiones de la demo."

    red = in_review(fresh, "VEH199")
    decide(fresh, red["id"], action="adjust", amount=20000, reason="Apoyo nocturno confirmado por radio")
    one_click = _indicators(fresh)["one_click"]
    assert one_click["current_value"] == 0.333 and plain(one_click["current_display"]) == "33 %"
    assert one_click["status"] == "not_met" and one_click["note"] == "1 de 3 decisiones de la demo."
    # After the demo script the six criteria of "expand" are no longer all met: one click is below 60 %.
    assert one_click["current_value"] < one_click["target_value"]


def test_reconciliation_indicator_follows_authorizations_and_the_provider_file(fresh):
    authorized_green(fresh)
    pending = _indicators(fresh)["reconciliation"]
    assert pending["current_value"] == 0.0 and plain(pending["current_display"]) == "0 %" and pending["status"] == "not_met"
    assert pending["note"].startswith("0 de 1 autorizaciones de la demo conciliadas; 0 con diferencia de 5 % o menos.")

    imported(fresh, sample_csv(fresh))
    done = _indicators(fresh)["reconciliation"]
    assert done["current_value"] == 1.0 and plain(done["current_display"]) == "100 %" and done["status"] == "met"
    assert done["note"].startswith("1 de 1 autorizaciones de la demo conciliadas; 1 con diferencia de 5 % o menos.")
    assert _board(fresh)["activity"] == {"requests": 1, "decisions": 1, "authorizations": 1, "alerts_open": 16,
                                         "alerts_reviewed": 8}


def test_alert_indicator_follows_the_reviews(fresh):
    before = _indicators(fresh)["high_priority_alerts"]
    assert before["current_value"] == 0.5 and before["status"] == "at_risk"       # 2 high-priority alerts are overdue
    review(fresh, vehicle_alert(fresh, "VEH015")["id"], "confirmed", "Se revisó con el conductor.")
    after = _indicators(fresh)["high_priority_alerts"]
    assert after["current_value"] == 0.556 and plain(after["current_display"]) == "Precisión 56 %"
    assert after["note"] == "5 confirmadas de 9 revisadas. Prioridad alta: 6 en total, 2 revisadas a tiempo y 1 vencidas."
    assert _board(fresh)["activity"]["alerts_open"] == 10 and _board(fresh)["activity"]["alerts_reviewed"] == 9


def test_alert_indicator_is_met_when_precision_holds_and_nothing_is_overdue(fresh):
    review(fresh, vehicle_alert(fresh, "VEH015")["id"], "confirmed", "Se revisó con el conductor.")
    refuel = next(a for a in fresh.get("/api/alerts?kind=refuel&status=open", headers=COORD).json()["items"]
                  if a["vehicle"]["code"] == "VEH906")
    review(fresh, refuel["id"], "confirmed", "Venta recuperada sin soporte.")
    indicator = _indicators(fresh)["high_priority_alerts"]
    assert indicator["current_value"] == 0.6 and indicator["status"] == "met"
    assert indicator["note"].endswith("0 vencidas.")


def test_request_escalated_by_the_sla_lowers_complete_at_first_try(fresh, clock):
    play(fresh, "GREEN", steps=2)
    clock.advance(minutes=11)
    queue(fresh, None)
    indicator = _indicators(fresh)["complete_first_try"]
    assert indicator["source"] == "demo" and indicator["current_value"] == 0.0 and indicator["status"] == "not_met"
    assert indicator["note"] == "0 de 1 solicitudes llegaron completas al técnico."


def test_slow_decision_moves_attention_time_out_of_the_target(fresh, clock):
    request = in_review(fresh, "GREEN")
    clock.advance(minutes=8)
    decide(fresh, request["id"], action="approve")
    indicators = _indicators(fresh)
    attention = indicators["attention_time"]
    assert 8.0 <= attention["current_value"] < 8.2 and attention["status"] == "not_met"
    assert plain(attention["current_display"]).startswith("8,")
    load = indicators["technician_load"]
    assert 8.0 <= load["current_value"] < 8.2 and load["status"] == "not_met"      # more than 5 + 2 minutes in queue


def test_authorization_does_not_count_as_a_decision_twice(fresh):
    request = in_review(fresh, "GREEN")
    decide(fresh, request["id"], action="approve")
    authorize(fresh, request["id"], "TER-TABLERO-1")
    activity = _board(fresh)["activity"]
    assert activity["requests"] == 1 and activity["decisions"] == 1 and activity["authorizations"] == 1
