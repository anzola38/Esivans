import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { DemoService } from '../../core/demo.service';
import { formatNumber } from '../../core/format';
import { RoleService } from '../../core/role.service';
import { ToastService } from '../../core/toast.service';
import { SHARED } from '../../shared';
import { RuleItem, RulesResponse } from './alerts.models';

const STAGES: { key: RuleItem['stage']; label: string }[] = [
  { key: 'before_authorization', label: 'Antes de autorizar' },
  { key: 'reconciliation', label: 'Al conciliar' },
  { key: 'after_authorization', label: 'Después de autorizar (control posterior)' },
  { key: 'vehicle', label: 'Por vehículo (análisis de 90 días)' },
];

/** Rule catalogue with versions. Only the coordinator can change a threshold (creates a new version). */
@Component({
  selector: 'app-rules-tab',
  imports: [SHARED],
  templateUrl: './rules.tab.html',
  styleUrls: ['./alerts.shared.css', './rules.tab.css'],
})
export class RulesTab {
  private readonly api = inject(ApiService);
  private readonly demo = inject(DemoService);
  protected readonly roles = inject(RoleService);
  private readonly toast = inject(ToastService);

  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  protected readonly rulesVersion = signal('');
  protected readonly rules = signal<RuleItem[]>([]);
  protected readonly selectedCode = signal<string | null>(null);

  protected readonly groups = computed(() =>
    STAGES.map((stage) => ({ ...stage, items: this.rules().filter((r) => r.stage === stage.key) })).filter(
      (group) => group.items.length,
    ),
  );
  protected readonly selected = computed(() => this.rules().find((r) => r.code === this.selectedCode()) ?? null);
  protected readonly canEdit = computed(() => this.roles.can('rules.edit'));

  // Edit form
  protected readonly draft = signal<Record<string, string>>({});
  protected readonly pointsDraft = signal('');
  protected readonly reason = signal('');
  protected readonly submitted = signal(false);
  protected readonly saving = signal(false);

  protected readonly params = computed(() => {
    const rule = this.selected();
    if (!rule) return [];
    return Object.keys(rule.threshold).map((key) => ({
      key,
      label: rule.param_labels[key] ?? key,
      current: rule.threshold[key],
    }));
  });

  /** Changes against the version in force; null when a value is not a valid number. */
  protected readonly changes = computed(() => {
    const rule = this.selected();
    if (!rule) return null;
    const threshold: Record<string, number> = {};
    for (const param of this.params()) {
      const value = parseNumber(this.draft()[param.key]);
      if (value === null || value < 0) return null;
      if (value !== param.current) threshold[param.key] = value;
    }
    const points = parseNumber(this.pointsDraft());
    if (points === null || !Number.isInteger(points) || points < 0 || points > 5) return null;
    const body: { threshold?: Record<string, number>; points?: number } = {};
    if (Object.keys(threshold).length) body.threshold = threshold;
    if (points !== rule.points) body.points = points;
    return body;
  });
  protected readonly hasChanges = computed(() => {
    const changes = this.changes();
    return !!changes && Object.keys(changes).length > 0;
  });
  protected readonly reasonInvalid = computed(() => this.reason().trim().length < 3);

  constructor() {
    effect(() => {
      this.demo.dataVersion();
      untracked(() => this.load());
    });
  }

  protected fmt(value: number): string {
    return formatNumber(value, 0, 3);
  }

  protected thresholdText(rule: Pick<RuleItem, 'param_labels'>, threshold: Record<string, number>): string {
    const keys = Object.keys(threshold);
    if (!keys.length) return 'Sin parámetros';
    return keys.map((key) => (rule.param_labels[key] ?? key) + ': ' + this.fmt(threshold[key])).join(' · ');
  }

  protected select(code: string): void {
    this.selectedCode.set(code);
    this.resetForm();
  }

  protected setParam(key: string, value: string): void {
    this.draft.update((draft) => ({ ...draft, [key]: value }));
  }

  protected resetForm(): void {
    const rule = this.selected();
    const draft: Record<string, string> = {};
    for (const key of Object.keys(rule?.threshold ?? {})) draft[key] = String(rule!.threshold[key]);
    this.draft.set(draft);
    this.pointsDraft.set(String(rule?.points ?? ''));
    this.reason.set('');
    this.submitted.set(false);
  }

  protected save(rule: RuleItem): void {
    this.submitted.set(true);
    const changes = this.changes();
    if (!changes || !this.hasChanges() || this.reasonInvalid() || this.saving() || !this.canEdit()) return;
    this.saving.set(true);
    this.api
      .put<{ rules_version: string; rule: RuleItem }>('/rules/' + rule.code, { ...changes, reason: this.reason().trim() })
      .subscribe({
        next: (response) => {
          this.rulesVersion.set(response.rules_version);
          this.rules.update((rules) => rules.map((r) => (r.code === rule.code ? response.rule : r)));
          this.saving.set(false);
          this.resetForm();
          this.toast.success(
            rule.code + ' quedó en la versión ' + response.rule.version + '. La anterior se conserva en el historial.',
            'Umbral actualizado',
          );
        },
        error: () => this.saving.set(false),
      });
  }

  private load(): void {
    this.api.get<RulesResponse>('/rules', { silent: true }).subscribe({
      next: (response) => {
        this.rules.set(response.items);
        this.rulesVersion.set(response.rules_version);
        this.loading.set(false);
        this.failed.set(false);
        const first = response.items.find((r) => r.code === 'R08') ?? response.items[0];
        if (this.selected()) this.resetForm();
        else if (first) this.select(first.code);
      },
      error: () => {
        this.loading.set(false);
        this.failed.set(true);
      },
    });
  }
}

function parseNumber(raw: string | undefined): number | null {
  const text = (raw ?? '').trim().replace(',', '.');
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}
