"""Reconciliation: import provider transactions (idempotent), compare with what was authorized
and open alerts. Also the alert payloads and their review.
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.decisions.audit import Actor, audit, emit
from app.errors import ApiError
from app.ledger import service as ledger
from app.models import Alert, Authorization, FuelRequest, ImportBatch, ProviderTransaction, Vehicle
from app.rules.catalog import CATALOG_BY_CODE, PRIORITY_LABELS, priority
from app.rules.engine import ActiveRule, evaluate_transaction
from app.rules.repository import current_rules, rules_version_label
from app.timeutil import BOGOTA, fmt_cop, fmt_num, fmt_unit, iso, now, to_local

PROVIDERS = ("terpel", "gopass")
REVIEW_RESULTS = {"confirmed": "Confirmado", "justified": "Justificado", "data_error": "Error de dato"}
KIND_LABELS = {"refuel": "Tanqueo", "vehicle": "Vehículo", "reconciliation": "Conciliación"}
REQUIRED_COLUMNS = ("external_id", "timestamp", "vehicle", "product", "quantity", "unit_price", "amount")
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def due_date(created_at: datetime, level: str) -> datetime:
    """High priority is reviewed within 48 hours; the rest within the week."""
    return created_at + (timedelta(hours=48) if level == "high" else timedelta(days=7))


def create_alert(db: Session, *, kind: str, entity: str, entity_id: int, vehicle: Vehicle, reasons: list[dict],
                 evidence: dict, version: str, created_at: datetime | None = None) -> Alert:
    """`reasons`: [{code, name, points, explanation}]. Points and priority follow the report."""
    created = created_at or now()
    points = sum(r["points"] for r in reasons)
    level = priority(points)
    codes = [r["code"] for r in reasons]
    alert = Alert(kind=kind, entity=entity, entity_id=entity_id, vehicle_id=vehicle.id, rule_code=", ".join(codes),
                  rule_codes=codes, points=points, priority=level,
                  reason=" | ".join(f"{r['code']} {r['name']}: {r['explanation']}" for r in reasons),
                  reasons=reasons, evidence=evidence, rules_version=version, status="open",
                  created_at=created, due_at=due_date(created, level))
    db.add(alert)
    db.flush()
    return alert


def alert_payload(alert: Alert) -> dict:
    current = now()
    open_ = alert.status == "open"
    overdue = open_ and to_local(alert.due_at) < current
    return {
        "id": alert.id,
        "kind": alert.kind,
        "kind_label": KIND_LABELS.get(alert.kind, alert.kind),
        "entity": alert.entity,
        "entity_id": alert.entity_id,
        "vehicle": {"id": alert.vehicle.id, "code": alert.vehicle.code, "plate": alert.vehicle.plate,
                    "fuel_type_label": ledger.FUEL_TYPE_LABELS.get(alert.vehicle.fuel_type),
                    "group_label": ledger.GROUP_LABELS.get(alert.vehicle.group)},
        "rule_code": alert.rule_code,
        "rule_codes": alert.rule_codes,
        "points": alert.points,
        "priority": alert.priority,
        "priority_label": PRIORITY_LABELS[alert.priority],
        "reason": alert.reason,
        "reasons": alert.reasons,
        "evidence": alert.evidence,
        "rules_version": alert.rules_version,
        "status": alert.status,
        "status_label": "Abierta" if open_ else "Revisada",
        "review_result": alert.review_result,
        "review_result_label": REVIEW_RESULTS.get(alert.review_result) if alert.review_result else None,
        "review_comment": alert.review_comment,
        "reviewed_by": alert.reviewed_by,
        "reviewed_at": iso(alert.reviewed_at),
        "created_at": iso(alert.created_at),
        "due_at": iso(alert.due_at),
        "deadline_label": "48 horas" if alert.priority == "high" else "En la semana",
        "overdue": overdue,
        "hours_to_due": round((to_local(alert.due_at) - current).total_seconds() / 3600, 1) if open_ else None,
    }


def list_alerts(db: Session, *, status: str | None = None, kind: str | None = None,
                priority_level: str | None = None) -> list[Alert]:
    query = select(Alert)
    if status:
        query = query.where(Alert.status == status)
    if kind:
        query = query.where(Alert.kind == kind)
    if priority_level:
        query = query.where(Alert.priority == priority_level)
    rows = list(db.scalars(query).all())
    rows.sort(key=lambda a: (a.status != "open", PRIORITY_ORDER[a.priority], -a.points, a.due_at, a.id))
    return rows


def review_alert(db: Session, alert_id: int, result: str, comment: str, actor: Actor) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise ApiError(404, f"No existe la alerta {alert_id}.", "alert_not_found")
    before = {"status": alert.status, "review_result": alert.review_result, "review_comment": alert.review_comment,
              "reviewed_by": alert.reviewed_by}
    alert.status = "reviewed"
    alert.review_result = result
    alert.review_comment = comment
    alert.reviewed_by = actor.user
    alert.reviewed_at = now()
    audit(db, actor, "alert.reviewed", "alert", alert.id,
          summary=f"{actor.user} revisó la alerta {alert.rule_code} de {alert.vehicle.code}: {REVIEW_RESULTS[result]}. {comment}",
          before=before, after={"status": "reviewed", "review_result": result, "review_comment": comment})
    return alert


# --------------------------------------------------------------------------- import

def transaction_hash(provider: str, external_id: str, vehicle_code: str, timestamp: datetime, product: str,
                     quantity: float, amount: int) -> str:
    key = "|".join([provider, external_id.strip(), vehicle_code, to_local(timestamp).strftime("%Y-%m-%dT%H:%M:%S"),
                    product.strip().lower(), f"{quantity:.3f}", str(int(amount))])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _number(value: str | None) -> float | None:
    text = (value or "").strip().replace("$", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


def _timestamp(value: str) -> datetime:
    text = value.strip().replace("T", " ")
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=BOGOTA)
        except ValueError:
            continue
    return to_local(datetime.fromisoformat(value.strip()))


def _corriente_price(db: Session, tx: ProviderTransaction) -> tuple[float, str]:
    """Price of Corriente at the same station that day or, if it did not sell, the reference."""
    day = to_local(tx.timestamp).replace(hour=0, minute=0, second=0, microsecond=0)
    prices = db.scalars(select(ProviderTransaction.unit_price).where(
        ProviderTransaction.station == tx.station, ProviderTransaction.product == "Gasolina Corriente",
        ProviderTransaction.timestamp >= day, ProviderTransaction.timestamp < day + timedelta(days=1))).all()
    if prices:
        return float(median(prices)), "misma estación, mismo día"
    return float(ledger.REFERENCE_PRICES["Gasolina Corriente"]), "precio de referencia más cercano"


def _evaluate_new_transaction(db: Session, tx: ProviderTransaction, rules: dict[str, ActiveRule]) -> tuple[list[dict], dict]:
    window = timedelta(minutes=rules["R12"].params["window_min"])
    cluster = list(db.scalars(select(ProviderTransaction).where(
        ProviderTransaction.vehicle_id == tx.vehicle_id, ProviderTransaction.product == tx.product,
        ProviderTransaction.timestamp >= tx.timestamp - window,
        ProviderTransaction.timestamp <= tx.timestamp + window).order_by(ProviderTransaction.timestamp)).all())
    is_last = bool(cluster) and cluster[-1].id == tx.id
    days = timedelta(days=rules["R14"].params["window_days"])
    neighbors = db.scalars(select(ProviderTransaction.unit_price).where(
        ProviderTransaction.station == tx.station, ProviderTransaction.product == tx.product,
        ProviderTransaction.id != tx.id, ProviderTransaction.timestamp >= tx.timestamp - days,
        ProviderTransaction.timestamp <= tx.timestamp + days)).all()
    station_median = float(median(neighbors)) if len(neighbors) >= 3 else None
    deviation = (tx.unit_price / station_median - 1) if station_median else None
    data = {
        "sale_type": tx.sale_type,
        "amount": tx.amount,
        "split_count": len(cluster) if is_last else 1,
        "split_amount": sum(t.amount for t in cluster) if is_last else tx.amount,
        "split_minutes": ((cluster[-1].timestamp - cluster[0].timestamp).total_seconds() / 60) if is_last else 0,
        "price_deviation": deviation,
    }
    checks = evaluate_transaction(data, rules)
    reasons = [{"code": c["code"], "name": c["name"], "points": c["points"], "explanation": c["explanation"]} for c in checks]
    evidence: dict = {"transaction": ledger.transaction_payload(tx), "station_median_price": station_median}
    if tx.odometer is None:
        r = rules["R01"]
        reasons.insert(0, {"code": "R01", "name": r.name, "points": r.points, "explanation": "no se registró odómetro"})

    vehicle = tx.vehicle
    if vehicle.product == "Gasolina Corriente" and tx.product == "Gasolina Extra":
        corriente, source = _corriente_price(db, tx)
        difference = tx.unit_price - corriente
        overpaid = int(round(difference * tx.quantity))
        r = rules["C01"]
        reasons.append({"code": "C01", "name": r.name, "points": r.points, "explanation": (
            f"cargó Gasolina Extra a {fmt_cop(tx.unit_price)} por galón y su ficha pide Corriente, que estaba a "
            f"{fmt_cop(corriente)} en la misma estación ese día: {fmt_num(tx.quantity, 3)} galones y "
            f"{fmt_cop(overpaid)} pagados de más")})
        evidence["product_difference"] = {
            "authorized_product": vehicle.product, "sold_product": tx.product, "sold_price": tx.unit_price,
            "corriente_price": corriente, "corriente_price_source": source, "difference_per_gallon": difference,
            "gallons": tx.quantity, "overpaid": overpaid}
    return reasons, evidence


def _match_authorization(db: Session, tx: ProviderTransaction, rules: dict[str, ActiveRule]) -> tuple[dict | None, dict | None]:
    """Authorized vs. recorded: links the transaction to the open authorization of the vehicle."""
    row = db.execute(select(Authorization, FuelRequest).join(FuelRequest, FuelRequest.id == Authorization.request_id).where(
        FuelRequest.vehicle_id == tx.vehicle_id, Authorization.reconciled_transaction_id.is_(None),
        Authorization.created_at >= now() - timedelta(hours=36)).order_by(Authorization.id.desc())).first()
    if row is None:
        return None, None
    authorization, _ = row
    difference = tx.amount - authorization.amount
    share = abs(difference) / authorization.amount if authorization.amount else 0
    authorization.reconciled_transaction_id = tx.id
    authorization.reconciled_difference = difference
    info = {"authorization_id": authorization.id, "request_id": authorization.request_id,
            "reference": authorization.reference, "authorized_amount": authorization.amount,
            "recorded_amount": tx.amount, "difference": difference, "difference_share": round(share, 4),
            "within_tolerance": share <= rules["C02"].params["max_difference"]}
    reason = None
    if not info["within_tolerance"]:
        r = rules["C02"]
        reason = {"code": "C02", "name": r.name, "points": r.points, "explanation": (
            f"autorizado {fmt_cop(authorization.amount)} (referencia {authorization.reference}) y el proveedor registró "
            f"{fmt_cop(tx.amount)}: diferencia de {fmt_cop(difference)} ({fmt_num(share * 100, 1)} %)")}
    return info, reason


def import_csv(db: Session, provider: str, content: str, filename: str | None, actor: Actor) -> dict:
    provider = provider.lower()
    if provider not in PROVIDERS:
        raise ApiError(404, f"Proveedor desconocido: {provider}. Usa terpel o gopass.", "unknown_provider")
    text = content.lstrip("﻿")
    if not text.strip():
        raise ApiError(422, "El archivo está vacío.", "empty_file")
    delimiter = ";" if text.splitlines()[0].count(";") > text.splitlines()[0].count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    columns = [c.strip().lower() for c in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise ApiError(422, "Al archivo le faltan columnas: " + ", ".join(missing) + ".", "missing_columns",
                       {"required": list(REQUIRED_COLUMNS)})

    rules = current_rules(db)
    version = rules_version_label(db)
    batch = ImportBatch(provider=provider, filename=filename, file_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        created_by=actor.user)
    db.add(batch)
    db.flush()

    vehicles = {v.code: v for v in db.scalars(select(Vehicle)).all()}
    by_plate = {v.plate: v for v in vehicles.values()}
    rows_out: list[dict] = []
    new_transactions: list[ProviderTransaction] = []
    for line, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()):
            continue
        batch.rows += 1
        entry = {"line": line, "external_id": row.get("external_id"), "vehicle": row.get("vehicle"), "status": "imported",
                 "message": None}
        rows_out.append(entry)
        try:
            vehicle = vehicles.get(row.get("vehicle", "").upper()) or by_plate.get(row.get("plate", "").upper())
            if vehicle is None:
                raise ValueError(f"vehículo {row.get('vehicle') or row.get('plate')} no existe en el maestro")
            timestamp = _timestamp(row["timestamp"])
            quantity, unit_price, amount = _number(row["quantity"]), _number(row["unit_price"]), _number(row["amount"])
            if quantity is None or unit_price is None or amount is None:
                raise ValueError("cantidad, precio o valor vacío")
            product = row["product"]
            odometer = _number(row.get("odometer"))
            tx_hash = transaction_hash(provider, row["external_id"], vehicle.code, timestamp, product, quantity, int(amount))
        except (ValueError, KeyError) as exc:
            batch.rejected += 1
            entry.update(status="rejected", message=f"Fila rechazada: {exc}")
            continue
        if db.scalar(select(ProviderTransaction.id).where(ProviderTransaction.tx_hash == tx_hash)):
            batch.duplicates += 1
            entry.update(status="duplicate", message="Ya estaba en el libro único (mismo hash de transacción)")
            continue
        tank = ledger.tank_of(product)
        tx = ProviderTransaction(
            provider=provider, external_id=row["external_id"], tx_hash=tx_hash, vehicle_id=vehicle.id,
            timestamp=timestamp, station=row.get("station") or "Sin estación", region=row.get("region") or None,
            product=product, tank=tank, quantity=quantity, unit=row.get("unit") or ("m3" if tank == "cng" else "gal"),
            unit_price=unit_price, amount=int(round(amount)), odometer=int(odometer) if odometer is not None else None,
            sale_type=row.get("sale_type") or "En línea", source="import", import_batch_id=batch.id)
        tx.vehicle = vehicle
        db.add(tx)
        db.flush()
        batch.imported += 1
        entry["transaction_id"] = tx.id
        new_transactions.append(tx)

    deviations: list[Alert] = []
    matches: list[dict] = []
    for tx in new_transactions:  # evaluated after loading the whole file: R12 and R14 need the neighbors
        reasons, evidence = _evaluate_new_transaction(db, tx, rules)
        match, match_reason = _match_authorization(db, tx, rules)
        if match:
            matches.append({**match, "vehicle": tx.vehicle.code})
            evidence["authorization"] = match
        if match_reason:
            reasons.append(match_reason)
        if not reasons:
            continue
        alert = create_alert(db, kind="reconciliation", entity="provider_transaction", entity_id=tx.id,
                             vehicle=tx.vehicle, reasons=reasons, evidence=evidence, version=version)
        deviations.append(alert)
        emit(db, "DeviationDetected", "alert", alert.id,
             {"alert_id": alert.id, "vehicle": tx.vehicle.code, "rules": alert.rule_codes, "points": alert.points,
              "priority": alert.priority, "transaction_id": tx.id})
        for entry in rows_out:
            if entry.get("transaction_id") == tx.id:
                entry["alert_id"] = alert.id
                entry["rule_codes"] = alert.rule_codes

    emit(db, "TransactionImported", "import_batch", batch.id,
         {"batch_id": batch.id, "provider": provider, "rows": batch.rows, "imported": batch.imported,
          "duplicates": batch.duplicates, "rejected": batch.rejected, "alerts": len(deviations)})
    audit(db, actor, "import.executed", "import_batch", batch.id,
          summary=(f"{actor.user} cargó {filename or 'un archivo'} de {ledger.PROVIDER_LABELS[provider]}: "
                   f"{batch.imported} nuevas, {batch.duplicates} duplicadas, {batch.rejected} rechazadas, "
                   f"{len(deviations)} alertas"),
          after={"rows": batch.rows, "imported": batch.imported, "duplicates": batch.duplicates,
                 "rejected": batch.rejected, "alerts": len(deviations)})
    db.commit()
    overpaid = sum((a.evidence.get("product_difference") or {}).get("overpaid", 0) for a in deviations)
    return {
        "batch_id": batch.id,
        "provider": provider,
        "provider_label": ledger.PROVIDER_LABELS[provider],
        "filename": filename,
        "rows": batch.rows,
        "imported": batch.imported,
        "duplicates": batch.duplicates,
        "rejected": batch.rejected,
        "alerts_created": len(deviations),
        "overpaid_by_product": overpaid,
        "matched_authorizations": matches,
        "rules_version": version,
        "message": (f"{batch.imported} transacciones nuevas en el libro único, {batch.duplicates} duplicadas sin cargar, "
                    f"{batch.rejected} rechazadas y {len(deviations)} alertas."),
        "deviations": [alert_payload(a) for a in deviations],
        "lines": rows_out,
    }


__all__ = ["PROVIDERS", "REVIEW_RESULTS", "create_alert", "alert_payload", "list_alerts", "review_alert",
           "import_csv", "transaction_hash", "due_date", "CATALOG_BY_CODE", "fmt_unit"]
