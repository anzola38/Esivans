import { Component, input } from '@angular/core';

/** Encabezado de sección: rótulo superior opcional, título navy, subtítulo y acciones (contenido). */
@Component({
  selector: 'app-section-header',
  template: `
    <div class="ui-section-header__text">
      @if (eyebrow()) {
        <div class="eyebrow">{{ eyebrow() }}</div>
      }
      <h2>{{ title() }}</h2>
      @if (subtitle()) {
        <p class="ui-section-header__subtitle">{{ subtitle() }}</p>
      }
    </div>
    <div class="ui-section-header__actions"><ng-content /></div>
  `,
  host: { class: 'ui-section-header' },
})
export class SectionHeader {
  readonly title = input.required<string>();
  readonly subtitle = input<string>();
  readonly eyebrow = input<string>();
}
