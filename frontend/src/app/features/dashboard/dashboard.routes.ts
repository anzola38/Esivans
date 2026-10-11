import { Routes } from '@angular/router';

export const DASHBOARD_ROUTES: Routes = [
  {
    path: '',
    title: 'Tablero del piloto | Prototipo',
    data: {
      title: 'Tablero del piloto',
      subtitle: 'Indicadores frente a su línea base y su meta, y la decisión al cierre',
    },
    loadComponent: () => import('./dashboard.page').then((m) => m.DashboardPage),
  },
];
