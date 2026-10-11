"""Versioned rules stored in `rule_version`: read the current ones and create new versions."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.decisions.audit import Actor, audit
from app.errors import ApiError
from app.models import Alert, RuleVersion
from app.rules.catalog import CATALOG, CATALOG_BY_CODE, STAGE_LABELS, TREATMENT_LABELS
from app.rules.engine import ActiveRule, active_from_def
from app.timeutil import iso, now


def seed_rules(db: Session, author: str = "Calibración inicial (análisis de 90 días)") -> None:
    for rule in CATALOG:
        db.add(RuleVersion(code=rule.code, version=1, threshold=dict(rule.params), points=rule.points,
                           author=author, change_reason="Umbral inicial de la hoja Reglas y umbrales"))


def _latest_rows(db: Session) -> dict[str, RuleVersion]:
    rows = db.scalars(select(RuleVersion).order_by(RuleVersion.code, RuleVersion.version)).all()
    return {row.code: row for row in rows}  # the last one per code wins


def current_rules(db: Session) -> dict[str, ActiveRule]:
    latest = _latest_rows(db)
    rules: dict[str, ActiveRule] = {}
    for rule in CATALOG:
        row = latest.get(rule.code)
        rules[rule.code] = (active_from_def(rule, row.threshold, row.points, row.version) if row
                            else active_from_def(rule))
    return rules


def rules_version_label(db: Session) -> str:
    """Catalog version: v1 is the initial calibration and each threshold change adds one."""
    changes = db.scalar(select(func.count()).select_from(RuleVersion).where(RuleVersion.version > 1)) or 0
    return f"v{1 + changes}"


def _precision(db: Session) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for alert in db.scalars(select(Alert).where(Alert.status == "reviewed")).all():
        for code in alert.rule_codes or []:
            entry = stats.setdefault(code, {"reviewed": 0, "confirmed": 0})
            entry["reviewed"] += 1
            if alert.review_result == "confirmed":
                entry["confirmed"] += 1
    return stats


def catalog_payload(db: Session) -> list[dict]:
    rows = db.scalars(select(RuleVersion).order_by(RuleVersion.code, RuleVersion.version.desc())).all()
    history: dict[str, list[RuleVersion]] = {}
    for row in rows:
        history.setdefault(row.code, []).append(row)
    precision = _precision(db)
    payload = []
    for rule in CATALOG:
        versions = history.get(rule.code, [])
        current = versions[0] if versions else None
        stat = precision.get(rule.code, {"reviewed": 0, "confirmed": 0})
        payload.append({
            "code": rule.code,
            "name": rule.name,
            "stage": rule.stage,
            "stage_label": STAGE_LABELS[rule.stage],
            "treatment": rule.treatment,
            "treatment_label": TREATMENT_LABELS[rule.treatment],
            "threshold_text": rule.threshold_text,
            "threshold": current.threshold if current else dict(rule.params),
            "param_labels": rule.param_labels,
            "points": current.points if current else rule.points,
            "version": current.version if current else 1,
            "valid_from": iso(current.valid_from) if current else None,
            "author": current.author if current else None,
            "reviewed": stat["reviewed"],
            "confirmed": stat["confirmed"],
            "precision": round(stat["confirmed"] / stat["reviewed"], 3) if stat["reviewed"] else None,
            "history": [{
                "version": v.version, "threshold": v.threshold, "points": v.points,
                "valid_from": iso(v.valid_from), "author": v.author, "change_reason": v.change_reason,
            } for v in versions],
        })
    return payload


def update_rule(db: Session, code: str, threshold: dict | None, points: int | None,
                reason: str | None, actor: Actor) -> RuleVersion:
    """Creates a new version; the previous ones are never modified nor deleted."""
    code = code.upper()
    rule = CATALOG_BY_CODE.get(code)
    if rule is None:
        raise ApiError(404, f"La regla {code} no existe.", "rule_not_found")
    current = _latest_rows(db).get(code)
    base = dict(current.threshold if current else rule.params)
    new_threshold = dict(base)
    for key, value in (threshold or {}).items():
        if key not in rule.params:
            raise ApiError(422, f"La regla {code} no tiene el parámetro '{key}'.", "unknown_param",
                           {"allowed_params": list(rule.params)})
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ApiError(422, f"El parámetro '{key}' debe ser un número mayor o igual a 0.", "invalid_param")
        new_threshold[key] = value
    new_points = current.points if current else rule.points
    if points is not None:
        if not 0 <= points <= 5:
            raise ApiError(422, "Los puntos deben estar entre 0 y 5.", "invalid_points")
        new_points = points
    old_points = current.points if current else rule.points
    if new_threshold == base and new_points == old_points:
        raise ApiError(422, "No hay cambios frente a la versión vigente.", "no_changes")
    row = RuleVersion(code=code, version=(current.version if current else 0) + 1, threshold=new_threshold,
                      points=new_points, valid_from=now(), author=actor.user, change_reason=reason)
    db.add(row)
    db.flush()
    audit(db, actor, "rule.updated", "rule_version", row.id,
          summary=f"{code} {rule.name}: versión {row.version}" + (f". Motivo: {reason}" if reason else ""),
          before={"version": current.version if current else None, "threshold": base, "points": old_points},
          after={"version": row.version, "threshold": new_threshold, "points": new_points})
    return row
