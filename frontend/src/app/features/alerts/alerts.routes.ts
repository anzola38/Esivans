import { Routes } from '@angular/router';

export const ALERTS_ROUTES: Routes = [
  {
    path: '',
    title: 'Alertas del coordinador | Prototipo',
    data: {
      title: 'Alertas del coordinador',
      subtitle: 'Tanqueos y vehículos para revisión, conciliación y reglas por vehículo',
    },
    loadComponent: () => import('./alerts.page').then((m) => m.AlertsPage),
  },
];
