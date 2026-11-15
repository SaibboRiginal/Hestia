/** Fixed texts in the owner's language (dossier docs/work/2026-11-14-backend-inglese).
 *
 * Write the Italian text and wrap it: `tr('Salva')`, `tr('{0} capi', n)`. The WebUI loads the catalog
 * (`/api/webui/i18n`, «Lingua» = `themis.personal.language`) before any plugin and shares it on
 * `globalThis.__hestiaI18n`; a missing text shows the Italian source. */
function catalog(): { language: string; messages: Record<string, string> } {
  const c = (globalThis as any).__hestiaI18n;
  return c && typeof c.messages === 'object' ? c : { language: 'it', messages: {} };
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
  const out = (c.language !== 'it' && c.messages[source]) || source;
  if (!args.length) return out;
  return format(out, args) ?? format(source, args) ?? source;
}
