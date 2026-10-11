import { Component, booleanAttribute, computed, input } from '@angular/core';
import { Icon, IconName } from './icon';

/** Estado vacío: ícono, título, mensaje y acciones opcionales (contenido). */
@Component({
  selector: 'app-empty-state',
  imports: [Icon],
  template: `
    <div class="ui-empty__icon"><app-icon [name]="icon()" [size]="compact() ? 20 : 26" /></div>
    <div class="ui-empty__title">{{ title() }}</div>
    @if (message()) {
      <p class="ui-empty__message">{{ message() }}</p>
    }
    <div class="ui-empty__actions"><ng-content /></div>
  `,
  host: { class: 'ui-empty', '[class.ui-empty--compact]': 'compact()' },
})
export class EmptyState {
  readonly title = input.required<string>();
  readonly message = input<string>();
  readonly icon = input<IconName>('inbox');
  readonly compact = input(false, { transform: booleanAttribute });
}

/**
 * Esqueleto de carga. `lines` barras de texto, o un bloque único si se pasa `height`
 * (por ejemplo "8rem" para una foto o una gráfica).
 */
@Component({
  selector: 'app-skeleton',
  template: `
    @for (line of bars(); track line) {
      <div class="ui-skeleton__bar" [style.height]="height() || null"></div>
    }
  `,
  host: {
    class: 'ui-skeleton',
    '[class.ui-skeleton--block]': '!!height()',
    'aria-busy': 'true',
    'aria-label': 'Cargando',
  },
})
export class Skeleton {
  readonly lines = input(3);
  readonly height = input<string>();

  protected readonly bars = computed(() =>
    Array.from({ length: this.height() ? 1 : Math.max(1, this.lines()) }, (_, i) => i),
  );
}
