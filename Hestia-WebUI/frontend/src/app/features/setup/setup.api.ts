import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** Guided setup «Benvenuto» (docs/work/2026-10-30-setup-un-click §4.2): browser → WebUI → Hub → Hephaestus. */
export interface SetupState {
  completed: boolean;
  later: string[];
  brain: { recipe?: string; local_model?: string; local_provider?: string; cloud?: string[];
           cloud_models?: Record<string, string>; summary?: string };
  hardware: { os?: string; ram_gb?: number; gpu?: string; vram_gb?: number; free_gb?: number };
  telegram: { token: boolean; owner: boolean; linked: boolean; code_active: boolean };
  backup: { passphrase: boolean };
  claude: { token: boolean };
}
export interface CatalogModel { model: string; size_gb: number; good: string; }
/** A chat model a program on this computer already has (size 0 = the program does not say). */
export interface LocalModel { model: string; size_gb: number; params: string; quant: string; fits: boolean; }
/** A program for local models (Ollama, LM Studio, Jan, llama.cpp, vLLM): found on its usual port or not. */
export interface Runtime { name: string; label: string; url: string; site: string; found: boolean; configured: boolean;
  models: LocalModel[]; embed: string[]; }
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
export interface Download { module?: string; id: string; what: string; source?: string;
  state: 'in_coda' | 'in_corso' | 'in_pausa' | 'fatto' | 'errore'; size: number; done: number;
  speed?: number; eta_s?: number | null; error?: string; }
export interface Outcome { ok: boolean; detail?: string; }
/** «Prova»: the model tried ('' = pick another) and the chat models the service really has. */
export interface TestOutcome extends Outcome { model?: string; models?: string[]; }
export interface BrainChoice { local_provider: string; cloud_models: Record<string, string>; embedding: { provider: string; model: string } | null; }
export interface TunnelState { on: boolean; url: string; detail?: string; }

@Injectable({ providedIn: 'root' })
export class SetupApi {
  private http = inject(HttpClient);
  private base = '/api/webui/setup';

  private get<T>(path: string) { return firstValueFrom(this.http.get<T>(`${this.base}/${path}`)); }
  private post<T>(path: string, body: object = {}) { return firstValueFrom(this.http.post<T>(`${this.base}/${path}`, body)); }

  state() { return this.get<SetupState>('state'); }
  later(step: string) { return this.post<SetupState>('later', { step }); }
  complete() { return this.post<SetupState>('complete'); }
  catalog() { return this.get<BrainCatalog>('brain/catalog'); }
  test(provider: string, key = '', model = '') { return this.post<TestOutcome>('brain/test', { provider, key, model }); }
  apply(recipe: string, local_model: string, cloud: string[], claude_token: string, choice: BrainChoice) {
    return this.post<Outcome>('brain/apply', { recipe, local_model, cloud, claude_token, local_provider: choice.local_provider,
      cloud_models: choice.cloud_models, embedding: choice.embedding || {} });
  }
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
