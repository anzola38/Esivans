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
const SLA_SECONDS = 600;

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
          <span class="queue__count queue__count--pending">Por decidir: <strong class="queue__count-n">{{ counts().in_review }}</strong></span>
          <span class="queue__count queue__count--green"><span class="queue__dot" aria-hidden="true"></span>Verde: <strong class="queue__count-n">{{ counts().green }}</strong></span>
          <span class="queue__count queue__count--yellow"><span class="queue__dot" aria-hidden="true"></span>Amarillo: <strong class="queue__count-n">{{ counts().yellow }}</strong></span>
          <span class="queue__count queue__count--red"><span class="queue__dot" aria-hidden="true"></span>Rojo: <strong class="queue__count-n">{{ counts().red }}</strong></span>
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
                    class="is-clickable queue__row"
                    [class.queue__closed]="!row.isOpen"
                    [class.is-green]="row.traffic_light === 'green'"
                    [class.is-yellow]="row.traffic_light === 'yellow'"
                    [class.is-red]="row.traffic_light === 'red'"
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
                      <div class="queue__plate">{{ row.vehicle?.plate ?? 'Sin placa' }}</div>
                      <div class="queue__sub">
                        {{ row.vehicle ? row.vehicle.code + ' · ' + row.vehicle.fuel_type_label : 'Vehículo sin identificar' }}
                      </div>
                    </td>
                    <td>
                      <div class="queue__driver">{{ row.driver?.name ?? 'Número no registrado' }}</div>
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
                        <span class="queue__sla-done">{{ row.isOpen ? 'Decidida' : 'Cerrada' }}</span>
                      } @else if (row.slaNow > 0) {
                        <span class="queue__sla" [class.is-warn]="row.slaNow <= 180">
                          <app-icon name="clock" [size]="14" />
                          {{ row.slaNow | duration }}
                        </span>
                        <span class="queue__sla-meter" [class.is-warn]="row.slaNow <= 180" aria-hidden="true">
                          <span class="queue__sla-fill" [style.width.%]="slaPercent(row.slaNow)"></span>
                        </span>
                      } @else {
                        <span class="queue__sla is-late">
                          <app-icon name="alert" [size]="14" />
                          Vencido hace {{ -row.slaNow | duration }}
                        </span>
                      }
                    </td>
                    <td class="num">
                      <div class="queue__amount">{{ row.authorized_amount ?? row.suggested_amount | cop }}</div>
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
            <span class="queue__live" aria-hidden="true"></span>
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

    /* Resumen de la cola: una sola barra con cuatro contadores */
    .queue__counts {
      display: flex;
      align-items: stretch;
      flex: none;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-xs);
    }

    .queue__count {
      padding: 0.4rem 0.9rem;
      font-size: var(--fs-sm);
      line-height: 1.5rem;
      color: var(--ink-2);
      white-space: nowrap;
    }

    .queue__count + .queue__count {
      border-left: 1px solid var(--line);
    }

    .queue__count-n {
      margin-left: 0.15rem;
      font-size: var(--fs-lg);
      font-weight: 900;
      color: var(--navy);
      font-variant-numeric: tabular-nums;
      vertical-align: -0.06em;
    }

    .queue__count--pending {
      border-radius: calc(var(--radius-md) - 1px) 0 0 calc(var(--radius-md) - 1px);
      background: var(--orange-soft);
      color: var(--orange-ink);
      font-weight: 700;
    }

    .queue__count--pending .queue__count-n {
      color: var(--orange-ink);
    }

    .queue__dot {
      display: inline-block;
      width: 0.55rem;
      height: 0.55rem;
      margin-right: 0.45rem;
      border-radius: 50%;
      background: var(--muted);
    }

    .queue__count--green .queue__dot {
      background: var(--good);
      box-shadow: 0 0 0 3px var(--good-soft);
    }

    .queue__count--yellow .queue__dot {
      background: var(--warn);
      box-shadow: 0 0 0 3px var(--warn-soft);
    }

    .queue__count--red .queue__dot {
      background: var(--crit);
      box-shadow: 0 0 0 3px var(--crit-soft);
    }

    .queue__pad {
      padding: var(--space-5);
    }

    /* Filas: filete del color del semáforo (el texto va en la insignia) */
    .queue__row td {
      padding-top: 0.7rem;
      padding-bottom: 0.7rem;
    }
    .queue__plate + .queue__sub {
      white-space: nowrap;
    }

    .queue__row.is-green td:first-child {
      box-shadow: inset 3px 0 0 var(--good);
    }

    .queue__row.is-yellow td:first-child {
      box-shadow: inset 3px 0 0 var(--warn);
    }

    .queue__row.is-red td:first-child {
      box-shadow: inset 3px 0 0 var(--crit);
    }

    .queue__row.queue__closed td {
      background: var(--surface-2);
    }

    .queue__row.queue__closed td:first-child {
      box-shadow: inset 3px 0 0 var(--line-strong);
    }

    .queue__row.queue__closed:hover td {
      background: var(--blue-soft);
    }

    .queue__plate {
      font-size: var(--fs-md);
      font-weight: 900;
      letter-spacing: 0.02em;
      color: var(--navy);
      font-variant-numeric: tabular-nums;
    }

    .queue__driver {
      font-weight: 700;
      color: var(--ink);
    }

    .queue__amount {
      font-size: var(--fs-md);
      font-weight: 900;
      color: var(--navy);
    }

    .queue__closed .queue__plate,
    .queue__closed .queue__amount,
    .queue__closed .queue__driver {
      color: var(--ink-2);
    }

    .queue__sub {
      margin-top: 0.15rem;
      font-size: var(--fs-xs);
      line-height: 1.3;
      color: var(--ink-2);
    }

    /* SLA: cuenta regresiva con barra que se vacía */
    .queue__sla {
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
      font-weight: 700;
      color: var(--ink);
    }

    .queue__sla.is-warn {
      color: var(--warn-ink);
    }

    .queue__sla.is-late {
      color: var(--crit-ink);
    }

    .queue__sla-done {
      color: var(--ink-2);
    }

    .queue__sla-meter {
      display: block;
      width: 4.5rem;
      height: 0.25rem;
      margin: 0.3rem 0 0 auto;
      border-radius: var(--radius-pill);
      background: var(--soft-2);
      overflow: hidden;
    }

    .queue__sla-fill {
      display: block;
      height: 100%;
      border-radius: inherit;
      background: var(--good);
      transition: width 1s linear;
    }

    .queue__sla-meter.is-warn .queue__sla-fill {
      background: var(--warn);
    }

    .queue__footer {
      display: flex;
      justify-content: space-between;
      gap: var(--space-4);
      font-size: var(--fs-xs);
      color: var(--ink-2);
    }

    .queue__footer span {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
    }

    .queue__live {
      width: 0.45rem;
      height: 0.45rem;
      border-radius: 50%;
      background: var(--good);
      animation: queue-pulse 3s var(--ease) infinite;
    }

    @keyframes queue-pulse {
      0% {
        box-shadow: 0 0 0 0 rgba(12, 163, 12, 0.45);
      }

      60%,
      100% {
        box-shadow: 0 0 0 0.4rem rgba(12, 163, 12, 0);
      }
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

  /** Share of the 10-minute SLA still available, for the countdown bar. */
  protected slaPercent(seconds: number): number {
    return Math.max(0, Math.min(100, (seconds / SLA_SECONDS) * 100));
  }

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
