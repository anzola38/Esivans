import { Component, booleanAttribute, computed, input } from '@angular/core';
import {
  PRIORITY_LABELS,
  Priority,
  REQUEST_STATUS_LABELS,
  RequestStatus,
  TRAFFIC_LIGHT_LABELS,
  TrafficLight,
} from '../../core/models';

/** Semáforo: siempre color + TEXTO (Verde, Amarillo, Rojo). */
@Component({
  selector: 'app-traffic-light',
  template: `
    <span class="ui-badge__dot"></span>
    <span>{{ label() }}</span>
    @if (pointsText(); as text) {
      <span class="ui-badge__points">· {{ text }}</span>
    }
  `,
  host: {
    class: 'ui-badge',
    '[class.ui-badge--green]': 'value() === "green"',
    '[class.ui-badge--yellow]': 'value() === "yellow"',
    '[class.ui-badge--red]': 'value() === "red"',
    '[class.ui-badge--lg]': 'size() === "lg"',
    '[attr.aria-label]': '"Semáforo: " + label()',
  },
})
export class TrafficLightBadge {
  readonly value = input<TrafficLight | null | undefined>(null);
  /** Optional rule points, rendered as "· 7 puntos". */
  readonly points = input<number | null | undefined>(null);
  readonly size = input<'md' | 'lg'>('md');

  protected readonly label = computed(() => {
    const value = this.value();
    return value ? (TRAFFIC_LIGHT_LABELS[value] ?? 'Sin evaluar') : 'Sin evaluar';
  });

  protected readonly pointsText = computed(() => {
    const points = this.points();
    if (points === null || points === undefined) return null;
    return points + (points === 1 ? ' punto' : ' puntos');
  });
}

const STATUS_TONE: Record<RequestStatus, string> = {
  received: 'neutral',
  identified: 'neutral',
  awaiting_evidence: 'yellow',
  ready: 'blue',
  in_review: 'orange',
  authorized: 'green',
  rejected: 'red',
};

/** Estado de la solicitud: received → … → authorized | rejected. */
@Component({
  selector: 'app-status-chip',
  template: `{{ label() }}`,
  host: { '[class]': '"ui-badge ui-badge--" + tone()' },
})
export class StatusChip {
  readonly status = input.required<RequestStatus | string>();

  protected readonly label = computed(
    () => REQUEST_STATUS_LABELS[this.status() as RequestStatus] ?? String(this.status()),
  );
  protected readonly tone = computed(() => STATUS_TONE[this.status() as RequestStatus] ?? 'neutral');
}

const PRIORITY_TONE: Record<Priority, string> = { high: 'red', medium: 'yellow', low: 'neutral' };

/** Prioridad de la alerta: alta (48 h), media, baja (en la semana). */
@Component({
  selector: 'app-priority-chip',
  template: `{{ text() }}`,
  host: { '[class]': '"ui-badge ui-badge--" + tone()' },
})
export class PriorityChip {
  readonly priority = input.required<Priority | string>();
  /** Compact shows "Alta" instead of "Prioridad alta". */
  readonly compact = input(false, { transform: booleanAttribute });

  protected readonly tone = computed(() => PRIORITY_TONE[this.priority() as Priority] ?? 'neutral');
  protected readonly text = computed(() => {
    const label = PRIORITY_LABELS[this.priority() as Priority] ?? String(this.priority());
    return this.compact() ? label : 'Prioridad ' + label.toLowerCase();
  });
}
