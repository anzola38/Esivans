import { APP_CONFIG } from './config';

/** es-CO formatting helpers. Pure functions: the pipes in shared/pipes wrap them. */

export const NBSP = ' ';
const EMPTY = '—';

export type Numeric = number | string | null | undefined;
export type DateInput = Date | string | number | null | undefined;

function toNumber(value: Numeric): number | null {
  if (value === null || value === undefined || value === '') return null;
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : null;
}

/** 1234.5 -> "1.234,5". Thousands with dot, decimals with comma. */
export function formatNumber(value: Numeric, minDecimals = 0, maxDecimals = minDecimals): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const max = Math.max(minDecimals, maxDecimals);
  let fixed = Math.abs(n).toFixed(max);
  if (max > minDecimals && fixed.includes('.')) {
    // Trim optional trailing zeros down to minDecimals.
    const [int, dec] = fixed.split('.');
    let trimmed = dec;
    while (trimmed.length > minDecimals && trimmed.endsWith('0')) trimmed = trimmed.slice(0, -1);
    fixed = trimmed ? int + '.' + trimmed : int;
  }
  const [intPart, decPart] = fixed.split('.');
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  const sign = n < 0 && Number(fixed) !== 0 ? '-' : '';
  return sign + grouped + (decPart ? ',' + decPart : '');
}

/** 27783 -> "$27.783". Colombian pesos, no decimals. */
export function formatCop(value: Numeric): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  const rounded = Math.round(n);
  return (rounded < 0 ? '-$' : '$') + formatNumber(Math.abs(rounded));
}

/** 73 -> "73 %" (non-breaking space). Pass `isRatio` when the value is 0.73. */
export function formatPercent(value: Numeric, decimals = 0, isRatio = false): string {
  const n = toNumber(value);
  if (n === null) return EMPTY;
  return formatNumber(isRatio ? n * 100 : n, 0, decimals) + NBSP + '%';
}

/** Timestamps without an offset are read as Bogota local time (UTC-5, no DST). */
export function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  if (typeof value === 'number') return new Date(value);
  let text = value.trim().replace(' ', 'T');
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += 'T00:00:00';
  if (!/(Z|[+-]\d{2}:?\d{2})$/i.test(text)) text += '-05:00';
  const date = new Date(text);
  return Number.isNaN(date.getTime()) ? null : date;
}

const partsFormatter = new Intl.DateTimeFormat('en-GB', {
  timeZone: APP_CONFIG.timeZone,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
});

function bogotaParts(date: Date): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of partsFormatter.formatToParts(date)) out[part.type] = part.value;
  return out;
}

/** dd/mm/aaaa */
export function formatDate(value: DateInput): string {
  const date = toDate(value);
  if (!date) return EMPTY;
  const p = bogotaParts(date);
  return p['day'] + '/' + p['month'] + '/' + p['year'];
}

/** h:mm a. m. / p. m. (the single time convention of the app) */
export function formatTime(value: DateInput): string {
  const date = toDate(value);
  if (!date) return EMPTY;
  const p = bogotaParts(date);
  const hour24 = Number(p['hour']) % 24;
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  const suffix = (hour24 < 12 ? 'a.' : 'p.') + NBSP + 'm.';
  return hour12 + ':' + p['minute'] + NBSP + suffix;
}

/** dd/mm/aaaa, h:mm a. m. */
export function formatDateTime(value: DateInput): string {
  const date = toDate(value);
  if (!date) return EMPTY;
  return formatDate(date) + ', ' + formatTime(date);
}

/** Seconds -> "mm:ss" (or "h:mm:ss" from one hour). Negative values keep the sign. */
export function formatDuration(seconds: Numeric): string {
  const n = toNumber(seconds);
  if (n === null) return EMPTY;
  const total = Math.round(Math.abs(n));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (x: number) => String(x).padStart(2, '0');
  const body = h > 0 ? h + ':' + pad(m) + ':' + pad(s) : pad(m) + ':' + pad(s);
  return (n < 0 && total > 0 ? '-' : '') + body;
}

/** "hace 3 min", "hace 2 h", "hace 4 días"; future dates read "en 3 min". */
export function formatTimeAgo(value: DateInput, now: DateInput = new Date()): string {
  const date = toDate(value);
  const ref = toDate(now) ?? new Date();
  if (!date) return EMPTY;
  const diff = Math.round((ref.getTime() - date.getTime()) / 1000);
  const abs = Math.abs(diff);
  if (abs < 45) return diff >= 0 ? 'hace un momento' : 'en un momento';
  let amount: string;
  if (abs < 3600) {
    amount = Math.max(1, Math.round(abs / 60)) + NBSP + 'min';
  } else if (abs < 86400) {
    amount = Math.round(abs / 3600) + NBSP + 'h';
  } else {
    const days = Math.round(abs / 86400);
    amount = days + NBSP + (days === 1 ? 'día' : 'días');
  }
  return (diff >= 0 ? 'hace' : 'en') + NBSP + amount;
}
