import { Pipe, PipeTransform } from '@angular/core';

/** Fixed texts in the owner's language (dossier docs/work/2026-11-14-backend-inglese).
 *
 * The English text in the code is the key (standard: docs/LANGUAGES.md): `tr('Save')`, `tr('Today — {0}', day)`, in
 * templates `{{ 'Save' | tr }}`; `f::Active` = a context tag, never shown.
 * index.html loads `/api/webui/i18n.js` (Themis catalog for «Lingua» = `themis.personal.language`) before any
 * bundle, so even module-level constants are translated; plugins read the same `globalThis.__hestiaI18n` through
 * `tr` of `@hestia/webui-sdk`. A missing text shows the English source; `localize` translates the labels of API payloads (HTTP interceptor). A new «Lingua» reloads the page (`followLanguage`). */
interface Catalog { language: string; messages: Record<string, string>; }

function catalog(): Catalog {
  const c = (globalThis as any).__hestiaI18n;
  return c && typeof c.messages === 'object' ? c : { language: 'it', messages: {} };
}

/** Fallback when the script did not run (e.g. the page was served from the cache): fetch the JSON once. */
export async function loadI18n(): Promise<void> {
  if ((globalThis as any).__hestiaI18n) return;
  try {
    const r = await fetch('/api/webui/i18n', { credentials: 'same-origin' });
    if (r.ok) {
      const d = await r.json();
      (globalThis as any).__hestiaI18n = { language: String(d?.language || 'it'), messages: d?.messages || {} };
    }
  } catch { /* settings unreachable: Italian source texts */ }
}

export function currentLanguage(): string { return catalog().language || 'it'; }

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

/** Keys whose string value a person reads (same list as `hestia_common.i18n.LABEL_KEYS`). */
const LABEL_KEYS = new Set(['title', 'label', 'subtitle', 'summary', 'description', 'help', 'group', 'hint',
  'placeholder', 'unit', 'section', 'caption', 'empty', 'tooltip', 'action_label', 'button', 'heading', 'badge', 'note']);

/** A copy of an API payload whose people texts (values of LABEL_KEYS that are catalog keys) are in the owner's
 * language: module manifests, pages, widgets, cards. Ids, statuses and user data stay as they are. */
export function localize<T>(payload: T): T {
  const c = catalog();
  if (c.language === 'en' || !payload || typeof payload !== 'object') return payload;
  const walk = (node: any, key: string): any => {
    if (Array.isArray(node)) return node.map(v => walk(v, key));
    if (node && typeof node === 'object') {
      const out: any = {};
      for (const [k, v] of Object.entries(node)) out[k] = walk(v, k);
      return out;
    }
    return typeof node === 'string' && LABEL_KEYS.has(key) && c.messages[node] ? c.messages[node] : node;
  };
  return walk(payload, '');
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
  const out = (c.language !== 'en' && c.messages[source]) || plain;
  if (!args.length) return out;
  return format(out, args) ?? format(plain, args) ?? plain;
}

@Pipe({ name: 'tr', standalone: true })
export class TrPipe implements PipeTransform {
  transform(text: string, ...args: unknown[]): string { return tr(text, ...args); }
}
