/** Fixed texts in the owner's language (dossier docs/work/2026-11-14-backend-inglese).
 *
 * Write the text in English and wrap it: `tr('Save')`, `tr('{0} items', n)` (standard: docs/LANGUAGES.md). The WebUI
 * loads the catalog (`/api/webui/i18n`, «Lingua» = `themis.personal.language`) before any plugin and shares it on
 * `globalThis.__hestiaI18n`; a missing text shows the English source. `f::Active` = a context tag, never shown. */
function catalog(): { language: string; messages: Record<string, string> } {
  const c = (globalThis as any).__hestiaI18n;
  return c && typeof c.messages === 'object' ? c : { language: 'it', messages: {} };
}

export function language(): string { return catalog().language || 'it'; }

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

export function tr(text: string, ...args: unknown[]): string {
  const source = text == null ? '' : String(text);
  const c = catalog();
  const plain = source.replace(/^[a-z][a-z0-9.]*::/, '');
  const out = (c.language !== 'en' && c.messages[source]) || plain;
  if (!args.length) return out;
  return format(out, args) ?? format(plain, args) ?? plain;
}
