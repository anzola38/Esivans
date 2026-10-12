import { Component, computed, inject, output, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { DemoService } from '../../core/demo.service';
import { RoleService } from '../../core/role.service';
import { ToastService } from '../../core/toast.service';
import { SHARED } from '../../shared';
import { ImportResult } from './alerts.models';
import { AlertsStore } from './alerts.store';

const LINE_STATUS: Record<string, { label: string; tone: string }> = {
  imported: { label: 'Cargada', tone: 'green' },
  duplicate: { label: 'Duplicada', tone: 'neutral' },
  rejected: { label: 'Rechazada', tone: 'red' },
};

/** Reconciliation: load the provider export into the single ledger and list what does not match. */
@Component({
  selector: 'app-reconciliation-tab',
  imports: [SHARED],
  templateUrl: './reconciliation.tab.html',
  styleUrls: ['./alerts.shared.css', './reconciliation.tab.css'],
})
export class ReconciliationTab {
  /** Emits the id of the deviation the coordinator wants to review. */
  readonly review = output<number>();

  protected readonly store = inject(AlertsStore);
  private readonly api = inject(ApiService);
  private readonly demo = inject(DemoService);
  protected readonly roles = inject(RoleService);
  private readonly toast = inject(ToastService);

  protected readonly importing = signal(false);
  protected readonly canImport = computed(() => this.roles.can('provider.import'));
  protected readonly result = this.store.lastImport;
  protected readonly deviations = this.store.reconciliationAlerts;
  protected readonly overpaid = computed(
    () => this.deviations().find((a) => a.evidence.product_difference) ?? null,
  );
  protected readonly otherDeviations = computed(() =>
    this.deviations().filter((a) => a.id !== this.overpaid()?.id),
  );

  protected lineStatus(status: string): { label: string; tone: string } {
    return LINE_STATUS[status] ?? { label: status, tone: 'neutral' };
  }

  protected async loadSample(): Promise<void> {
    if (this.importing() || !this.canImport()) return;
    this.importing.set(true);
    try {
      const response = await fetch(this.api.url('/dev/samples/terpel'));
      if (!response.ok) throw new Error('sample');
      const content = await response.text();
      this.api
        .post<ImportResult>('/integrations/terpel/imports', { filename: 'terpel_ejemplo.csv', content })
        .subscribe({
          next: (result) => {
            this.store.setImport(result);
            this.store.load();
            this.demo.notifyDataChanged();
            this.importing.set(false);
            this.toast.success(result.message, 'Archivo de Terpel cargado');
          },
          error: () => this.importing.set(false),
        });
    } catch {
      this.importing.set(false);
      this.toast.error('No se pudo leer el exporte de ejemplo de Terpel.');
    }
  }
}
