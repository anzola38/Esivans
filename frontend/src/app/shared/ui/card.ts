import { Component, booleanAttribute, input } from '@angular/core';

export type CardTone = 'default' | 'soft' | 'accent' | 'dark';

/**
 * Tarjeta blanca con borde `line` y radio de 10 px.
 * Slots: `[card-actions]` (a la derecha del título; requiere `title`), contenido y `[card-footer]`.
 */
@Component({
  selector: 'app-card',
  template: `
    @if (title()) {
      <div class="ui-card__header">
        <div class="ui-card__titles">
          <div class="ui-card__title">{{ title() }}</div>
          @if (subtitle()) {
            <div class="ui-card__subtitle">{{ subtitle() }}</div>
          }
        </div>
        <div class="ui-card__actions"><ng-content select="[card-actions]" /></div>
      </div>
    }
    <div class="ui-card__body"><ng-content /></div>
    <div class="ui-card__footer"><ng-content select="[card-footer]" /></div>
  `,
  host: {
    class: 'ui-card',
    '[class.ui-card--soft]': 'tone() === "soft"',
    '[class.ui-card--accent]': 'tone() === "accent"',
    '[class.ui-card--dark]': 'tone() === "dark"',
    '[class.ui-card--flush]': 'flush()',
    '[class.ui-card--scroll]': 'scroll()',
  },
})
export class Card {
  readonly title = input<string>();
  readonly subtitle = input<string>();
  readonly tone = input<CardTone>('default');
  /** Removes the body padding (tables or lists edge to edge). */
  readonly flush = input(false, { transform: booleanAttribute });
  /** The body scrolls; give the card a bounded height (for example class="fill"). */
  readonly scroll = input(false, { transform: booleanAttribute });
}
