import {
  AfterViewChecked, ChangeDetectionStrategy, OnDestroy, Component, ElementRef, computed, effect, inject, signal, untracked, viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { SessionService } from '../../services/session.service';
import { SettingsService } from '../../services/settings.service';
import { FeedbackService } from '../../services/feedback.service';
import { SignalRService } from '../../services/signalr.service';
import { ChatChange, ChatMessage } from '../../models/chat.models';
import { AssistantTextComponent } from './assistant-text.component';
import { ChatsService } from '../../services/chats.service';
import { PluginsService } from '../plugins/plugins.service';
import { Router } from '@angular/router';
import { ButtonComponent, DialogService, IconComponent, MenuComponent, MenuItem, SpinnerComponent, ToastService } from '../../ui';
import { ThinkingStepsComponent } from './thinking-steps.component';
import { ChatModeComponent } from './chat-mode.component';
import { ChatContextComponent } from './chat-context.component';
import { QuestionCardComponent } from './question-card.component';
import { ChatQuickSettingsComponent } from '../settings/chat-quick-settings.component';
import { NoticePrefsService } from '../../services/notice-prefs.service';
import { PresenceService } from '../../services/presence.service';
import { MicRecorder, VoiceService } from '../../services/voice.service';
import { LiveVoiceService } from '../../services/live-voice.service';
import { REACTION_EMOJI } from './reaction-emoji';
import { IdentityService } from '../../services/identity.service';

const LIVE_LABELS: Record<string, string> = {
  starting: 'Accendo il microfono…', listening: 'Ti ascolto', hearing: 'Ti sento…', thinking: 'Ci penso…', speaking: 'Sto parlando',
};

function dayKey(d: Date | undefined): string {
  return d && !isNaN(+d) ? `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}` : '';
}

/** «Oggi», «Ieri», «mer 5 nov» (with the year when it is not this one). */
export function dayLabel(d: Date, now = new Date()): string {
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(now) - start(d)) / 86400000);
  if (diff === 0) return 'Oggi';
  if (diff === 1) return 'Ieri';
  return new Intl.DateTimeFormat('it-IT', { weekday: 'short', day: 'numeric', month: 'short',
    ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) }).format(d);
}

