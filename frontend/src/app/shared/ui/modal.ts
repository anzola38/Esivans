import { Component, booleanAttribute, input, output } from '@angular/core';
import { Icon } from './icon';

/**
 * Modal / diálogo. El padre controla `open` y lo apaga al recibir `closed`
 * (clic en la X, en el fondo o tecla Escape). Slots: contenido y `[modal-actions]`.
 */
@Component({
  selector: 'app-modal',
  imports: [Icon],
  template: `
    @if (open()) {
      <div class="ui-modal" (click)="onBackdrop($event)">
        <div
          class="ui-modal__dialog"
          [class.ui-modal__dialog--sm]="size() === 'sm'"
          [class.ui-modal__dialog--lg]="size() === 'lg'"
          role="dialog"
          aria-modal="true"
          [attr.aria-label]="title()"
        >
          <div class="ui-modal__header">
            <h2 class="ui-modal__title">{{ title() }}</h2>
            <button type="button" class="ui-icon-btn" aria-label="Cerrar" (click)="closed.emit()">
              <app-icon name="close" [size]="18" />
            </button>
          </div>
          <div class="ui-modal__body"><ng-content /></div>
          <div class="ui-modal__footer"><ng-content select="[modal-actions]" /></div>
        </div>
      </div>
    }
  `,
  host: { '(document:keydown.escape)': 'onEscape()' },
})
export class Modal {
  readonly open = input(false, { transform: booleanAttribute });
  readonly title = input('');
  readonly size = input<'sm' | 'md' | 'lg'>('md');
  /** Set to false while an action is running so the dialog cannot be dismissed. */
  readonly dismissible = input(true, { transform: booleanAttribute });

  readonly closed = output<void>();

  protected onBackdrop(event: MouseEvent): void {
    if (event.target === event.currentTarget && this.dismissible()) this.closed.emit();
  }

  protected onEscape(): void {
    if (this.open() && this.dismissible()) this.closed.emit();
  }
}
