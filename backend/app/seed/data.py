"""Illustrative seed, written by hand from the examples of the documents.

Pilot zone: Córdoba (CARIBE COR). 24 vehicles with drivers, assignments, EOM services and
90 days of refuels. Dates are relative to the day the seed is loaded. Nothing here is copied
from the case files: plates, names, stations and amounts are invented; only the figures the
documents quote for the example vehicles are reproduced (VEH015, VEH199, VEH023, VEH129,
VEH215 and VEH160).
"""
from __future__ import annotations

ZONE = "CARIBE COR"
DEPARTMENT = "Córdoba"
REGION = "NORTE"

# Stations (generic names) and their price per product.
S1, S2, S3 = "EDS Montería Centro", "EDS Cereté Norte", "EDS Lorica Puerto"
G1, G2 = "EDS GNV Montería Sur", "EDS GNV Planeta Rica"
P1 = "Estación aliada Sahagún"
STATION_PRICES = {
    S1: {"Gasolina Corriente": 16330, "Gasolina Extra": 21250, "Diesel": 11150},
    S2: {"Gasolina Corriente": 16000, "Diesel": 11100},
    S3: {"Gasolina Corriente": 16500, "Diesel": 11050},
    G1: {"GNV": 3200},
    G2: {"GNV": 3200},
    P1: {"Gasolina Corriente": 16030, "Diesel": 11410},
}

ROUTES = [("Montería", "Cereté"), ("Cereté", "San Pelayo"), ("San Pelayo", "Lorica"), ("Lorica", "Montería"),
          ("Montería", "Planeta Rica"), ("Planeta Rica", "Sahagún"), ("Sahagún", "Montería"),
          ("Montería", "Tierralta"), ("Tierralta", "Montería")]
FULL_DAY = ["06:00", "07:30", "09:00", "10:30", "12:00", "13:30", "15:00", "16:30", "18:00"]
SHORT_DAY = ["06:00", "07:30", "09:00", "12:00", "14:00"]

# Illustrative technical data (the case data has neither tank capacity nor km per service).
CAPACITY = {"gasoline": 12.0, "dual_fuel": 12.0, "light_diesel": 18.0, "heavy_diesel": 40.0, "cng": 14.0}


def gas(n, amounts, station=S2, start=90, end=2):
    return {"provider": "terpel", "product": "Gasolina Corriente", "n": n, "amounts": amounts,
            "stations": [station], "start": start, "end": end}


