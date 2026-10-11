import { Injectable, signal } from '@angular/core';

/** A shared one-second tick for SLA countdowns and "hace 3 min" labels. */
@Injectable({ providedIn: 'root' })
export class ClockService {
  private readonly _now = signal(new Date());
  readonly now = this._now.asReadonly();

  constructor() {
    setInterval(() => this._now.set(new Date()), 1000);
  }
}
