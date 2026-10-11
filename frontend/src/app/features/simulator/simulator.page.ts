import { Component } from '@angular/core';
import { SHARED } from '../../shared';

/** Placeholder: the simulator (chat in a phone frame + request progress) is built in H4. */
@Component({
  selector: 'app-simulator-page',
  imports: [SHARED],
  template: `
    <div class="page page--fill">
      <app-section-header
        eyebrow="Paso 1 de la demo"
        title="Conversación del conductor"
        subtitle="Selector de caso, reloj simulado, chat con el asistente y estado de la solicitud."
      />
      <app-card class="fill">
        <app-empty-state
          icon="chat"
          title="El simulador se conecta en el siguiente hito"
          message="Aquí va el chat dentro del marco de teléfono y, al lado, el estado de la solicitud avanzando de Recibida a Autorizada."
        />
      </app-card>
    </div>
  `,
})
export class SimulatorPage {}
