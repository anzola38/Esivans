import {
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  input,
  signal,
  untracked,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { AiService, AiSource, shortModel } from '../../core/ai.service';
import { ApiService } from '../../core/api.service';
import { ClockService } from '../../core/clock.service';
import { DemoService } from '../../core/demo.service';
import { formatTime, toDate } from '../../core/format';
import { PhoneFrame, SHARED } from '../../shared';
import {
  Authorization,
  Decision,
  Person,
  QueueItem,
  StatusStep,
  VehicleRef,
  stageTone,
  validityLabel,
} from '../console/request.models';

interface ScriptStep {
  type: 'text' | 'image';
  text?: string;
  media_id?: string;
}

interface SimCase {
  code: string;
  title: string;
  description: string;
  driver: Person;
  wa_id: string;
  vehicle: VehicleRef | null;
  plate: string | null;
  case_time: string;
  script: ScriptStep[];
  photo: { media_id: string; url: string } | null;
}

interface ChatMessage {
  id: string;
  direction: 'inbound' | 'outbound';
  type: string;
  text: string | null;
  media_url: string | null;
  kind: string;
  timestamp: string;
  ai: AiSource | null;
}

interface ConversationRequest extends QueueItem {
  step: string | null;
  is_open: boolean;
  status_history: StatusStep[];
  decision: Decision | null;
  authorization: Authorization | null;
}

interface Conversation {
  wa_id: string;
  assistant_typing: boolean;
  quick_replies: string[];
  messages: ChatMessage[];
  request: ConversationRequest | null;
}

interface TimelineItem {
  key: string;
  label: string;
  note: string | null;
  time: string | null;
  state: 'done' | 'current' | 'pending' | 'skipped';
  tone: 'default' | 'good' | 'crit';
}

const FLOW = ['received', 'identified', 'awaiting_evidence', 'ready', 'in_review'];
const FLOW_LABELS: Record<string, string> = {
  received: 'Recibida',
  identified: 'Identificada',
  awaiting_evidence: 'Esperando evidencia',
  ready: 'Lista',
  in_review: 'En revisión',
  authorized: 'Autorizada',
  rejected: 'Rechazada',
  cancelled: 'Cerrada sin tanqueo',
};
const TERMINAL = ['authorized', 'rejected', 'cancelled'];
const STEP_PENDING: Record<string, string> = {
  service: 'Confirmar el servicio de EOM o el motivo del recorrido',
  photo: 'Foto del tablero (kilometraje y nivel)',
  confirm: 'Confirmar el kilometraje y el nivel leídos',
  manual_km: 'Escribir el kilometraje a mano',
  not_needed: 'Confirmar que no necesita tanquear ahora',
};
/** Assistant messages that report what the AI read on the dashboard photo. */
const READING_KINDS = ['confirm_reading', 'confirm_correction'];
const SLA_SECONDS = 600;
const STORAGE_KEY = 'esivans.simulator.case';
const POLL_MS = 1200;

/** Driver simulator: chat inside a generic phone frame plus the request progress. */
@Component({
  selector: 'app-simulator-page',
  imports: [SHARED, RouterLink],
  templateUrl: './simulator.page.html',
  styleUrl: './simulator.page.css',
})
export class SimulatorPage {
  private readonly api = inject(ApiService);
  private readonly demo = inject(DemoService);
  protected readonly ai = inject(AiService);
  private readonly clockService = inject(ClockService);

  /** Optional query param: opens the case of that phone number (link from the console). */
  readonly wa = input<string>();

  protected readonly cases = signal<SimCase[]>([]);
  protected readonly loadError = signal(false);
  protected readonly selectedCode = signal<string>(this.readStoredCase());
  protected readonly clock = signal('09:40');
  protected readonly conversation = signal<Conversation | null>(null);
  protected readonly sending = signal(false);
  protected readonly draft = signal('');

  private readonly phone = viewChild(PhoneFrame);
  private readonly fetchedAt = signal(Date.now());

  protected readonly selected = computed(
    () => this.cases().find((c) => c.code === this.selectedCode()) ?? this.cases()[0] ?? null,
  );
  protected readonly messages = computed(() => this.conversation()?.messages ?? []);
  protected readonly request = computed(() => this.conversation()?.request ?? null);
  private readonly messageCount = computed(() => this.messages().length);
  private readonly replyCount = computed(() => this.quickReplies().length);
  protected readonly started = computed(() => this.messages().length > 0);
  protected readonly typing = computed(
    () => this.sending() || (this.conversation()?.assistant_typing ?? false),
  );
  protected readonly quickReplies = computed(() =>
    this.typing() ? [] : (this.conversation()?.quick_replies ?? []),
  );

  /** Last message of the driver: its AI source stays visible under the bubble. */
  private readonly lastInboundId = computed(() => {
    const inbound = this.messages().filter((m) => m.direction === 'inbound');
    return inbound.at(-1)?.id ?? null;
  });

  /** One line under the switch: what the active provider does, or why Groq cannot be chosen. */
  protected readonly aiNote = computed(() => {
    const state = this.ai.state();
    if (!state) return '';
    const groq = state.options.find((option) => option.key === 'groq');
    if (state.active === 'groq' && groq) {
      return (
        'Groq: ' + shortModel(groq.text_model) + ' (mensajes) y ' + shortModel(groq.vision_model) + ' (foto).'
      );
    }
    if (groq && !groq.available) return 'Groq deshabilitado. ' + (groq.unavailable_reason ?? '');
    return 'Intérprete local y lecturas de ejemplo, sin internet.';
  });

  protected readonly scriptIndex = computed(() => {
    const total = this.selected()?.script.length ?? 0;
    const sent = this.messages().filter((m) => m.direction === 'inbound').length;
    return Math.min(sent, total);
  });
  protected readonly nextStep = computed(
    () => this.selected()?.script[this.scriptIndex()] ?? null,
  );

  /** Value of the clock input: editable before the first message, then the time of the case. */
  protected readonly clockValue = computed(() => {
    const first = this.messages()[0];
    const date = first ? toDate(first.timestamp) : null;
    if (!date) return this.clock();
    return new Intl.DateTimeFormat('en-GB', {
      timeZone: 'America/Bogota',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(date);
  });

  /** Clock shown in the phone status bar: the simulated time of the case. */
  protected readonly phoneTime = computed(() => {
    const last = this.messages().at(-1);
    if (last) return formatTime(last.timestamp);
    return formatTime(this.todayAt(this.clock()));
  });

  protected readonly timeline = computed<TimelineItem[]>(() => {
    const request = this.request();
    const history = request?.status_history ?? [];
    const offset = request
      ? (toDate(request.occurred_at)?.getTime() ?? 0) - (toDate(request.created_at)?.getTime() ?? 0)
      : 0;
    const at = (status: string): StatusStep | undefined => history.find((h) => h.status === status);
    const caseTime = (step: StatusStep | undefined): string | null => {
      const real = step ? toDate(step.at) : null;
      return real ? formatTime(new Date(real.getTime() + offset)) : null;
    };
    const terminal = request && TERMINAL.includes(request.status) ? request.status : null;
    const lastReached = history.at(-1)?.status ?? null;

    const items: TimelineItem[] = FLOW.map((status) => {
      const step = at(status);
      let state: TimelineItem['state'] = 'pending';
      if (step) state = !terminal && status === lastReached ? 'current' : 'done';
      else if (terminal) state = 'skipped';
      let note = step?.note ?? null;
      if (status === 'in_review' && request?.stage === 'pending_enablement') {
        note = 'Decidida: falta habilitar en el portal del proveedor';
      }
      return {
        key: status,
        label: FLOW_LABELS[status],
        note,
        time: caseTime(step),
        state,
        tone: 'default',
      };
    });

    const finalStatus = terminal ?? 'authorized';
    const finalStep = at(finalStatus);
    items.push({
      key: finalStatus,
      label: FLOW_LABELS[finalStatus],
      note: finalStep?.note ?? (terminal ? null : 'O rechazada, con el motivo para el conductor'),
      time: caseTime(finalStep),
      state: terminal ? 'done' : 'pending',
      tone: terminal === 'authorized' ? 'good' : terminal === 'rejected' ? 'crit' : 'default',
    });
    return items;
  });

  /** What is still missing for the request to move forward. */
  protected readonly pending = computed<string[]>(() => {
    const request = this.request();
    if (!request) return [];
    if (TERMINAL.includes(request.status)) return [];
    if (request.stage === 'pending_enablement') {
      return ['Habilitar el valor en el portal del proveedor y confirmar la referencia'];
    }
    if (request.status === 'in_review') {
      const missing = request.missing.map((m) => 'Llegó sin: ' + m.label.toLowerCase());
      return [...missing, 'Decisión del técnico de Control y Monitoreo'];
    }
    const step = request.step ? STEP_PENDING[request.step] : null;
    return step ? [step] : ['Respuesta del conductor'];
  });

  protected readonly slaRemaining = computed(() => {
    const request = this.request();
    if (!request || request.sla_remaining_seconds === null || !request.is_open) return null;
    const elapsed = Math.floor((this.clockService.now().getTime() - this.fetchedAt()) / 1000);
    return request.sla_remaining_seconds - Math.max(0, elapsed);
  });

  protected readonly stageTone = stageTone;
  protected readonly validityLabel = validityLabel;

  constructor() {
    effect(() => {
      this.demo.dataVersion();
      untracked(() => {
        this.loadCases();
        this.ai.load(); // "Reiniciar demo" goes back to the configured provider
      });
    });

    // Link from the console: open the case of that phone number.
    effect(() => {
      const wa = this.wa();
      const match = wa ? this.cases().find((c) => c.wa_id === wa) : null;
      if (match) untracked(() => this.selectCase(match.code));
    });

    // Keep the latest message in view.
    effect(() => {
      this.messageCount();
      this.typing();
      this.replyCount();
      this.phone()?.scrollToBottom();
    });

    const timer = setInterval(() => this.poll(), POLL_MS);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected selectCase(code: string): void {
    if (code === this.selectedCode() && this.conversation()) return;
    this.selectedCode.set(code);
    try {
      sessionStorage.setItem(STORAGE_KEY, code);
    } catch {
      /* storage unavailable */
    }
    this.conversation.set(null);
    this.draft.set('');
    this.clock.set(this.selected()?.case_time ?? '09:40');
    this.poll();
  }

  protected onClockChange(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    if (/^\d{2}:\d{2}$/.test(value)) this.clock.set(value);
  }

  protected onDraftInput(event: Event): void {
    this.draft.set((event.target as HTMLInputElement).value);
  }

  protected sendDraft(): void {
    const text = this.draft().trim();
    if (!text || this.typing()) return;
    this.draft.set('');
    this.send({ type: 'text', text });
  }

  protected sendQuickReply(text: string): void {
    this.send({ type: 'text', text });
  }

  protected attachPhoto(): void {
    const photo = this.selected()?.photo;
    if (photo) this.send({ type: 'image', media_id: photo.media_id });
  }

  protected runNextStep(): void {
    const step = this.nextStep();
    if (step) this.send(step);
  }

  protected stepText(step: ScriptStep): string {
    return step.type === 'image' ? 'Adjuntar la foto del tablero' : '«' + (step.text ?? '') + '»';
  }

  /** Shows who interpreted a driver message: always for the last one and for photos, and whenever it was not the chosen provider. */
  protected showsAiSource(message: ChatMessage): boolean {
    if (!message.ai) return false;
    return message.id === this.lastInboundId() || message.type === 'image' || message.ai.status !== 'ok';
  }

  protected isReading(kind: string): boolean {
    return READING_KINDS.includes(kind);
  }

  /** Share of the 10-minute SLA still available, for the progress meter. */
  protected slaPercent(remaining: number): number {
    return Math.max(0, Math.min(100, (remaining / SLA_SECONDS) * 100));
  }

  private send(step: ScriptStep): void {
    const current = this.selected();
    if (!current || this.typing()) return;
    this.sending.set(true);
    this.api
      .post('/dev/simulator/messages', {
        case_code: current.code,
        type: step.type,
        text: step.text,
        media_id: step.media_id,
        simulated_time: this.clock(),
      })
      .subscribe({
        next: () => this.poll(() => this.sending.set(false)),
        error: () => this.sending.set(false),
      });
  }

  private loadCases(): void {
    this.api.get<{ items: SimCase[] }>('/dev/simulator/cases').subscribe({
      next: (response) => {
        this.loadError.set(false);
        this.cases.set(response.items);
        this.conversation.set(null);
        this.clock.set(this.selected()?.case_time ?? '09:40');
        this.poll();
      },
      error: () => this.loadError.set(true),
    });
  }

  private poll(done?: () => void): void {
    const current = this.selected();
    if (!current) {
      done?.();
      return;
    }
    this.api
      .get<Conversation>('/dev/simulator/conversations/' + current.wa_id, { silent: true })
      .subscribe({
        next: (conversation) => {
          if (this.selected()?.wa_id === conversation.wa_id) {
            this.fetchedAt.set(Date.now());
            this.conversation.set(conversation);
          }
          done?.();
        },
        error: () => done?.(),
      });
  }

  private todayAt(time: string): string {
    const now = new Date();
    const pad = (n: number): string => String(n).padStart(2, '0');
    return (
      now.getFullYear() + '-' + pad(now.getMonth() + 1) + '-' + pad(now.getDate()) + 'T' + time + ':00'
    );
  }

  private readStoredCase(): string {
    try {
      return sessionStorage.getItem(STORAGE_KEY) ?? 'GREEN';
    } catch {
      return 'GREEN';
    }
  }
}
