import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { REVIEW_RESULT_LABELS, ReviewResult } from '../../core/models';
import { RoleService } from '../../core/role.service';
import { ToastService } from '../../core/toast.service';
import { SHARED } from '../../shared';
import {
  AlertItem,
  LedgerResponse,
  SUGGESTED_COMMENTS,
  dueText,
  nextActions,
  unitLabel,
} from './alerts.models';
import { AlertsStore } from './alerts.store';

type StatusFilter = 'open' | 'reviewed' | 'all';

const LEDGER_PREVIEW = 8;

/** List of alerts by priority + detail with evidence, single ledger and the review form. */
@Component({
  selector: 'app-alerts-review-tab',
  imports: [SHARED],
  templateUrl: './alerts-review.tab.html',
  styleUrls: ['./alerts.shared.css', './alerts-review.tab.css'],
})
export class AlertsReviewTab {
  readonly kind = input.required<'refuel' | 'vehicle'>();

  protected readonly store = inject(AlertsStore);
  private readonly api = inject(ApiService);
  protected readonly roles = inject(RoleService);
  private readonly toast = inject(ToastService);

  protected readonly filter = signal<StatusFilter>('open');
  protected readonly selectedId = signal<number | null>(null);

  protected readonly source = computed(() =>
    this.kind() === 'vehicle' ? this.store.vehicleAlerts() : this.store.refuelAlerts(),
  );
  protected readonly rows = computed(() => {
    const filter = this.filter();
    const selected = this.selectedId();
    return this.source().filter((a) => filter === 'all' || a.status === filter || a.id === selected);
  });
  protected readonly counts = computed(() => {
    const items = this.source();
    const open = items.filter((a) => a.status === 'open').length;
    return { open, reviewed: items.length - open, all: items.length };
  });
  protected readonly selected = computed(() => this.source().find((a) => a.id === this.selectedId()) ?? null);

  // Review form
  protected readonly results: { value: ReviewResult; label: string; hint: string }[] = [
    { value: 'confirmed', label: REVIEW_RESULT_LABELS.confirmed, hint: 'La desviación es real' },
    { value: 'justified', label: REVIEW_RESULT_LABELS.justified, hint: 'Hay una causa válida' },
    { value: 'data_error', label: REVIEW_RESULT_LABELS.data_error, hint: 'El dato venía mal' },
  ];
  protected readonly result = signal<ReviewResult | null>(null);
  protected readonly comment = signal('');
  protected readonly submitted = signal(false);
  protected readonly saving = signal(false);
  protected readonly editing = signal(false);
  protected readonly canReview = computed(() => this.roles.can('alert.review'));
  protected readonly commentInvalid = computed(() => this.comment().trim().length < 3);
  protected readonly actions = computed(() => {
    const alert = this.selected();
    return alert?.review_result ? nextActions(alert.review_result, alert.rule_codes) : [];
  });

  // Single ledger of the selected vehicle
  protected readonly ledger = signal<LedgerResponse | null>(null);
  protected readonly ledgerLoading = signal(false);
  protected readonly ledgerProvider = signal<string>('all');
  protected readonly ledgerExpanded = signal(false);
  private ledgerCode: string | null = null;

  protected readonly ledgerRows = computed(() => {
    const provider = this.ledgerProvider();
    const entries = (this.ledger()?.entries ?? []).filter((e) => provider === 'all' || e.provider === provider);
    return {
      total: entries.length,
      items: this.ledgerExpanded() ? entries : entries.slice(0, LEDGER_PREVIEW),
    };
  });

  protected readonly efficiencyBars = computed(() => {
    const eff = this.selected()?.evidence.efficiency ?? this.ledger()?.efficiency;
    if (!eff || eff.value === null) return null;
    const max = Math.max(eff.value, eff.group_median, eff.low_limit) * 1.08;
    return {
      eff,
      value: (eff.value / max) * 100,
      median: (eff.group_median / max) * 100,
      limit: (eff.low_limit / max) * 100,
      tone: eff.status === 'low' ? 'crit' : eff.status === 'high' ? 'warn' : 'good',
    };
  });

  protected readonly unit = unitLabel;
  protected readonly due = dueText;

  constructor() {
    // Open the alert another tab asked for, or the first of the list.
    effect(() => {
      const focus = this.store.focusId();
      const source = this.source();
      const rows = this.rows();
      untracked(() => {
        if (focus !== null && source.some((a) => a.id === focus)) {
          this.filter.set('all');
          this.select(focus);
          this.store.focusId.set(null);
        } else if (this.selectedId() === null || !source.some((a) => a.id === this.selectedId())) {
          if (rows.length) this.select(rows[0].id);
          else this.selectedId.set(null);
        }
      });
    });
    effect(() => {
      const code = this.selected()?.vehicle?.code ?? null;
      untracked(() => this.loadLedger(code));
    });
  }

  protected select(id: number): void {
    if (this.selectedId() === id) return;
    this.selectedId.set(id);
    this.result.set(null);
    this.comment.set('');
    this.submitted.set(false);
    this.editing.set(false);
  }

  protected setFilter(filter: StatusFilter): void {
    this.filter.set(filter);
    // `rows()` keeps the selected alert even when it does not match the filter (so a just-reviewed
    // alert stays in view), so the next selection is picked from the alerts that do match.
    const matching = this.source().filter((a) => filter === 'all' || a.status === filter);
    if (!matching.some((a) => a.id === this.selectedId())) this.selectedId.set(null);
    if (matching.length && this.selectedId() === null) this.select(matching[0].id);
  }

  protected pickResult(value: ReviewResult): void {
    const previous = this.result();
    this.result.set(value);
    // Keep what the coordinator typed; only swap an untouched suggestion.
    if (!this.comment().trim() || (previous && this.comment() === SUGGESTED_COMMENTS[previous])) {
      this.comment.set(SUGGESTED_COMMENTS[value]);
    }
  }

  protected startEditing(alert: AlertItem): void {
    this.result.set(alert.review_result);
    this.comment.set(alert.review_comment ?? '');
    this.submitted.set(false);
    this.editing.set(true);
  }

  protected save(alert: AlertItem): void {
    this.submitted.set(true);
    const result = this.result();
    if (!result || this.commentInvalid() || this.saving()) return;
    this.saving.set(true);
    this.api
      .patch<AlertItem>('/alerts/' + alert.id, { review_result: result, comment: this.comment().trim() })
      .subscribe({
        next: (updated) => {
          this.store.replace(updated);
          this.saving.set(false);
          this.editing.set(false);
          this.submitted.set(false);
          this.toast.success(
            'Resultado "' + (updated.review_result_label ?? '') + '" registrado en la bitácora.',
            'Alerta revisada',
          );
        },
        error: () => this.saving.set(false),
      });
  }

  private loadLedger(code: string | null): void {
    if (code === this.ledgerCode) return;
    this.ledgerCode = code;
    this.ledger.set(null);
    this.ledgerProvider.set('all');
    this.ledgerExpanded.set(false);
    if (!code) return;
    this.ledgerLoading.set(true);
    this.api.get<LedgerResponse>('/vehicles/' + code + '/ledger', { silent: true }).subscribe({
      next: (ledger) => {
        if (this.ledgerCode !== code) return;
        this.ledger.set(ledger);
        this.ledgerLoading.set(false);
      },
      error: () => {
        if (this.ledgerCode === code) this.ledgerLoading.set(false);
      },
    });
  }
}
