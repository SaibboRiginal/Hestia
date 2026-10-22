import { Injectable, inject, signal } from '@angular/core';
import { uid } from '../core/uid';
import { ChatService } from './chat.service';
import { SessionService } from './session.service';
import { PLAY_FORMAT, VoiceService, b64ToBlob, blobToB64, recorderMime, speakableText } from './voice.service';

/**
 * Live mode «Parla» (dossier docs/work/2026-10-20-modulo-voce §7.1): a conversation by voice with the same Hestia
 * of the chat (same models, same conversation; no external live service). The browser only:
 * - notices when Marko speaks and when he stops (pause = `echo.live.silence_ms`, from the voice module);
 * - sends the microphone in chunks to the listen stream (partial text shown while speaking);
 * - sends the answer to the say stream while it is written and plays the sentences in order;
 * - stops talking when Marko starts speaking again (or taps «Interrompi»).
 * The chat shows everything as usual: voice bubble + transcript, written answer.
 */
export type LiveState = 'off' | 'starting' | 'listening' | 'hearing' | 'thinking' | 'speaking';

const TICK_MS = 60;
const SPEECH_START_MS = 180;
const BARGE_IN_MS = 450;
const CHUNK_MS = 800;

@Injectable({ providedIn: 'root' })
export class LiveVoiceService {
  private voice = inject(VoiceService);
  private chat = inject(ChatService);
  private session = inject(SessionService);

  state = signal<LiveState>('off');
  partial = signal('');
  error = signal('');

  private stream: MediaStream | null = null;
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private timer: number | undefined;
  private silenceMs = 900;
  private floor = 0.01;
  private loudFor = 0;
  private quietFor = 0;
  private mode = 'auto';

  // hearing
  private rec: MediaRecorder | null = null;
  private mime = 'audio/webm';
  private parts: Blob[] = [];
  private listenId = '';
  private seq = 0;
  private sending: Promise<unknown> = Promise.resolve();
  private heardAt = 0;

  // speaking
  private answerId = '';
  private sayId = '';
  private sentLen = 0;
  private sayChain: Promise<unknown> = Promise.resolve();
  private queue: Blob[] = [];
  private audio: HTMLAudioElement | null = null;
  private answerDone = false;
  private sayDone = false;

  get on() { return this.state() !== 'off'; }

  async start(mode = 'auto'): Promise<void> {
    if (this.on) return;
    this.mode = mode;
    this.state.set('starting');
    this.error.set('');
    try {
      const cfg = await this.voice.get<any>('live').catch(() => ({}));
      this.silenceMs = Number(cfg?.silence_ms) || this.silenceMs;
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      this.ctx = new AudioContext();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      this.ctx.createMediaStreamSource(this.stream).connect(this.analyser);
    } catch {
      this.error.set('Il browser non mi dà il microfono.');
      this.stop();
      return;
    }
    this.mime = (recorderMime() || 'audio/webm').split(';')[0];
    this.state.set('listening');
    this.timer = window.setInterval(() => this.tick(), TICK_MS);
  }

  stop(): void {
    window.clearInterval(this.timer);
    this.timer = undefined;
    this.cancelSpeaking();
    if (this.rec) { try { this.rec.stop(); } catch { /* */ } this.rec = null; }
    this.stream?.getTracks().forEach(t => t.stop());
    this.stream = null;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    this.analyser = null;
    this.partial.set('');
    this.state.set('off');
  }

  /** «Interrompi»: stop the voice (and the answer still being written), listen again. */
  interrupt(): void {
    if (this.chat.isStreaming()) this.chat.cancelStream();
    this.cancelSpeaking();
    if (this.on) this.state.set('listening');
  }

  // ── microphone level ───────────────────────────────────────────────────
  private level(): number {
    if (!this.analyser) return 0;
    const buf = new Float32Array(this.analyser.fftSize);
    this.analyser.getFloatTimeDomainData(buf);
    let sum = 0;
    for (const v of buf) sum += v * v;
    return Math.sqrt(sum / buf.length);
  }

  private tick(): void {
    const lvl = this.level();
    const st = this.state();
    if (st === 'listening' || st === 'thinking') this.floor = this.floor * 0.97 + Math.min(lvl, 0.05) * 0.03;
    const loud = lvl > Math.max(0.02, this.floor * 3);
    this.loudFor = loud ? this.loudFor + TICK_MS : 0;
    this.quietFor = loud ? 0 : this.quietFor + TICK_MS;
    if (st === 'listening' && this.loudFor >= SPEECH_START_MS) void this.beginHearing();
    else if (st === 'hearing' && this.quietFor >= this.silenceMs) void this.endHearing();
    else if (st === 'speaking' && lvl > Math.max(0.05, this.floor * 6) && this.loudFor >= BARGE_IN_MS) {
      this.interrupt();
      void this.beginHearing();
    }
  }

