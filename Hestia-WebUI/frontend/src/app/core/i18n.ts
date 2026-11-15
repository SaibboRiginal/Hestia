import { Pipe, PipeTransform } from '@angular/core';

/** Fixed texts in the owner's language (dossier docs/work/2026-11-14-backend-inglese).
 *
 * The Italian text in the code is the key: `tr('Salva')`, `tr('Oggi — {0}', day)`, in templates `{{ 'Salva' | tr }}`.
 * index.html loads `/api/webui/i18n.js` (Themis catalog for «Lingua» = `themis.personal.language`) before any
 * bundle, so even module-level constants are translated; plugins read the same `globalThis.__hestiaI18n` through
 * `tr` of `@hestia/webui-sdk`. A missing text shows the Italian source. A new «Lingua» reloads the page (`followLanguage`). */
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

function format(text: string, args: unknown[]): string | null {
  let ok = true;
  const out = text.replace(/\{(\d+)\}/g, (m, i) => (Number(i) < args.length ? String(args[Number(i)] ?? '') : (ok = false, m)));
  return ok ? out : null;
}

/** `text` (Italian source) in the owner's language; `{0}`, `{1}` … take `args`. Never throws. */
export function tr(text: string, ...args: unknown[]): string {
  const source = text == null ? '' : String(text);
  const c = catalog();
  const out = (c.language !== 'it' && c.messages[source]) || source;
  if (!args.length) return out;
  return format(out, args) ?? format(source, args) ?? source;
}

@Pipe({ name: 'tr', standalone: true })
export class TrPipe implements PipeTransform {
  transform(text: string, ...args: unknown[]): string { return tr(text, ...args); }
}
