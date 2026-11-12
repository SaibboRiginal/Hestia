import { Injectable, inject, signal } from '@angular/core';
import { CentralSettingsApi } from '../features/settings/central-settings.api';

/** Who the assistant is and whose it is: four personal settings (Themis `themis.personal.*`, dossier
 * docs/work/2026-11-12-identita-e-proattivita). The pages that talk to the owner show the chosen name; the product
 * stays «Hestia». Settings unreachable → the defaults, nothing breaks. */
export interface Identity { assistant: string; gender: 'lei' | 'lui'; ownerName: string; ownerCall: string; }

const KEYS = {
  assistant: 'themis.personal.assistant_name', gender: 'themis.personal.assistant_gender',
  ownerName: 'themis.personal.owner_name', ownerCall: 'themis.personal.owner_call',
} as const;
export const DEFAULT_ASSISTANT = 'Hestia';

@Injectable({ providedIn: 'root' })
export class IdentityService {
  private api = inject(CentralSettingsApi);
  private asked = false;

  readonly assistant = signal(DEFAULT_ASSISTANT);
  readonly gender = signal<'lei' | 'lui'>('lei');
  readonly ownerName = signal('');
  readonly ownerCall = signal('');

  /** Read once (pages call it freely); `force` after a change made elsewhere. */
  async load(force = false): Promise<void> {
    if (this.asked && !force) return;
    this.asked = true;
    try {
      const page = await this.api.items('themis');
      const value = (key: string) => String(page.items.find(i => i.key === key)?.value ?? '').trim();
      this.assistant.set(value(KEYS.assistant) || DEFAULT_ASSISTANT);
      this.gender.set(value(KEYS.gender) === 'lui' ? 'lui' : 'lei');
      this.ownerName.set(value(KEYS.ownerName));
      this.ownerCall.set(value(KEYS.ownerCall));
    } catch { this.asked = false; /* defaults stay; the next page tries again */ }
  }

  /** Save what changed (each is one Themis setting, live for every module). */
  async save(next: Identity): Promise<void> {
    const assistant = next.assistant.trim() || DEFAULT_ASSISTANT;
    const jobs: Promise<unknown>[] = [];
    if (assistant !== this.assistant()) jobs.push(this.api.set(KEYS.assistant, assistant));
    if (next.gender !== this.gender()) jobs.push(this.api.set(KEYS.gender, next.gender));
    if (next.ownerName.trim() !== this.ownerName()) jobs.push(this.api.set(KEYS.ownerName, next.ownerName.trim()));
    if (next.ownerCall.trim() !== this.ownerCall()) jobs.push(this.api.set(KEYS.ownerCall, next.ownerCall.trim()));
    await Promise.all(jobs);
    this.assistant.set(assistant);
    this.gender.set(next.gender);
    this.ownerName.set(next.ownerName.trim());
    this.ownerCall.set(next.ownerCall.trim());
  }
}
