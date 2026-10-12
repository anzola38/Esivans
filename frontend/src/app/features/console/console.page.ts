import { Component, DestroyRef, computed, effect, inject, signal, untracked } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { ApiService } from '../../core/api.service';
import { ClockService } from '../../core/clock.service';
import { DemoService } from '../../core/demo.service';
import { SHARED } from '../../shared';
import { QueueItem, QueueResponse, stageTone } from './request.models';

interface QueueRow extends QueueItem {
  waitNow: number;
  slaNow: number | null;
  isOpen: boolean;
}

const POLL_MS = 3000;

/** Technician queue: ordered by waiting time, with traffic light and SLA countdown. */
@Component({
  selector: 'app-console-page',
  imports: [SHARED, RouterLink],
  template: `
    <div class="page page--fill">
      <app-section-header
        title="Cola de solicitudes"
        subtitle="Ordenada por tiempo de espera. Lo verde se aprueba en un clic; lo amarillo o rojo pide el motivo."
      >
        <div class="queue__counts" data-testid="queue-counts">
          <span class="ui-badge ui-badge--orange">Por decidir: {{ counts().in_review }}</span>
          <span class="ui-badge ui-badge--green"><span class="ui-badge__dot"></span>Verde: {{ counts().green }}</span>
          <span class="ui-badge ui-badge--yellow"><span class="ui-badge__dot"></span>Amarillo: {{ counts().yellow }}</span>
          <span class="ui-badge ui-badge--red"><span class="ui-badge__dot"></span>Rojo: {{ counts().red }}</span>
        </div>
      </app-section-header>

      <app-card class="fill" flush scroll>
        @if (loading()) {
          <div class="queue__pad"><app-skeleton [lines]="5" /></div>
        } @else if (failed() && !rows().length) {
          <app-empty-state
            icon="alert"
            title="No se pudo cargar la cola"
            message="Verifica que el backend esté arriba. La pantalla vuelve a intentar sola."
          />
        } @else if (!rows().length) {
          <app-empty-state
            icon="inbox"
            title="No hay solicitudes en la cola"
            message="Envía una desde el simulador del conductor: aparece aquí apenas el asistente la complete."
          >
            <a appButton routerLink="/simulador">
              <app-icon name="chat" [size]="16" />
              Ir al simulador
            </a>
          </app-empty-state>
        } @else {
          <app-table plain data-testid="queue-table">
            <table>
              <thead>
                <tr>
                  <th>Semáforo</th>
                  <th>Placa</th>
                  <th>Conductor</th>
                  <th>Estado</th>
                  <th class="num">Hora</th>
                  <th class="num">Espera</th>
                  <th class="num">SLA (10 min)</th>
                  <th class="num">Valor</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (row of rows(); track row.id) {
                  <tr
                    class="is-clickable"
                    [class.queue__closed]="!row.isOpen"
                    [attr.data-testid]="'queue-row-' + row.id"
                    [attr.data-plate]="row.vehicle?.plate"
                    (click)="open(row.id)"
                  >
                    <td>
                      <app-traffic-light [value]="row.traffic_light" [points]="row.traffic_light ? row.points : null" />
                      @if (row.rule_codes.length) {
                        <div class="queue__sub">{{ row.rule_codes.join(', ') }}</div>
                      }
                    </td>
                    <td>
                      <div class="fw-700 text-navy">{{ row.vehicle?.plate ?? 'Sin placa' }}</div>
                      <div class="queue__sub">
                        {{ row.vehicle ? row.vehicle.code + ' · ' + row.vehicle.fuel_type_label : 'Vehículo sin identificar' }}
                      </div>
                    </td>
                    <td>
                      <div>{{ row.driver?.name ?? 'Número no registrado' }}</div>
                      @if (!row.driver) {
                        <div class="queue__sub">{{ row.wa_id }}</div>
                      }
                    </td>
                    <td>
                      <span [class]="'ui-badge ui-badge--' + tone(row.stage)">{{ row.stage_label }}</span>
                      @if (row.missing.length) {
                        <div class="queue__sub">Llegó sin: {{ missingText(row) }}</div>
                      }
                    </td>
                    <td class="num">{{ row.occurred_at | esTime }}</td>
                    <td class="num">
                      @if (row.isOpen) {
                        {{ row.waitNow | duration }}
                      } @else {
                        —
                      }
                    </td>
                    <td class="num">
                      @if (row.slaNow === null) {
                        <span class="text-muted">{{ row.isOpen ? 'Decidida' : 'Cerrada' }}</span>
                      } @else if (row.slaNow > 0) {
                        <span class="queue__sla" [class.is-warn]="row.slaNow <= 180">
                          <app-icon name="clock" [size]="14" />
                          {{ row.slaNow | duration }}
                        </span>
                      } @else {
                        <span class="queue__sla is-late">
                          <app-icon name="alert" [size]="14" />
                          Vencido hace {{ -row.slaNow | duration }}
                        </span>
                      }
                    </td>
                    <td class="num">
                      <div class="fw-700">{{ row.authorized_amount ?? row.suggested_amount | cop }}</div>
                      @if (row.authorized_amount !== null) {
                        <div class="queue__sub">Autorizado</div>
                      } @else if (row.suggested_amount !== null) {
                        <div class="queue__sub">Sugerido</div>
                      }
                    </td>
                    <td class="num">
                      <a
                        appButton="outline"
                        size="sm"
                        [routerLink]="['/consola', row.id]"
                        (click)="$event.stopPropagation()"
                      >
                        {{ row.isOpen ? 'Revisar' : 'Ver' }}
                        <app-icon name="chevron-right" [size]="14" />
                      </a>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </app-table>
        }
        <div card-footer class="queue__footer">
          <span>
            <app-icon name="refresh" [size]="13" />
            Se actualiza sola cada 3 segundos.
          </span>
          <span>{{ counts().total }} {{ counts().total === 1 ? 'solicitud' : 'solicitudes' }} hoy</span>
        </div>
      </app-card>
    </div>
  `,
  styles: `
    :host {
      display: block;
      height: 100%;
    }
    .queue__counts {
      display: flex;
      flex-wrap: wrap;
      gap: 0.4rem;
      justify-content: flex-end;
    }
    .queue__pad {
      padding: 1rem;
    }
    .queue__sub {
      font-size: 0.76rem;
      color: var(--muted);
      margin-top: 0.1rem;
    }
    .queue__closed td {
      background: var(--soft);
    }
    .queue__sla {
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      font-weight: 700;
      color: var(--ink-2);
    }
    .queue__sla.is-warn {
      color: var(--warn-ink);
    }
    .queue__sla.is-late {
      color: var(--crit-ink);
    }
    .queue__footer {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      font-size: 0.78rem;
      color: var(--muted);
    }
    .queue__footer span {
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
    }
  `,
})
export class ConsolePage {
  private readonly api = inject(ApiService);
  private readonly demo = inject(DemoService);
  private readonly clock = inject(ClockService);
  private readonly router = inject(Router);

