import { Pipe, PipeTransform } from '@angular/core';

/** Fixed texts in the owner's language (dossier docs/work/2026-11-14-backend-inglese).
 *
 * The English text in the code is the key (standard: docs/LANGUAGES.md): `tr('Save')`, `tr('Today — {0}', day)`, in
 * templates `{{ 'Save' | tr }}`; `f::Active` = a context tag, never shown.
 * index.html loads `/api/webui/i18n.js` (Themis catalog for «Lingua» = `themis.personal.language`) before any
 * bundle, so even module-level constants are translated; plugins read the same `globalThis.__hestiaI18n` through
 * `tr` of `@hestia/webui-sdk`. A missing text shows the English source; `localize` translates the labels of API payloads (HTTP interceptor). A new «Lingua» reloads the page (`followLanguage`). */
interface Catalog { language: string; messages: Record<string, string>; assistant?: string; gender?: string; }

function catalog(): Catalog {
  const c = (globalThis as any).__hestiaI18n;
  return c && typeof c.messages === 'object' ? c : { language: 'en', messages: {} };
}

/** The assistant's chosen name (`themis.personal.assistant_name`, served with the catalog; default «Hestia»). */
export function assistantName(): string { return String(catalog().assistant || '').trim() || 'Hestia'; }

/** `{assistant}` → the chosen name, `{g:lei-form|lui-form}` → the form for her or him
 * (docs/work/2026-11-16-nome-ovunque). Where «Hestia» is the app (version, files, installation) the text says
 * «Hestia» and nothing changes. Also for texts that do not go through `tr` (plugin page titles and help). */
export function named(text: string): string {
  const s = text == null ? '' : String(text);
  if (!s.includes('{assistant}') && !s.includes('{g:')) return s;
  const he = catalog().gender === 'he';
  return s.replace(/\{g:([^{}|]*)\|([^{}|]*)\}/g, (_m, a, b) => (he ? b : a)).split('{assistant}').join(assistantName());
}

/** Fallback when the script did not run (e.g. the page was served from the cache): fetch the JSON once. */
export async function loadI18n(): Promise<void> {
  if ((globalThis as any).__hestiaI18n) return;
  try {
    const r = await fetch('/api/webui/i18n', { credentials: 'same-origin' });
    if (r.ok) {
      const d = await r.json();
      (globalThis as any).__hestiaI18n = { language: String(d?.language || 'it'), messages: d?.messages || {},
        assistant: d?.assistant, gender: d?.gender };
    }
  } catch { /* settings unreachable: the English source texts */ }
}

export function currentLanguage(): string { return catalog().language || 'it'; }

/** The date/number locale of the owner's language (`toLocaleDateString(locale(), …)`), never a hardcoded 'it-IT'. */
export function locale(): string { return currentLanguage() === 'en' ? 'en-GB' : 'it-IT'; }

/** The key of «Lingua»: saving it reloads the page so shell and plugins come back in the new language. */
export const LANGUAGE_KEY = 'themis.personal.language';
let reloading = false;
/** After «Lingua» was saved: a value other than the loaded one reloads the page once (short delay: saves sent
 * together with it finish first). */
export function followLanguage(value: unknown): void {
  const lang = String(value ?? '').trim();
  if (!lang || lang === currentLanguage() || reloading) return;
  reloading = true;
  setTimeout(() => location.reload(), 400);
}

/** After the assistant's name or she/he was saved: update the texts at once (the page reloads, like «Lingua»;
 * not during the guided setup, which reads the name live and must not lose its steps). */
export const IDENTITY_KEYS = ['themis.personal.assistant_name', 'themis.personal.assistant_gender'];
export function followIdentity(key: string, value: unknown): void {
  const c = (globalThis as any).__hestiaI18n;
  if (!IDENTITY_KEYS.includes(key) || !c || reloading) return;
  const v = String(value ?? '').trim();
  const now = key === IDENTITY_KEYS[0] ? assistantName() : (c.gender || 'she');
  if ((v || (key === IDENTITY_KEYS[0] ? 'Hestia' : 'she')) === now) return;
  if (key === IDENTITY_KEYS[0]) c.assistant = v || 'Hestia'; else c.gender = v === 'he' ? 'he' : 'she';
  if (location.pathname.startsWith('/setup')) return;
  reloading = true;
  setTimeout(() => location.reload(), 400);
}

/** Keys whose string value is never a people text (same list as `hestia_common.i18n.KEEP_KEYS`). */
const KEEP_KEYS = new Set(['id', 'key', 'value', 'status', 'state', 'type', 'kind', 'slug', 'path', 'url', 'href',
  'code', 'icon', 'color', 'tone', 'module', 'service', 'method', 'tool', 'command', 'domain', 'source', 'role', 'lang',
  'language', 'page', 'link', 'view', 'tab', 'event', 'event_type', 'use_case', 'provider', 'model', 'format', 'mime',
  'unit_code', 'action', 'name_id', 'entity_id', 'dedupe_key', 'replaces', 'query', 'q', 'args', 'params']);
const TAG = /^[a-z][a-z0-9.]*::/;

/** A copy of an API payload whose people texts are in the owner's language: every string value that is a catalog
 * key (an English source text) is translated, except under KEEP_KEYS. Module labels (manifests, pages, widgets,
 * cards, choices) are written in English and translated here. */
export function localize<T>(payload: T): T {
  const c = catalog();
  if (!payload || typeof payload !== 'object') return payload;
  const messages = c.language === 'en' ? {} as Record<string, string> : c.messages;
  const text = (s: string): string => named(messages[s] || (TAG.test(s) ? s.replace(TAG, '') : s));
  const walk = (node: any): any => {
    if (Array.isArray(node)) return node.map(walk);
    if (node && typeof node === 'object') {
      const out: any = {};
      for (const [k, v] of Object.entries(node)) out[k] = KEEP_KEYS.has(k) ? v : walk(v);
      return out;
    }
    return typeof node === 'string' ? text(node) : node;
  };
  return walk(payload);
}

function format(text: string, args: unknown[]): string | null {
  let ok = true;
  const out = text.replace(/\{(\d+)\}/g, (m, i) => (Number(i) < args.length ? String(args[Number(i)] ?? '') : (ok = false, m)));
  return ok ? out : null;
}

/** `text` (English source) in the owner's language; `{0}`, `{1}` … take `args`. Never throws. */
export function tr(text: string, ...args: unknown[]): string {
  const source = text == null ? '' : String(text);
  const c = catalog();
  const plain = source.replace(/^[a-z][a-z0-9.]*::/, '');
  const out = named((c.language !== 'en' && c.messages[source]) || plain);
  if (!args.length) return out;
  return format(out, args) ?? format(named(plain), args) ?? named(plain);
}

@Pipe({ name: 'tr', standalone: true })
export class TrPipe implements PipeTransform {
  transform(text: string, ...args: unknown[]): string { return tr(text, ...args); }
}
