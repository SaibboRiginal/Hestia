/** Helpers shared by the Voce page: API prefix, labels, audio in the browser (play base64, record the mic). */
export const API = '/api/voice';

export const STATES: Record<string, { label: string; tone: string }> = {
  ready: { label: 'pronto', tone: 'success' },
  no_key: { label: 'manca la chiave', tone: 'warning' },
  no_url: { label: 'manca l\'indirizzo', tone: 'warning' },
  not_installed: { label: 'non installato', tone: 'warning' },
  downloading: { label: 'scarico il modello', tone: 'info' },
  quota: { label: 'senza quota', tone: 'warning' },
  missing: { label: 'fornitore tolto', tone: 'danger' },
  wrong_direction: { label: 'direzione sbagliata', tone: 'danger' },
};

export const DIRECTIONS = [{ value: 'ascolto', label: 'Ascolto (voce → testo)' }, { value: 'voce', label: 'Voce (testo → voce)' }];

export function slug(s: string): string {
  return s.trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '');
}

export function clone<T>(v: T): T { return JSON.parse(JSON.stringify(v ?? {})); }

export function bytes(n: number | null | undefined): string {
  const v = Number(n || 0);
  if (v < 1024 * 1024) return `${Math.round(v / 1024)} KB`;
  if (v < 1024 ** 3) return `${(v / 1024 / 1024).toFixed(1).replace('.', ',')} MB`;
  return `${(v / 1024 ** 3).toFixed(2).replace('.', ',')} GB`;
}

export function secs(n: number | null | undefined): string {
  const v = Math.round(Number(n || 0));
  return v < 60 ? `${v} s` : `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return '–';
  const d = new Date(iso);
  const today = new Date().toDateString() === d.toDateString();
  return today ? d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function money(eur: number | null | undefined): string {
  const v = Number(eur || 0);
  return v ? `${v < 0.01 ? v.toFixed(4) : v.toFixed(2)} €`.replace('.', ',') : '0 €';
}

/** Plays base64 audio; returns the element so the caller can stop it. */
export function playB64(b64: string, mime = 'audio/ogg'): HTMLAudioElement {
  const raw = atob(b64);
  const buf = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([buf], { type: mime }));
  const el = new Audio(url);
  el.onended = () => URL.revokeObjectURL(url);
  el.play().catch(() => URL.revokeObjectURL(url));
  return el;
}

export function blobToB64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',', 2)[1] || '');
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

/** Microphone recorder (webm/opus where the browser has it). */
export class Recorder {
  private rec: MediaRecorder | null = null;
  private parts: Blob[] = [];
  private stream: MediaStream | null = null;
  mime = '';

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const types = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
    const mime = types.find(t => (window as any).MediaRecorder?.isTypeSupported?.(t)) || '';
    this.rec = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.mime = (this.rec.mimeType || mime || 'audio/webm').split(';')[0];
    this.parts = [];
    this.rec.ondataavailable = e => { if (e.data.size) this.parts.push(e.data); };
    this.rec.start();
  }

  stop(): Promise<Blob | null> {
    return new Promise(resolve => {
      if (!this.rec) { resolve(null); return; }
      this.rec.onstop = () => {
        this.stream?.getTracks().forEach(t => t.stop());
        resolve(this.parts.length ? new Blob(this.parts, { type: this.mime }) : null);
        this.rec = null;
      };
      this.rec.stop();
    });
  }
}
