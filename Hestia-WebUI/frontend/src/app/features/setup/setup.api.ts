import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** Guided setup «Benvenuto» (docs/work/2026-10-30-setup-un-click §4.2): browser → WebUI → Hub → Hephaestus. */
export interface SetupState {
  completed: boolean;
  later: string[];
  voice?: { listen?: VoiceStep | VoiceStep[]; speak?: VoiceStep | VoiceStep[] };
  brain: { recipe?: string; local_model?: string; local_provider?: string; cloud?: string[];
           cloud_models?: Record<string, string | string[]>; summary?: string;
           embedding?: { provider?: string; model?: string }; modes?: Record<string, { provider?: string; model?: string; steps?: { provider: string; model: string }[] }>;
           order?: { provider: string; model: string }[] };
  hardware: { os?: string; ram_gb?: number; gpu?: string; vram_gb?: number; free_gb?: number };
  telegram: { token: boolean; owner: boolean; linked: boolean; code_active: boolean };
  backup: { passphrase: boolean };
  claude: { token: boolean };
}
export interface CatalogModel { model: string; size_gb: number; good: string; }
/** A chat model a program on this computer already has (size 0 = the program does not say). */
export interface LocalModel { model: string; size_gb: number; params: string; quant: string; fits: boolean; }
/** A program for local models (Ollama, LM Studio, Jan, llama.cpp, vLLM): found on its usual port or not. */
/** ``host`` empty = this computer; else another computer of the house (``type`` ollama | openai). */
export interface Runtime { name: string; label: string; url: string; site: string; found: boolean; configured: boolean;
  models: LocalModel[]; embed: string[]; host?: string; type?: string; }
export interface CloudProvider { name: string; label: string; type: string; key_set: boolean; available: boolean; }
export interface BrainCatalog {
  recommended: { tier: string; label: string; chat: CatalogModel[]; model: string; embedding: CatalogModel; recipe: string };
  installed: string[];
  local?: LocalModel[];
  runtimes?: Runtime[];
  /** The memory's model now (one step: changing it re-indexes the memory). */
  embedding?: { provider: string; model: string };
  ollama: boolean;
  cloud: CloudProvider[];
}
/** Any module's download (models through Ollama, voices in Hestia's data folder), as the Download page lists them. */
/** A speech service of the setup «Voce» (Echo's blocks): local engines first, then cloud ones (key needed). */
export interface VoiceOption { id: string; label: string; note?: string; }
export interface VoiceProvider { name: string; label: string; type: string; local: boolean; needs_key: boolean; key: boolean;
  state: string; models: VoiceOption[]; voices: VoiceOption[]; note?: string; found?: boolean; url?: string; }
/** ``url``/``type``/``label`` only for a speech program found at home that is not a block yet. */
export interface VoiceStep { provider: string; model: string; voice: string; url?: string; type?: string; label?: string; }
/** Per direction: the services, the first step now and the whole chain in order. */
export interface VoiceDirection { providers: VoiceProvider[]; current: VoiceStep; steps?: VoiceStep[];
  /** Free speech programs not found at home, offered to install (Chatterbox, Kokoro, Speaches). */
  programs?: { name: string; label: string; site: string; note: string }[]; }
export interface VoiceCatalog { ascolto: VoiceDirection; voce: VoiceDirection; }
export interface Download { module?: string; id: string; what: string; source?: string;
  state: 'in_coda' | 'in_corso' | 'in_pausa' | 'fatto' | 'errore'; size: number; done: number;
  speed?: number; eta_s?: number | null; error?: string; }
export interface Outcome { ok: boolean; detail?: string; }
/** «Prova»: the model tried ('' = pick another) and the chat models the service really has. */
export interface TestOutcome extends Outcome { model?: string; models?: string[]; recommended?: string[]; embed?: string[]; }
type RuntimeRef = { url?: string; type?: string; label?: string };
export interface BrainChoice { local_provider: string; cloud_models: Record<string, string[]>;
  embedding: ({ provider: string; model: string } & RuntimeRef) | null; local_runtime: RuntimeRef;
  /** «Per modalità»: potente / codice / visione with their own model (first there, the general choice after). */
  modes: Record<string, { steps: ({ provider: string; model: string } & RuntimeRef)[] }>;
  /** «Scelti» in the user's order, local and cloud mixed. */
  order?: { provider: string; model: string }[]; }
export interface TunnelState { on: boolean; url: string; detail?: string; phase?: '' | 'start' | 'download' | 'address' | 'ready' | 'error'; }

