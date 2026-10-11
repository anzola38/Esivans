import { Routes } from '@angular/router';
import { Shell } from './layout/shell';

/**
 * Each feature owns its own `*.routes.ts` (lazy). To add a screen inside a feature,
 * edit that file; this one only changes when a new top-level section appears.
 * `data.title` and `data.subtitle` feed the top bar.
 */
export const routes: Routes = [
  {
    path: '',
    component: Shell,
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'simulador' },
      {
        path: 'simulador',
        loadChildren: () =>
          import('./features/simulator/simulator.routes').then((m) => m.SIMULATOR_ROUTES),
      },
      {
        path: 'consola',
        loadChildren: () =>
          import('./features/console/console.routes').then((m) => m.CONSOLE_ROUTES),
      },
      {
        path: 'alertas',
        loadChildren: () => import('./features/alerts/alerts.routes').then((m) => m.ALERTS_ROUTES),
      },
      {
        path: 'tablero',
        loadChildren: () =>
          import('./features/dashboard/dashboard.routes').then((m) => m.DASHBOARD_ROUTES),
      },
      {
        // Internal reference page, not linked from the menu.
        path: 'guia-estilo',
        title: 'Guía de estilo | Prototipo',
        data: { title: 'Guía de estilo', subtitle: 'Componentes compartidos del prototipo' },
        loadComponent: () =>
          import('./features/style-guide/style-guide.page').then((m) => m.StyleGuidePage),
      },
      { path: '**', redirectTo: 'simulador' },
    ],
  },
];
