/** Fixed texts in the owner's language (dossier docs/work/2026-11-14-backend-inglese).
 *
 * Write the text in English and wrap it: `tr('Save')`, `tr('{0} items', n)` (standard: docs/LANGUAGES.md). The WebUI
 * loads the catalog (`/api/webui/i18n`, «Lingua» = `themis.personal.language`) before any plugin and shares it on
 * `globalThis.__hestiaI18n`; a missing text shows the English source. `f::Active` = a context tag, never shown. */
function catalog(): { language: string; messages: Record<string, string>; assistant?: string; gender?: string } {
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

export function language(): string { return catalog().language || 'it'; }

/** The date/number locale of the owner's language (`toLocaleDateString(locale(), …)`), never a hardcoded 'it-IT'. */
export function locale(): string { return language() === 'en' ? 'en-GB' : 'it-IT'; }

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

export function tr(text: string, ...args: unknown[]): string {
  const source = text == null ? '' : String(text);
  const c = catalog();
  const plain = source.replace(/^[a-z][a-z0-9.]*::/, '');
  const out = named((c.language !== 'en' && c.messages[source]) || plain);
  if (!args.length) return out;
  return format(out, args) ?? format(named(plain), args) ?? named(plain);
}
