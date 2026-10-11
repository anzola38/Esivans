import { Routes } from '@angular/router';

const DATA = {
  title: 'Consola del técnico',
  subtitle: 'Cola por tiempo de espera, semáforo, valor sugerido y decisión',
};

export const CONSOLE_ROUTES: Routes = [
  {
    path: '',
    title: 'Consola del técnico | Prototipo',
    data: DATA,
    loadComponent: () => import('./console.page').then((m) => m.ConsolePage),
  },
  {
    // The `id` param reaches the component as an input (withComponentInputBinding).
    path: ':id',
    title: 'Solicitud | Consola del técnico',
    data: DATA,
    loadComponent: () => import('./console-detail.page').then((m) => m.ConsoleDetailPage),
  },
];