VEHICLES = [
    # ---- demo cases ------------------------------------------------------------------
    {"code": "VEH901", "plate": "ZZA901", "driver": "Carlos Andrés Pérez", "phone": "573005550901",
     "group": "gasoline", "efficiency": 40.5, "provider": "terpel", "eom": {"today": FULL_DAY},
     "streams": [gas(30, [80000, 70000, 90000, 80000, 60000])],
     "last": {"hour": "17:30", "amount": 80000, "station": S2, "product": "Gasolina Corriente"}, "last_odo": 48210},
    {"code": "VEH902", "plate": "ZZA902", "driver": "Luis Fernando Ortega", "phone": "573005550902",
     "group": "gasoline", "efficiency": 42.3, "provider": "terpel", "eom": {"today": SHORT_DAY},
     "streams": [gas(28, [100000, 90000, 80000])],
     "last": {"hour": "18:10", "amount": 100000, "station": S2, "product": "Gasolina Corriente"}, "last_odo": 61480},
    {"code": "VEH015", "plate": "ZZA015", "driver": "Jorge Iván Castaño", "phone": "573005550015",
     "group": "dual_fuel", "efficiency": 26.3, "provider": "terpel", "eom": None, "flags": ["V01", "V05"],
     "stats": {"refuels_90d": 99, "amount_90d": 4984000, "alert_share": 0.071},
     "streams": [
         {"provider": "terpel", "product": "GNV", "n": 80, "quantities": [14.0, 13.5, 14.5, 14.0],
          "stations": [G1, G2], "start": 90, "end": 2},
         {"provider": "terpel", "product": "Gasolina Corriente", "n": 18, "amounts": [70000, 80000],
          "stations": [S2], "start": 88, "end": 4, "hour_shift": 3},
     ],
     "last": {"hour": "16:45", "amount": 50000, "station": S2, "product": "Gasolina Corriente"}, "last_odo": 33948},
    {"code": "VEH199", "plate": "ZZA199", "driver": "Wilson Darío Hoyos", "phone": "573005550199",
     "group": "cng", "efficiency": 16.2, "provider": "terpel", "eom": {"old_days": (20, 15)}, "flags": ["V08"],
     "stats": {"alert_share": 0.96},
     "streams": [{"provider": "terpel", "product": "GNV", "n": 48,
                  "quantities": [8.6, 9.1, 9.7, 9.7, 9.7, 10.3, 11.8], "stations": [G1, G2], "start": 90, "end": 2}],
     "overrides": {47: {"hour": "15:17", "quantity": 6.6, "km_from_prev": 20},
                   44: {"hour": "22:13", "quantity": 7.1, "km_from_prev": 37}},
     "last": {"hour": "15:40", "quantity": 3.0, "station": G1, "product": "GNV", "gap_km": 107}, "last_odo": 195384},
    {"code": "VEH023", "plate": "ZZA023", "driver": "Andrea Milena Suárez", "phone": "573005550023",
     "group": "gasoline", "efficiency": 43.6, "provider": "terpel", "eom": {},
     "streams": [gas(30, [60000, 70000, 80000], station=S1)], "last_odo": 87420},
    {"code": "VEH129", "plate": "ZZA129", "driver": "Hernán Darío Bula", "phone": "573005550129",
     "group": "dual_fuel", "efficiency": 20.3, "provider": "terpel", "eom": None, "flags": ["V01", "V05", "V08"],
     "stats": {"refuels_90d": 102, "amount_90d": 4128960, "alert_share": 0.26},
     "streams": [{"provider": "terpel", "product": "GNV", "n": 102, "quantities": [12.0, 13.3, 12.65, 12.4, 12.9],
                  "stations": [G1, G2], "start": 90, "end": 1}],
     "last_odo": 164870},
    {"code": "VEH215", "plate": "ZZA215", "driver": "Yesid Antonio Vargas", "phone": "573005550215",
     "group": "gasoline", "efficiency": 24.0, "provider": "terpel", "eom": {}, "flags": ["V01"],
     "stats": {"refuels_90d": 17, "amount_90d": 1205000, "km_90d": 1755, "fuel_90d": 73.04},
     "streams": [{"provider": "terpel", "product": "Gasolina Corriente", "n": 17,
                  "amounts": [70000, 70000, 73000, 70000, 70000, 73000, 70000, 70000, 73000, 70000, 70000, 73000,
                              70000, 70000, 73000, 70000, 70000],
                  "stations": [S3], "start": 65, "end": 6}],
     "total_km": 1755, "last_odo": 52300},
    {"code": "VEH160", "plate": "ZZA160", "driver": "Óscar Javier Montes", "phone": "573005550160",
     "group": "dual_fuel", "efficiency": 49.8, "provider": "gopass", "eom": {}, "flags": ["V06"], "custom": "veh160"},
    # ---- rest of the pilot fleet (fictitious) -----------------------------------------
    {"code": "VEH903", "plate": "ZZA903", "driver": "María Fernanda Lozano", "phone": "573005550903",
     "group": "gasoline", "efficiency": 43.1, "provider": "terpel", "eom": {},
     "streams": [gas(30, [70000, 80000, 60000])], "last_odo": 72150,
     "overrides": {20: {"km_from_prev": 18}}},
    {"code": "VEH904", "plate": "ZZA904", "driver": "Julio César Benítez", "phone": "573005550904",
     "group": "gasoline", "efficiency": 39.8, "provider": "terpel", "eom": {},
     "streams": [gas(30, [80000, 90000, 70000])], "last_odo": 65820,
     "overrides": {28: {"km_from_prev": 1240}}},
    {"code": "VEH905", "plate": "ZZA905", "driver": "Sandra Patricia Negrete", "phone": "573005550905",
     "group": "gasoline", "efficiency": 45.0, "provider": "terpel", "eom": {},
     "streams": [gas(30, [60000, 60000, 70000], station=S1)], "last_odo": 91340,
     "overrides": {26: {"odometer": None}}},
    {"code": "VEH906", "plate": "ZZA906", "driver": "Robinson Elías Pacheco", "phone": "573005550906",
     "group": "gasoline", "efficiency": 38.2, "provider": "gopass", "eom": {},
     "streams": [{"provider": "gopass", "product": "Gasolina Corriente", "n": 28, "amounts": [70000, 70000, 80000],
                  "stations": [P1], "start": 90, "end": 2}], "last_odo": 54630,
     "overrides": {26: {"km_from_prev": 12, "sale_type": "Recuperado"}}},
    {"code": "VEH907", "plate": "ZZA907", "driver": "Diana Marcela Espitia", "phone": "573005550907",
     "group": "gasoline", "efficiency": 41.5, "provider": "terpel", "eom": {},
     "streams": [gas(32, [70000, 60000, 80000, 70000])], "last_odo": 58760},
    {"code": "VEH908", "plate": "ZZA908", "driver": "Álvaro José Doria", "phone": "573005550908",
     "group": "light_diesel", "efficiency": 33.2, "provider": "terpel", "eom": {},
     "streams": [{"provider": "terpel", "product": "Diesel", "n": 26, "amounts": [120000, 140000, 130000],
                  "stations": [S2, S3], "start": 90, "end": 2}], "last_odo": 118240,
     "overrides": {24: {"quantity": 26.4}}},
    {"code": "VEH909", "plate": "ZZA909", "driver": "Nelson Enrique Ramos", "phone": "573005550909",
     "group": "light_diesel", "efficiency": 35.6, "provider": "gopass", "eom": {},
     "streams": [{"provider": "gopass", "product": "Diesel", "n": 24, "amounts": [130000, 150000],
                  "stations": [P1], "start": 90, "end": 3}], "last_odo": 102910},
    {"code": "VEH910", "plate": "ZZA910", "driver": "Eduardo Luis Petro", "phone": "573005550910",
     "group": "gasoline", "efficiency": None, "provider": "terpel", "eom": {}, "flags": ["V04"],
     "stats": {"frozen_share": 0.62}, "frozen": True,
     "streams": [gas(29, [70000, 80000])], "last_odo": 80412},
    {"code": "VEH911", "plate": "ZZA911", "driver": "Claudia Inés Villadiego", "phone": "573005550911",
     "group": "gasoline", "efficiency": 61.0, "provider": "terpel", "eom": {}, "flags": ["V02"],
     "streams": [gas(18, [60000, 50000, 60000])], "last_odo": 69350},
    {"code": "VEH912", "plate": "ZZA912", "driver": "Ramiro Alfonso Durango", "phone": "573005550912",
     "group": "heavy_diesel", "efficiency": 15.4, "provider": "terpel", "eom": {},
     "streams": [{"provider": "terpel", "product": "Diesel", "n": 30, "amounts": [300000, 330000, 310000],
                  "stations": [S2, S1], "start": 90, "end": 2}], "last_odo": 143900},
    {"code": "VEH913", "plate": "ZZA913", "driver": "Fabio Andrés Mestra", "phone": "573005550913",
     "group": "dual_fuel", "efficiency": 55.3, "provider": "terpel", "eom": {},
     "streams": [
         {"provider": "terpel", "product": "GNV", "n": 40, "quantities": [9.0, 9.6, 8.7, 10.2],
          "stations": [G1], "start": 90, "end": 2},
         {"provider": "terpel", "product": "Gasolina Corriente", "n": 10, "amounts": [50000, 60000],
          "stations": [S1], "start": 86, "end": 5, "hour_shift": 3},
     ], "last_odo": 133580,
     "overrides": {30: {"odometer": None, "sale_type": "Fuera del sistema"}}},
    {"code": "VEH914", "plate": "ZZA914", "driver": "Gustavo Adolfo Sierra", "phone": "573005550914",
     "group": "cng", "efficiency": 17.6, "provider": "terpel", "eom": {},
     "streams": [{"provider": "terpel", "product": "GNV", "n": 40, "quantities": [9.4, 10.1, 8.8],
                  "stations": [G1, G2], "start": 90, "end": 2}], "last_odo": 121480},
    {"code": "VEH915", "plate": "ZZA915", "driver": "Liliana Paola Argel", "phone": "573005550915",
     "group": "gasoline", "efficiency": 42.0, "provider": "terpel", "eom": {}, "flags": ["V07"],
     "stats": {"odometer_issue_share": 0.14}, "missing_odometer_every": 7,
     "streams": [gas(28, [70000, 80000, 70000], station=S3)], "last_odo": 47890},
    {"code": "VEH916", "plate": "ZZA916", "driver": "Manuel Esteban Cogollo", "phone": "573005550916",
     "group": "gasoline", "efficiency": 40.9, "provider": "terpel", "eom": {}, "flags": ["V03"],
     "stats": {"recent_drop": -0.31},
     "streams": [gas(30, [80000, 70000, 80000])], "last_odo": 77230},
    {"code": "VEH917", "plate": "ZZA917", "driver": "Pedro Pablo Guzmán", "phone": "573005550917",
     "group": "light_diesel", "efficiency": 34.4, "provider": "terpel", "eom": {},
     "streams": [{"provider": "terpel", "product": "Diesel", "n": 25, "amounts": [130000, 120000, 140000],
                  "stations": [S3, S2], "start": 90, "end": 2}], "last_odo": 96120},
    {"code": "VEH918", "plate": "ZZA918", "driver": "Tatiana Isabel Burgos", "phone": "573005550918",
     "group": "gasoline", "efficiency": 44.2, "provider": "terpel", "eom": {},
     "streams": [gas(30, [60000, 70000, 60000, 80000])], "last_odo": 39510},
]

