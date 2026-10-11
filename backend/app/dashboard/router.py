"""Pilot dashboard: the 9 indicators with baseline, target and current value.

A value is "demo" when it is computed from the activity of the demo, and "illustrative" when
the prototype cannot measure it (it says so in each indicator).
"""
from __future__ import annotations

from statistics import median

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.decisions.audit import Actor, get_actor
from app.models import Alert, Authorization, Decision, FuelRequest
from app.seed import loader
from app.timeutil import NBSP, fmt_num, iso, now, to_local

router = APIRouter(tags=["dashboard"])

STATUS_LABELS = {"met": "Cumple la meta", "at_risk": "Cerca de la meta", "not_met": "No cumple",
                 "no_data": "Sin datos todavía"}
SOURCE_LABELS = {"demo": "Calculado con la actividad de la demo", "illustrative": "Valor ilustrativo"}


def _pct(value: float) -> str:
    return f"{fmt_num(value * 100, 0)}{NBSP}%"


def _minutes(value: float) -> str:
    return f"{fmt_num(value, 1)} min"


def _indicator(key: str, name: str, baseline: str, target: str, value: float | None, display: str, unit: str,
               source: str, status: str, note: str, target_value: float | None = None,
               higher_is_better: bool = True) -> dict:
    return {"key": key, "name": name, "baseline": baseline, "target": target, "current_value": value,
            "current_display": display, "unit": unit, "target_value": target_value,
            "higher_is_better": higher_is_better, "source": source, "source_label": SOURCE_LABELS[source],
            "status": status, "status_label": STATUS_LABELS[status], "note": note}


def _status(value: float, target: float, higher_is_better: bool, margin: float) -> str:
    if (value >= target) if higher_is_better else (value <= target):
        return "met"
    if (value >= target - margin) if higher_is_better else (value <= target + margin):
        return "at_risk"
    return "not_met"