  protected readonly loading = signal(true);
  protected readonly failed = signal(false);
  private readonly data = signal<QueueResponse | null>(null);
  private readonly fetchedAt = signal(Date.now());

  protected readonly counts = computed(
    () =>
      this.data()?.counts ?? { total: 0, in_review: 0, green: 0, yellow: 0, red: 0, sla_breached: 0 },
  );

  /** Rows with the wait and the SLA ticking every second between two refreshes. */
  protected readonly rows = computed<QueueRow[]>(() => {
    const elapsed = Math.max(
      0,
      Math.floor((this.clock.now().getTime() - this.fetchedAt()) / 1000),
    );
    return (this.data()?.items ?? []).map((item) => ({
      ...item,
      isOpen: item.closed_at === null,
      waitNow: item.wait_seconds + (item.closed_at === null ? elapsed : 0),
      slaNow: item.sla_remaining_seconds === null ? null : item.sla_remaining_seconds - elapsed,
    }));
  });

  protected readonly tone = stageTone;

  constructor() {
    effect(() => {
      this.demo.dataVersion();
      untracked(() => this.load());
    });
    const timer = setInterval(() => this.load(), POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected open(id: number): void {
    void this.router.navigate(['/consola', id]);
  }

  protected missingText(row: QueueItem): string {
    return row.missing.map((m) => m.label.toLowerCase()).join(', ');
  }

  private load(): void {
    this.api.get<QueueResponse>('/requests', { silent: true }).subscribe({
      next: (response) => {
        this.fetchedAt.set(Date.now());
        this.data.set(response);
        this.failed.set(false);
        this.loading.set(false);
      },
      error: () => {
        this.failed.set(true);
        this.loading.set(false);
      },
    });
  }
}
