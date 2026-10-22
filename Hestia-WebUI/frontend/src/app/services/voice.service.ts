import { Injectable, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/**
 * Voice in the WebUI (dossier docs/work/2026-10-20-modulo-voce §7). The browser only records and plays:
 * listening and speaking happen in the voice module through `/api/webui/voice/*`.
 * - voice messages in the chat (recording kept with its message, transcript shown under the audio);
 * - «Ascolta» under a reply (audio kept with the reply: the second time it is not generated again);
 * - helpers for live mode «Parla» (listen/say streams), used by LiveVoiceService.
 */
export const VOICE_API = '/api/webui/voice';
/** mp3 plays everywhere (Safari has no ogg/opus in <audio>). */
export const PLAY_FORMAT = 'mp3';

export interface Heard { text: string; provider?: string; duration_s?: number; }

export function blobToB64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',', 2)[1] || '');
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

export function b64ToBlob(b64: string, mime: string): Blob {
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  return new Blob([buf], { type: mime });
}

/** Plain text of a rendered answer (the voice module also drops markdown, links and code). */
export function speakableText(html: string): string {
  const el = document.createElement('div');
  el.innerHTML = html;
  el.querySelectorAll('pre, code, table').forEach(n => n.remove());
  return (el.innerText || el.textContent || '').trim();
}

export function recorderMime(): string {
  const types = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
  return types.find(t => (window as any).MediaRecorder?.isTypeSupported?.(t)) || '';
}

/** Microphone recording of one voice message. */
export class MicRecorder {
  private rec: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private parts: Blob[] = [];
  private startedAt = 0;
  mime = 'audio/webm';

  get active() { return !!this.rec; }

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    const mime = recorderMime();
    this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.mime = (this.rec.mimeType || mime || 'audio/webm').split(';')[0];
    this.parts = [];
    this.rec.ondataavailable = e => { if (e.data.size) this.parts.push(e.data); };
    this.rec.start();
    this.startedAt = performance.now();
  }

  /** Stops; `null` when cancelled or too short to be a message. */
  stop(cancel = false): Promise<{ blob: Blob; seconds: number } | null> {
    return new Promise(resolve => {
      const rec = this.rec;
      if (!rec) { resolve(null); return; }
      const seconds = (performance.now() - this.startedAt) / 1000;
      rec.onstop = () => {
        this.stream?.getTracks().forEach(t => t.stop());
        this.stream = null;
        const blob = new Blob(this.parts, { type: this.mime });
        resolve(cancel || seconds < 0.6 || !blob.size ? null : { blob, seconds });
      };
      this.rec = null;
      rec.stop();
    });
  }
}

@Injectable({ providedIn: 'root' })
export class VoiceService {
  private http = inject(HttpClient);
  private player: HTMLAudioElement | null = null;
  private playerUrl = '';
  /** Id of the message whose audio is playing (or loading), for the play/stop toggle. */
  playing = signal<string | null>(null);
  loading = signal<string | null>(null);

  post<T = any>(path: string, body: unknown): Promise<T> {
    return firstValueFrom(this.http.post<T>(`${VOICE_API}/${path}`, body));
  }

  get<T = any>(path: string, params: Record<string, string> = {}): Promise<T> {
    return firstValueFrom(this.http.get<T>(`${VOICE_API}/${path}`, { params }));
  }

  /** Text of a voice message; the recording is kept with the message `messageId`. */
  async transcribe(blob: Blob, mime: string, messageId: string, useCase = 'webui.vocale'): Promise<Heard> {
    return this.post<Heard>('transcribe', {
      audio_b64: await blobToB64(blob), mime_type: mime, use_case: useCase,
      keep: { kind: 'recording', message_id: messageId },
    });
  }

  /** «Ascolta»: play/stop the reading of a reply (the kept one when it exists). */
  async toggle(messageId: string, html: string): Promise<void> {
    if (this.playing() === messageId || this.loading() === messageId) { this.stop(); return; }
    this.stop();
    const text = speakableText(html);
    if (!text) return;
    this.loading.set(messageId);
    try {
      const out = await this.post<any>('speak', { text, format: PLAY_FORMAT, use_case: 'webui.ascolta',
                                                 keep: { kind: 'generated', message_id: messageId } });
      if (this.loading() !== messageId) return;          // stopped meanwhile
      this.play(messageId, b64ToBlob(out.audio_b64, out.mime_type || 'audio/mpeg'));
    } finally {
      if (this.loading() === messageId) this.loading.set(null);
    }
  }

  /** Plays a blob (a recorded voice message or a reading); one sound at a time. */
  play(id: string, blob: Blob): HTMLAudioElement {
    this.stop();
    this.playerUrl = URL.createObjectURL(blob);
    const el = new Audio(this.playerUrl);
    this.player = el;
    this.playing.set(id);
    el.onended = () => { if (this.player === el) this.stop(); };
    el.play().catch(() => this.stop());
    return el;
  }

  stop(): void {
    this.player?.pause();
    this.player = null;
    if (this.playerUrl) URL.revokeObjectURL(this.playerUrl);
    this.playerUrl = '';
    this.playing.set(null);
    this.loading.set(null);
  }
}