/** Chat with Hestia (Oracle via SignalR): streaming, reasoning, questions, attachments, feedback. */
@Component({
  selector: 'app-chat-page',
  imports: [FormsModule, ButtonComponent, IconComponent, SpinnerComponent, MenuComponent, ThinkingStepsComponent, ChatQuickSettingsComponent,
            ChatModeComponent, ChatContextComponent, QuestionCardComponent, AssistantTextComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="top">
      <button hx-btn variant="ghost" size="sm" icon="history" (click)="chats.historyOpen.set(!chats.historyOpen())"
              [attr.aria-pressed]="chats.historyOpen()" title="Tutte le conversazioni">Cronologia</button>
      <span class="ttl">{{ chat.messages().length ? 'Conversazione' : '' }}</span>
      <div class="hx-grow"></div>
      <button hx-btn [variant]="live.on ? 'primary' : 'ghost'" size="sm" icon="waveform" (click)="toggleLive()"
              [attr.aria-pressed]="live.on" [title]="'Parla con ' + identity.assistant() + ' a voce'">Parla</button>
      <hx-chat-context />
      <hx-chat-quick-settings />
      <hx-menu [items]="menu" (select)="onMenu($event)">
        <button hx-btn variant="ghost" size="sm" icon="more" iconOnly trigger aria-label="Altro"></button>
      </hx-menu>
    </header>

    <div class="scroll" #scroller>
      <div class="thread">
        @if (!chat.messages().length) {
          <div class="welcome hx-fade-in">
            <div class="logo">◈</div>
            <h1>{{ greeting() }}</h1>
            <p>Chiedi qualcosa, pianifica nell'agenda, fai sviluppare Hestia.</p>
            <div class="chips">
              @for (s of suggestions; track s) { <button (click)="use(s)">{{ s }}</button> }
            </div>
          </div>
        }
        @for (m of chat.messages(); track m.id) {
          @if (marks()[m.id]; as k) {
            @if (k.day) { <div class="hx-divider" role="separator">{{ k.day }}</div> }
            @if (k.model) { <div class="hx-divider" role="separator" title="Da qui risponde un altro modello"><hx-icon name="brain" [size]="12" />{{ k.model }}</div> }
          }
          @if (m.role === 'user') {
            @if (m.audio) {
              <div class="msg user hx-fade-in"><div class="bubble voice">
                <div class="vrow">
                  <button class="vplay" (click)="playVoice(m)" [attr.aria-label]="voice.playing() === m.id ? 'Ferma' : 'Ascolta il vocale'">
                    <hx-icon [name]="voice.playing() === m.id ? 'pause' : 'play'" [size]="15" /></button>
                  <hx-icon class="vwave" name="waveform" [size]="22" />
                  <span class="vdur">{{ duration(m.audio.seconds) }}</span>
                </div>
                @if (m.transcribing) { <div class="vtext muted">Trascrivo…</div> }
                @else if (m.content) { <div class="vtext" [class.verr]="m.error">{{ m.content }}</div> }
                @if (m.reaction) { <span class="rx" [title]="'Reazione di ' + identity.assistant()">{{ m.reaction }}</span> }
              </div></div>
            } @else {
              <div class="msg user hx-fade-in"><div class="bubble">@if (m.icon) { <hx-icon class="bi" [name]="m.icon" [size]="14" /> }{{ m.content }}@if (m.reaction) { <span class="rx" [title]="'Reazione di ' + identity.assistant()">{{ m.reaction }}</span> }</div></div>
            }
          } @else {
            <div class="msg asst hx-fade-in">
              @if (m.thinkingSteps?.length && thinkingMode() !== 'hidden') {
                <chat-thinking [steps]="m.thinkingSteps!" [live]="!!m.isStreaming && !m.content" [display]="thinkingMode()" />
              }
              @if (m.origin; as o) { <div class="origin"><hx-icon name="zap" [size]="13" />{{ o.label || 'Avviata in automatico' }}</div> }
              @if (m.error) { <div class="err"><hx-icon name="alert" tone="danger" [size]="15" /><span>{{ m.content }}</span></div> }
              @else { <hx-assistant-text [html]="m.content" [streaming]="!!m.isStreaming" [queued]="!!m.queuedId" (send)="use($event)" /> }
              @if (m.changes?.length && !m.isStreaming) {
                <div class="changes" aria-label="Ho fatto">
                  <div class="ch"><hx-icon name="check-circle" [size]="14" />Ho fatto</div>
                  @for (c of m.changes; track $index) {
                    <div class="cr" [class.done]="c.done">
                      <span class="ct">{{ c.title }}@if (c.detail) {<span class="cd"> · {{ c.detail }}</span>}</span>
                      @if (c.done) { <span class="cu">Annullato</span> }
                      @else if (c.undo) { <button hx-btn variant="ghost" size="sm" icon="undo" [loading]="undoing() === m.id + $index" (click)="undo(m, $index, c)">{{ c.undo.label || 'Annulla' }}</button> }
                    </div>
                  }
                </div>
              }
              @if (m.queuedId) { <div class="inq"><hx-icon name="clock" [size]="14" /> In coda</div> }
              @if (m.notices?.length && notices.inline()) {
                <div class="hx-notices" [class.rich]="notices.prefs().style === 'rich'">
                  @for (n of m.notices; track n.id) {
                    <div class="hx-notice hx-fade-in" [attr.data-level]="n.level" [title]="n.kind">
                      <hx-icon [name]="n.icon" [size]="14" />
                      <span class="nt">{{ n.title }}</span>
                      @if (n.detail) { <span class="nd">{{ n.detail }}</span> }
                    </div>
                  }
                </div>
              }
              @if (m.reaction && !m.isStreaming) {
                <button class="rx mine" (click)="chat.reactTo(m.id, m.reaction!)" title="Togli la reazione">{{ m.reaction }}</button>
              }
              @if (!m.isStreaming && m.content && !m.queuedId) {
                <div class="foot">
                  <span class="rxw">
                    <button class="fb" [class.on]="picker() === m.id" (click)="picker.set(picker() === m.id ? null : m.id)" title="Reagisci" aria-haspopup="true"><hx-icon name="smile" [size]="15" /></button>
                    @if (picker() === m.id) {
                      <span class="rxp hx-fade-in" role="menu">
                        @for (e of reactions; track e) { <button role="menuitem" [class.on]="m.reaction === e" (click)="react(m, e)">{{ e }}</button> }
                      </span>
                    }
                  </span>
                  <button class="fb" [class.on]="rated()[m.id] === 'good'" (click)="feedback('good', m)" title="Utile"><hx-icon name="thumb-up" [size]="15" /></button>
                  <button class="fb" [class.on]="rated()[m.id] === 'bad'" (click)="feedback('bad', m)" title="Non utile"><hx-icon name="thumb-down" [size]="15" /></button>
                  <button class="fb" (click)="copy(m)" title="Copia"><hx-icon name="copy" [size]="15" /></button>
                  <button class="fb" [class.on]="voice.playing() === m.id" [class.busy]="voice.loading() === m.id" (click)="voice.toggle(m.id, m.content)"
                          [title]="voice.loading() === m.id ? 'Preparo la voce… (clic per fermare)' : voice.playing() === m.id ? 'Ferma' : 'Ascolta'"
                          [attr.aria-label]="voice.loading() === m.id ? 'Preparo la voce' : voice.playing() === m.id ? 'Ferma' : 'Ascolta'">
                    @if (voice.loading() === m.id) { <hx-spinner [size]="14" /> }
                    @else { <hx-icon [name]="voice.playing() === m.id ? 'stop' : 'volume'" [size]="15" /> }</button>
                  @if ($last) { <button class="fb" (click)="chat.retry()" [disabled]="chat.isStreaming()" title="Rigenera"><hx-icon name="refresh" [size]="15" /></button> }
                </div>
              }
            </div>
          }
        }
        <div #bottom></div>
      </div>
    </div>

    <div class="composer-wrap">
      @if (presence.chatQueued()) {
        <div class="offline hx-fade-in" role="status">
          <hx-icon class="oe" name="hourglass" tone="warning" [size]="16" />
          <span><b>Non disponibile</b> · i messaggi restano in coda e avranno risposta appena possibile.</span>
        </div>
      }
      @if (chat.pendingQuestion(); as q) { <hx-question-card [question]="q" (answered)="answer(q.questionId, $event)" /> }
      @if (live.on) {
        <div class="live hx-fade-in" role="status" [attr.data-state]="live.state()">
          <span class="ldot"></span>
          <div class="hx-grow">
            <div class="lst">{{ liveLabel() }}</div>
            @if (live.partial()) { <div class="lpart">{{ live.partial() }}</div> }
          </div>
          @if (live.state() === 'speaking' || live.state() === 'thinking') {
            <button hx-btn variant="secondary" size="sm" icon="stop" (click)="live.interrupt()">Interrompi</button>
          }
          <button hx-btn variant="ghost" size="sm" icon="x" iconOnly aria-label="Chiudi Parla" (click)="live.stop()"></button>
        </div>
      }
      <div class="composer hx-glass" [class.disabled]="signalR.connectionState() !== 'connected'">
        @if (recording()) {
          <div class="rec" role="status">
            <span class="rdot"></span><span class="rtime">{{ duration(recSeconds()) }}</span>
            <span class="rhint" [class.cancel]="recCancel()">{{ recCancel() ? 'Rilascia per annullare' : 'Rilascia per inviare · scorri a sinistra per annullare' }}</span>
          </div>
        }
        <textarea #ta [hidden]="recording()" [(ngModel)]="text" (keydown)="onKey($event)" (input)="grow()" rows="1"
                  [placeholder]="signalR.connectionState() === 'connected' ? 'Scrivi a ' + identity.assistant() + '…' : 'Connessione in corso…'"></textarea>
        <div class="tools">
          <input #file type="file" hidden (change)="onFile($event)" />
          <button hx-btn variant="ghost" size="sm" icon="paperclip" iconOnly aria-label="Allega" (click)="file.click()" [disabled]="chat.isStreaming()"></button>
          <hx-chat-mode [(mode)]="mode" />
          <div class="hx-grow"></div>
          @if (chat.isStreaming()) {
            <button hx-btn variant="secondary" size="sm" icon="stop" iconOnly aria-label="Stop" (click)="chat.cancelStream()"></button>
          } @else {
            @if (dictating()) { <span class="dhint" role="status">Ti ascolto: tocca di nuovo per scrivere il testo</span> }
            <!-- One microphone, always here: a tap dictates into the box, holding it records a voice message. -->
            <button hx-btn [variant]="dictating() || recording() ? 'primary' : 'ghost'" size="sm" [icon]="dictating() ? 'stop' : 'mic'" iconOnly class="micbtn"
                    [loading]="dictBusy()" [attr.aria-pressed]="dictating()" [attr.aria-label]="micLabel()" [title]="micLabel()"
                    (pointerdown)="micDown($event)" (pointermove)="micMove($event)" (pointerup)="micUp()"
                    (pointercancel)="micCancel()" (contextmenu)="$event.preventDefault()" (click)="micKey($event)"></button>
            @if (text.trim() && !recording()) { <button hx-btn variant="primary" size="sm" icon="send" iconOnly aria-label="Invia" (click)="send()"></button> }
          }
        </div>
      </div>
      <p class="disc">Invio per mandare · Shift+Invio per andare a capo · microfono: tocca per dettare, tieni premuto per un messaggio vocale</p>
    </div>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .top { display: flex; align-items: center; gap: 8px; padding: 10px 16px 8px 56px; min-height: 52px; }
    .ttl { font-size: 14px; color: var(--text-2); }
    .scroll { flex: 1; overflow-y: auto; }
    .thread { max-width: var(--chat-width); margin: 0 auto; padding: 8px 20px 24px; display: flex; flex-direction: column; gap: 22px; }
    .welcome { text-align: center; padding: 12vh 0 0; display: flex; flex-direction: column; align-items: center; gap: 10px; }
    .welcome .logo { font-size: 34px; color: var(--accent); }
    .welcome h1 { font-family: var(--font-serif); font-weight: 400; font-size: 32px; }
    .welcome p { color: var(--text-3); }
    .chips { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 14px; max-width: 600px; }
    .chips button { border: 1px solid var(--border-strong); border-radius: var(--radius-full); padding: 7px 14px; font-size: 13.5px; color: var(--text-2); background: var(--surface); }
    .chips button:hover { background: var(--surface-2); color: var(--text); }
    .msg.user { display: flex; justify-content: flex-end; }
    .bubble .bi { vertical-align: -2px; margin-right: 6px; opacity: .8; }
    .err { display: flex; gap: 8px; align-items: flex-start; color: var(--text-2); }
    .err hx-icon { margin-top: 2px; }
    .bubble { background: var(--user-bubble); color: var(--user-bubble-text); padding: 10px 15px; border-radius: var(--radius-xl);
              max-width: 80%; white-space: pre-wrap; word-wrap: break-word; font-size: 15px; }
    .msg.asst { position: relative; }
    .foot { display: flex; gap: 2px; margin-top: 8px; opacity: 0; transition: opacity var(--dur); }
    .bubble { position: relative; }
    .rx { position: absolute; bottom: -12px; left: -6px; font-size: 14px; line-height: 1; padding: 3px 5px; border-radius: var(--radius-full);
          background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-sm); white-space: nowrap; }
    .rx.mine { position: static; display: inline-block; margin-top: 6px; cursor: pointer; }
    .rxw { position: relative; display: inline-flex; }
    .rxp { position: absolute; bottom: 100%; left: 0; margin-bottom: 4px; display: flex; gap: 2px; padding: 4px; z-index: 5;
           background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-full); box-shadow: var(--shadow-md); }
    .rxp button { font-size: 18px; line-height: 1; padding: 5px; border-radius: var(--radius-full); }
    .rxp button:hover, .rxp button.on { background: var(--surface-2); }
    .msg.asst:hover .foot, .msg.asst:last-child .foot { opacity: 1; }
    .fb { width: 28px; height: 28px; border-radius: var(--radius-sm); display: grid; place-items: center; color: var(--text-3); }
    .fb:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
    .fb.on { color: var(--accent); }
    .composer-wrap { padding: 0 20px 10px; max-width: calc(var(--chat-width) + 40px); width: 100%; margin: 0 auto; }
    .composer { background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius-xl); box-shadow: var(--shadow-2);
                padding: 12px 12px 8px 16px; transition: border-color var(--dur-fast); }
    .composer:focus-within { border-color: var(--accent); }
    .composer.disabled { opacity: .7; }
    textarea { width: 100%; border: 0; outline: 0; resize: none; background: transparent; font-size: 15.5px; line-height: 1.5; max-height: 240px; color: var(--text); }
    textarea::placeholder { color: var(--text-3); }
    .tools { display: flex; align-items: center; gap: 4px; margin-top: 4px; }
    .disc { text-align: center; font-size: 11.5px; color: var(--text-3); margin-top: 6px; }
    .offline { display: flex; align-items: center; gap: 8px; background: var(--warning-soft); color: var(--text);
               border-radius: var(--radius-lg); padding: 9px 14px; margin-bottom: 10px; font-size: 13.5px; }
    .offline .oe { font-size: 16px; }
    .origin { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--text-3); margin-bottom: 6px;
              border: 1px solid var(--border); border-radius: var(--radius-full); padding: 2px 9px; }
    .origin hx-icon { color: var(--accent); }
    .changes { margin-top: 10px; border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 8px 10px; background: var(--surface); }
    .ch { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 600; color: var(--text-3); margin-bottom: 4px; }
    .ch hx-icon { color: var(--success); }
    .cr { display: flex; align-items: center; gap: 8px; min-height: 32px; font-size: 13.5px; }
    .cr .ct { flex: 1; min-width: 0; overflow-wrap: anywhere; } .cd { color: var(--text-3); }
    .cr.done .ct { color: var(--text-3); text-decoration: line-through; }
    .cu { font-size: 12px; color: var(--text-3); }
    .inq { display: inline-flex; align-items: center; gap: 5px; margin-top: 6px; font-size: 12px; color: var(--warning); }
    .bubble.voice { min-width: 200px; }
    .vrow { display: flex; align-items: center; gap: 8px; }
    .vplay { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; background: var(--surface); color: var(--accent); flex: none; }
    .vwave { opacity: .7; }
    .vdur { font-size: 12.5px; font-variant-numeric: tabular-nums; opacity: .8; margin-left: auto; }
    .vtext { margin-top: 6px; font-size: 14px; font-style: italic; opacity: .9; }
    .vtext.verr { font-style: normal; color: var(--danger); }
    .rec { display: flex; align-items: center; gap: 10px; min-height: 34px; }
    .rdot { width: 10px; height: 10px; border-radius: 50%; background: var(--danger); animation: hx-pulse 1s infinite; }
    .rtime { font-variant-numeric: tabular-nums; font-size: 14px; }
    .rhint { color: var(--text-3); font-size: 13px; margin-left: auto; }
    .rhint.cancel { color: var(--danger); }
    .dhint { font-size: 12.5px; color: var(--text-3); margin-right: 4px; }
    .fb.busy { color: var(--accent); }
    .micbtn { touch-action: none; user-select: none; -webkit-user-select: none; }
    .live { display: flex; align-items: center; gap: 10px; background: var(--surface); border: 1px solid var(--accent);
            border-radius: var(--radius-lg); padding: 10px 14px; margin-bottom: 10px; box-shadow: var(--shadow-1); }
    .ldot { width: 12px; height: 12px; border-radius: 50%; background: var(--text-3); flex: none; }
    .live[data-state=listening] .ldot { background: var(--accent); }
    .live[data-state=hearing] .ldot { background: var(--danger); animation: hx-pulse 1s infinite; }
    .live[data-state=thinking] .ldot { background: var(--warning); animation: hx-pulse 1.4s infinite; }
    .live[data-state=speaking] .ldot { background: var(--success); animation: hx-pulse .8s infinite; }
    .lst { font-weight: 600; font-size: 14px; }
    .lpart { color: var(--text-2); font-size: 13.5px; font-style: italic; }
    @media (prefers-reduced-motion: reduce) { .rdot, .ldot { animation: none !important; } }
    @media (max-width: 720px) { .thread { padding: 4px 12px 18px; } .composer-wrap { padding: 0 10px 8px; } .welcome h1 { font-size: 25px; } }
  `],
})
export class ChatPageComponent implements AfterViewChecked, OnDestroy {
  chat = inject(ChatService);
  chats = inject(ChatsService);
  private plugins = inject(PluginsService);
  undoing = signal('');
  dictating = signal(false);
  dictBusy = signal(false);
  private dict = new MicRecorder();
  signalR = inject(SignalRService);
  private session = inject(SessionService);
  private settings = inject(SettingsService);
  notices = inject(NoticePrefsService);
  presence = inject(PresenceService);
  private fb = inject(FeedbackService);
  private toast = inject(ToastService);
  private dialogs = inject(DialogService);
  private bottom = viewChild<ElementRef<HTMLElement>>('bottom');
  private ta = viewChild<ElementRef<HTMLTextAreaElement>>('ta');
  voice = inject(VoiceService);
  live = inject(LiveVoiceService);

  // one microphone: a tap dictates (text in the box, to read again), holding it records a voice message
  // (release to send, slide left to cancel); with the keyboard it dictates
  private mic = new MicRecorder();
  private router = inject(Router);
  recording = signal(false);
  recCancel = signal(false);
  private holdTimer: number | undefined;
  private held = false;
  /** Set when the button is released before the microphone has started: null = still held. */
  private released: boolean | null = null;
  micLabel = computed(() => this.dictating() ? 'Ferma la dettatura: il testo va nella casella'
    : 'Microfono: tocca per dettare, tieni premuto per un messaggio vocale');
  recSeconds = signal(0);
  private recX = 0;
  private recTimer: number | undefined;
  liveLabel = computed(() => LIVE_LABELS[this.live.state()] || '');

  text = '';
  mode = signal('auto');   // hx-chat-mode: this conversation's mode (Themis), sent with every message
  rated = signal<Record<string, 'good' | 'bad'>>({});
  /** Emoji reactions on Hestia's messages, like any chat (docs/work/2026-11-06-hestia-viva F4). */
  readonly reactions = REACTION_EMOJI;
  /** The assistant's chosen name (personal setting): the chat talks about her or him by name. */
  readonly identity = inject(IdentityService);
  picker = signal<string | null>(null);

  react(m: ChatMessage, emoji: string): void {
    this.picker.set(null);
    void this.chat.reactTo(m.id, emoji);
  }
  private lastCount = 0;
  private lastLen = 0;

  readonly suggestions = ['Cosa ho in agenda questa settimana?', 'Riassumi le ultime email importanti', 'Cosa ha pianificato Hestia per stanotte?', 'Ci sono nuove case interessanti?'];
  readonly menu: MenuItem[] = [
    { id: 'new', label: 'Nuova conversazione', icon: 'plus' },
    { id: 'clear', label: 'Pulisci schermo', icon: 'trash' },
  ];

  /** Dividers of the conversation: the day when it changes (always before the first message of another day than
   *  today) and the model when another one starts answering. */
  marks = computed(() => {
    const out: Record<string, { day?: string; model?: string }> = {};
    let day = '', model = '';
    for (const m of this.chat.messages()) {
      const d = dayKey(m.timestamp);
      if (d && d !== day) {
        if (day || d !== dayKey(new Date())) out[m.id] = { day: dayLabel(m.timestamp) };
        day = d;
      }
      if (m.role === 'assistant' && m.model) {
        if (model && m.model !== model) out[m.id] = { ...out[m.id], model: m.model };
        model = m.model;
      }
    }
    return out;
  });

  thinkingMode = computed(() => this.settings.settings().thinkingDisplay || 'compact');
  greeting = computed(() => {
    const h = new Date().getHours();
    return h < 6 ? 'Buona notte' : h < 13 ? 'Buongiorno' : h < 18 ? 'Buon pomeriggio' : 'Buonasera';
  });

  constructor() {
    // After a reload: queued messages keep their hourglass and an open question comes back (oracle-offline v3).
    void this.chat.restorePending();
    void this.identity.load();
    // «Ascolta» that gives no sound says why, with the way to the voice page.
    let seen = this.voice.failed()?.n ?? 0;
    effect(() => {
      const f = this.voice.failed();
      if (!f || f.n === seen) return;
      seen = f.n;
      untracked(() => this.toast.show(f.text, 'danger', { label: 'Apri Voce', run: () => void this.router.navigateByUrl('/p/echo/voce') }, 9000));
    });
  }

  ngOnDestroy() {
    if (this.recording()) void this.finishRec(true);
    if (this.dictating()) void this.dict.stop(true);
    // live mode goes on over the other pages (layout/live-overlay)
    this.voice.stop();
  }

  ngAfterViewChecked() {
    const msgs = this.chat.messages();
    const len = msgs.length ? msgs[msgs.length - 1].content.length : 0;
    if (msgs.length !== this.lastCount || len !== this.lastLen) {
      this.lastCount = msgs.length;
      this.lastLen = len;
      this.bottom()?.nativeElement.scrollIntoView({ block: 'end' });
    }
  }

  use(s: string) { this.text = s; this.send(); }

  /** «Annulla» under «Ho fatto»: the inverse tool, through the commands door (Hestia-MCP). */
  async undo(m: ChatMessage, i: number, c: ChatChange) {
    if (!c.undo) return;
    this.undoing.set(m.id + i);
    const r = await this.plugins.call<{ ok?: boolean; error?: string }>('mcp', 'POST', '/api/mcp/ui/tools/call',
      { body: { command: c.undo.tool, args: c.undo.args ?? {} } });
    this.undoing.set('');
    if (!r.ok || r.data?.ok === false) { this.toast.error(r.data?.error || 'Non annullato'); return; }
    this.chat.patch(m.id, { changes: (m.changes ?? []).map((x, k) => k === i ? { ...x, done: true } : x) });
    this.toast.success('Annullato');
  }

  /** Dictation (brainstorm C12): speak, the text lands in the box to read again; nothing is sent or kept. */
  async toggleDictation() {
    if (!this.dictating()) {
      try { await this.dict.start(); } catch { this.toast.error('Il browser non mi dà il microfono'); return; }
      this.dictating.set(true);
      return;
    }
    this.dictating.set(false);
    const out = await this.dict.stop();
    if (!out) return;
    this.dictBusy.set(true);
    try {
      const heard = await this.voice.dictate(out.blob, this.dict.mime);
      const t = (heard.text || '').trim();
      if (!t) { this.toast.show('Non ho sentito niente', 'warning'); return; }
      this.text = this.text.trim() ? `${this.text.trim()} ${t}` : t;
      queueMicrotask(() => { this.grow(); this.ta()?.nativeElement.focus(); });
    } catch {
      this.toast.error('Dettatura non disponibile ora');
    } finally {
      this.dictBusy.set(false);
    }
  }

  send() {
    const t = this.text.trim();
    if (!t || this.chat.isStreaming()) return;
    void this.chat.sendMessage(t, this.session.sessionId() || '', this.mode(), 'generic');
    this.text = '';
    queueMicrotask(() => this.grow());
  }

  onKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(); }
  }

  grow() {
    const el = this.ta()?.nativeElement;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 240) + 'px';
  }

  onFile(e: Event) {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    input.value = '';
    if (!f) return;
    const t = this.text.trim();
    this.text = '';
    void this.chat.sendDocument(f, t, this.session.sessionId() || '');
  }

  duration(seconds: number): string {
    const v = Math.max(0, Math.round(seconds || 0));
    return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
  }

  micDown(e: PointerEvent) {
    if (this.recording() || this.chat.isStreaming() || this.dictBusy()) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    this.recX = e.clientX;
    this.recCancel.set(false);
    this.held = false;
    if (this.dictating()) return;                       // the tap that stops the dictation
    this.holdTimer = window.setTimeout(() => { this.held = true; void this.startVoice(); }, 350);
  }

  private async startVoice() {
    this.released = null;
    try { await this.mic.start(); }
    catch { this.toast.error('Il browser non mi dà il microfono'); return; }
    this.voice.stop();
    this.recording.set(true);
    this.recSeconds.set(0);
    const t0 = performance.now();
    this.recTimer = window.setInterval(() => this.recSeconds.set((performance.now() - t0) / 1000), 250);
    if (this.released !== null) void this.finishRec(this.released);
  }

  micMove(e: PointerEvent) {
    if (!this.recording()) return;
    this.recCancel.set(this.recX - e.clientX > 80);
  }

  micUp() {
    window.clearTimeout(this.holdTimer);
    if (!this.held) { if (!this.chat.isStreaming() && !this.dictBusy()) void this.toggleDictation(); return; }
    this.held = false;
    if (this.recording()) void this.finishRec(this.recCancel()); else this.released = this.recCancel();
  }

  micCancel() {
    window.clearTimeout(this.holdTimer);
    if (!this.held) return;
    this.held = false;
    if (this.recording()) void this.finishRec(true); else this.released = true;
  }

  /** Enter or Space on the microphone (no pointer): dictation. */
  micKey(e: MouseEvent) { if (e.detail === 0) void this.toggleDictation(); }

  async finishRec(cancel: boolean) {
    window.clearInterval(this.recTimer);
    this.recording.set(false);
    this.recCancel.set(false);
    const out = await this.mic.stop(cancel);
    if (!out) return;
    void this.chat.sendVoice(out.blob, this.mic.mime, out.seconds, this.session.sessionId() || '', this.mode());
  }

  playVoice(m: ChatMessage) {
    if (!m.audio) return;
    if (this.voice.playing() === m.id) { this.voice.stop(); return; }
    void fetch(m.audio.url).then(r => r.blob()).then(b => this.voice.play(m.id, b));
  }

  toggleLive() {
    if (this.live.on) { this.live.stop(); return; }
    this.voice.stop();
    void this.live.start(this.mode()).then(() => { if (this.live.error()) this.toast.error(this.live.error()); });
  }

  answer(id: string, v: string) { this.chat.answerQuestion(id, v, this.session.sessionId() || '', this.mode()); }

  async feedback(label: 'good' | 'bad', m: ChatMessage) {
    const msgs = this.chat.messages();
    const idx = msgs.findIndex(x => x.id === m.id);
    const prompt = msgs.slice(0, Math.max(0, idx)).reverse().find(x => x.role === 'user')?.content || '';
    if (await this.fb.submit(label, '', { interactionId: m.traceId || m.id, prompt, response: m.content.replace(/<[^>]+>/g, '') })) {
      this.rated.update(r => ({ ...r, [m.id]: label }));
      this.toast.success('Grazie del feedback');
    }
  }

  async copy(m: ChatMessage) {
    const tmp = document.createElement('div');
    tmp.innerHTML = m.content;
    try { await navigator.clipboard.writeText(tmp.innerText); this.toast.success('Copiato'); } catch { /* */ }
  }

  async onMenu(id: string) {
    if (id === 'clear') this.chat.clearMessages();
    if (id === 'new' && await this.dialogs.confirm('Nuova conversazione?', 'Hestia dimentica il contesto di questa chat (le memorie restano).')) {
      await this.session.clear();
      this.chat.clearMessages();
    }
  }
}
