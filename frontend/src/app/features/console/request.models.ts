/** Shapes of the request API (GET /requests, GET /requests/{id}) and small display helpers. */
import { TrafficLight } from '../../core/models';
import { formatCop, formatDateTime, formatNumber, formatPercent } from '../../core/format';

export interface Person {
  id: number | null;
  name: string;
  phone: string;
}

export interface VehicleRef {
  id: number;
  code: string;
  plate: string;
  fuel_type: string;
  fuel_type_label: string;
  product: string;
  unit: string;
  group_label?: string;
  tank_capacity?: number;
  provider_label?: string;
  payment_method?: string;
  zone?: string;
  efficiency_unit?: string;
}

export interface MissingItem {
  key: string;
  label: string;
}

export interface StatusStep {
  status: string;
  status_label: string;
  note: string | null;
  at: string;
}

export interface QueueItem {
  id: number;
  status: string;
  status_label: string;
  stage: string;
  stage_label: string;
  traffic_light: TrafficLight | null;
  traffic_light_label: string | null;
  points: number | null;
  rule_codes: string[];
  has_inconsistency: boolean;
  one_click_allowed: boolean;
  suggested_amount: number | null;
  requested_quantity: number | null;
  driver: Person | null;
  wa_id: string;
  vehicle: VehicleRef | null;
  occurred_at: string;
  created_at: string;
  ready_at: string | null;
  closed_at: string | null;
  wait_seconds: number;
  sla_due_at: string | null;
  sla_remaining_seconds: number | null;
  sla_breached: boolean;
  missing: MissingItem[];
  decision_action: string | null;
  decided_by: string | null;
  authorized_amount: number | null;
}

export interface QueueResponse {
  items: QueueItem[];
  counts: {
    total: number;
    in_review: number;
    green: number;
    yellow: number;
    red: number;
    sla_breached: number;
  };
}

export interface EomService {
  id: number;
  external_id: string;
  start: string;
  end: string;
  origin: string;
  destination: string;
  km: number;
  status: string;
  status_label: string;
}

export interface Refuel {
  provider_label: string;
  timestamp: string;
  station: string;
  product: string;
  quantity: number;
  unit: string;
  amount: number;
  odometer: number | null;
  hours_ago?: number;
}

export interface Efficiency {
  value: number | null;
  unit: string;
  group_label: string;
  group_median: number;
  ratio_to_group: number | null;
  difference_pct: number | null;
  low_limit: number;
  high_limit: number;
  status: string;
  status_label: string;
}

export interface Reason {
  code: string;
  kind: string;
  name: string;
  points: number;
  explanation: string;
  threshold?: string;
  treatment_label?: string;
  triggered?: boolean;
  evaluated?: boolean;
}

export interface VehicleFlag {
  code: string;
  name: string;
  points: number;
  explanation: string;
}

export interface CalcStep {
  key: string;
  label: string;
  formula: string;
  result: number;
  display: string;
  unit: string;
}

export interface Calculation {
  computable: boolean;
  needs_refuel: boolean;
  quantity: number | null;
  unit: string;
  price: number | null;
  product: string;
  cap_amount: number | null;
  amount: number | null;
  note: string | null;
  steps: CalcStep[];
  cross_check: { consistent: boolean; explanation: string } | null;
}

export interface Evidence {
  media_id: string;
  photo_url: string;
  odometer_read: number | null;
  odometer_km: number | null;
  odometer_source_label: string | null;
  fuel_level: number | null;
  confidence: { odometer_km?: number | null; fuel_level?: number | null } | null;
  error_label: string | null;
  proposed_odometer: number | null;
  confirmed_by_driver: boolean;
  /** Who read the photo. `mode: 'groq_text'` means it was not sent to Groq: the sample reading was used. */
  ai_source: { provider: string; model: string | null; status: string; mode?: string } | null;
  ai_source_label: string | null;
}

export interface Decision {
  action: 'approve' | 'adjust' | 'reject';
  action_label: string;
  amount: number | null;
  reason: string | null;
  one_click: boolean;
  decided_by: string;
  role_label: string;
  decided_at: string;
  original_amount: number | null;
}

export interface Enablement {
  provider: string;
  provider_label: string;
  payment_method: string;
  plate: string;
  vehicle_code: string;
  product: string;
  amount: number;
  valid_minutes: number;
  suggested_reference: string;
}

export interface Authorization {
  provider_label: string;
  payment_method: string;
  reference: string;
  product: string;
  amount: number;
  enabled_by: string;
  created_at: string;
  expires_at: string;
  expires_at_case_time: string;
  valid_minutes: number;
}

export interface AuditEntry {
  id: number;
  actor: string;
  role_label: string | null;
  action: string;
  summary: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
}

export interface RequestContext {
  last_refuel: Refuel | null;
  km_since_last_refuel: number | null;
  last_valid_odometer: number | null;
  typical_load: number | null;
  loads_24h: number | null;
  providers: string[];
  efficiency: Efficiency | null;
  services: {
    vehicle_in_eom: boolean;
    today: EomService[];
    today_count: number;
    pending_count: number;
    next_service: EomService | null;
    services_24h: number;
  } | null;
  vehicle_flags: VehicleFlag[];
  vehicle: VehicleRef | null;
}

export interface RequestDetail extends QueueItem {
  service: { chosen: EomService | null; note: string | null } | null;
  evidence: Evidence | null;
  context: RequestContext | null;
  evaluation: {
    traffic_light: TrafficLight | null;
    points: number;
    rules_version: string;
    reasons: Reason[];
    checks: Reason[];
  } | null;
  calculation: Calculation | null;
  decision: Decision | null;
  enablement: Enablement | null;
  authorization: Authorization | null;
  status_history: StatusStep[];
  audit: AuditEntry[];
}

