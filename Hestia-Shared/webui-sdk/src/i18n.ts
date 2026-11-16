/** Fixed texts in the owner's language (dossier docs/work/2026-11-14-backend-inglese).
 *
 * Write the Italian text and wrap it: `tr('Salva')`, `tr('{0} capi', n)`. The WebUI loads the catalog
 * (`/api/webui/i18n`, «Lingua» = `themis.personal.language`) before any plugin and shares it on
 * `globalThis.__hestiaI18n`; a missing text shows the Italian source. */
function catalog(): { language: string; messages: Record<string, string>; assistant?: string; gender?: string } {
  const c = (globalThis as any).__hestiaI18n;
  return c && typeof c.messages === 'object' ? c : { language: 'it', messages: {} };
}

/** The assistant's chosen name (default «Hestia»). */
export function assistantName(): string { return String(catalog().assistant || '').trim() || 'Hestia'; }

/** `{assistant}` → the chosen name, `{g:lei-form|lui-form}` → her or him (docs/work/2026-11-16-nome-ovunque).
 * Write «Hestia» only where it is the app (version, files, installation, the whole system). */
export function named(text: string): string {
  const s = text == null ? '' : String(text);
  if (!s.includes('{assistant}') && !s.includes('{g:')) return s;
  const he = catalog().gender === 'lui';
  return s.replace(/\{g:([^{}|]*)\|([^{}|]*)\}/g, (_m, a, b) => (he ? b : a)).split('{assistant}').join(assistantName());
}

export function language(): string { return catalog().language || 'it'; }

function format(text: string, args: unknown[]): string | null {
  let ok = true;
  const out = text.replace(/\{(\d+)\}/g, (m, i) => (Number(i) < args.length ? String(args[Number(i)] ?? '') : (ok = false, m)));
  return ok ? out : null;
}

export function tr(text: string, ...args: unknown[]): string {
  const source = text == null ? '' : String(text);
  const c = catalog();
  const out = named((c.language !== 'it' && c.messages[source]) || source);
  if (!args.length) return out;
  return format(out, args) ?? format(named(source), args) ?? named(source);
}
