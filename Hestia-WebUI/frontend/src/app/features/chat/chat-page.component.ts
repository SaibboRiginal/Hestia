import {
  AfterViewChecked, ChangeDetectionStrategy, OnDestroy, Component, ElementRef, computed, inject, signal, viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../services/chat.service';
import { SessionService } from '../../services/session.service';
import { SettingsService } from '../../services/settings.service';
import { FeedbackService } from '../../services/feedback.service';
import { SignalRService } from '../../services/signalr.service';
import { ChatMessage } from '../../models/chat.models';
import { ButtonComponent, DialogService, IconComponent, MenuComponent, MenuItem, ToastService } from '../../ui';
import { ThinkingStepsComponent } from './thinking-steps.component';
import { ChatModeComponent } from './chat-mode.component';
import { ChatContextComponent } from './chat-context.component';
import { QuestionCardComponent } from './question-card.component';
import { ChatQuickSettingsComponent } from '../settings/chat-quick-settings.component';
import { NoticePrefsService } from '../../services/notice-prefs.service';
import { PresenceService } from '../../services/presence.service';
import { MicRecorder, VoiceService } from '../../services/voice.service';
import { LiveVoiceService } from '../../services/live-voice.service';

const LIVE_LABELS: Record<string, string> = {
  starting: 'Accendo il microfono…', listening: 'Ti ascolto', hearing: 'Ti sento…', thinking: 'Ci penso…', speaking: 'Sto parlando',
};

/** Chat with Hestia (Oracle via SignalR): streaming, reasoning, questions, attachments, feedback. */
@Component({
  selector: 'app-chat-page',
  imports: [FormsModule, ButtonComponent, IconComponent, MenuComponent, ThinkingStepsComponent, ChatQuickSettingsComponent,
            ChatModeComponent, ChatContextComponent, QuestionCardComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="top">
      <span class="ttl">{{ chat.messages().length ? 'Conversazione' : '' }}</span>
      <div class="hx-grow"></div>
      <button hx-btn [variant]="live.on ? 'primary' : 'ghost'" size="sm" icon="waveform" (click)="toggleLive()"
              [attr.aria-pressed]="live.on" title="Parla con Hestia a voce">Parla</button>
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
              </div></div>
            } @else {
              <div class="msg user hx-fade-in"><div class="bubble">@if (m.icon) { <hx-icon class="bi" [name]="m.icon" [size]="14" /> }{{ m.content }}</div></div>
            }
          } @else {
            <div class="msg asst hx-fade-in">
              @if (m.thinkingSteps?.length && thinkingMode() !== 'hidden') {
                <chat-thinking [steps]="m.thinkingSteps!" [live]="!!m.isStreaming && !m.content" [display]="thinkingMode()" />
              }
              @if (m.error) { <div class="err"><hx-icon name="alert" tone="danger" [size]="15" /><span>{{ m.content }}</span></div> }
              @else if (m.content) { <div class="hx-prose" [class.queued]="m.queuedId" [innerHTML]="m.content"></div> }
              @if (m.queuedId) { <div class="inq"><hx-icon name="clock" [size]="14" /> In coda</div> }
              @else if (m.isStreaming) { <div class="typing"><span></span><span></span><span></span></div> }
              @if (m.isStreaming && m.content) { <span class="caret"></span> }
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
              @if (!m.isStreaming && m.content && !m.queuedId) {
                <div class="foot">
                  <button class="fb" [class.on]="rated()[m.id] === 'good'" (click)="feedback('good', m)" title="Utile"><hx-icon name="thumb-up" [size]="15" /></button>
                  <button class="fb" [class.on]="rated()[m.id] === 'bad'" (click)="feedback('bad', m)" title="Non utile"><hx-icon name="thumb-down" [size]="15" /></button>
                  <button class="fb" (click)="copy(m)" title="Copia"><hx-icon name="copy" [size]="15" /></button>
                  <button class="fb" [class.on]="voice.playing() === m.id" (click)="voice.toggle(m.id, m.content)"
                          [title]="voice.playing() === m.id || voice.loading() === m.id ? 'Ferma' : 'Ascolta'">
                    <hx-icon [name]="voice.playing() === m.id || voice.loading() === m.id ? 'stop' : 'volume'" [size]="15" /></button>
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
      <div class="composer" [class.disabled]="signalR.connectionState() !== 'connected'">
        @if (recording()) {
          <div class="rec" role="status">
            <span class="rdot"></span><span class="rtime">{{ duration(recSeconds()) }}</span>
            @if (recLocked()) {
              <div class="hx-grow"></div>
              <button hx-btn variant="ghost" size="sm" icon="trash" iconOnly aria-label="Annulla il vocale" (click)="finishRec(true)"></button>
              <button hx-btn variant="primary" size="sm" icon="send" iconOnly aria-label="Invia il vocale" (click)="finishRec(false)"></button>
            } @else {
              <span class="rhint" [class.cancel]="recCancel()">{{ recCancel() ? 'Rilascia per annullare' : '‹ Scorri per annullare' }}</span>
            }
          </div>
        }
        <textarea #ta [hidden]="recording()" [(ngModel)]="text" (keydown)="onKey($event)" (input)="grow()" rows="1"
                  [placeholder]="signalR.connectionState() === 'connected' ? 'Scrivi a Hestia…' : 'Connessione in corso…'"></textarea>
        <div class="tools">
          <input #file type="file" hidden (change)="onFile($event)" />
          <button hx-btn variant="ghost" size="sm" icon="paperclip" iconOnly aria-label="Allega" (click)="file.click()" [disabled]="chat.isStreaming()"></button>
          <hx-chat-mode [(mode)]="mode" />
          <div class="hx-grow"></div>
          @if (chat.isStreaming()) {
            <button hx-btn variant="secondary" size="sm" icon="stop" iconOnly aria-label="Stop" (click)="chat.cancelStream()"></button>
          } @else if (text.trim() || recLocked()) {
            @if (!recording()) { <button hx-btn variant="primary" size="sm" icon="send" iconOnly aria-label="Invia" (click)="send()" [disabled]="!text.trim()"></button> }
          } @else {
            <button hx-btn [variant]="recording() ? 'primary' : 'ghost'" size="sm" icon="mic" iconOnly class="micbtn"
                    aria-label="Tieni premuto per registrare un vocale" title="Vocale: tieni premuto (o clic per registrare)"
                    (pointerdown)="micDown($event)" (pointermove)="micMove($event)" (pointerup)="micUp($event)"
                    (pointercancel)="finishRec(true)" (contextmenu)="$event.preventDefault()"></button>
          }
        </div>
      </div>
      <p class="disc">Invio per mandare · Shift+Invio per andare a capo · tieni premuto il microfono per un vocale</p>
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
    .caret { display: inline-block; width: 8px; height: 17px; background: var(--accent); vertical-align: text-bottom; margin-left: 2px; animation: hx-pulse 1s infinite; border-radius: 2px; }
    .typing { display: inline-flex; gap: 4px; padding: 6px 0; }
    .typing span { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); animation: hx-pulse 1.2s infinite; }
    .typing span:nth-child(2) { animation-delay: .2s; } .typing span:nth-child(3) { animation-delay: .4s; }
    .foot { display: flex; gap: 2px; margin-top: 8px; opacity: 0; transition: opacity var(--dur); }
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
    .hx-prose.queued { color: var(--text-2); }
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

  // voice message: hold to record, release to send, slide left to cancel; mouse: click, then bin or send
  private mic = new MicRecorder();
  recording = signal(false);
  recLocked = signal(false);
  recCancel = signal(false);
  recSeconds = signal(0);
  private recX = 0;
  private recTimer: number | undefined;
  liveLabel = computed(() => LIVE_LABELS[this.live.state()] || '');

  text = '';
  mode = signal('auto');   // hx-chat-mode: this conversation's mode (Themis), sent with every message
  rated = signal<Record<string, 'good' | 'bad'>>({});
  private lastCount = 0;
  private lastLen = 0;

  readonly suggestions = ['Cosa ho in agenda questa settimana?', 'Riassumi le ultime email importanti', 'Cosa ha pianificato Hestia per stanotte?', 'Ci sono nuove case interessanti?'];
  readonly menu: MenuItem[] = [
    { id: 'new', label: 'Nuova conversazione', icon: 'plus' },
    { id: 'clear', label: 'Pulisci schermo', icon: 'trash' },
  ];

  thinkingMode = computed(() => this.settings.settings().thinkingDisplay || 'compact');
  greeting = computed(() => {
    const h = new Date().getHours();
    return h < 6 ? 'Buona notte' : h < 13 ? 'Buongiorno' : h < 18 ? 'Buon pomeriggio' : 'Buonasera';
  });

  constructor() {
    // After a reload: queued messages keep their hourglass and an open question comes back (oracle-offline v3).
    void this.chat.restorePending();
  }

  ngOnDestroy() {
    if (this.recording()) void this.finishRec(true);
    this.live.stop();
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

  async micDown(e: PointerEvent) {
    if (this.recording() || this.chat.isStreaming()) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    this.recX = e.clientX;
    this.recCancel.set(false);
    this.recLocked.set(e.pointerType === 'mouse');
    try { await this.mic.start(); }
    catch { this.toast.error('Il browser non mi dà il microfono'); return; }
    this.voice.stop();
    this.recording.set(true);
    this.recSeconds.set(0);
    const t0 = performance.now();
    this.recTimer = window.setInterval(() => this.recSeconds.set((performance.now() - t0) / 1000), 250);
  }

  micMove(e: PointerEvent) {
    if (!this.recording() || this.recLocked()) return;
    this.recCancel.set(this.recX - e.clientX > 80);
  }

  micUp(_e: PointerEvent) {
    if (!this.recording() || this.recLocked()) return;
    void this.finishRec(this.recCancel());
  }

  async finishRec(cancel: boolean) {
    window.clearInterval(this.recTimer);
    this.recording.set(false);
    this.recLocked.set(false);
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
    if (await this.fb.submit(label, '', { interactionId: m.id, prompt, response: m.content.replace(/<[^>]+>/g, '') })) {
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
