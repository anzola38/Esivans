import { Priority, ReviewResult } from '../../core/models';

export interface AlertVehicle {
  id: number;
  code: string;
  plate: string;
  fuel_type_label: string;
  group_label: string;
}

export interface AlertReason {
  code: string;
  name: string;
  points: number;
  explanation: string;
}

export interface LedgerEntry {
  id: number;
  provider: string;
  provider_label: string;
  external_id: string;
  timestamp: string;
  station: string;
  region: string;
  product: string;
  tank: string;
  quantity: number;
  unit: string;
  unit_price: number;
  amount: number;
  odometer: number | null;
  km_since_previous: number | null;
  sale_type: string;
  source: string;
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
  source: string;
}

export interface VehicleStats {
  refuels_90d: number;
  amount_90d: number;
  services_90d: number;
  alert_share?: number;
  providers: string[];
}

export interface ProductDifference {
  authorized_product: string;
  sold_product: string;
  sold_price: number;
  corriente_price: number;
  corriente_price_source: string;
  difference_per_gallon: number;
  gallons: number;
  overpaid: number;
}

export interface AlertEvidence {
  source?: string;
  efficiency?: Efficiency;
  stats?: VehicleStats;
  ledger_url?: string;
  transaction?: LedgerEntry;
  previous_transaction?: LedgerEntry | null;
  station_median_price?: number | null;
  product_difference?: ProductDifference | null;
  authorization?: { reference?: string; amount?: number } | null;
  request?: {
    id: number;
    authorized_amount: number;
    suggested_amount: number | null;
    decided_by: string;
    decided_at: string;
    reason: string | null;
    points: number;
    rule_codes: string[];
    reference: string | null;
  } | null;
}

export type AlertKind = 'refuel' | 'vehicle' | 'reconciliation';

export interface AlertItem {
  id: number;
  kind: AlertKind;
  kind_label: string;
  vehicle: AlertVehicle | null;
  rule_code: string;
  rule_codes: string[];
  points: number;
  priority: Priority;
  priority_label: string;
  reason: string;
  reasons: AlertReason[];
  evidence: AlertEvidence;
  rules_version: string;
  status: 'open' | 'reviewed';
  status_label: string;
  review_result: ReviewResult | null;
  review_result_label: string | null;
  review_comment: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  due_at: string;
  deadline_label: string;
  overdue: boolean;
  hours_to_due: number | null;
}

export interface AlertsResponse {
  items: AlertItem[];
  counts: Record<string, number>;
}

export interface LedgerResponse {
  vehicle: { code: string; plate: string; fuel_type_label: string; product: string; provider_label: string };
  efficiency: Efficiency;
  flags: { code: string; name: string; points: number; explanation: string }[];
  stats: VehicleStats;
  summary: {
    refuels: number;
    amount: number;
    providers: { provider: string; provider_label: string; refuels: number; amount: number }[];
    first: string | null;
    last: string | null;
    eom_services_loaded: number;
  };
  comparison: {
    km: number;
    gopass_only: { gallons: number; efficiency: number; unit: string };
    single_ledger: { gallons: number; cng_m3: number; gallon_equivalent: number; efficiency: number; unit: string };
    hidden_cng_loads: number;
    explanation: string;
  } | null;
  entries: LedgerEntry[];
}

export interface ImportLine {
  line: number;
  external_id: string;
  vehicle: string | null;
  status: 'imported' | 'duplicate' | 'rejected';
  message: string | null;
  alert_id?: number;
  rule_codes?: string[];
}

export interface MatchedAuthorization {
  authorization_id: number;
  request_id: number;
  reference: string;
  authorized_amount: number;
  recorded_amount: number;
  difference: number;
  difference_share: number;
  within_tolerance: boolean;
  vehicle: string;
}

