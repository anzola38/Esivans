import { Component, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
  ActivatedRoute,
  NavigationEnd,
  Router,
  RouterLink,
  RouterLinkActive,
  RouterOutlet,
} from '@angular/router';
import { filter } from 'rxjs';
import { APP_CONFIG } from '../core/config';
import { DemoService } from '../core/demo.service';
import { Role } from '../core/models';
import { RoleService } from '../core/role.service';
import { ToastService } from '../core/toast.service';
import { Button } from '../shared/ui/button';
import { Icon, IconName } from '../shared/ui/icon';
import { Modal } from '../shared/ui/modal';
import { ToastHost } from '../shared/ui/toast-host';

interface NavItem {
  path: string;
  label: string;
  hint: string;
  icon: IconName;
}

const NAV_ITEMS: readonly NavItem[] = [
  { path: '/simulador', label: 'Simulador del conductor', hint: 'Chat con el asistente', icon: 'chat' },
  { path: '/consola', label: 'Consola del técnico', hint: 'Cola, semáforo y decisión', icon: 'console' },
  { path: '/alertas', label: 'Alertas del coordinador', hint: 'Revisión y conciliación', icon: 'bell' },
  { path: '/tablero', label: 'Tablero del piloto', hint: 'Indicadores y metas', icon: 'chart' },
];

/** App frame: navy sidebar, top bar (title, role, demo reset), routed content and fixed footer. */
@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, Icon, Button, Modal, ToastHost],
  templateUrl: './shell.html',
})
export class Shell {
  protected readonly roles = inject(RoleService);
  protected readonly demo = inject(DemoService);
  private readonly toasts = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly navItems = NAV_ITEMS;
  protected readonly config = APP_CONFIG;

  protected readonly title = signal('');
  protected readonly subtitle = signal('');
  protected readonly confirmOpen = signal(false);

  constructor() {
    this.readRouteData();
    this.router.events
      .pipe(
        filter((event) => event instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.readRouteData());
  }

  protected onRoleChange(event: Event): void {
    this.roles.setRole((event.target as HTMLSelectElement).value as Role);
  }

  protected confirmReset(): void {
    this.demo.reset().subscribe({
      next: () => {
        this.confirmOpen.set(false);
        this.toasts.success(
          'Se volvió a cargar la semilla. Las pantallas ya muestran los datos iniciales.',
          'Demo reiniciada',
        );
      },
      // The interceptor already showed the error toast.
      error: () => this.confirmOpen.set(false),
    });
  }

  /** Title and subtitle come from the `data` of the deepest active route. */
  private readRouteData(): void {
    let current = this.route.snapshot;
    while (current.firstChild) current = current.firstChild;
    this.title.set(current.data['title'] ?? '');
    this.subtitle.set(current.data['subtitle'] ?? '');
  }
}
