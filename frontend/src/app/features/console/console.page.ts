import { Component } from '@angular/core';
import { SHARED } from '../../shared';

/** Placeholder: the technician queue is built in H4. */
@Component({
  selector: 'app-console-page',
  imports: [SHARED],
  template: `
    <div class="page page--fill">
      <app-section-header
        eyebrow="Paso 2 de la demo"
        title="Solicitudes en cola"
        subtitle="Ordenadas por tiempo de espera, con su semáforo y el tiempo restante del SLA de 10 minutos."
      />
      <app-card class="fill">
        <app-empty-state
          icon="console"
          title="La cola se conecta en el siguiente hito"
          message="Aquí aparecen las solicitudes listas para decidir: lo verde se aprueba en un clic; lo amarillo o rojo trae el motivo."
        />
      </app-card>
    </div>
  `,
})
export class ConsolePage {}
