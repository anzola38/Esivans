import { Injectable, signal } from '@angular/core';

export type ToastKind = 'success' | 'error' | 'info' | 'warning';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  title?: string;
}

const DEDUPE_WINDOW_MS = 6000;

@Injectable({ providedIn: 'root' })
export class ToastService {
  private nextId = 1;
  private readonly lastShown = new Map<string, number>();
  private readonly _toasts = signal<Toast[]>([]);

  readonly toasts = this._toasts.asReadonly();

  success(message: string, title?: string): void {
    this.show('success', message, title);
  }

  error(message: string, title?: string): void {
    this.show('error', message, title, 6000);
  }

  info(message: string, title?: string): void {
    this.show('info', message, title);
  }

  warning(message: string, title?: string): void {
    this.show('warning', message, title, 6000);
  }

  show(kind: ToastKind, message: string, title?: string, durationMs = 4000): void {
    // Polling screens would otherwise stack the same error every second.
    const key = [kind, title ?? '', message].join('|');
    const now = Date.now();
    if (now - (this.lastShown.get(key) ?? 0) < DEDUPE_WINDOW_MS) return;
    this.lastShown.set(key, now);

    const id = this.nextId++;
    this._toasts.update((list) => [...list.slice(-3), { id, kind, message, title }]);
    if (durationMs > 0) setTimeout(() => this.dismiss(id), durationMs);
  }

  dismiss(id: number): void {
    this._toasts.update((list) => list.filter((t) => t.id !== id));
  }
}