export interface ImportResult {
  batch_id: number;
  provider_label: string;
  filename: string | null;
  rows: number;
  imported: number;
  duplicates: number;
  rejected: number;
  alerts_created: number;
  overpaid_by_product: number;
  matched_authorizations: MatchedAuthorization[];
  message: string;
  deviations: AlertItem[];
  lines: ImportLine[];
}

export interface RuleVersion {
  version: number;
  threshold: Record<string, number>;
  points: number;
  valid_from: string;
  author: string;
  change_reason: string | null;
}

export interface RuleItem {
  code: string;
  name: string;
  stage: 'before_authorization' | 'reconciliation' | 'after_authorization' | 'vehicle';
  stage_label: string;
  treatment: 'automatic' | 'review';
  treatment_label: string;
  threshold_text: string;
  threshold: Record<string, number>;
  param_labels: Record<string, string>;
  points: number;
  version: number;
  valid_from: string;
  author: string;
  reviewed: number;
  confirmed: number;
  precision: number | null;
  history: RuleVersion[];
}

export interface RulesResponse {
  rules_version: string;
  can_edit: boolean;
  items: RuleItem[];
}

export interface NextAction {
  title: string;
  action: string;
  owner: string;
  closes: string;
}

const EFFICIENCY_RULES = ['V01', 'V03'];

/** What follows each review result, as the report's deviation table defines it (section 6). */
export function nextActions(result: ReviewResult, ruleCodes: string[]): NextAction[] {
  if (result === 'justified') {
    return [
      {
        title: 'Justificada',
        action: 'Se registra la causa y, si se repite, una excepción con vigencia (por ejemplo, una ruta de montaña).',
        owner: 'Técnico',
        closes: 'Al registrar la causa o al vencer la excepción.',
      },
    ];
  }
  if (result === 'data_error') {
    return [
      {
        title: 'Error de dato',
        action: 'Se corrige en la fuente: odómetro, ficha técnica o asignación en EOM.',
        owner: 'Técnico; el proveedor si el dato es suyo',
        closes: 'Cuando el dato queda corregido.',
      },
    ];
  }
  const actions: NextAction[] = [];
  if (ruleCodes.some((code) => EFFICIENCY_RULES.includes(code))) {
    actions.push({
      title: 'Confirmada: rendimiento bajo o caída reciente',
      action: 'Revisión mecánica del vehículo; mientras tanto, el valor sugerido usa su rendimiento real.',
      owner: 'Coordinador con mantenimiento',
      closes: 'Cuando el vehículo vuelve a su rango por 4 semanas.',
    });
  }
  if (ruleCodes.some((code) => !EFFICIENCY_RULES.includes(code))) {
    actions.push({
      title: 'Confirmada: uso indebido (otra placa, recarga sin recorrido, carga sin servicio)',
      action: 'Conversación con el conductor con la evidencia; si se repite, se aplica el reglamento interno.',
      owner: 'Coordinador',
      closes: 'Con la decisión y su soporte en la bitácora.',
    });
  }
  return actions;
}

export const SUGGESTED_COMMENTS: Record<ReviewResult, string> = {
  confirmed: 'Se revisó la evidencia con el técnico y se confirma la desviación.',
  justified: 'El coordinador de zona confirmó la causa: operación especial ya registrada.',
  data_error: 'El dato venía mal desde la fuente; se pide la corrección.',
};

export function unitLabel(unit: string | null | undefined): string {
  return unit === 'm3' ? 'm³' : (unit ?? '');
}

/** "Vence en 11 h", "Vence en 5 días" or "Vencida hace 36 h". */
export function dueText(alert: Pick<AlertItem, 'hours_to_due' | 'overdue'>): string {
  const hours = alert.hours_to_due;
  if (hours === null) return '';
  const abs = Math.abs(hours);
  const amount = abs >= 48 ? Math.round(abs / 24) + ' días' : Math.max(1, Math.round(abs)) + ' h';
  return hours < 0 || alert.overdue ? 'Vencida hace ' + amount : 'Vence en ' + amount;
}
