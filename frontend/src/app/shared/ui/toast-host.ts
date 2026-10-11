import { Component, inject } from '@angular/core';
import { ToastKind, ToastService } from '../../core/toast.service';
import { Icon, IconName } from './icon';

const KIND_ICON: Record<ToastKind, IconName> = {
  success: 'check-circle',
  error: 'alert',
  warning: 'alert',
  info: 'info',
};

/** Renders the toast stack. Mounted once in the shell; use `ToastService` to show messages. */
@Component({
  selector: 'app-toast-host',
  imports: [Icon],
  template: `
    <div class="ui-toasts" aria-live="polite">
      @for (toast of toasts.toasts(); track toast.id) {
        <div class="ui-toast" [class]="'ui-toast ui-toast--' + toast.kind" role="status">
          <app-icon class="ui-toast__icon" [name]="icon(toast.kind)" [size]="20" />
          <div class="ui-toast__text">
            @if (toast.title) {
              <div class="ui-toast__title">{{ toast.title }}</div>
            }
            <div>{{ toast.message }}</div>
          </div>
          <button
            type="button"
            class="ui-icon-btn"
            aria-label="Cerrar aviso"
            (click)="toasts.dismiss(toast.id)"
          >
            <app-icon name="close" [size]="16" />
          </button>
        </div>
      }
    </div>
  `,
})
export class ToastHost {
  protected readonly toasts = inject(ToastService);

  protected icon(kind: ToastKind): IconName {
    return KIND_ICON[kind];
  }
}
