import { HttpErrorResponse } from '@angular/common/http';
import { Component, DestroyRef, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { describeHttpError } from '../../core/api.interceptor';
import { ApiService } from '../../core/api.service';
import { ClockService } from '../../core/clock.service';
import { DemoService } from '../../core/demo.service';
import { formatCop, formatPercent } from '../../core/format';
import { RoleService } from '../../core/role.service';
import { ToastService } from '../../core/toast.service';
import { SHARED } from '../../shared';
import {
  RequestDetail,
  describeAuditData,
  fuelFractionLabel,
  paymentMethodLabel,
  stageTone,
  unitLabel,
  validityLabel,
} from './request.models';

type DecisionMode = 'approve' | 'adjust' | 'reject';

interface BarRow {
  label: string;
  value: number;
  percent: number;
  tone: string;
}

const POLL_MS = 3000;
const MIN_REASON = 5;
const SLA_SECONDS = 600;

const MODE_TEXT: Record<DecisionMode, { title: string; confirm: string; suggestions: string[] }> = {
  approve: {
    title: 'Aprobar con motivo',
    confirm: 'Aprobar',
    suggestions: [
      'Kilometraje corregido y confirmado por el conductor',
      'Recorrido confirmado con el coordinador',
    ],
  },
  adjust: {
    title: 'Ajustar el valor',
    confirm: 'Guardar ajuste',
    suggestions: [
      'Apoyo nocturno confirmado con el coordinador',
      'Ruta adicional asignada por fuera de EOM',
    ],
  },
  reject: {
    title: 'Rechazar la solicitud',
    confirm: 'Rechazar',
    suggestions: ['Sin servicio que respalde la carga', 'Recarga reciente sin recorrido'],
  },
};

/** Request detail: evidence, single-ledger context, reasons, value, decision and audit log. */
@Component({
  selector: 'app-console-detail-page',
  imports: [SHARED, RouterLink],
  templateUrl: './console-detail.page.html',
  styleUrls: ['./console-detail.page.css', './console-detail.cards.css'],
})
export class ConsoleDetailPage {
  private readonly api = inject(ApiService);
  private readonly demo = inject(DemoService);
  private readonly clock = inject(ClockService);
  private readonly toasts = inject(ToastService);
  protected readonly roles = inject(RoleService);

  /** Route param `:id`. */
  readonly id = input<string>();

  protected readonly detail = signal<RequestDetail | null>(null);
  protected readonly notFound = signal(false);
  private readonly fetchedAt = signal(Date.now());

  protected readonly busy = signal(false);
  protected readonly mode = signal<DecisionMode | null>(null);
  protected readonly amount = signal<number | null>(null);
  protected readonly reason = signal('');
  protected readonly submitted = signal(false);
  protected readonly serverError = signal<string | null>(null);

  protected readonly reference = signal('');
  protected readonly referenceTouched = signal(false);
  protected readonly photoOpen = signal(false);

  /** The backend lets the technician and the coordinator decide and enable. */
  protected readonly canDecide = computed(() =>
    ['technician', 'coordinator'].includes(this.roles.role()),
  );

  protected readonly isPendingDecision = computed(() => {
    const d = this.detail();
    return !!d && d.status === 'in_review' && !d.decision;
  });

  protected readonly slaRemaining = computed(() => {
    const d = this.detail();
    if (!d || d.sla_remaining_seconds === null) return null;
    const elapsed = Math.floor((this.clock.now().getTime() - this.fetchedAt()) / 1000);
    return d.sla_remaining_seconds - Math.max(0, elapsed);
  });

  /** Share of the 10-minute SLA still available, for the countdown bar. */
  protected slaPercent(seconds: number): number {
    return Math.max(0, Math.min(100, (seconds / SLA_SECONDS) * 100));
  }

  protected readonly modeText = computed(() => {
    const mode = this.mode();
    return mode ? MODE_TEXT[mode] : null;
  });

  protected readonly reasonError = computed(() =>
    this.reason().trim().length < MIN_REASON
      ? 'Escribe el motivo (mínimo ' + MIN_REASON + ' caracteres): queda en la bitácora.'
      : null,
  );

  protected readonly amountError = computed(() => {
    if (this.mode() !== 'adjust') return null;
    const value = this.amount();
    const cap = this.detail()?.calculation?.cap_amount ?? null;
    if (value === null || !Number.isFinite(value) || value <= 0) {
      return 'Escribe un valor mayor que $0.';
    }
    if (!Number.isInteger(value)) return 'El valor va en pesos, sin decimales.';
    if (cap !== null && value > cap) {
      return 'No puede pasar del tope del vehículo (' + formatCop(cap) + ').';
    }
    return null;
  });

  protected readonly referenceError = computed(() => {
    const length = this.reference().trim().length;
    return length < 3 || length > 60 ? 'Escribe la referencia que entrega el portal (3 a 60 caracteres).' : null;
  });

  /** Comparative bars: the vehicle against the median of its group. */
  protected readonly efficiencyBars = computed<{ rows: BarRow[]; limit: number } | null>(() => {
    const eff = this.detail()?.context?.efficiency;
    if (!eff || eff.value === null) return null;
    const max = Math.max(eff.value, eff.group_median) * 1.12;
    const tone = eff.status === 'low' ? 'crit' : eff.status === 'high' ? 'warn' : 'good';
    return {
      rows: [
        { label: 'Vehículo', value: eff.value, percent: (eff.value / max) * 100, tone },
        {
          label: 'Su grupo',
          value: eff.group_median,
          percent: (eff.group_median / max) * 100,
          tone: 'group',
        },
      ],
      limit: (eff.low_limit / max) * 100,
    };
  });

  protected readonly efficiencyLabel = computed(() => {
    const eff = this.detail()?.context?.efficiency;
    if (!eff) return '';
    if (eff.status === 'normal' || eff.difference_pct === null) return eff.status_label;
    return (
      eff.status_label +
      ': ' +
      formatPercent(Math.abs(eff.difference_pct), 0, true) +
      (eff.difference_pct < 0 ? ' menos' : ' más')
    );
  });

  protected readonly auditRows = computed(() =>
    (this.detail()?.audit ?? []).map((entry) => ({
      ...entry,
      beforeLines: describeAuditData(entry.before),
      afterLines: describeAuditData(entry.after),
      rulesVersion:
        (entry.after?.['rules_version'] as string | undefined) ??
        (entry.before?.['rules_version'] as string | undefined) ??
        this.detail()?.evaluation?.rules_version ??
        '—',
    })),
  );

  protected readonly stageTone = stageTone;
  protected readonly unitLabel = unitLabel;
  protected readonly fuelFractionLabel = fuelFractionLabel;
  protected readonly validityLabel = validityLabel;
  protected readonly paymentMethodLabel = paymentMethodLabel;

  constructor() {
    effect(() => {
      this.id();
      this.demo.dataVersion();
      untracked(() => {
        this.detail.set(null);
        this.notFound.set(false);
        this.load();
      });
    });
    const timer = setInterval(() => {
      if (!this.busy()) this.load();
    }, POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected confidenceTone(value: number | null | undefined): string {
    if (value === null || value === undefined) return 'neutral';
    return value >= 0.9 ? 'good' : value >= 0.8 ? 'warn' : 'crit';
  }

  // ---------- Decision ----------

  protected approve(): void {
    const d = this.detail();
    if (!d || !this.canDecide()) return;
    if (d.one_click_allowed) this.submitDecision({ action: 'approve' });
    else this.openMode('approve');
  }

  protected openMode(mode: DecisionMode): void {
    if (!this.canDecide()) return;
    this.mode.set(mode);
    this.reason.set('');
    this.amount.set(this.detail()?.suggested_amount ?? null);
    this.submitted.set(false);
    this.serverError.set(null);
  }

  protected closeMode(): void {
    if (!this.busy()) this.mode.set(null);
  }

  protected onReasonInput(event: Event): void {
    this.reason.set((event.target as HTMLTextAreaElement).value);
  }

  protected onAmountInput(event: Event): void {
    const raw = (event.target as HTMLInputElement).value;
    this.amount.set(raw === '' ? null : Number(raw));
  }

  protected confirmMode(): void {
    const mode = this.mode();
    if (!mode) return;
    this.submitted.set(true);
    if (this.reasonError() || this.amountError()) return;
    const body: Record<string, unknown> = { action: mode, reason: this.reason().trim() };
    if (mode === 'adjust') body['amount'] = this.amount();
    this.submitDecision(body);
  }

  private submitDecision(body: Record<string, unknown>): void {
    const d = this.detail();
    // A fast double click must not send the decision twice (the second one would answer 409).
    if (!d || this.busy()) return;
    this.busy.set(true);
    this.serverError.set(null);
    this.api
      .post<RequestDetail>('/requests/' + d.id + '/decision', body, { silent: this.mode() !== null })
      .subscribe({
        next: (detail) => {
          this.busy.set(false);
          this.mode.set(null);
          this.applyDetail(detail);
          this.reference.set(detail.enablement?.suggested_reference ?? '');
          this.referenceTouched.set(false);
          const action = detail.decision?.action;
          // Approve and adjust need no toast: the enablement panel that appears is the feedback.
          if (action === 'reject') {
            this.toasts.success('Solicitud rechazada: el conductor recibió el motivo.');
          }
          this.demo.notifyDataChanged();
        },
        error: (error: HttpErrorResponse) => {
          this.busy.set(false);
          this.serverError.set(describeHttpError(error));
          if (error.status === 409) this.load();
        },
      });
  }

  // ---------- Enablement ----------

  protected onReferenceInput(event: Event): void {
    this.reference.set((event.target as HTMLInputElement).value);
    this.referenceTouched.set(true);
  }

  protected copy(text: string, label: string): void {
    const done = (): void => this.toasts.info(label + ' en el portapapeles.', 'Copiado');
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done, () => this.copyFallback(text, done));
    } else {
      this.copyFallback(text, done);
    }
  }

  protected copyAll(): void {
    const e = this.detail()?.enablement;
    if (!e) return;
    const text = [
      'Proveedor: ' + e.provider_label,
      'Placa: ' + e.plate,
      'Valor: ' + e.amount,
      'Producto: ' + e.product,
      'Vigencia: ' + validityLabel(e.valid_minutes),
    ].join('\n');
    this.copy(text, 'Datos de la habilitación');
  }

  protected confirmEnablement(): void {
    const d = this.detail();
    this.referenceTouched.set(true);
    if (!d || this.referenceError() || !this.canDecide() || this.busy()) return;
    this.busy.set(true);
    this.api
      .post<RequestDetail>('/requests/' + d.id + '/authorization', {
        reference: this.reference().trim(),
      })
      .subscribe({
        next: (detail) => {
          this.busy.set(false);
          this.applyDetail(detail);
          this.toasts.success(
            'Habilitación confirmada: el conductor recibió valor, producto, referencia y vigencia.',
          );
          this.demo.notifyDataChanged();
        },
        error: () => {
          this.busy.set(false);
          this.load();
        },
      });
  }

  // ---------- Data ----------

  private load(): void {
    const id = this.id();
    if (!id) return;
    this.api.get<RequestDetail>('/requests/' + id, { silent: true }).subscribe({
      next: (detail) => {
        if (String(detail.id) === this.id()) this.applyDetail(detail);
      },
      error: (error: HttpErrorResponse) => {
        if (error.status === 404) this.notFound.set(true);
      },
    });
  }

  private applyDetail(detail: RequestDetail): void {
    const previous = this.detail();
    this.fetchedAt.set(Date.now());
    this.detail.set(detail);
    this.notFound.set(false);
    // Prefill the reference once, when the enablement panel first appears.
    if (detail.enablement && !previous?.enablement && !this.referenceTouched()) {
      this.reference.set(detail.enablement.suggested_reference);
    }
  }

  private copyFallback(text: string, done: () => void): void {
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try {
      document.execCommand('copy');
      done();
    } catch {
      this.toasts.warning('No se pudo copiar: selecciona el texto a mano.');
    }
    area.remove();
  }
}
