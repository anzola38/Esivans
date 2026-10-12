"""Shared helpers for the API tests: roles, the driver simulator, decisions and CSV files."""
from __future__ import annotations

from datetime import timedelta

from app.integrations.whatsapp import encode, sign
from app.timeutil import today

TECH = {"X-Demo-Role": "technician", "X-Demo-User": "Laura Gomez"}
COORD = {"X-Demo-Role": "coordinator", "X-Demo-User": "Andres Molina"}
FINANCE = {"X-Demo-Role": "finance", "X-Demo-User": "Paola Ruiz"}
SUPPORT = {"X-Demo-Role": "support", "X-Demo-User": "Soporte TI"}

SECRET = "test-secret"
NBSP = " "

WA = {
    "GREEN": "573005550901",
    "VEH015": "573005550015",
    "VEH199": "573005550199",
    "NO_FUEL": "573005550902",
    "UNREGISTERED": "573009990000",
    "VEH910": "573005550910",   # vehicle with V04 (frozen odometer)
    "VEH903": "573005550903",
}

CSV_HEADER = "external_id,timestamp,vehicle,plate,station,region,product,quantity,unit,unit_price,amount,odometer,sale_type"
S2 = "EDS Cereté Norte"


def plain(text: str | None) -> str:
    """User-facing texts use non-breaking spaces ("61 %", "11:40 a. m."); compare with normal ones."""
    return (text or "").replace(NBSP, " ")


# ----------------------------------------------------------------------------- driver simulator

def send(client, *, case: str | None = None, wa_id: str | None = None, text: str | None = None,
         media_id: str | None = None, time: str | None = None) -> dict:
    """Sends one message as the driver through the simulator (same handler as the webhook)."""
    body: dict = {"type": "image" if media_id else "text"}
    for key, value in (("case_code", case), ("wa_id", wa_id), ("text", text), ("media_id", media_id),
                       ("simulated_time", time)):
        if value is not None:
            body[key] = value
    response = client.post("/api/dev/simulator/messages", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def conversation(client, wa_id: str) -> dict:
    response = client.get(f"/api/dev/simulator/conversations/{wa_id}")
    assert response.status_code == 200, response.text
    return response.json()


def outbound(chat: dict) -> list[dict]:
    return [m for m in chat["messages"] if m["direction"] == "outbound"]


def kinds(chat: dict) -> list[str]:
    return [m["kind"] for m in outbound(chat)]


def script_of(client, case_code: str) -> list[dict]:
    cases = client.get("/api/dev/simulator/cases").json()["items"]
    return next(c for c in cases if c["code"] == case_code)["script"]


def play(client, case_code: str, steps: int | None = None) -> dict:
    """Sends the first `steps` messages of the suggested script (all by default) and returns the chat."""
    for message in script_of(client, case_code)[:steps]:
        send(client, case=case_code, text=message.get("text"), media_id=message.get("media_id"))
    return conversation(client, WA[case_code])


# ----------------------------------------------------------------------------- console

def detail(client, request_id: int, headers: dict = TECH) -> dict:
    response = client.get(f"/api/requests/{request_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def queue(client, status: str | None = "in_review", headers: dict = TECH) -> dict:
    url = "/api/requests" + (f"?status={status}" if status else "")
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def decide(client, request_id: int, headers: dict = TECH, **body):
    return client.post(f"/api/requests/{request_id}/decision", json=body, headers=headers)


def authorize(client, request_id: int, reference: str = "TER-PRUEBA-0001", headers: dict = TECH, **extra):
    return client.post(f"/api/requests/{request_id}/authorization", json={"reference": reference, **extra},
                       headers=headers)


def in_review(client, case_code: str) -> dict:
    """Plays a demo case to the end and returns the detail of its request."""
    chat = play(client, case_code)
    return detail(client, chat["request"]["id"])


def authorized_green(client, reference: str = "TER-PRUEBA-0001") -> dict:
    """Green case approved in one click and enabled; returns the detail."""
    request = in_review(client, "GREEN")
    assert decide(client, request["id"], action="approve").status_code == 200
    response = authorize(client, request["id"], reference)
    assert response.status_code == 200, response.text
    return response.json()


def audit_items(client, query: str = "", headers: dict = COORD) -> list[dict]:
    response = client.get("/api/audit" + (f"?{query}" if query else ""), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def outbox(client) -> list[dict]:
    return client.get("/api/dev/outbox").json()["items"]


# ----------------------------------------------------------------------------- webhook

def post_webhook(client, payload: dict | None = None, *, raw: bytes | None = None, signature: str | None = "auto",
                 secret: str = SECRET):
    """POSTs to the real webhook. `signature="auto"` signs the body sent; `None` sends no header."""
    body = raw if raw is not None else encode(payload)
    headers = {"Content-Type": "application/json"}
    if signature == "auto":
        headers["X-Hub-Signature-256"] = sign(body, secret)
    elif signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/api/webhooks/whatsapp", content=body, headers=headers)


# ----------------------------------------------------------------------------- provider files

def day(offset: int = 1) -> str:
    """ISO date `offset` days ago (1 = yesterday, the day of the sample file)."""
    return (today() - timedelta(days=offset)).isoformat()


def csv_row(external_id: str, vehicle: str, amount: int, *, hour: str = "19:00:00", station: str = S2,
            product: str = "Gasolina Corriente", unit_price: float = 16000, quantity: float | None = None,
            unit: str = "gal", odometer: int | str = 50000, sale_type: str = "En línea", days_ago: int = 1) -> str:
    quantity = round(amount / unit_price, 3) if quantity is None else quantity
    plate = "ZZA" + vehicle[-3:]
    return ",".join(str(v) for v in [external_id, f"{day(days_ago)} {hour}", vehicle, plate, station, "NORTE", product,
                                     f"{quantity:.3f}", unit, unit_price, amount, odometer, sale_type])


def csv_file(*rows: str) -> str:
    return "\n".join([CSV_HEADER, *rows]) + "\n"


def sample_csv(client) -> str:
    response = client.get("/api/dev/samples/terpel")
    assert response.status_code == 200
    return response.text


def import_csv(client, text: str, headers: dict = FINANCE, provider: str = "terpel", filename: str = "prueba.csv"):
    return client.post(f"/api/integrations/{provider}/imports", json={"filename": filename, "content": text},
                       headers=headers)


def imported(client, text: str, headers: dict = FINANCE) -> dict:
    response = import_csv(client, text, headers)
    assert response.status_code == 200, response.text
    return response.json()


def alerts(client, query: str = "", headers: dict = COORD) -> dict:
    response = client.get("/api/alerts" + (f"?{query}" if query else ""), headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def vehicle_alert(client, code: str) -> dict:
    return next(a for a in alerts(client, "kind=vehicle")["items"] if a["vehicle"]["code"] == code)


def review(client, alert_id: int, result: str = "confirmed", comment: str = "Revisado con la evidencia.",
           headers: dict = COORD):
    return client.patch(f"/api/alerts/{alert_id}", json={"review_result": result, "comment": comment}, headers=headers)


def rule(client, code: str, headers: dict = COORD) -> dict:
    return next(r for r in client.get("/api/rules", headers=headers).json()["items"] if r["code"] == code)


def put_rule(client, code: str, headers: dict = COORD, **body):
    return client.put(f"/api/rules/{code}", json=body, headers=headers)
