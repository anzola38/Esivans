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
        <div class="tabs__list" role="tablist" aria-label="Secciones de alertas">
          @for (item of tabs(); track item.key) {
            <button
              type="button"
              role="tab"
              class="tabs__tab"
              [class.is-active]="tab() === item.key"
              [attr.aria-selected]="tab() === item.key"
              [attr.data-testid]="'tab-' + item.key"
              (click)="setTab(item.key)"
            >
              <app-icon [name]="$any(item.icon)" [size]="16" />
              {{ item.label }}
              @if (item.count !== null) {
                <span class="tabs__count">{{ item.count }}</span>
              }
            </button>
          }
        </div>
        <div class="tabs__summary" data-testid="alerts-summary">
          <span class="ui-badge ui-badge--navy">Abiertas: {{ summary().open }}</span>
          <span class="ui-badge ui-badge--red">Prioridad alta: {{ summary().high }}</span>
          <span class="ui-badge ui-badge--yellow">Vencidas: {{ summary().overdue }}</span>
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
      align-items: flex-end;
      gap: 1rem;
      border-bottom: 1px solid var(--line-strong);
    }
    .tabs__list {
      display: flex;
      gap: 0.15rem;
      flex: 1;
      min-width: 0;
    }
    .tabs__tab {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.5rem 0.8rem;
      margin-bottom: -1px;
      border: 0;
      border-bottom: 3px solid transparent;
      background: transparent;
      color: var(--ink-2);
      font-weight: 700;
      font-size: 0.92rem;
      white-space: nowrap;
      cursor: pointer;
    }
    .tabs__tab:hover {
      color: var(--navy);
      background: var(--blue-soft);
    }
    .tabs__tab.is-active {
      color: var(--navy);
      border-bottom-color: var(--orange);
    }
    .tabs__count {
      min-width: 1.4rem;
      padding: 0 0.35rem;
      border-radius: 999px;
      background: var(--line);
      color: var(--ink-2);
      font-size: 0.74rem;
      line-height: 1.4rem;
      text-align: center;
    }
    .tabs__tab.is-active .tabs__count {
      background: var(--navy);
      color: var(--white);
    }
    .tabs__summary {
      display: flex;
      gap: 0.4rem;
      padding-bottom: 0.45rem;
      flex: none;
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
