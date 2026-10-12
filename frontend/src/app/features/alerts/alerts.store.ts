import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { AlertItem, AlertsResponse, ImportResult } from './alerts.models';

const IMPORT_KEY = 'esivans.demo.lastImport';

/** State shared by the tabs of the alerts screen. Provided by the page component. */
@Injectable()
export class AlertsStore {
  private readonly api = inject(ApiService);

  readonly alerts = signal<AlertItem[]>([]);
  readonly loading = signal(true);
  readonly failed = signal(false);
  /** Alert to open when another tab sends the coordinator to the review list. */
  readonly focusId = signal<number | null>(null);
  readonly lastImport = signal<ImportResult | null>(readStoredImport());

  readonly refuelAlerts = computed(() => this.alerts().filter((a) => a.kind !== 'vehicle'));
  readonly vehicleAlerts = computed(() => this.alerts().filter((a) => a.kind === 'vehicle'));
  readonly reconciliationAlerts = computed(() => this.alerts().filter((a) => a.kind === 'reconciliation'));

  load(): void {
    this.api.get<AlertsResponse>('/alerts', { silent: true }).subscribe({
      next: (response) => {
        this.alerts.set(response.items);
        this.failed.set(false);
        this.loading.set(false);
        // After "Reiniciar demo" the provider file is gone: forget the stored summary.
        if (this.lastImport() && !response.items.some((a) => a.kind === 'reconciliation')) {
          this.setImport(null);
        }
      },
      error: () => {
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }

  replace(alert: AlertItem): void {
    this.alerts.update((items) => items.map((item) => (item.id === alert.id ? alert : item)));
  }

  setImport(result: ImportResult | null): void {
    this.lastImport.set(result);
    try {
      if (result) sessionStorage.setItem(IMPORT_KEY, JSON.stringify(result));
      else sessionStorage.removeItem(IMPORT_KEY);
    } catch {
      /* storage unavailable: the summary still lives in memory */
    }
  }
}

function readStoredImport(): ImportResult | null {
  try {
    const raw = sessionStorage.getItem(IMPORT_KEY);
    return raw ? (JSON.parse(raw) as ImportResult) : null;
  } catch {
    return null;
  }
}
