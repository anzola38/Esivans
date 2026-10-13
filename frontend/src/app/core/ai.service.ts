import { Injectable, computed, inject, signal } from '@angular/core';
import { ApiService } from './api.service';

/** `groq_text`: Groq interprets the messages and the photo is not sent, the sample reading is used. */
export type AiProviderKey = 'groq' | 'groq_text' | 'mock';

export interface AiOption {
  key: AiProviderKey;
  label: string;
  available: boolean;
  unavailable_reason: string | null;
  text_model: string | null;
  vision_model: string | null;
}

export interface AiState {
  active: string;
  active_label: string;
  configured: string;
  pinned: boolean;
  options: AiOption[];
}

/** Which provider and model produced an interpretation or a reading, as the backend recorded it. */
export interface AiSource {
  kind: 'text' | 'vision';
  provider: string;
  model: string | null;
  status: 'ok' | 'fallback' | 'failed';
  label: string;
}

/** "openai/gpt-oss-120b" -> "gpt-oss-120b" */
export function shortModel(model: string | null | undefined): string {
  return (model ?? '').split('/').pop() ?? '';
}

/** Demo switch of the AI provider (Groq, Groq only for the text, or the simulated one). The state always comes from the backend. */
@Injectable({ providedIn: 'root' })
export class AiService {
  private readonly api = inject(ApiService);

  private readonly _state = signal<AiState | null>(null);
  private readonly _switching = signal(false);

  readonly state = this._state.asReadonly();
  readonly switching = this._switching.asReadonly();
  readonly active = computed(() => this._state()?.active ?? null);
  readonly options = computed(() => this._state()?.options ?? []);

  load(): void {
    this.api.get<AiState>('/dev/ai', { silent: true }).subscribe({
      next: (state) => this._state.set(state),
      error: () => this._state.set(null),
    });
  }

  select(key: AiProviderKey): void {
    if (this._switching() || key === this.active()) return;
    this._switching.set(true);
    this.api.put<AiState>('/dev/ai', { provider: key }).subscribe({
      next: (state) => {
        this._state.set(state);
        this._switching.set(false);
      },
      error: () => {
        this._switching.set(false);
        this.load();
      },
    });
  }
}
