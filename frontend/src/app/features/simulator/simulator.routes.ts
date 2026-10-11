import { Routes } from '@angular/router';

export const SIMULATOR_ROUTES: Routes = [
  {
    path: '',
    title: 'Simulador del conductor | Prototipo',
    data: {
      title: 'Simulador del conductor',
      subtitle: 'El conductor pide combustible por mensajería y el asistente arma la solicitud',
    },
    loadComponent: () => import('./simulator.page').then((m) => m.SimulatorPage),
  },
];