@router.get("/dashboard", summary="Tablero del piloto: indicadores, contexto y decisión al cierre")
def dashboard(db: Session = Depends(get_db), actor: Actor = Depends(get_actor)) -> dict:
    requests = db.scalars(select(FuelRequest)).all()
    decisions = db.execute(select(Decision, FuelRequest).join(FuelRequest, FuelRequest.id == Decision.request_id)).all()
    authorizations = db.scalars(select(Authorization)).all()
    alerts = db.scalars(select(Alert)).all()
    indicators: list[dict] = []

    # 1. Attention time: first message -> decision.
    minutes = [(to_local(d.decided_at) - to_local(r.created_at)).total_seconds() / 60 for d, r in decisions]
    if minutes:
        med = median(minutes)
        within = sum(1 for m in minutes if m <= 10) / len(minutes)
        status = "met" if med <= 3 and within >= 0.9 else ("at_risk" if med <= 6 else "not_met")
        indicators.append(_indicator(
            "attention_time", "Tiempo de atención", "2 semanas de marcas de tiempo de WhatsApp; referencia del caso: 3 a 20 min",
            "Mediana de 3 min o menos y 9 de cada 10 en 10 min o menos", round(med, 2), _minutes(med), "min", "demo", status,
            f"Mediana de {len(minutes)} solicitudes decididas en la demo; {_pct(within)} en 10 min o menos.", 3, False))
    else:
        indicators.append(_indicator(
            "attention_time", "Tiempo de atención", "2 semanas de marcas de tiempo de WhatsApp; referencia del caso: 3 a 20 min",
            "Mediana de 3 min o menos y 9 de cada 10 en 10 min o menos", 2.6, _minutes(2.6), "min", "illustrative", "met",
            "Todavía no hay decisiones en la demo: se muestra un valor ilustrativo.", 3, False))

    # 2. Solved in one click.
    if decisions:
        share = sum(1 for d, _ in decisions if d.one_click) / len(decisions)
        indicators.append(_indicator(
            "one_click", "Resueltas en un clic", "Hoy 0 %: todo es manual",
            "60 % o más; sin intervención desde la etapa 3, con la autoaprobación", round(share, 3), _pct(share), "%",
            "demo", _status(share, 0.6, True, 0.15),
            f"{sum(1 for d, _ in decisions if d.one_click)} de {len(decisions)} decisiones de la demo.", 0.6))
    else:
        indicators.append(_indicator(
            "one_click", "Resueltas en un clic", "Hoy 0 %: todo es manual",
            "60 % o más; sin intervención desde la etapa 3, con la autoaprobación", 0.64, _pct(0.64), "%",
            "illustrative", "met", "Todavía no hay decisiones en la demo: se muestra un valor ilustrativo.", 0.6))

    # 3. Complete at the first attempt.
    finished = [r for r in requests if r.ready_at is not None and r.driver_id is not None]
    if finished:
        share = sum(1 for r in finished if not r.missing) / len(finished)
        indicators.append(_indicator(
            "complete_first_try", "Completas al primer intento", "Muestra de 100 conversaciones etiquetadas",
            "90 % o más", round(share, 3), _pct(share), "%", "demo", _status(share, 0.9, True, 0.1),
            f"{sum(1 for r in finished if not r.missing)} de {len(finished)} solicitudes llegaron completas al técnico.", 0.9))
    else:
        indicators.append(_indicator(
            "complete_first_try", "Completas al primer intento", "Muestra de 100 conversaciones etiquetadas",
            "90 % o más", 0.92, _pct(0.92), "%", "illustrative", "met",
            "Todavía no hay solicitudes en la demo: se muestra un valor ilustrativo.", 0.9))

    # 4. Reconciliation with the provider.
    if authorizations:
        reconciled = [a for a in authorizations if a.reconciled_transaction_id is not None]
        share = len(reconciled) / len(authorizations)
        within = sum(1 for a in reconciled if a.amount and abs(a.reconciled_difference or 0) / a.amount <= 0.05)
        indicators.append(_indicator(
            "reconciliation", "Conciliación con el proveedor", "Hoy no es medible: no hay registro de lo autorizado",
            "100 % conciliado en 24 h; diferencia de 5 % o menos en el 95 % de los casos", round(share, 3), _pct(share), "%",
            "demo", "met" if share >= 1 else ("at_risk" if share >= 0.8 else "not_met"),
            (f"{len(reconciled)} de {len(authorizations)} autorizaciones de la demo conciliadas; {within} con diferencia de "
             "5 % o menos. Carga el CSV de ejemplo para conciliar."), 1.0))
    else:
        indicators.append(_indicator(
            "reconciliation", "Conciliación con el proveedor", "Hoy no es medible: no hay registro de lo autorizado",
            "100 % conciliado en 24 h; diferencia de 5 % o menos en el 95 % de los casos", None, "Sin autorizaciones", "%",
            "demo", "no_data", "Se calcula cuando haya autorizaciones en la demo y se cargue el archivo del proveedor.", 1.0))

    # 5. High-priority alerts: reviewed within 48 h and precision.
    high = [a for a in alerts if a.priority == "high"]
    reviewed = [a for a in alerts if a.status == "reviewed"]
    confirmed = sum(1 for a in reviewed if a.review_result == "confirmed")
    precision = confirmed / len(reviewed) if reviewed else None
    overdue = sum(1 for a in high if a.status == "open" and to_local(a.due_at) < now())
    on_time = sum(1 for a in high if a.status == "reviewed" and a.reviewed_at and to_local(a.reviewed_at) <= to_local(a.due_at))
    if precision is None:
        status = "no_data"
    elif precision >= 0.5 and overdue == 0:
        status = "met"
    elif precision >= 0.3:
        status = "at_risk"
    else:
        status = "not_met"
    indicators.append(_indicator(
        "high_priority_alerts", "Alertas de prioridad alta",
        "Prueba con datos históricos: 1.682 tanqueos con alerta en 90 días, 53 de prioridad alta",
        "Revisadas en 48 h; precisión de 50 % o más", round(precision, 3) if precision is not None else None,
        f"Precisión {_pct(precision)}" if precision is not None else "Sin alertas revisadas", "%", "demo", status,
        (f"{confirmed} confirmadas de {len(reviewed)} revisadas. Prioridad alta: {len(high)} en total, {on_time} revisadas "
         f"a tiempo y {overdue} vencidas."), 0.5))

    # 6. Integrations (the prototype has no real integrations to measure).
    indicators.append(_indicator(
        "integrations", "Integraciones", "Se mide desde el día 1", "Flujo de 99,5 % o más", 0.997, f"99,7{NBSP}%", "%",
        "illustrative", "met", "En el prototipo las integraciones están simuladas: no hay disponibilidad real que medir.",
        0.995))

    # 7. Technician workload: wait in queue until the decision.
    waits = [(to_local(d.decided_at) - to_local(r.ready_at or r.created_at)).total_seconds() / 60 for d, r in decisions]
    if waits:
        avg = sum(waits) / len(waits)
        indicators.append(_indicator(
            "technician_load", "Carga del técnico", "Solicitudes por hora pico y espera en cola",
            "Espera en pico menor a 5 min", round(avg, 2), _minutes(avg), "min", "demo", _status(avg, 5, False, 2),
            f"Espera promedio en cola de {len(waits)} solicitudes de la demo, de lista a decidida.", 5, False))
    else:
        indicators.append(_indicator(
            "technician_load", "Carga del técnico", "Solicitudes por hora pico y espera en cola",
            "Espera en pico menor a 5 min", 3.4, _minutes(3.4), "min", "illustrative", "met",
            "Todavía no hay decisiones en la demo: se muestra un valor ilustrativo.", 5, False))

    # 8. Use of the assistant.
    if requests:
        indicators.append(_indicator(
            "assistant_usage", "Uso del asistente", "Se mide desde el día 1", "80 % o más de las solicitudes", 1.0,
            _pct(1.0), "%", "demo", "met",
            f"Las {len(requests)} solicitudes de la demo entraron por el asistente; en el piloto se compara con las que "
            "llegan al número actual.", 0.8))
    else:
        indicators.append(_indicator(
            "assistant_usage", "Uso del asistente", "Se mide desde el día 1", "80 % o más de las solicitudes", 0.84,
            _pct(0.84), "%", "illustrative", "met", "Todavía no hay solicitudes en la demo: se muestra un valor ilustrativo.",
            0.8))

    # 9. Continuity.
    indicators.append(_indicator(
        "continuity", "Continuidad", "Se mide desde el día 1", "Cero vehículos sin combustible por causa del sistema",
        0, "0 incidentes", "incidentes", "illustrative", "met",
        "Ninguna regla rechaza ni bloquea: si algo falla se vuelve al procedimiento actual con cupo de emergencia.",
        0, False))

    return {
        "generated_at": iso(now()),
        "seed_date": loader.seed_date(db),
        "pilot": {"zone": "Córdoba (CARIBE COR)", "vehicles": 59, "refuels_per_day": 66, "services_per_day": 467,
                  "weeks": 6, "note": "Cifras de la zona en los datos reales; el prototipo carga 24 vehículos ilustrativos."},
        "activity": {"requests": len(requests), "decisions": len(decisions), "authorizations": len(authorizations),
                     "alerts_open": sum(1 for a in alerts if a.status == "open"),
                     "alerts_reviewed": len(reviewed)},
        "indicators": indicators,
        "context": {
            "requests_per_day": 200, "minutes_per_request_today": 20, "hours_today": 66.7, "shift_hours": 24,
            "minutes_per_request_target": 3, "hours_target": 10,
            "title": "De 66,7 a 10 horas de gestión al día",
            "text": ("Hoy, con 200 solicitudes al día de 20 minutos, la gestión suma 66,7 horas diarias frente a 24 horas "
                     "de turnos; con 3 minutos por solicitud bajaría a 10 horas."),
        },
        "decision": {
            "title": "Decisión al cierre de las 6 semanas",
            "options": [
                {"key": "expand", "label": "Ampliar",
                 "text": ("Mediana de 3 min o menos, 90 % o más de solicitudes completas, 60 % o más en un clic, 80 % o más "
                          "por el asistente, precisión de alertas de 50 % o más y ningún vehículo sin combustible.")},
                {"key": "adjust", "label": "Ajustar",
                 "text": ("Cualquier otro resultado, como una mediana entre 3 y 6 min, precisión entre 30 y 50 % o adopción "
                          "entre 50 y 80 %: se corrige y se extiende 4 semanas.")},
                {"key": "stop", "label": "Detener",
                 "text": ("Cualquier vehículo sin combustible atribuible al sistema, un tiempo peor que la línea base después "
                          "de 4 semanas o una adopción menor al 50 %.")},
            ],
            "note": "Los indicadores se leen juntos: de nada sirve bajar el tiempo si aparecen vehículos sin combustible.",
        },
    }