  // ── hearing: mic → listen stream ───────────────────────────────────────
  private async beginHearing(): Promise<void> {
    if (!this.stream || this.rec) return;
    this.state.set('hearing');
    this.partial.set('');
    this.parts = [];
    this.seq = 0;
    this.listenId = '';
    this.heardAt = performance.now();
    const rec = new MediaRecorder(this.stream, recorderMime() ? { mimeType: recorderMime() } : undefined);
    this.rec = rec;
    const opened = this.voice.post<any>('listen', { mime_type: this.mime, use_case: 'webui.live.ascolto' })
      .then(r => { this.listenId = r.stream_id; }).catch(() => { this.listenId = ''; });
    this.sending = opened;
    rec.ondataavailable = e => {
      if (!e.data.size) return;
      this.parts.push(e.data);
      const seq = this.seq++;
      const chunk = e.data;
      this.sending = this.sending.then(async () => {
        if (!this.listenId) return;
        const r = await this.voice.post<any>(`listen/${this.listenId}/chunk`, { seq, audio_b64: await blobToB64(chunk) })
          .catch(() => null);
        if (r?.partial && this.state() === 'hearing') this.partial.set(r.partial);
      });
    };
    rec.start(CHUNK_MS);
  }

  private async endHearing(): Promise<void> {
    const rec = this.rec;
    if (!rec) return;
    this.rec = null;
    this.state.set('thinking');
    const seconds = (performance.now() - this.heardAt) / 1000;
    await new Promise<void>(resolve => { rec.onstop = () => resolve(); rec.stop(); });
    await this.sending;
    const id = uid();
    const blob = new Blob(this.parts, { type: this.mime });
    let text = '';
    try {
      const out = this.listenId
        ? await this.voice.post<any>(`listen/${this.listenId}/end`, { keep: { kind: 'recording', message_id: id } })
        : await this.voice.transcribe(blob, this.mime, id, 'webui.live.ascolto');
      text = String(out?.text || '').trim();
    } catch { text = ''; }
    this.partial.set('');
    if (!this.on) return;
    if (!text) { this.state.set('listening'); return; }
    this.chat.messages.update(msgs => [...msgs, { id, role: 'user', content: text, timestamp: new Date(),
                                                  audio: { url: URL.createObjectURL(blob), seconds } }]);
    await this.chat.sendMessage(text, this.session.sessionId() || '', this.mode, 'generic', undefined, id);
    this.followAnswer();
  }

  // ── speaking: answer text → say stream → sentences played in order ─────
  private followAnswer(): void {
    this.answerId = this.chat.currentStreamingId() || '';
    this.sayId = '';
    this.sentLen = 0;
    this.queue = [];
    this.answerDone = false;
    this.sayDone = false;
    this.sayChain = this.voice.post<any>('say', { format: PLAY_FORMAT, use_case: 'webui.live.voce' })
      .then(r => { this.sayId = r.stream_id; }).catch(() => { this.sayId = ''; });
    const poll = window.setInterval(() => {
      if (!this.on || this.state() === 'hearing' || this.state() === 'listening' && !this.answerId) { window.clearInterval(poll); return; }
      const msg = this.chat.messages().find(m => m.id === this.answerId);
      if (!msg) { window.clearInterval(poll); this.state.set('listening'); return; }
      const text = speakableText(msg.content);
      if (text.length > this.sentLen && !msg.isStreaming || text.length > this.sentLen + 40) {
        const delta = text.slice(this.sentLen);
        this.sentLen = text.length;
        this.pushSay('text', delta);
      }
      if (!msg.isStreaming && !this.answerDone) {
        this.answerDone = true;
        window.clearInterval(poll);
        if (msg.error || !text) { this.state.set('listening'); return; }
        this.pushSay('end', '', this.answerId);
      }
    }, 300);
  }

  private pushSay(step: 'text' | 'end', delta: string, keepId = ''): void {
    const answerId = this.answerId;
    this.sayChain = this.sayChain.then(async () => {
      if (!this.sayId || answerId !== this.answerId) return;
      const body: any = step === 'text' ? { delta } : { keep: { kind: 'generated', message_id: keepId } };
      const r = await this.voice.post<any>(`say/${this.sayId}/${step}`, body).catch(() => null);
      if (answerId !== this.answerId) return;
      for (const b of r?.blocks || []) this.queue.push(b64ToBlob(b.audio_b64, b.mime_type || 'audio/mpeg'));
      if (step === 'end') this.sayDone = true;
      this.playNext();
    });
  }

  private playNext(): void {
    if (this.audio || !this.on) return;
    const next = this.queue.shift();
    if (!next) {
      if (this.sayDone && this.state() === 'speaking') this.state.set('listening');
      return;
    }
    this.state.set('speaking');
    this.loudFor = 0;
    const url = URL.createObjectURL(next);
    const el = new Audio(url);
    this.audio = el;
    const done = () => { URL.revokeObjectURL(url); if (this.audio === el) { this.audio = null; this.playNext(); } };
    el.onended = done;
    el.onerror = done;
    el.play().catch(done);
  }

  private cancelSpeaking(): void {
    this.answerId = '';
    this.queue = [];
    this.sayDone = true;
    if (this.audio) { this.audio.pause(); this.audio = null; }
  }
}
