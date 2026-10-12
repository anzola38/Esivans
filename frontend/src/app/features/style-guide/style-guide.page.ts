import { Component, inject, signal } from '@angular/core';
import { ApiService } from '../../core/api.service';
import { ClockService } from '../../core/clock.service';
import { REQUEST_STATUS_ORDER, RequestStatus } from '../../core/models';
import { RoleService } from '../../core/role.service';
import { ToastService } from '../../core/toast.service';
import { ICON_NAMES, IconName, SHARED } from '../../shared';

/** Internal reference: every shared component, pipe and utility in one place. */
@Component({
  selector: 'app-style-guide-page',
  imports: [SHARED],
  templateUrl: './style-guide.page.html',
  styles: `
    /* Mosaico: las tarjetas se reparten solas en 2 columnas (1366) o 3 (1920), sin huecos. */
    .sg {
      columns: 28rem;
      column-gap: var(--space-4);
    }
    .sg > * {
      break-inside: avoid;
      margin-bottom: var(--space-4);
    }
    .sg__heading,
    .sg__wide {
      column-span: all;
    }
    .sg__heading {
      margin-top: var(--space-4);
      padding-bottom: var(--space-3);
      border-bottom: 1px solid var(--line);
    }
    .sg__heading:first-child {
      margin-top: 0;
    }
    .swatches {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr));
      gap: var(--space-2);
    }
    .swatch {
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      overflow: hidden;
      font-size: var(--fs-xs);
      background: var(--surface);
      color: var(--ink-2);
    }
    .swatch strong {
      color: var(--ink);
    }
    .swatch__color {
      height: 2.4rem;
      box-shadow: inset 0 -1px 0 var(--line);
    }
    .swatch__text {
      padding: 0.35rem 0.55rem 0.45rem;
      line-height: 1.35;
    }
    .icons {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(5.6rem, 1fr));
      gap: var(--space-2);
    }
    .icons > div {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.3rem;
      padding: 0.6rem 0.2rem 0.5rem;
      border: 1px solid var(--line);
      border-radius: var(--radius-md);
      font-size: var(--fs-2xs);
      color: var(--ink-2);
    }
    .icons app-icon {
      color: var(--navy);
    }
    .scale {
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      align-items: baseline;
      gap: 0.35rem 1rem;
    }
    .scale__token {
      font-family: var(--font-mono);
      font-size: 0.74rem;
      color: var(--ink-2);
      white-space: nowrap;
    }
    .scale__sample {
      font-weight: 900;
      color: var(--navy);
      line-height: 1.15;
      letter-spacing: var(--tracking-tight);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .spaces {
      display: flex;
      align-items: flex-end;
      gap: 0.6rem;
    }
    .spaces > div {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.3rem;
      font-family: var(--font-mono);
      font-size: var(--fs-2xs);
      color: var(--ink-2);
    }
    .spaces i {
      display: block;
      width: 1.1rem;
      border-radius: 3px;
      background: var(--blue);
    }
    .tiles {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 1rem;
    }
    .tile {
      display: grid;
      place-items: center;
      height: 3.6rem;
      border: 1px solid var(--line);
      background: var(--surface);
      font-family: var(--font-mono);
      font-size: 0.74rem;
      color: var(--ink-2);
    }
    .phone-box {
      height: 30rem;
      display: flex;
      justify-content: center;
    }
    .pipes td:first-child {
      font-family: var(--font-mono);
      font-size: var(--fs-xs);
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

  protected readonly demoTab = signal('alerts');
  protected readonly demoFilter = signal('pending');
  protected readonly demoChip = signal('VEH901');

  protected readonly iconNames = ICON_NAMES;

  protected readonly demoTabs: readonly { key: string; label: string; icon: IconName; count: number | null }[] = [
    { key: 'alerts', label: 'Tanqueos', icon: 'fuel', count: 9 },
    { key: 'vehicles', label: 'Vehículos', icon: 'truck', count: 7 },
    { key: 'rules', label: 'Reglas', icon: 'sliders', count: null },
  ];
  protected readonly demoFilters = [
    { key: 'pending', label: 'Abiertas', count: 7 },
    { key: 'done', label: 'Revisadas', count: 2 },
    { key: 'all', label: 'Todas', count: 9 },
  ];
  protected readonly demoChips = ['VEH901', 'VEH015', 'VEH199'];

  protected readonly derived = [
    { token: 'navy-dark', use: 'Fondo de la barra lateral' },
    { token: 'blue-dark', use: 'Enlaces y texto azul' },
    { token: 'orange-ink', use: 'Texto sobre naranja suave' },
    { token: 'orange-soft', use: 'Fondo de lo que hace la IA' },
    { token: 'good-soft', use: 'Fondo verde' },
    { token: 'warn-soft', use: 'Fondo amarillo' },
    { token: 'crit-soft', use: 'Fondo rojo' },
    { token: 'good-ink', use: 'Texto sobre verde' },
    { token: 'warn-ink', use: 'Texto sobre amarillo' },
    { token: 'crit-ink', use: 'Texto sobre rojo' },
    { token: 'surface-2', use: 'Pies y filas alternas' },
    { token: 'soft-2', use: 'Pistas y deshabilitados' },
    { token: 'line-soft', use: 'Divisores internos' },
    { token: 'line-strong', use: 'Borde de controles' },
  ];

  protected readonly typeScale = [
    { token: '--fs-3xl', sample: '66,7 h' },
    { token: '--fs-2xl', sample: '$80.000' },
    { token: '--fs-xl', sample: 'Consola del técnico' },
    { token: '--fs-lg', sample: 'Cola de solicitudes' },
    { token: '--fs-md', sample: 'Cálculo del valor sugerido' },
    { token: '--fs-sm', sample: 'Ordenada por tiempo de espera' },
    { token: '--fs-xs', sample: 'Se actualiza sola cada 3 segundos' },
  ];

  protected readonly spaces = [1, 2, 3, 4, 5, 6, 8, 10, 12];
  protected readonly shadows = ['xs', 'sm', 'md', 'lg'];
  protected readonly radii = ['xs', 'sm', 'md', 'lg'];
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
