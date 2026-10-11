"""Rule catalog: codes, initial thresholds and points.

Ported from the analysis code (`fuel/config.py` and `fuel/rules.py`): what was calibrated
against historical data is what the engine applies. The values below are only the INITIAL
version; at runtime the engine reads the current `rule_version` rows.
"""
from __future__ import annotations

from dataclasses import dataclass, field

BEFORE_AUTH = "before_authorization"
AT_RECONCILIATION = "reconciliation"
VEHICLE = "vehicle"

AUTOMATIC = "automatic"
REVIEW = "review"

STAGE_LABELS = {
    BEFORE_AUTH: "Antes de autorizar",
    AT_RECONCILIATION: "Al conciliar",
    VEHICLE: "Por vehículo (revisión semanal)",
}
TREATMENT_LABELS = {AUTOMATIC: "Automática", REVIEW: "Revisión"}


@dataclass(frozen=True)
class RuleDef:
    code: str
    name: str
    stage: str
    treatment: str
    points: int
    threshold_text: str
    params: dict = field(default_factory=dict)
    param_labels: dict = field(default_factory=dict)


CATALOG: list[RuleDef] = [
    RuleDef("R01", "Odómetro sin dato", BEFORE_AUTH, AUTOMATIC, 1, "Sin lectura de odómetro"),
    RuleDef("R02", "Odómetro con error de digitación", BEFORE_AUTH, AUTOMATIC, 1,
            "Lectura atípica explicable por un dígito (cambiado, faltante, de más o invertido)",
            {"typo_tolerance_km": 20}, {"typo_tolerance_km": "Margen del valor corregido (km)"}),
    RuleDef("R03", "Odómetro inconsistente", BEFORE_AUTH, REVIEW, 2,
            "Lectura atípica no explicable: retrocede más de 50 km o implica más de 1.200 km por día",
            {"rollback_km": 50, "max_km_per_day": 1200},
            {"rollback_km": "Retroceso tolerado (km)", "max_km_per_day": "Máximo de km por día"}),
    RuleDef("R04", "Salto de kilometraje", BEFORE_AUTH, REVIEW, 2,
            "Más de 1.000 km desde el último tanqueo, en 10 días o menos",
            {"max_jump_km": 1000, "max_days": 10},
            {"max_jump_km": "Salto máximo (km)", "max_days": "Ventana (días)"}),
    RuleDef("R05", "Recarga sin recorrido", BEFORE_AUTH, REVIEW, 3,
            "Menos de 30 km desde la carga del mismo combustible y 50 % o más de su carga típica",
            {"min_km": 30, "load_fraction": 0.5},
            {"min_km": "Recorrido mínimo (km)", "load_fraction": "Fracción de la carga típica"}),
    RuleDef("R06", "Frecuencia excesiva", BEFORE_AUTH, AUTOMATIC, 2,
            "Más de 3 cargas de líquido o más de 5 de gas en 24 h",
            {"max_liquid_24h": 3, "max_cng_24h": 5},
            {"max_liquid_24h": "Cargas de líquido en 24 h", "max_cng_24h": "Cargas de gas en 24 h"}),
    RuleDef("R07", "Carga superior a su capacidad típica", BEFORE_AUTH, REVIEW, 3,
            "Más de 1,5 veces sus cargas más grandes del mismo combustible",
            {"factor": 1.5}, {"factor": "Veces sus cargas más grandes"}),
    RuleDef("R08", "Sin servicios en EOM", BEFORE_AUTH, REVIEW, 2,
            "Sin servicios con desplazamiento en ±24 h",
            {"window_h": 24}, {"window_h": "Ventana (± horas)"}),
    RuleDef("R09", "Tanqueo nocturno sin servicio", BEFORE_AUTH, REVIEW, 2,
            "Entre las 22 y las 4 h sin servicio en ±3 h",
            {"night_start_h": 22, "night_end_h": 4, "window_h": 3},
            {"night_start_h": "Inicio de la franja (h)", "night_end_h": "Fin de la franja (h)",
             "window_h": "Ventana (± horas)"}),
    RuleDef("R10", "Estación fuera de la zona de operación", BEFORE_AUTH, REVIEW, 3,
            "Regional incompatible con los departamentos de sus servicios"),
    RuleDef("R11", "Venta fuera del sistema o recuperada", AT_RECONCILIATION, REVIEW, 2,
            "Tipo de venta distinto de \"En línea\""),
    RuleDef("R12", "Carga fraccionada sobre el tope", AT_RECONCILIATION, REVIEW, 2,
            "Mismo producto en 30 min por más de $150.000",
            {"window_min": 30, "amount_cop": 150000},
            {"window_min": "Ventana (min)", "amount_cop": "Valor acumulado ($)"}),
    RuleDef("R13", "Transacción de valor mínimo", AT_RECONCILIATION, AUTOMATIC, 1,
            "Transacción de menos de $2.000",
            {"amount_cop": 2000}, {"amount_cop": "Valor mínimo ($)"}),
    RuleDef("R14", "Precio unitario atípico", AT_RECONCILIATION, AUTOMATIC, 1,
            "±15 % frente a la mediana de la estación (±7 días)",
            {"max_deviation": 0.15, "window_days": 7},
            {"max_deviation": "Desviación máxima (fracción)", "window_days": "Ventana (± días)"}),
    # Reconciliation controls of the prototype (authorized vs. recorded, in product and amount).
    RuleDef("C01", "Producto distinto al de la ficha técnica", AT_RECONCILIATION, AUTOMATIC, 2,
            "Gasolina Extra en un vehículo cuya ficha pide Corriente"),
    RuleDef("C02", "Valor distinto al autorizado", AT_RECONCILIATION, AUTOMATIC, 2,
            "Diferencia de más de 5 % entre lo autorizado y lo registrado por el proveedor",
            {"max_difference": 0.05}, {"max_difference": "Diferencia máxima (fracción)"}),
    # Vehicle rules: computed by the 90-day analysis, loaded with the seed.
    RuleDef("V01", "Rendimiento bajo", VEHICLE, REVIEW, 3, "Menos del 75 % de la mediana de su grupo",
            {"factor": 0.75}, {"factor": "Fracción de la mediana del grupo"}),
    RuleDef("V02", "Rendimiento alto", VEHICLE, REVIEW, 2, "Más del 140 % de la mediana de su grupo",
            {"factor": 1.40}, {"factor": "Fracción de la mediana del grupo"}),
    RuleDef("V03", "Caída reciente", VEHICLE, REVIEW, 2, "Últimas 8 cargas por debajo del 75 % de su rendimiento",
            {"factor": 0.75, "loads": 8}, {"factor": "Fracción de su rendimiento", "loads": "Cargas recientes"}),
    RuleDef("V04", "Odómetro congelado", VEHICLE, REVIEW, 3,
            "30 % o más de los tanqueos con el mismo odómetro (la foto del tablero se vuelve obligatoria)",
            {"share": 0.30}, {"share": "Fracción de tanqueos"}),
    RuleDef("V05", "Sin servicios en EOM", VEHICLE, REVIEW, 3, "Ningún servicio en EOM en 90 días",
            {"days": 90}, {"days": "Ventana (días)"}),
    RuleDef("V06", "Usa los dos proveedores", VEHICLE, REVIEW, 1, "Carga con Terpel y con GoPass"),
    RuleDef("V07", "Odómetro con problemas", VEHICLE, REVIEW, 1,
            "10 % o más de los tanqueos sin odómetro o con lectura atípica",
            {"share": 0.10}, {"share": "Fracción de tanqueos"}),
    RuleDef("V08", "Muchas alertas", VEHICLE, REVIEW, 2, "20 % o más de los tanqueos con alerta (mínimo 10)",
            {"share": 0.20, "min_events": 10}, {"share": "Fracción de tanqueos", "min_events": "Mínimo de tanqueos"}),
]