# Refuel alerts loaded with the seed (the historical test of the rules). `index` points to the
# refuel in the vehicle's ledger, in chronological order; texts use the data of that refuel.
REFUEL_ALERTS = [
    {"vehicle": "VEH199", "index": 47, "created_days_ago": 1,
     "rules": [("R05", "cargó {qty} {unit} de GNV con {km} km desde su carga anterior (típica 9,7 {unit})"),
               ("R08", "sin servicios con desplazamiento 24 h antes ni después")]},
    {"vehicle": "VEH199", "index": 44,
     "rules": [("R08", "sin servicios con desplazamiento 24 h antes ni después"),
               ("R09", "tanqueo a las {time} sin servicios cercanos")],
     "review": ("confirmed", "Sin operación registrada esa noche. Se habló con el conductor y quedó el compromiso.", 36)},
    {"vehicle": "VEH906", "index": 26, "created_days_ago": 3,
     "rules": [("R05", "cargó {qty} {unit} de combustible líquido con {km} km desde su carga anterior (típica {typical} {unit})"),
               ("R11", "tipo de venta: {sale_type}")]},
    {"vehicle": "VEH904", "index": 28,
     "rules": [("R04", "{km} km en {days} días: posible tanqueo no registrado en estos proveedores")]},
    {"vehicle": "VEH908", "index": 24,
     "rules": [("R07", "cargó {qty} {unit} de combustible líquido; sus cargas más grandes son de {largest} {unit}")]},
    {"vehicle": "VEH903", "index": 20,
     "rules": [("R05", "cargó {qty} {unit} de combustible líquido con {km} km desde su carga anterior (típica {typical} {unit})"),
               ("R08", "sin servicios con desplazamiento 24 h antes ni después")],
     "review": ("confirmed", "Recarga sin recorrido ni servicio. Se revisó con el conductor con la evidencia.", 40)},
    {"vehicle": "VEH907", "index": 25,
     "rules": [("R06", "4 cargas de combustible líquido en 24 h")],
     "review": ("justified", "Apoyo a la zona de Sucre ese día: recorrido extraordinario sustentado por el coordinador.", 20)},
    {"vehicle": "VEH905", "index": 26,
     "rules": [("R01", "no se registró odómetro")],
     "review": ("data_error", "La estación no digitó el kilometraje. Se pidió la corrección al proveedor.", 30)},
    {"vehicle": "VEH918", "index": 24,
     "rules": [("R08", "sin servicios con desplazamiento 24 h antes ni después")],
     "review": ("justified", "Traslado administrativo que no se registra en EOM.", 26)},
    {"vehicle": "VEH913", "index": 30,
     "rules": [("R01", "no se registró odómetro"), ("R11", "tipo de venta: {sale_type}")],
     "review": ("confirmed", "Venta fuera del sistema sin soporte de la estación.", 44)},
]

