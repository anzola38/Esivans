import { Component, inject, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { ClockService } from '../../core/clock.service';
import { REQUEST_STATUS_ORDER, RequestStatus } from '../../core/models';
import { RoleService } from '../../core/role.service';
import { ToastService } from '../../core/toast.service';
import { ICON_NAMES, SHARED } from '../../shared';

/** Internal reference: every shared component, pipe and utility in one place. */
@Component({
  selector: 'app-style-guide-page',
  imports: [SHARED],
  templateUrl: './style-guide.page.html',
  styles: `
    .swatches {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr));
      gap: 0.6rem;
    }
    .swatch {
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      font-size: 0.76rem;
      background: var(--white);
    }
    .swatch__color {
      height: 2.4rem;
    }
    .swatch__text {
      padding: 0.3rem 0.5rem;
      line-height: 1.3;
    }
    .icons {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(5.6rem, 1fr));
      gap: 0.5rem;
    }
    .icons > div {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.25rem;
      padding: 0.5rem 0.2rem;
      border: 1px solid var(--line);
      border-radius: 8px;
      font-size: 0.7rem;
      color: var(--ink-2);
    }
    .phone-box {
      height: 30rem;
      display: flex;
      justify-content: center;
    }
    .pipes td:first-child {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      color: var(--navy);
    }
  `,
})
export class StyleGuidePage {
  protected readonly toasts = inject(ToastService);
  protected readonly roles = inject(RoleService);
  protected readonly clock = inject(ClockService);
  private readonly api = inject(ApiService);

  protected readonly modalOpen = signal(false);
  protected readonly loading = signal(false);

  protected readonly iconNames = ICON_NAMES;
  protected readonly statuses: readonly RequestStatus[] = [...REQUEST_STATUS_ORDER, 'rejected'];

  protected readonly colors = [
    { token: 'navy', hex: '#1F3A5F', use: 'Barra lateral, títulos' },
    { token: 'navy-2', hex: '#2A4A75', use: 'Tarjetas sobre oscuro' },
    { token: 'blue', hex: '#2A78D6', use: 'Acción secundaria' },
    { token: 'blue-soft', hex: '#EEF4FC', use: 'Fondos suaves' },
    { token: 'ice', hex: '#C9D8EC', use: 'Texto sobre oscuro' },
    { token: 'orange', hex: '#EB6834', use: 'IA y acción principal' },
    { token: 'orange-light', hex: '#F7A47C', use: 'Acento suave' },
    { token: 'soft', hex: '#F5F7FA', use: 'Fondo de la página' },
    { token: 'line', hex: '#E4E7EC', use: 'Bordes y divisores' },
    { token: 'ink', hex: '#101828', use: 'Texto principal' },
    { token: 'ink-2', hex: '#475467', use: 'Texto secundario' },
    { token: 'muted', hex: '#667085', use: 'Texto de apoyo' },
    { token: 'good', hex: '#0CA30C', use: 'Semáforo verde' },
    { token: 'warn', hex: '#E09A00', use: 'Semáforo amarillo' },
    { token: 'crit', hex: '#D03B3B', use: 'Semáforo rojo' },
  ];

  // Illustrative values, written by hand for this page.
  protected readonly sampleRows = [
    { vehicle: 'VEH901', plate: 'ZZA901', light: 'green' as const, points: 0, amount: 80000, wait: 95 },
    { vehicle: 'VEH015', plate: 'ZZA015', light: 'yellow' as const, points: 1, amount: 60000, wait: 260 },
    { vehicle: 'VEH199', plate: 'ZZA199', light: 'red' as const, points: 7, amount: 20000, wait: 545 },
  ];

  protected readonly sampleInstant = '2026-10-06T23:14:00-05:00';
  protected readonly threeMinutesAgo = new Date(Date.now() - 3 * 60 * 1000);

  protected simulateLoading(): void {
    this.loading.set(true);
    setTimeout(() => this.loading.set(false), 1500);
  }

  /** Shows how a failed API call surfaces: the interceptor raises the toast. */
  protected callMissingEndpoint(): void {
    this.api.get('/health').subscribe({
      next: () => this.toasts.success('El backend respondió.', 'API disponible'),
      error: () => undefined,
    });
  }
}