CATALOG_BY_CODE: dict[str, RuleDef] = {r.code: r for r in CATALOG}

# Group medians from the report (section 4.2) and their units.
GROUP_MEDIANS = {
    "gasoline": 41.8,
    "dual_fuel": 52.7,
    "light_diesel": 34.0,
    "heavy_diesel": 16.0,
    "cng": 18.0,
}
GROUP_LABELS = {
    "gasoline": "Gasolina",
    "dual_fuel": "Bicombustible",
    "light_diesel": "Diésel liviano",
    "heavy_diesel": "Diésel pesado",
    "cng": "Gas",
}
EFFICIENCY_UNITS = {
    "gasoline": "km/gal",
    "dual_fuel": "km/gal-eq",
    "light_diesel": "km/gal",
    "heavy_diesel": "km/gal",
    "cng": "km/m³",
}
CNG_M3_PER_GALLON = 5.3  # assumption S4 of the report

TRAFFIC_LIGHT_LABELS = {"green": "Verde", "yellow": "Amarillo", "red": "Rojo"}
PRIORITY_LABELS = {"high": "Alta", "medium": "Media", "low": "Baja"}


def traffic_light(points: int, has_inconsistency: bool = False) -> str:
    """Green: no rule and no inconsistency. Yellow: 1 to 3 points or an inconsistency. Red: 4 or more."""
    if points >= 4:
        return "red"
    if points >= 1 or has_inconsistency:
        return "yellow"
    return "green"


def priority(points: int) -> str:
    """High with 4 or more points (review in 48 h), medium with 2 or 3, low with 1 (within the week)."""
    if points >= 4:
        return "high"
    if points >= 2:
        return "medium"
    return "low"
