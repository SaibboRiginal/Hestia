import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/** Guided setup «Benvenuto» (docs/work/2026-10-30-setup-un-click §4.2): browser → WebUI → Hub → Hephaestus. */
export interface SetupState {
  completed: boolean;
  later: string[];
  brain: { recipe?: string; local_model?: string; cloud?: string[]; summary?: string };
  hardware: { os?: string; ram_gb?: number; gpu?: string; vram_gb?: number; free_gb?: number };
  telegram: { token: boolean; owner: boolean; linked: boolean; code_active: boolean };
  backup: { passphrase: boolean };
  claude: { token: boolean };
}
export interface CatalogModel { model: string; size_gb: number; good: string; }
export interface CloudProvider { name: string; label: string; type: string; key_set: boolean; available: boolean; }
export interface BrainCatalog {
  recommended: { tier: string; label: string; chat: CatalogModel[]; model: string; embedding: CatalogModel; recipe: string };
  installed: string[];
  ollama: boolean;
  cloud: CloudProvider[];
}
export interface Download { id: string; what: string; state: 'in_coda' | 'in_corso' | 'fatto' | 'errore'; size: number; done: number; error?: string; }
export interface Outcome { ok: boolean; detail?: string; }
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
  test(provider: string, key = '', model = '') { return this.post<Outcome>('brain/test', { provider, key, model }); }
  apply(recipe: string, local_model: string, cloud: string[], claude_token = '') {
    return this.post<Outcome>('brain/apply', { recipe, local_model, cloud, claude_token });
  }
  /** Echo's local voice models (through the WebUI voice door, not Hephaestus). */
  prefetchVoice() { return firstValueFrom(this.http.post<{ queued: string[] }>('/api/webui/voice/models/prefetch', {})); }
  pulls() { return this.get<{ downloads: Download[] }>('brain/pulls').then(r => r.downloads || []); }
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
