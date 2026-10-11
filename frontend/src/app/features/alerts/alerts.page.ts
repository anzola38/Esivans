import { Component } from '@angular/core';
import { SHARED } from '../../shared';

/** Placeholder: alerts, reconciliation and per-vehicle rules are built in H5. */
@Component({
  selector: 'app-alerts-page',
  imports: [SHARED],
  template: `
    <div class="page page--fill">
      <app-section-header
        eyebrow="Paso 3 de la demo"
        title="Alertas por prioridad"
        subtitle="Cada alerta con su razón, su plazo (48 h o la semana) y la evidencia."
      />
      <app-card class="fill">
        <app-empty-state
          icon="bell"
          title="Las alertas se conectan en un hito posterior"
          message="Aquí se registra el resultado de cada revisión: Confirmado, Justificado o Error de dato, con comentario, autor y fecha."
        />
      </app-card>
    </div>
  `,
})
export class AlertsPage {}
