/** Shared domain vocabulary used across features. Identifiers match the backend (English). */

export type Role = 'technician' | 'coordinator' | 'finance' | 'support';

export type TrafficLight = 'green' | 'yellow' | 'red';

export type RequestStatus =
  | 'received'
  | 'identified'
  | 'awaiting_evidence'
  | 'ready'
  | 'in_review'
  | 'authorized'
  | 'rejected';

export type Priority = 'high' | 'medium' | 'low';

export type ReviewResult = 'confirmed' | 'justified' | 'data_error';

export interface DemoUser {
  /** ASCII-only id, sent as X-Demo-User. */
  id: string;
  name: string;
  initials: string;
}

export interface RoleOption {
  role: Role;
  label: string;
  shortLabel: string;
  user: DemoUser;
}

/** Actions that a role may perform. Every role can open every screen in the demo. */
export type Permission =
  | 'request.decide'
  | 'alert.review'
  | 'rules.edit'
  | 'provider.import'
  | 'demo.reset';

/** Happy-path order, used by the simulator's progress panel. */
export const REQUEST_STATUS_ORDER: readonly RequestStatus[] = [
  'received',
  'identified',
  'awaiting_evidence',
  'ready',
  'in_review',
  'authorized',
];

export const REQUEST_STATUS_LABELS: Record<RequestStatus, string> = {
  received: 'Recibida',
  identified: 'Identificada',
  awaiting_evidence: 'Esperando evidencia',
  ready: 'Lista',
  in_review: 'En revisión',
  authorized: 'Autorizada',
  rejected: 'Rechazada',
};

export const TRAFFIC_LIGHT_LABELS: Record<TrafficLight, string> = {
  green: 'Verde',
  yellow: 'Amarillo',
  red: 'Rojo',
};

export const PRIORITY_LABELS: Record<Priority, string> = {
  high: 'Alta',
  medium: 'Media',
  low: 'Baja',
};

export const REVIEW_RESULT_LABELS: Record<ReviewResult, string> = {
  confirmed: 'Confirmado',
  justified: 'Justificado',
  data_error: 'Error de dato',
};
