"""Data model (subset of section 8 of the report). One file keeps the prototype easy to read."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.timeutil import now


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicle"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    plate: Mapped[str] = mapped_column(String(10), unique=True)
    fuel_type: Mapped[str] = mapped_column(String(20))  # gasoline | dual_fuel | diesel | cng
    group: Mapped[str] = mapped_column("vehicle_group", String(20))  # gasoline | dual_fuel | light_diesel | heavy_diesel | cng
    product: Mapped[str] = mapped_column(String(40))  # product authorized by its data sheet
    unit: Mapped[str] = mapped_column(String(5))  # gal | m3
    tank_capacity: Mapped[float | None] = mapped_column(Float)
    reference_efficiency: Mapped[float | None] = mapped_column(Float)
    efficiency_unit: Mapped[str] = mapped_column(String(12))
    zone: Mapped[str] = mapped_column(String(40))
    department: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(20))  # terpel (chip) | gopass (card)
    flags: Mapped[list] = mapped_column(JSONB, default=list)  # vehicle rules V01..V08 that apply
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)  # 90-day figures computed by the analysis


class Driver(Base):
    __tablename__ = "driver"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True)  # wa_id


class Assignment(Base):
    __tablename__ = "assignment"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("driver.id"), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vehicle: Mapped[Vehicle] = relationship()
    driver: Mapped[Driver] = relationship()


class EomService(Base):
    __tablename__ = "eom_service"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(30), unique=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    start: Mapped[datetime] = mapped_column("start_at", DateTime(timezone=True), index=True)
    end: Mapped[datetime | None] = mapped_column("end_at", DateTime(timezone=True))
    km: Mapped[float | None] = mapped_column(Float)
    zone: Mapped[str] = mapped_column(String(40))
    department: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(60))
    destination: Mapped[str] = mapped_column(String(60))


class ImportBatch(Base):
    __tablename__ = "import_batch"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str | None] = mapped_column(String(120))
    file_hash: Mapped[str] = mapped_column(String(64))
    rows: Mapped[int] = mapped_column(Integer, default=0)
    imported: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProviderTransaction(Base):
    __tablename__ = "provider_transaction"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), index=True)
    external_id: Mapped[str] = mapped_column(String(40))
    tx_hash: Mapped[str] = mapped_column(String(64), unique=True)  # idempotency key of the import
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column("occurred_at", DateTime(timezone=True), index=True)
    station: Mapped[str] = mapped_column(String(80))
    region: Mapped[str | None] = mapped_column(String(40))
    product: Mapped[str] = mapped_column(String(40))
    tank: Mapped[str] = mapped_column(String(10))  # liquid | cng
    quantity: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(5))
    unit_price: Mapped[float] = mapped_column(Float)
    amount: Mapped[int] = mapped_column(Integer)
    odometer: Mapped[int | None] = mapped_column(Integer)
    sale_type: Mapped[str] = mapped_column(String(30), default="En línea")
    source: Mapped[str] = mapped_column(String(10), default="seed")  # seed | import
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batch.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    vehicle: Mapped[Vehicle] = relationship()


class FuelRequest(Base):
    __tablename__ = "request"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), unique=True, default=_uuid)
    wa_id: Mapped[str] = mapped_column(String(20), index=True)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("driver.id"))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    step: Mapped[str | None] = mapped_column(String(20))  # conversation step
    data: Mapped[dict] = mapped_column(JSONB, default=dict)  # conversation slots
    chosen_service_id: Mapped[int | None] = mapped_column(ForeignKey("eom_service.id"))
    service_note: Mapped[str | None] = mapped_column(Text)
    requested_quantity: Mapped[float | None] = mapped_column(Float)
    missing: Mapped[list] = mapped_column(JSONB, default=list)
    close_reason: Mapped[str | None] = mapped_column(String(40))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # case time (rules use it)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)  # real time (queue, SLA)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    driver: Mapped[Driver | None] = relationship()
    vehicle: Mapped[Vehicle | None] = relationship()
    chosen_service: Mapped[EomService | None] = relationship()
    evidence: Mapped["Evidence | None"] = relationship(back_populates="request", uselist=False)
    evaluation: Mapped["Evaluation | None"] = relationship(back_populates="request", uselist=False)
    decision: Mapped["Decision | None"] = relationship(back_populates="request", uselist=False)
    authorization: Mapped["Authorization | None"] = relationship(back_populates="request", uselist=False)
    status_log: Mapped[list["RequestStatusLog"]] = relationship(
        back_populates="request", order_by="RequestStatusLog.id")


class RequestStatusLog(Base):
    __tablename__ = "request_status_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    request: Mapped[FuelRequest] = relationship(back_populates="status_log")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id"), unique=True)
    media_id: Mapped[str | None] = mapped_column(String(80))
    photo_path: Mapped[str | None] = mapped_column(String(200))
    photo_hash: Mapped[str | None] = mapped_column(String(64))
    odometer_read: Mapped[int | None] = mapped_column(Integer)  # as read from the photo
    odometer_km: Mapped[int | None] = mapped_column(Integer)  # value confirmed by the driver
    odometer_source: Mapped[str | None] = mapped_column(String(10))  # photo | driver
    fuel_level: Mapped[float | None] = mapped_column(Float)  # 0..1
    confidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_type: Mapped[str | None] = mapped_column(String(20))
    proposed_odometer: Mapped[int | None] = mapped_column(Integer)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_source: Mapped[dict | None] = mapped_column(JSONB)  # provider and model that read the photo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    request: Mapped[FuelRequest] = relationship(back_populates="evidence")


class Evaluation(Base):
    __tablename__ = "evaluation"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id"), unique=True)
    context: Mapped[dict] = mapped_column(JSONB, default=dict)
    rules_version: Mapped[str] = mapped_column(String(20))
    traffic_light: Mapped[str] = mapped_column(String(10))
    points: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    checks: Mapped[list] = mapped_column(JSONB, default=list)
    calculation: Mapped[dict] = mapped_column(JSONB, default=dict)
    suggested_amount: Mapped[int | None] = mapped_column(Integer)
    suggested_quantity: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    request: Mapped[FuelRequest] = relationship(back_populates="evaluation")


class Alert(Base):
    __tablename__ = "alert"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # refuel | vehicle | reconciliation
    entity: Mapped[str] = mapped_column(String(30))  # provider_transaction | vehicle
    entity_id: Mapped[int] = mapped_column(Integer)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicle.id"), index=True)
    rule_code: Mapped[str] = mapped_column(String(60))  # "R05, R08"
    rule_codes: Mapped[list] = mapped_column(JSONB, default=list)
    points: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(String(10), index=True)  # high | medium | low
    reason: Mapped[str] = mapped_column(Text)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    rules_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | reviewed
    review_result: Mapped[str | None] = mapped_column(String(20))  # confirmed | justified | data_error
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(80))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    vehicle: Mapped[Vehicle] = relationship()


class Decision(Base):
    __tablename__ = "decision"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id"), unique=True)  # one decision per request
    decided_by: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(10))  # approve | adjust | reject
    amount: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    one_click: Mapped[bool] = mapped_column(Boolean, default=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    original_calculation: Mapped[dict] = mapped_column(JSONB, default=dict)

    request: Mapped[FuelRequest] = relationship(back_populates="decision")


class Authorization(Base):
    __tablename__ = "authorization"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("request.id"), unique=True)
    decision_id: Mapped[int] = mapped_column(ForeignKey("decision.id"))
    provider: Mapped[str] = mapped_column(String(20))
    reference: Mapped[str] = mapped_column(String(60))
    product: Mapped[str] = mapped_column(String(40))
    amount: Mapped[int] = mapped_column(Integer)
    enabled_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reconciled_transaction_id: Mapped[int | None] = mapped_column(ForeignKey("provider_transaction.id"))
    reconciled_difference: Mapped[int | None] = mapped_column(Integer)

    request: Mapped[FuelRequest] = relationship(back_populates="authorization")


class RuleVersion(Base):
    __tablename__ = "rule_version"
    __table_args__ = (UniqueConstraint("code", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(5), index=True)
    version: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[dict] = mapped_column(JSONB, default=dict)
    points: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    author: Mapped[str] = mapped_column(String(80))
    change_reason: Mapped[str | None] = mapped_column(Text)


class AuditLog(Base):
    """Insert-only: a PostgreSQL trigger rejects UPDATE and DELETE."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    role: Mapped[str | None] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    request_id: Mapped[int | None] = mapped_column(Integer, index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class InboundMessage(Base):
    __tablename__ = "inbound_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    wa_message_id: Mapped[str] = mapped_column(String(80), unique=True)  # idempotency key
    wa_id: Mapped[str] = mapped_column(String(20), index=True)
    type: Mapped[str] = mapped_column(String(15))
    text: Mapped[str | None] = mapped_column(Text)
    media_id: Mapped[str | None] = mapped_column(String(80))
    case_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # timestamp sent by WhatsApp
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    request_id: Mapped[int | None] = mapped_column(Integer)
    interpretation: Mapped[dict | None] = mapped_column(JSONB)  # what the AI extracted and which provider did it
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboundMessage(Base):
    """Simulates POST /{phone-number-id}/messages of the WhatsApp Cloud API."""

    __tablename__ = "outbound_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    wa_message_id: Mapped[str] = mapped_column(String(80), unique=True)
    wa_id: Mapped[str] = mapped_column(String(20), index=True)
    request_id: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    body: Mapped[str] = mapped_column(Text)
    quick_replies: Mapped[list] = mapped_column(JSONB, default=list)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    case_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OutboxEvent(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    aggregate: Mapped[str] = mapped_column(String(40))
    aggregate_id: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
