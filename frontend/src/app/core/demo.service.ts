import { Injectable, inject, signal } from '@angular/core';
import { Observable, finalize, tap } from 'rxjs';
import { ApiService } from './api.service';

/** Demo controls: reloads the seed and tells every screen to refetch. */
@Injectable({ providedIn: 'root' })
export class DemoService {
  private readonly api = inject(ApiService);

  private readonly _dataVersion = signal(0);
  private readonly _resetting = signal(false);

  /**
   * Increments after every "Reiniciar demo". Read it inside the `effect` that loads
   * a screen's data so the screen reloads on its own.
   */
  readonly dataVersion = this._dataVersion.asReadonly();
  readonly resetting = this._resetting.asReadonly();

  reset(): Observable<unknown> {
    this._resetting.set(true);
    return this.api.post('/dev/reset').pipe(
      tap(() => this._dataVersion.update((v) => v + 1)),
      finalize(() => this._resetting.set(false)),
    );
  }

  /** Lets a feature ask the others to refetch (for example after a decision). */
  notifyDataChanged(): void {
    this._dataVersion.update((v) => v + 1);
  }
}
