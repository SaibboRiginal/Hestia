/**
 * <hermes-inbox> — «Notifiche»: the Hermes inbox, shared by every client (read here = read on Telegram).
 * Filters (da leggere / da rispondere / tutte, modulo, altri client), answers with the notification's buttons
 * (first answer wins), seen / all seen, «Apri» on a module page (`_link`), load more.
 * Ported from the WebUI built-in page (SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A4).
 * Live toasts and the toast preference stay in the WebUI shell (it is the client); this page polls the
 * counters while visible and reloads when they move.
 */
import { HestiaElement, html, css, nothing, svg } from '@hestia/webui-sdk';
import { API, hermesStyles } from './util';

type Filter = 'unread' | 'pending' | 'all';
type ToastMode = 'all' | 'important' | 'none';
interface Counts { unread: number; pending: number; }

const PAGE = 40;
const POLL_MS = 20000;
const SEEN_DELAY_MS = 1500;
/** Same key the WebUI shell reads for its live toasts (same origin: the plugin runs in the WebUI page). */
const PREFS_KEY = 'hestia_notification_prefs';
const PREFS_EVENT = 'hestia:notification-prefs';

const SOURCE_LABELS: Record<string, string> = {
  themis: 'Impostazioni', hephaestus: 'Sviluppo', chronos: 'Agenda', argus: 'Diagnosi', athena: 'Athena',
  scout: 'Scout', hecate: 'Account', system: 'Sistema', service: 'Sistema', real_estate: 'Scout', settings: 'Impostazioni',
};
const CLIENT_LABELS: Record<string, string> = { telegram: 'Telegram', webui: 'WebUI' };
const clientLabel = (name?: string | null) => (name && CLIENT_LABELS[name]) || name || '';
const sourceLabel = (s: string) => SOURCE_LABELS[s] || (s ? s.charAt(0).toUpperCase() + s.slice(1) : 'Hestia');
const TOAST_OPTIONS: Array<{ id: ToastMode; label: string }> = [
  { id: 'all', label: 'Avvisi a comparsa per tutte' },
  { id: 'important', label: 'Solo importanti e da rispondere' },
  { id: 'none', label: 'Nessun avviso a comparsa' },
];

const ICON_PATHS: Record<string, string> = {
  bell: 'M6 8a6 6 0 1112 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 003.4 0',
  alert: 'M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z',
  check: 'M5 12l5 5L20 7',
  clock: 'M12 7v5l3 2M12 21a9 9 0 110-18 9 9 0 010 18z',
};
const LEVEL_ICON: Record<string, string> = { info: 'bell', success: 'check', warning: 'alert', error: 'alert', critical: 'alert' };
const icon = (name: string, size = 16) => html`<svg width=${size} height=${size} viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${svg`<path d=${ICON_PATHS[name] || ICON_PATHS.bell}></path>`}</svg>`;

