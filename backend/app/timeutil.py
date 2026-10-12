"""Time helpers (America/Bogota) and es-CO number formatting for user-facing texts."""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")
NBSP = " "


def now() -> datetime:
    return datetime.now(BOGOTA)


def today() -> date:
    return now().date()


def at(day: date, hhmm_text: str) -> datetime:
    hour, minute = (int(p) for p in hhmm_text.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=BOGOTA)


def to_local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BOGOTA)
    return dt.astimezone(BOGOTA)


def iso(dt: datetime | None) -> str | None:
    local = to_local(dt)
    return local.isoformat(timespec="seconds") if local else None


def parse_iso(value: str) -> datetime:
    return to_local(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))


def hhmm(dt: datetime) -> str:
    return to_local(dt).strftime("%H:%M")


def clock12(dt: datetime) -> str:
    """Hour as the interface shows it: '11:40 a. m.' (single convention across the app)."""
    local = to_local(dt)
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d}{NBSP}{'a.' if local.hour < 12 else 'p.'}{NBSP}m."


def ddmmyyyy(dt: datetime) -> str:
    return to_local(dt).strftime("%d/%m/%Y")


def fmt_num(value: float | int | None, decimals: int = 1) -> str:
    """1234.5 -> '1.234,5' (es-CO)."""
    if value is None:
        return "s/d"
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_int(value: float | int | None) -> str:
    return fmt_num(value, 0)


def fmt_cop(value: float | int | None) -> str:
    if value is None:
        return "s/d"
    return ("-" if value < 0 else "") + "$" + fmt_num(abs(round(value)), 0)


def fmt_pct(fraction: float | None, decimals: int = 0) -> str:
    if fraction is None:
        return "s/d"
    return f"{fmt_num(fraction * 100, decimals)}{NBSP}%"


def fmt_unit(unit: str) -> str:
    return {"m3": "m³"}.get(unit, unit)


def seconds_between(start: datetime, end: datetime) -> int:
    return int((to_local(end) - to_local(start)).total_seconds())
