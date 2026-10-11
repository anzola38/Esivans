import { Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { SHARED } from '../../shared';

/** Placeholder: the request detail (evidence, context, reasons, value and actions) is built in H4. */
@Component({
  selector: 'app-console-detail-page',
  imports: [SHARED, RouterLink],
  template: `
    <div class="page page--fill">
      <app-section-header
        eyebrow="Detalle de la solicitud"
        [title]="'Solicitud ' + (id() ?? '')"
        subtitle="Foto y lectura, libro único de tanqueos, razones, cálculo del valor y bitácora."
      >
        <a appButton="outline" routerLink="/consola">
          <app-icon name="arrow-left" [size]="16" />
          Volver a la cola
        </a>
      </app-section-header>
      <app-card class="fill">
        <app-empty-state
          icon="file"
          title="El detalle se conecta en el siguiente hito"
          message="Aquí van la evidencia, el contexto del libro único, cada regla con sus puntos, el cálculo paso a paso y las acciones Aprobar, Ajustar y Rechazar."
        />
      </app-card>
    </div>
  `,
})
export class ConsoleDetailPage {
  /** Route param `:id`. */
  readonly id = input<string>();
}
