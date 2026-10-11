import { Component, booleanAttribute, input } from '@angular/core';

/**
 * Tabla base: envuelve una `<table>` nativa y le da el estilo (encabezado navy fijo, filas con divisor).
 * Clases útiles dentro: `th.num` / `td.num` (cifras a la derecha), `.center`,
 * `tr.is-clickable`, `tr.is-selected`.
 */
@Component({
  selector: 'app-table',
  template: `<ng-content />`,
  host: {
    class: 'ui-table-wrap',
    '[class.ui-table-wrap--dense]': 'dense()',
    '[class.ui-table-wrap--striped]': 'striped()',
    '[class.ui-table-wrap--plain]': 'plain()',
    '[style.max-height]': 'maxHeight() || null',
  },
})
export class DataTable {
  readonly dense = input(false, { transform: booleanAttribute });
  readonly striped = input(false, { transform: booleanAttribute });
  /** No outer border or radius (when the table sits inside a flush card). */
  readonly plain = input(false, { transform: booleanAttribute });
  /** Any CSS length, e.g. "20rem": the body scrolls under the sticky header. */
  readonly maxHeight = input<string>();
}
