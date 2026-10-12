import { Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { forkJoin } from 'rxjs';
import { ApiService } from '../../core/api.service';
import { DemoService } from '../../core/demo.service';
import { formatNumber } from '../../core/format';
import { Priority } from '../../core/models';
import { SHARED } from '../../shared';

interface Indicator {
  key: string;
  name: string;
  baseline: string;
  target: string;
  current_value: number | null;
  current_display: string;
  unit: string;
  target_value: number;
  higher_is_better: boolean;
  source: 'demo' | 'illustrative';
  source_label: string;
  status: 'met' | 'at_risk' | 'not_met' | 'no_data';
  status_label: string;
  note: string;
}

interface DashboardResponse {
  generated_at: string;
  pilot: { zone: string; vehicles: number; refuels_per_day: number; services_per_day: number; weeks: number; note: string };
  activity: { requests: number; decisions: number; authorizations: number; alerts_open: number; alerts_reviewed: number };
  indicators: Indicator[];
  context: {
    requests_per_day: number;
    minutes_per_request_today: number;
    hours_today: number;
    shift_hours: number;
    minutes_per_request_target: number;
    hours_target: number;
    title: string;
    text: string;
  };
  decision: { title: string; options: { key: 'expand' | 'adjust' | 'stop'; label: string; text: string }[]; note: string };
}

interface OpenAlert {
  rule_codes: string[];
  priority: Priority;
  created_at: string;
  overdue: boolean;
}

const STATUS_TONE: Record<Indicator['status'], string> = {
  met: 'green',
  at_risk: 'yellow',
  not_met: 'red',
  no_data: 'neutral',
};

const POLL_MS = 5000;
// Geometry of the context chart (SVG user units).
const CHART = { left: 4, width: 300, max: 70 };

/** Pilot dashboard: 9 indicators against baseline and target, open deviations and the closing decision. */
@Component({
  selector: 'app-dashboard-page',
  imports: [SHARED],
  templateUrl: './dashboard.page.html',
  styleUrl: './dashboard.page.css',
})
export class DashboardPage {
  private readonly api = inject(ApiService);
  private readonly demo = inject(DemoService);

  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  protected readonly data = signal<DashboardResponse | null>(null);
  private readonly openAlerts = signal<OpenAlert[]>([]);

  protected readonly tone = (status: Indicator['status']) => STATUS_TONE[status] ?? 'neutral';

  protected readonly metCount = computed(
    () => (this.data()?.indicators ?? []).filter((i) => i.status === 'met').length,
  );

  /** Bars of "hours of management per day": today, available shifts and with the MVP. */
  protected readonly chart = computed(() => {
    const ctx = this.data()?.context;
    if (!ctx) return null;
    const x = (hours: number) => (hours / CHART.max) * CHART.width;
    const hours = (value: number) => formatNumber(value, 0, 1) + ' h';
    return {
      left: CHART.left,
      shiftX: CHART.left + x(ctx.shift_hours),
      shiftLabel: hours(ctx.shift_hours) + ' de turnos',
      bars: [
        {
          label: 'Hoy: ' + ctx.requests_per_day + ' solicitudes de ' + ctx.minutes_per_request_today + ' min',
          value: hours(ctx.hours_today),
          width: x(ctx.hours_today),
          tone: 'crit',
          y: 24,
        },
        {
          label: 'Con el MVP: ' + ctx.minutes_per_request_target + ' min por solicitud',
          value: hours(ctx.hours_target),
          width: x(ctx.hours_target),
          tone: 'good',
          y: 76,
        },
      ],
      overload: formatNumber(ctx.hours_today / ctx.shift_hours, 1, 1),
    };
  });

  protected readonly deviations = computed(() => {
    const alerts = this.openAlerts();
    const now = Date.now();
    const count = (test: (a: OpenAlert) => boolean) => alerts.filter(test).length;
    const ageDays = (a: OpenAlert) => (now - new Date(a.created_at).getTime()) / 86_400_000;
    const byRule = new Map<string, number>();
    for (const alert of alerts) for (const code of alert.rule_codes) byRule.set(code, (byRule.get(code) ?? 0) + 1);
    const rules = [...byRule.entries()]
      .map(([code, total]) => ({ code, total }))
      .sort((a, b) => b.total - a.total || a.code.localeCompare(b.code));
    const top = rules.slice(0, 8);
    const max = Math.max(1, ...top.map((r) => r.total));
    return {
      total: alerts.length,
      overdue: count((a) => a.overdue),
      priority: [
        { label: 'Alta', hint: '48 h', tone: 'crit', total: count((a) => a.priority === 'high') },
        { label: 'Media', hint: 'semana', tone: 'warn', total: count((a) => a.priority === 'medium') },
        { label: 'Baja', hint: 'semana', tone: 'muted', total: count((a) => a.priority === 'low') },
      ],
      rules: top.map((r) => ({ ...r, width: (r.total / max) * 100 })),
      moreRules: rules.length - top.length,
      age: [
        { label: 'Menos de 48 h', total: count((a) => ageDays(a) < 2) },
        { label: '2 a 7 días', total: count((a) => ageDays(a) >= 2 && ageDays(a) <= 7) },
        { label: 'Más de 7 días', total: count((a) => ageDays(a) > 7) },
      ],
    };
  });

  /** Which closing decision would apply today, read from the indicators as the report states it. */
  protected readonly verdict = computed(() => {
    const indicators = this.data()?.indicators ?? [];
    const get = (key: string) => indicators.find((i) => i.key === key);
    const check = (key: string, label: string, test: (value: number) => boolean) => {
      const indicator = get(key);
      const value = indicator?.current_value ?? null;
      return { label, display: indicator?.current_display ?? 'Sin datos', ok: value !== null && test(value) };
    };
    const criteria = [
      check('attention_time', 'Mediana de 3 min o menos', (v) => v <= 3),
      check('complete_first_try', '90 % o más completas', (v) => v >= 0.9),
      check('one_click', '60 % o más en un clic', (v) => v >= 0.6),
      check('assistant_usage', '80 % o más por el asistente', (v) => v >= 0.8),
      check('high_priority_alerts', 'Precisión de 50 % o más', (v) => v >= 0.5),
      check('continuity', '0 vehículos sin combustible', (v) => v === 0),
    ];
    const stranded = (get('continuity')?.current_value ?? 0) > 0;
    const adoption = get('assistant_usage')?.current_value ?? null;
    let key: 'expand' | 'adjust' | 'stop' = 'adjust';
    let why = 'Algún criterio de ampliación todavía no se cumple: se corrige y se extiende 4 semanas.';
    if (stranded || (adoption !== null && adoption < 0.5)) {
      key = 'stop';
      why = stranded
        ? 'Hay vehículos sin combustible atribuibles al sistema.'
        : 'La adopción del asistente está por debajo del 50 %.';
    } else if (criteria.every((c) => c.ok)) {
      key = 'expand';
      why = 'Se cumplen los seis criterios de ampliación.';
    }
    return { key, why, criteria, met: criteria.filter((c) => c.ok).length };
  });

  constructor() {
    effect(() => {
      this.demo.dataVersion();
      untracked(() => this.load());
    });
    const timer = setInterval(() => this.load(), POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected load(): void {
    forkJoin({
      dashboard: this.api.get<DashboardResponse>('/dashboard', { silent: true }),
      alerts: this.api.get<{ items: OpenAlert[] }>('/alerts', { params: { status: 'open' }, silent: true }),
    }).subscribe({
      next: ({ dashboard, alerts }) => {
        this.data.set(dashboard);
        this.openAlerts.set(alerts.items);
        this.loading.set(false);
        this.failed.set(false);
      },
      error: () => {
        this.loading.set(false);
        this.failed.set(true);
      },
    });
  }
}
