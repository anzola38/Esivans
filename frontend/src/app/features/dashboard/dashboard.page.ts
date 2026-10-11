import { Component } from '@angular/core';
import { SHARED } from '../../shared';

/** Placeholder: the pilot indicators are built in H6. */
@Component({
  selector: 'app-dashboard-page',
  imports: [SHARED],
  template: `
    <div class="page page--fill">
      <app-section-header
        eyebrow="Paso 4 de la demo"
        title="Indicadores del piloto"
        subtitle="Seis semanas en Córdoba: cada indicador con su línea base y su meta."
      />
      <app-card class="fill">
        <app-empty-state
          icon="chart"
          title="El tablero se conecta en un hito posterior"
          message="Aquí van los indicadores del piloto y el recuadro de la decisión al cierre: ampliar, ajustar o detener."
        />
      </app-card>
    </div>
  `,
})
export class DashboardPage {}