const time = (iso?: string) => (iso ? new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit', hour12: false }) : '');

function dayLabel(iso: string): string {
  const d = new Date(iso);
  const today = new Date();
  const yesterday = new Date(); yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return 'Oggi';
  if (d.toDateString() === yesterday.toDateString()) return 'Ieri';
  return d.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long' });
}

/** Hermes messages are Telegram-style HTML: keep the few formatting tags, drop everything else (no scripts,
 *  no handlers, links only http(s)). DOMParser runs nothing; the result is plain DOM nodes Lit can render. */
const ALLOWED = new Set(['B', 'STRONG', 'I', 'EM', 'U', 'INS', 'S', 'DEL', 'STRIKE', 'CODE', 'PRE', 'A', 'BR', 'BLOCKQUOTE', 'SPAN', 'P']);
export function richText(htmlText: string): DocumentFragment {
  const out = document.createDocumentFragment();
  const doc = new DOMParser().parseFromString(`<body>${htmlText || ''}</body>`, 'text/html');
  const copy = (from: Node, to: Node) => {
    for (const child of Array.from(from.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE) { to.appendChild(document.createTextNode(child.textContent || '')); continue; }
      if (child.nodeType !== Node.ELEMENT_NODE) continue;
      const el = child as Element;
      if (['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'TEMPLATE'].includes(el.tagName)) continue;
      if (!ALLOWED.has(el.tagName)) { copy(el, to); continue; }
      const clean = document.createElement(el.tagName.toLowerCase());
      if (el.tagName === 'A') {
        const href = el.getAttribute('href') || '';
        if (/^https?:\/\//i.test(href)) { clean.setAttribute('href', href); clean.setAttribute('target', '_blank'); clean.setAttribute('rel', 'noopener noreferrer'); }
      }
      copy(el, clean);
      to.appendChild(clean);
    }
  };
  copy(doc.body, out);
  return out;
}

function readToastMode(): ToastMode {
  try { return (JSON.parse(localStorage.getItem(PREFS_KEY) || '{}').toast as ToastMode) || 'all'; } catch { return 'all'; }
}

export class HermesInbox extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, counts: { state: true }, filter: { state: true },
                        source: { state: true }, others: { state: true }, error: { state: true }, loading: { state: true },
                        hasMore: { state: true }, busy: { state: true }, toastMode: { state: true } };
  declare items: any[] | null; declare counts: Counts; declare filter: Filter; declare source: string;
  declare others: boolean; declare error: string; declare loading: boolean; declare hasMore: boolean;
  declare busy: string; declare toastMode: ToastMode;

  static styles = [...HestiaElement.styles, hermesStyles, css`
    .page { max-width: 860px; }
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .head .sub { color: var(--text-3); font-size: 13px; }
    .bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); cursor: pointer; }
    .chip[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .chip:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .tog { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-2); cursor: pointer; }
    .tog input { accent-color: var(--accent); }
    .day { font: 500 12px var(--font-sans); color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 10px 0 0; }
    .list { display: flex; flex-direction: column; gap: 8px; }
    .ntf { display: flex; gap: 12px; padding: 12px 14px; border: 1px solid var(--border); border-radius: var(--radius-lg);
      background: var(--surface); }
    .ntf.unread { border-color: var(--border-strong); box-shadow: var(--shadow-1); }
    .ico { width: 30px; height: 30px; border-radius: 50%; display: grid; place-items: center; flex-shrink: 0;
      background: var(--surface-2); color: var(--text-3); }
    .ntf[data-level=warning] .ico { background: var(--warning-soft); color: var(--warning); }
    .ntf[data-level=error] .ico, .ntf[data-level=critical] .ico { background: var(--danger-soft); color: var(--danger); }
    .ntf[data-level=success] .ico { background: var(--success-soft); color: var(--success); }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
    .meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; font-size: 12px; color: var(--text-3); }
    .meta .src { font-weight: 600; color: var(--text-2); }
    .meta .time { margin-left: auto; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); }
    .title { font-weight: 600; font-size: 14px; overflow-wrap: anywhere; }
    .msg { font-size: 14px; color: var(--text); white-space: pre-line; overflow-wrap: anywhere; }
    .msg pre { white-space: pre-wrap; background: var(--surface-2); padding: 6px 8px; border-radius: var(--radius-sm); margin: 4px 0; }
    .msg code { font-size: 12.5px; background: var(--surface-2); padding: 0 4px; border-radius: 4px; }
    .msg blockquote { margin: 4px 0; padding-left: 10px; border-left: 3px solid var(--border-strong); color: var(--text-2); }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
    .outcome { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--success); margin-top: 4px; }
    .outcome[data-status=expired], .outcome[data-status=error] { color: var(--text-3); }
    .seen { font-size: 12px; color: var(--text-3); }
    .center { display: flex; justify-content: center; padding: 12px; }
  `];

  private seenTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  constructor() {
    super();
    this.items = null; this.counts = { unread: 0, pending: 0 }; this.filter = 'unread'; this.source = '';
    this.others = false; this.error = ''; this.loading = false; this.hasMore = false; this.busy = '';
    this.toastMode = readToastMode();
  }

  connectedCallback() {
    super.connectedCallback();
    const q = this.ctx?.query || {};
    if (q.filter === 'unread' || q.filter === 'pending' || q.filter === 'all') this.filter = q.filter;
    if (q.source) this.source = q.source;
    this.reload();
    this.onHost('refresh', () => this.reload());
    this.onHost('visible', () => this.reload());
    this.onHost('online', () => this.reload());
    this.addEventListener('retry', () => this.reload());
    this.pollTimer = setInterval(() => this.poll(), POLL_MS);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this.seenTimer) clearTimeout(this.seenTimer);
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.seenTimer = this.pollTimer = null;
  }

  // ── API ──────────────────────────────────────────────────────────────────

  private async load(more = false) {
    this.loading = true;
    const query: Record<string, any> = { filter: this.filter, limit: PAGE };
    if (this.source) query.source = this.source;
    const last = this.items?.at(-1);
    if (more && last) query.before = last.created_at;
    const r = await this.host.api('GET', `${API}/inbox`, { query });
    this.loading = false;
    if (!r.ok) {
      if (more || this.items) { this.host.toast('Notifiche non disponibili: Hermes non risponde', 'danger'); if (more) return; }
      this.error = 'Hermes non raggiungibile';
      return;
    }
    this.error = '';
    const items = r.data?.items ?? [];
    this.items = more ? [...(this.items || []), ...items] : items;
    this.hasMore = items.length >= PAGE;
    if (r.data?.counts) this.counts = r.data.counts;
  }

  private async loadCounts(): Promise<Counts | null> {
    const r = await this.host.api<Counts>('GET', `${API}/inbox/counts`);
    if (!r.ok || !r.data) return null;
    this.counts = r.data;
    return r.data;
  }

  /** Shown on the page in a visible tab = seen (on every client). */
  private async reload() {
    await this.load(false);
    if (this.seenTimer) clearTimeout(this.seenTimer);
    this.seenTimer = setTimeout(() => {
      if (document.visibilityState !== 'visible' || !this.isConnected) return;
      for (const n of this.visible()) if (!n.read) void this.markSeen(n);
    }, SEEN_DELAY_MS);
  }

  /** While the page is open: the counters moved (new notification, answered elsewhere) → reload in place. */
  private async poll() {
    if (document.visibilityState !== 'visible' || this.loading || this.busy) return;
    const before = this.counts;
    const now = await this.loadCounts();
    if (now && (now.unread !== before.unread || now.pending !== before.pending)) void this.reload();
  }

  private patch(id: string, changes: Record<string, unknown>) {
    this.items = (this.items || []).map(n => (n.id === id ? { ...n, ...changes } : n));
  }

  private async markSeen(n: any) {
    if (n.read) return;
    this.patch(n.id, { read: true, state: 'seen', seen: { by: 'webui', at: new Date().toISOString() } });
    this.counts = { ...this.counts, unread: Math.max(0, this.counts.unread - 1) };
    await this.host.api('POST', `${API}/inbox/${encodeURIComponent(n.id)}/seen`, { body: {} }); // failed: retried on next view
  }

  private async markAllSeen() {
    const r = await this.host.api('POST', `${API}/inbox/seen-all`, { body: {} });
    if (!r.ok) { this.host.toast('Non riuscito, riprova', 'danger'); return; }
    this.items = (this.items || []).map(n => (n.read ? n : { ...n, read: true, state: 'seen' }));
    await this.loadCounts();
    if (this.filter === 'unread') await this.reload();
  }

  private applyAnswer(id: string, answer: any, state = 'answered') {
    this.patch(id, { answer, state, pending: false, read: true });
    if (this.filter === 'pending') this.items = (this.items || []).filter(n => n.id !== id);
  }

  private async answer(n: any, a: any) {
    this.busy = n.id;
    const r = await this.host.api('POST', `${API}/inbox/${encodeURIComponent(n.id)}/answer`, { body: { action_id: a.id } });
    this.busy = '';
    if (r.ok) {
      this.applyAnswer(n.id, r.data?.answer ?? { label: a.label, by: 'webui', status: 'done' });
      this.host.toast(r.data?.answer?.outcome_text || `${a.label} ✓`, 'success');
    } else if (r.status === 409) {
      const answer = r.data?.answer ?? {};
      this.applyAnswer(n.id, answer);
      this.host.toast(answer.by && answer.by !== 'webui' ? `Già gestita da ${clientLabel(answer.by)}` : 'Già gestita', 'info');
    } else {
      this.host.toast(`Non riuscito: ${r.data?.detail || (r.error && r.error !== 'offline' ? r.error : '') || 'riprova più tardi'}`, 'danger');
    }
    void this.loadCounts();
  }

  private open(n: any) {
    const link = n.link;
    if (!link?.page) return;
    if (!n.read) void this.markSeen(n);
    this.host.navigate(link.page, link.params || {}, link.module || undefined);
  }

  private setFilter(f: Filter) { this.filter = f; this.items = null; this.reload(); }
  private setSource(e: Event) { this.source = (e.target as HTMLSelectElement).value; this.items = null; this.reload(); }

  /** Toasts are drawn by the WebUI shell: the choice is stored where the shell reads it, and announced. */
  private setToast(e: Event) {
    const mode = (e.target as HTMLSelectElement).value as ToastMode;
    this.toastMode = mode;
    try { localStorage.setItem(PREFS_KEY, JSON.stringify({ toast: mode })); } catch { /* private mode */ }
    window.dispatchEvent(new CustomEvent(PREFS_EVENT, { detail: { toast: mode } }));
  }

  // ── View ─────────────────────────────────────────────────────────────────

  private visible(): any[] { return (this.items || []).filter(n => this.others || !n.other_client); }

  private sources(): string[] {
    const list = [...new Set((this.items || []).map(n => n.source).filter(Boolean))].sort() as string[];
    return this.source && !list.includes(this.source) ? [this.source, ...list] : list;
  }

  private subtitle(): string {
    const c = this.counts;
    if (!c.unread && !c.pending) return 'Tutto letto';
    return [c.unread ? `${c.unread} da leggere` : '', c.pending ? `${c.pending} da rispondere` : ''].filter(Boolean).join(' · ');
  }

  private outcome(n: any): string {
    const a = n.answer || {};
    if (n.state === 'expired' || a.status === 'expired') return 'Scaduta';
    const parts = [a.outcome_text || a.label || 'Gestita'];
    if (a.by && a.by !== 'webui' && CLIENT_LABELS[a.by]) parts.push(`da ${clientLabel(a.by)}`);
    if (a.at) parts.push(time(a.at));
    return parts.join(' · ');
  }

  private variant(style: string) { return style === 'primary' ? 'primary' : style === 'danger' ? 'danger' : 'default'; }

  private renderItem(n: any) {
    const busy = this.busy === n.id;
    return html`<article class="ntf ${n.read ? '' : 'unread'}" data-level=${n.level || 'info'}>
      <div class="ico">${icon(LEVEL_ICON[n.level] || 'bell')}</div>
      <div class="main">
        <div class="meta">
          <span class="src">${sourceLabel(n.source)}</span>
          ${n.repeat ? html`<hxk-badge tone="warning" title="Lo stesso promemoria, inviato di nuovo">↻ ${n.repeat.text}</hxk-badge>` : nothing}
          ${n.other_client && n.origin ? html`<hxk-badge tone="neutral">da ${clientLabel(n.origin.client)}</hxk-badge>` : nothing}
          <span class="time tnum">${time(n.created_at)}</span>
          ${!n.read ? html`<span class="dot" title="Da leggere"></span>` : nothing}
        </div>
        ${n.title ? html`<div class="title">${n.title}</div>` : nothing}
        <div class="msg">${richText(n.message)}</div>
        ${n.link?.page ? html`<div class="actions"><hxk-button size="sm" icon="chevron-right" @click=${() => this.open(n)}>Apri</hxk-button></div>` : nothing}
        ${n.pending && n.actions?.length ? html`<div class="actions">
            ${n.actions.map((a: any) => html`<hxk-button size="sm" variant=${this.variant(a.style)} ?loading=${busy} ?disabled=${busy}
              @click=${() => this.answer(n, a)}>${a.label}</hxk-button>`)}</div>`
          : n.answer && (n.state === 'answered' || n.state === 'expired') ? html`<div class="outcome" data-status=${n.answer.status || ''}>
            ${icon(n.state === 'expired' ? 'clock' : 'check', 14)}<span>${this.outcome(n)}</span></div>` : nothing}
        ${n.seen && n.seen.by !== 'webui' && n.state === 'seen' ? html`<div class="seen">Vista su ${clientLabel(n.seen.by)}</div>` : nothing}
      </div>
    </article>`;
  }

  private renderList() {
    if (this.items === null) return html`<hxk-state kind="loading"></hxk-state>`;
    const shown = this.visible();
    if (!shown.length) {
      const empty = { unread: 'Nessuna notifica da leggere', pending: 'Niente in attesa di risposta', all: 'Nessuna notifica' }[this.filter];
      return html`<hxk-state kind="empty" text=${empty}></hxk-state>`;
    }
    const groups: Array<{ label: string; items: any[] }> = [];
    for (const n of shown) {
      const label = dayLabel(n.created_at);
      const last = groups.at(-1);
      if (last && last.label === label) last.items.push(n); else groups.push({ label, items: [n] });
    }
    return html`${groups.map(g => html`<h3 class="day">${g.label}</h3><div class="list">${g.items.map(n => this.renderItem(n))}</div>`)}
      ${this.hasMore ? html`<div class="center"><hxk-button size="sm" ?loading=${this.loading} @click=${() => this.load(true)}>Carica altre</hxk-button></div>` : nothing}`;
  }

  render() {
    if (this.error && !this.items) {
      return html`<div class="page"><h1>Notifiche</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    }
    const c = this.counts;
    const filters: Array<{ id: Filter; label: string }> = [
      { id: 'unread', label: c.unread ? `Da leggere · ${c.unread}` : 'Da leggere' },
      { id: 'pending', label: c.pending ? `Da rispondere · ${c.pending}` : 'Da rispondere' },
      { id: 'all', label: 'Tutte' },
    ];
    return html`<div class="page">
      <div class="head">
        <div class="grow"><h1>Notifiche</h1><div class="sub">${this.subtitle()}</div></div>
        ${c.unread ? html`<hxk-button size="sm" variant="ghost" icon="check" @click=${() => this.markAllSeen()}>Segna tutte lette</hxk-button>` : nothing}
      </div>
      <div class="bar">
        <div class="chips" role="group" aria-label="Filtro">${filters.map(f => html`<button class="chip" aria-pressed=${this.filter === f.id}
          @click=${() => this.setFilter(f.id)}>${f.label}</button>`)}</div>
        <select aria-label="Modulo" @change=${(e: Event) => this.setSource(e)}>
          <option value="" ?selected=${!this.source}>Tutti i moduli</option>
          ${this.sources().map(s => html`<option value=${s} ?selected=${this.source === s}>${sourceLabel(s)}</option>`)}
        </select>
        <label class="tog"><input type="checkbox" .checked=${this.others}
          @change=${(e: Event) => (this.others = (e.target as HTMLInputElement).checked)}>Anche da altri client</label>
        <select aria-label="Avvisi a comparsa" title="Avvisi a comparsa in questo browser" @change=${(e: Event) => this.setToast(e)}>
          ${TOAST_OPTIONS.map(o => html`<option value=${o.id} ?selected=${this.toastMode === o.id}>${o.label}</option>`)}
        </select>
      </div>
      ${this.renderList()}
    </div>`;
  }
}