/** Badge tone for a request stage (includes the stages the shared chip does not know). */
export function stageTone(stage: string): string {
  switch (stage) {
    case 'awaiting_evidence':
      return 'yellow';
    case 'ready':
      return 'blue';
    case 'in_review':
    case 'pending_enablement':
      return 'orange';
    case 'authorized':
      return 'green';
    case 'rejected':
      return 'red';
    default:
      return 'neutral';
  }
}

export function unitLabel(unit: string | null | undefined): string {
  if (!unit) return '';
  return unit === 'm3' ? 'm³' : unit;
}

const FRACTIONS: Record<string, string> = {
  '0.125': '⅛',
  '0.25': '¼',
  '0.375': '⅜',
  '0.5': '½',
  '0.625': '⅝',
  '0.75': '¾',
  '0.875': '⅞',
};

/** 0.25 -> "¼ de tanque (25 %)". */
export function fuelLevelLabel(level: number | null | undefined): string {
  if (level === null || level === undefined) return '—';
  const percent = formatPercent(level, 0, true);
  const fraction = FRACTIONS[String(level)];
  if (level >= 0.995) return 'Tanque lleno (' + percent + ')';
  return fraction ? fraction + ' de tanque (' + percent + ')' : percent + ' del tanque';
}

/** 0.25 -> "¼ de tanque"; without a clean fraction, "62 % del tanque". */
export function fuelFractionLabel(level: number | null | undefined): string {
  if (level === null || level === undefined) return '—';
  if (level >= 0.995) return 'Tanque lleno';
  const fraction = FRACTIONS[String(level)];
  return fraction ? fraction + ' de tanque' : formatPercent(level, 0, true) + ' del tanque';
}

export function validityLabel(minutes: number): string {
  if (minutes % 60 === 0) {
    const hours = minutes / 60;
    return hours + (hours === 1 ? ' hora' : ' horas');
  }
  return minutes + ' minutos';
}

export function paymentMethodLabel(method: string | null | undefined): string {
  if (method === 'chip') return 'chip';
  if (method === 'card') return 'tarjeta';
  return 'chip o tarjeta';
}

const TRAFFIC: Record<string, string> = { green: 'Verde', yellow: 'Amarillo', red: 'Rojo' };
const ACTIONS: Record<string, string> = { approve: 'Aprobar', adjust: 'Ajustar', reject: 'Rechazar' };
const ERRORS: Record<string, string> = {
  changed_digit: 'dígito cambiado',
  missing_digit: 'dígito faltante',
  extra_digit: 'dígito de más',
  swapped_digits: 'dígitos invertidos',
};
const PROVIDERS: Record<string, string> = { terpel: 'Terpel', gopass: 'GoPass', groq: 'Groq', mock: 'IA simulada' };

const AUDIT_LABELS: Record<string, string> = {
  suggested_amount: 'Valor sugerido',
  traffic_light: 'Semáforo',
  points: 'Puntos',
  rules: 'Reglas',
  action: 'Acción',
  amount: 'Valor',
  reason: 'Motivo',
  one_click: 'En un clic',
  original_amount: 'Valor original',
  reference: 'Referencia',
  product: 'Producto',
  provider: 'Proveedor',
  expires_at: 'Vence',
  fuel_level: 'Nivel',
  odometer_read: 'Km leído',
  odometer_km: 'Km',
  proposed_odometer: 'Km propuesto',
  confidence: 'Confianza',
  ai: 'IA',
  error_type: 'Tipo de error',
  status: 'Estado',
  missing: 'Faltó',
  quantity: 'Cantidad',
};

const AUDIT_HIDDEN = new Set(['rules_version', 'photo_hash', 'photo_path', 'media_id']);

function auditValue(key: string, value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Sí' : 'No';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'ninguna';
  if (key === 'confidence' && value && typeof value === 'object') {
    const c = value as { odometer_km?: number; fuel_level?: number };
    const parts: string[] = [];
    if (typeof c.odometer_km === 'number') parts.push('km ' + formatPercent(c.odometer_km, 0, true));
    if (typeof c.fuel_level === 'number') parts.push('nivel ' + formatPercent(c.fuel_level, 0, true));
    return parts.join(', ');
  }
  if (key === 'ai' && value && typeof value === 'object') {
    return String((value as { label?: string }).label ?? '');
  }
  if (typeof value === 'number') {
    if (key.endsWith('amount')) return formatCop(value);
    if (key === 'fuel_level') return formatPercent(value, 0, true);
    if (key.startsWith('odometer') || key === 'proposed_odometer') return formatNumber(value) + ' km';
    return formatNumber(value, 0, 2);
  }
  if (typeof value === 'string') {
    if (key === 'traffic_light') return TRAFFIC[value] ?? value;
    if (key === 'action') return ACTIONS[value] ?? value;
    if (key === 'error_type') return ERRORS[value] ?? value;
    if (key === 'provider') return PROVIDERS[value] ?? value;
    if (key.endsWith('_at')) return formatDateTime(value);
    return value;
  }
  return '';
}

/** Turns the `before` / `after` JSON of an audit entry into short Spanish lines. */
export function describeAuditData(data: Record<string, unknown> | null): string[] {
  if (!data) return [];
  const lines: string[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (value === null || value === undefined || AUDIT_HIDDEN.has(key)) continue;
    const label = AUDIT_LABELS[key];
    if (!label) continue;
    const text = auditValue(key, value);
    if (text) lines.push(label + ': ' + text);
  }
  return lines;
}