@Injectable({ providedIn: 'root' })
export class SetupApi {
  private http = inject(HttpClient);
  private base = '/api/webui/setup';

  private get<T>(path: string) { return firstValueFrom(this.http.get<T>(`${this.base}/${path}`)); }
  private post<T>(path: string, body: object = {}) { return firstValueFrom(this.http.post<T>(`${this.base}/${path}`, body)); }

  state() { return this.get<SetupState>('state'); }
  later(step: string) { return this.post<SetupState>('later', { step }); }
  complete() { return this.post<SetupState>('complete'); }
  /** ``hosts``: other computers of the house to look on too. */
  catalog(hosts: string[] = []) { return this.get<BrainCatalog>('brain/catalog' + (hosts.length ? `?hosts=${encodeURIComponent(hosts.join(','))}` : '')); }
  /** «Ascolta» on a chosen voice / «Prova» of listening, with that provider only (nothing saved). */
  voicePreview(provider: string, voice: string, model = '') {
    return this.post<{ ok: boolean; audio_b64?: string; mime_type?: string; detail?: string }>('voice/preview', { provider, voice, model });
  }
  voiceHear(provider: string, model: string, audio_b64: string, mime_type: string) {
    return this.post<{ ok: boolean; text?: string; detail?: string }>('voice/hear', { provider, model, audio_b64, mime_type });
  }
  /** «I modelli sono pronti»: the assistant's first message, written with the models just chosen. */
  hello() { return this.post<{ ok: boolean; text?: string; model?: string; provider?: string; detail?: string }>('brain/hello'); }
  test(provider: string, key = '', model = '') { return this.post<TestOutcome>('brain/test', { provider, key, model }); }
  apply(recipe: string, local_model: string, cloud: string[], claude_token: string, choice: BrainChoice) {
    return this.post<Outcome>('brain/apply', { recipe, local_model, cloud, claude_token, local_provider: choice.local_provider,
      cloud_models: choice.cloud_models, embedding: choice.embedding || {}, local_runtime: choice.local_runtime || {},
      modes: choice.modes || {}, order: choice.order || [] });
  }
  /** Setup «Voce»: the speech services (Echo), «Prova» (a typed key is saved first), the choice → Echo's chains. */
  voiceCatalog(hosts: string[] = []) { return this.get<VoiceCatalog>('voice/catalog' + (hosts.length ? `?hosts=${encodeURIComponent(hosts.join(','))}` : '')); }
  voiceTest(provider: string, key = '') {
    return this.post<Outcome & { models?: VoiceOption[]; voices?: VoiceOption[]; recommended?: Record<string, string[]> }>('voice/test', { provider, key });
  }
  /** Per direction the steps in order: the local engine, then the cloud services as fallbacks. */
  voiceApply(listen: VoiceStep[], speak: VoiceStep[]) { return this.post<Outcome & { queued?: string[] }>('voice/apply', { listen, speak }); }
  /** Echo's local voice models (through the WebUI voice door, not Hephaestus). */
  prefetchVoice() { return firstValueFrom(this.http.post<{ queued: string[] }>('/api/webui/voice/models/prefetch', {})); }
  pulls() { return this.get<{ downloads: Download[] }>('brain/pulls').then(r => r.downloads || []); }
  /** Every download of every module (models and voices): the same list as the Download page. */
  allDownloads() {
    return firstValueFrom(this.http.get<{ downloads: Download[] }>('/api/webui/downloads')).then(r => r.downloads || []);
  }
  telegramToken(token: string) { return this.post<Outcome & { code?: string; expires_in?: number }>('telegram/token', { token }); }
  telegramCode() { return this.post<{ code: string; expires_in: number }>('telegram/code'); }
  backup(passphrase: string) { return this.post<Outcome>('backup', { passphrase }); }
  /** «Da fuori casa»: the Cloudflare quick tunnel to this WebUI (Hephaestus starts/stops it). */
  tunnel() { return this.get<TunnelState>('tunnel'); }
  setTunnel(on: boolean) { return this.post<TunnelState>('tunnel', { on }); }
}

/** Plain words for an HTTP error of these endpoints. */
export function setupError(e: any): string {
  if (e?.status === 0) return 'Hestia non risponde: controlla che sia accesa.';
  const d = e?.error?.detail;
  if (typeof d === 'string' && d) return d.replace(/^\d+$/, 'Qualcosa non ha funzionato.');
  if (Array.isArray(d)) return 'Controlla il valore inserito.';
  return 'Qualcosa non ha funzionato, riprova tra poco.';
}
