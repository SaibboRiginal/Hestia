import { Injectable, inject, signal } from '@angular/core';
import { CentralSettingsApi } from '../features/settings/central-settings.api';
import { assistantName } from '../core/i18n';

/** Who the assistant is and whose it is, and the owner's language: five personal settings (Themis `themis.personal.*`, dossier
 * docs/work/2026-11-12-identity-and-proactivity). The pages and the site itself show the chosen name
 * (docs/work/2026-11-17-client-names). Settings unreachable → the defaults, nothing breaks. */
export interface Identity { assistant: string; gender: 'she' | 'he'; ownerName: string; ownerCall: string; language: string; }

/** The languages of `themis.personal.language` (notifications, recaps, messages she writes on her own). */
export const LANGUAGES: { value: string; label: string }[] = [
  { value: 'it', label: 'Italiano' }, { value: 'en', label: 'English' },
];
const DEFAULT_LANGUAGE = 'it';

const KEYS = {
  assistant: 'themis.personal.assistant_name', gender: 'themis.personal.assistant_gender',
  ownerName: 'themis.personal.owner_name', ownerCall: 'themis.personal.owner_call',
  language: 'themis.personal.language',
} as const;
export const DEFAULT_ASSISTANT = 'Hestia';

@Injectable({ providedIn: 'root' })
export class IdentityService {
  private api = inject(CentralSettingsApi);
  private asked = false;

  readonly assistant = signal(assistantName());   // the catalog already knows it before the settings answer
  readonly gender = signal<'she' | 'he'>('she');
  readonly ownerName = signal('');
  readonly ownerCall = signal('');
  readonly language = signal(DEFAULT_LANGUAGE);

  /** Read once (pages call it freely); `force` after a change made elsewhere. */
  async load(force = false): Promise<void> {
    if (this.asked && !force) return;
    this.asked = true;
    try {
      const page = await this.api.items('themis');
      const value = (key: string) => String(page.items.find(i => i.key === key)?.value ?? '').trim();
      this.assistant.set(value(KEYS.assistant) || DEFAULT_ASSISTANT);
      this.gender.set(value(KEYS.gender) === 'he' ? 'he' : 'she');
      this.ownerName.set(value(KEYS.ownerName));
      this.ownerCall.set(value(KEYS.ownerCall));
      const lang = value(KEYS.language);
      this.language.set(LANGUAGES.some(l => l.value === lang) ? lang : DEFAULT_LANGUAGE);
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
    if (next.language !== this.language()) jobs.push(this.api.set(KEYS.language, next.language));
    await Promise.all(jobs);
    this.assistant.set(assistant);
    this.gender.set(next.gender);
    this.ownerName.set(next.ownerName.trim());
    this.ownerCall.set(next.ownerCall.trim());
    this.language.set(next.language);
  }
}
