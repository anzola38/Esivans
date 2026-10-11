import { Component, ElementRef, input, viewChild } from '@angular/core';
import { Icon } from './icon';

/**
 * Marco de teléfono genérico (sin logos) para el simulador del conductor.
 * Slots: contenido (mensajes; usa `.ui-bubble` y `.ui-bubble--out`) y `[phone-footer]` (caja de texto).
 * El alto sigue al contenedor (máx. 44rem): ponlo dentro de un panel con alto definido.
 */
@Component({
  selector: 'app-phone-frame',
  imports: [Icon],
  template: `
    <div class="ui-phone__screen">
      <div class="ui-phone__status">
        <span>{{ time() }}</span>
        <span class="ui-phone__status-icons" aria-hidden="true">
          <svg width="16" height="11" viewBox="0 0 16 11" fill="currentColor">
            <rect x="0" y="7" width="3" height="4" rx="0.5" />
            <rect x="4.3" y="5" width="3" height="6" rx="0.5" />
            <rect x="8.600" y="2.500" width="3" height="8.500" rx="0.5" />
            <rect x="13" y="0" width="3" height="11" rx="0.5" />
          </svg>
          <svg width="23" height="11" viewBox="0 0 23 11" fill="none">
            <rect x="0.5" y="0.5" width="19" height="10" rx="2.500" stroke="currentColor" />
            <rect x="2" y="2" width="13" height="7" rx="1.200" fill="currentColor" />
            <rect x="21" y="3.500" width="1.500" height="4" rx="0.700" fill="currentColor" />
          </svg>
        </span>
      </div>
      <div class="ui-phone__header">
        <div class="ui-phone__avatar"><app-icon name="fuel" [size]="18" /></div>
        <div class="grow">
          <div class="ui-phone__title truncate">{{ title() }}</div>
          @if (subtitle()) {
            <div class="ui-phone__subtitle truncate">{{ subtitle() }}</div>
          }
        </div>
      </div>
      <div class="ui-phone__body" #body><ng-content /></div>
      <div class="ui-phone__footer"><ng-content select="[phone-footer]" /></div>
    </div>
  `,
  host: { class: 'ui-phone' },
})
export class PhoneFrame {
  readonly title = input('Asistente de combustible');
  readonly subtitle = input<string>();
  /** Text of the status-bar clock (the simulated time of the case). */
  readonly time = input('9:41');

  private readonly body = viewChild.required<ElementRef<HTMLElement>>('body');

  /** Call after appending a message to keep the latest one in view. */
  scrollToBottom(): void {
    const el = this.body().nativeElement;
    requestAnimationFrame(() => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }));
  }
}