# Vehicle alerts: one per vehicle with rules V01..V08 (90-day analysis). Reviewed ones carry the result.
VEHICLE_ALERT_REVIEWS = {
    "VEH916": ("confirmed", "Mantenimiento encontró inyectores sucios. Vuelve a medición por 4 semanas.", 30),
    "VEH915": ("data_error", "La estación omite el odómetro: se pidió al proveedor exigirlo en la venta.", 28),
}
VEHICLE_ALERT_CREATED_DAYS_AGO = {"VEH015": 3}  # this one is already past its 48 hours

# Demo cases of the simulator.
DEMO_CASES = [
    {"code": "GREEN", "vehicle": "VEH901", "time": "09:40", "media": "media-veh901",
     "title": "Caso verde: se aprueba en un clic",
     "description": ("Vehículo de gasolina con servicios en EOM y kilometraje coherente. El asistente arma la "
                     "solicitud y el técnico la aprueba en un clic."),
     "expected": {"traffic_light": "green", "points": 0, "rules": [], "suggested_amount": 90000},
     "script": [{"type": "text", "text": "Hola, necesito tanquear"},
                {"type": "text", "text": "Sí, es para esa ruta"},
                {"type": "image", "media_id": "media-veh901"},
                {"type": "text", "text": "Sí, es correcto"}]},
    {"code": "VEH015", "vehicle": "VEH015", "time": "14:20", "media": "media-veh015",
     "title": "Error de digitación en el kilometraje (R02)",
     "description": ("La lectura da 24.086 km y su último registro es 33.948. El asistente propone 34.086 "
                     "(el 3 quedó como 2) y pide confirmar el valor corregido."),
     "expected": {"traffic_light": "yellow", "points": 1, "rules": ["R02"], "suggested_amount": 50000},
     "script": [{"type": "text", "text": "Buenas, necesito combustible"},
                {"type": "text", "text": "Traslado no programado"},
                {"type": "image", "media_id": "media-veh015"},
                {"type": "text", "text": "Sí, es 34.086"}]},
    {"code": "VEH199", "vehicle": "VEH199", "time": "23:14", "media": "media-veh199",
     "title": "Solicitud nocturna en rojo (R05, R08 y R09)",
     "description": ("A las 11:14 p. m. pide 6,7 m³ de gas con 22 km desde su carga anterior (típica de 9,7 m³) y "
                     "sin servicios en EOM: 7 puntos, rojo, con la razón de cada regla."),
     "expected": {"traffic_light": "red", "points": 7, "rules": ["R05", "R08", "R09"], "suggested_amount": 10000},
     "script": [{"type": "text", "text": "Necesito tanquear 6,7 m3 de gas"},
                {"type": "text", "text": "No tengo servicio asignado"},
                {"type": "image", "media_id": "media-veh199"},
                {"type": "text", "text": "Sí, es correcto"}]},
    {"code": "NO_FUEL", "vehicle": "VEH902", "time": "11:05", "media": "media-veh902",
     "title": "No necesita tanquear (a cargar es 0 o menos)",
     "description": ("Tiene ⅞ de tanque y solo 2 servicios pendientes: el asistente le explica que por ahora "
                     "no necesita tanquear."),
     "expected": {"traffic_light": None, "points": 0, "rules": [], "suggested_amount": 0},
     "script": [{"type": "text", "text": "Necesito tanquear"},
                {"type": "text", "text": "Sí, es para esa ruta"},
                {"type": "image", "media_id": "media-veh902"},
                {"type": "text", "text": "Sí, es correcto"},
                {"type": "text", "text": "Entendido, gracias"}]},
    {"code": "UNREGISTERED", "vehicle": None, "time": "08:15", "media": None, "wa_id": "573009990000",
     "driver_name": "Número no registrado",
     "title": "Número no registrado: pasa al técnico",
     "description": "El número no está entre los conductores: el asistente pasa el caso al técnico con el motivo.",
     "expected": {"traffic_light": "yellow", "points": 0, "rules": [], "suggested_amount": None},
     "script": [{"type": "text", "text": "Buenos días, necesito tanquear la van"}]},
]
