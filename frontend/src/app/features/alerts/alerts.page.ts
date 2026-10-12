import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { DemoService } from '../../core/demo.service';
import { SHARED } from '../../shared';
import { AlertsReviewTab } from './alerts-review.tab';
import { AlertsStore } from './alerts.store';
import { ReconciliationTab } from './reconciliation.tab';
import { RulesTab } from './rules.tab';

type TabKey = 'refuels' | 'vehicles' | 'reconciliation' | 'rules';

const TAB_KEY = 'esivans.demo.alertsTab';

/** Coordinator screen: alerts by priority, reconciliation with the provider and the rule catalogue. */
@Component({
  selector: 'app-alerts-page',
  imports: [SHARED, AlertsReviewTab, ReconciliationTab, RulesTab],
  providers: [AlertsStore],
  template: `
    <div class="page page--fill">
      <div class="tabs">
        <div class="tabs__list ui-tabs" role="tablist" aria-label="Secciones de alertas">
          @for (item of tabs(); track item.key) {
            <button
              type="button"
              role="tab"
              class="tabs__tab ui-tab"
              [class.is-active]="tab() === item.key"
              [attr.aria-selected]="tab() === item.key"
              [attr.data-testid]="'tab-' + item.key"
              (click)="setTab(item.key)"
            >
              <app-icon [name]="$any(item.icon)" [size]="17" />
              {{ item.label }}
              @if (item.count !== null) {
                <span class="tabs__count ui-count">{{ item.count }}</span>
              }
            </button>
          }
        </div>
        <div class="tabs__summary" data-testid="alerts-summary">
          <span class="summary summary--open">Abiertas: <strong>{{ summary().open }}</strong></span>
          <span class="summary summary--high">Prioridad alta: <strong>{{ summary().high }}</strong></span>
          <span class="summary summary--late">Vencidas: <strong>{{ summary().overdue }}</strong></span>
        </div>
      </div>

      @switch (tab()) {
        @case ('refuels') {
          <app-alerts-review-tab class="fill" kind="refuel" />
        }
        @case ('vehicles') {
          <app-alerts-review-tab class="fill" kind="vehicle" />
        }
        @case ('reconciliation') {
          <app-reconciliation-tab class="fill" (review)="openAlert($event)" />
        }
        @case ('rules') {
          <app-rules-tab class="fill" />
        }
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
      height: 100%;
    }
    .tabs {
      display: flex;
      align-items: center;
      gap: var(--space-4);
      box-shadow: inset 0 -1px 0 var(--line);
    }
    .tabs__list {
      flex: 1;
    }
    /* Resumen de la bandeja: tres cifras en una sola pieza, con el color como apoyo del rótulo */
    .tabs__summary {
      display: flex;
      flex: none;
      margin-bottom: var(--space-2);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      background: var(--surface);
      box-shadow: var(--shadow-xs);
    }
    .summary {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.3rem 0.75rem;
      font-size: var(--fs-xs);
      font-weight: 700;
      line-height: 1.4;
      color: var(--ink-2);
      white-space: nowrap;
    }
    .summary + .summary {
      border-left: 1px solid var(--line);
    }
    .summary::before {
      content: '';
      flex: none;
      width: 0.5rem;
      height: 0.5rem;
      border-radius: 50%;
      background: var(--navy);
    }
    .summary--high::before {
      background: var(--crit);
    }
    .summary--late::before {
      background: var(--warn);
    }
    .summary strong {
      font-size: var(--fs-sm);
      font-weight: 900;
      color: var(--navy);
      font-variant-numeric: tabular-nums;
    }
    .summary--high strong {
      color: var(--crit-ink);
    }
    .summary--late strong {
      color: var(--warn-ink);
    }
  `,
})
export class AlertsPage {
  private readonly store = inject(AlertsStore);
  private readonly demo = inject(DemoService);

  protected readonly tab = signal<TabKey>(readStoredTab());

  protected readonly tabs = computed(() => {
    const open = (kind: 'refuel' | 'vehicle' | 'reconciliation') =>
      this.store.alerts().filter((a) => a.status === 'open' && (kind === 'refuel' ? a.kind !== 'vehicle' : a.kind === kind))
        .length;
    return [
      { key: 'refuels' as TabKey, label: 'Tanqueos con alerta', icon: 'fuel', count: open('refuel') as number | null },
      { key: 'vehicles' as TabKey, label: 'Vehículos', icon: 'truck', count: open('vehicle') as number | null },
      { key: 'reconciliation' as TabKey, label: 'Conciliación', icon: 'scale', count: open('reconciliation') || null },
      { key: 'rules' as TabKey, label: 'Reglas y umbrales', icon: 'sliders', count: null },
    ];
  });

  protected readonly summary = computed(() => {
    const open = this.store.alerts().filter((a) => a.status === 'open');
    return {
      open: open.length,
      high: open.filter((a) => a.priority === 'high').length,
      overdue: open.filter((a) => a.overdue).length,
    };
  });

  constructor() {
    effect(() => {
      this.demo.dataVersion();
      untracked(() => this.store.load());
    });
  }

  protected setTab(tab: TabKey): void {
    this.tab.set(tab);
    try {
      sessionStorage.setItem(TAB_KEY, tab);
    } catch {
      /* ignore */
    }
  }

  /** From the reconciliation tab: open that deviation in the review list. */
  protected openAlert(id: number): void {
    this.store.focusId.set(id);
    this.setTab('refuels');
  }
}

function readStoredTab(): TabKey {
  try {
    const stored = sessionStorage.getItem(TAB_KEY) as TabKey | null;
    if (stored && ['refuels', 'vehicles', 'reconciliation', 'rules'].includes(stored)) return stored;
  } catch {
    /* ignore */
  }
  return 'refuels';
}
