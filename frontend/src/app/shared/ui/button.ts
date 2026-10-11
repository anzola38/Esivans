import { Directive, booleanAttribute, computed, input } from '@angular/core';

export type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'outline'
  | 'ghost'
  | 'danger'
  | 'danger-solid';

/**
 * Botón: `<button appButton>` (primario naranja, uno por vista), `appButton="secondary"` (azul),
 * `"outline"`, `"ghost"`, `"danger"` (borde rojo) y `"danger-solid"`.
 * Recuerda `type="button"` fuera de formularios.
 */
@Directive({
  selector: 'button[appButton], a[appButton]',
  host: {
    '[class]': 'classes()',
    '[class.is-loading]': 'loading()',
    '[attr.aria-busy]': 'loading() ? "true" : null',
  },
})
export class Button {
  readonly variant = input<ButtonVariant | ''>('primary', { alias: 'appButton' });
  readonly size = input<'sm' | 'md' | 'lg'>('md');
  /** Shows a spinner and ignores clicks. */
  readonly loading = input(false, { transform: booleanAttribute });
  readonly block = input(false, { transform: booleanAttribute });

  protected readonly classes = computed(() => {
    const list = ['ui-btn', 'ui-btn--' + (this.variant() || 'primary')];
    if (this.size() !== 'md') list.push('ui-btn--' + this.size());
    if (this.block()) list.push('ui-btn--block');
    return list.join(' ');
  });
}
