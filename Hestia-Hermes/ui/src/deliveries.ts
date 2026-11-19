/**
 * <hermes-deliveries> — «Consegne»: what was sent to you, where it arrived and how it went
 * (SPEC docs/work/2026-10-18-core-modules-and-external-mcp §A2; rebuilt in docs/work/2026-11-18-real-test-problems F).
 *
 * One pattern: grouped by day; each row = the area's icon (never a module name), the title without HTML, ONE sentence
 * that says what happened (delivered where · held back while you were busy · not delivered: plain reason + «Try again
 * now» · waiting for your answer · your answer); the technical details only on demand. The count tiles filter the list.
 * Read-only apart from «Try again now»; the inbox is the Notifications page.
 */
import { HestiaElement, html, css, nothing, tr, locale } from '@hestia/webui-sdk';
import { API, hermesStyles, todayStart, when } from './util';

const FILTERS = [
  { id: '', label: tr('All') }, { id: 'failed', label: tr('Not delivered') }, { id: 'pending', label: tr('Waiting for you') },
  { id: 'held', label: tr('Held back') }, { id: 'answered', label: tr('With answer') }, { id: 'quiet', label: tr('Only in the list') },
];

/** Where a notification arrives, as people say it. */
function clientName(name: string): string {
  const n = String(name || '').toLowerCase();
  if (n === 'telegram') return 'Telegram';
  if (n === 'webui' || n === 'site' || n === 'web') return tr('the site');
  if (n === 'push' || n === 'webpush') return tr('phone notifications');
  return name;
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] || '';
  return tr('{0} and {1}', names.slice(0, -1).join(', '), names[names.length - 1]);
}

/** A delivery error in plain words (the raw text stays in the details). */
function plainError(detail: string): string {
  const d = String(detail || '').toLowerCase();
  if (/timeout|timed out/.test(d)) return tr('it did not answer in time');
  if (/401|403|unauthori|forbidden|token|blocked/.test(d)) return tr('access was refused: sign in to it again');
  if (/404|not found|chat not found|gone|410/.test(d)) return tr('the destination no longer exists');
  if (/connect|unreachable|refused|resolve|dns|network/.test(d)) return tr('it could not be reached');
  if (/429|too many|rate/.test(d)) return tr('too many messages at once: it will be sent again');
  return d ? tr('an unexpected error') : tr('no reason given');
}

function dayKey(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '' : d.toDateString();
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const today = new Date(); const y = new Date(); y.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return tr('Today');
  if (d.toDateString() === y.toDateString()) return tr('Yesterday');
  return d.toLocaleDateString(locale(), { weekday: 'long', day: 'numeric', month: 'long' });
}

export class HermesDeliveries extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, summary: { state: true }, next: { state: true },
                        error: { state: true }, flag: { state: true }, client: { state: true }, clients: { state: true },
                        subs: { state: true }, more: { state: true }, open: { state: true }, retrying: { state: true } };
  declare items: any[] | null; declare summary: any; declare next: string | null; declare error: string;
  declare flag: string; declare client: string; declare clients: string[]; declare subs: any[] | null;
  declare more: boolean; declare open: string; declare retrying: boolean;
  static styles = [...HestiaElement.styles, hermesStyles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 13px; padding: 4px 10px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); cursor: pointer; min-height: var(--tap, 0px); }
    .chip[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .chip:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .day { font-size: 12px; font-weight: 600; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin: 14px 0 4px; }
    .day:first-child { margin-top: 0; }
    .n { padding: 10px 0; border-top: 1px solid var(--border); display: grid; grid-template-columns: 32px minmax(0, 1fr); gap: 4px 10px; }
    .n:first-of-type { border-top: 0; }
    .ic { width: 32px; height: 32px; border-radius: 50%; background: var(--surface-2); display: flex; align-items: center;
      justify-content: center; color: var(--text-2); grid-row: span 3; }
    .ic[data-tone=danger] { background: color-mix(in srgb, var(--danger) 14%, transparent); color: var(--danger); }
    .ic[data-tone=accent] { background: var(--accent-soft); color: var(--accent); }
    .top { display: flex; gap: 8px; align-items: baseline; min-width: 0; }
    .t { font-weight: 550; overflow-wrap: anywhere; flex: 1; min-width: 0; }
    .time { color: var(--text-3); font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .st { font-size: 13px; color: var(--text-2); overflow-wrap: anywhere; }
    .st[data-tone=danger] { color: var(--danger); }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
    .det { font-size: 12.5px; color: var(--text-3); display: flex; flex-direction: column; gap: 3px; overflow-wrap: anywhere; }
    .pv { color: var(--text-2); }
    code { font-size: 12px; background: var(--surface-2); padding: 0 4px; border-radius: 4px; }
    details.how summary { cursor: pointer; color: var(--text-2); font-size: 13px; }
    .subrow { padding: 8px 0; border-top: 1px solid var(--border); font-size: 13px; overflow-wrap: anywhere; }
    .subrow:first-child { border-top: 0; }
    select { max-width: 100%; }
  `];

  constructor() {
    super();
    this.items = null; this.summary = null; this.next = null; this.error = ''; this.flag = ''; this.client = '';
    this.clients = []; this.subs = null; this.more = false; this.open = ''; this.retrying = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this.load(); this.loadSide();
    this.onHost('refresh', () => { this.load(); this.loadSide(); });
    this.addEventListener('retry', () => { this.load(); this.loadSide(); });
  }

  private async load(append = false) {
    const query: Record<string, any> = { limit: 40 };
    if (this.flag) query.flag = this.flag;
    if (this.client) query.client = this.client;
    if (append && this.next) query.before = this.next;
    this.more = append;
    const r = await this.host.api('GET', `${API}/deliveries`, { query });
    this.more = false;
    if (!r.ok) {
      if (append) { this.host.toast(r.error || tr('Not uploaded'), 'danger'); return; }
      this.error = tr('Not available right now');
      return;
    }
    this.error = '';
    this.items = append ? [...(this.items || []), ...r.data.items] : r.data.items;
    this.next = r.data.next_before;
    if (!append) this.loadSummary();
  }

  private async loadSummary() {
    const r = await this.host.api('GET', `${API}/deliveries`, { query: { since: todayStart(), limit: 200 } });
    this.summary = r.ok ? r.data.summary : null;
  }

  private async loadSide() {
    const [c, s] = await Promise.all([this.host.api('GET', `${API}/clients`), this.host.api('GET', `${API}/subscriptions`)]);
    this.clients = c.ok ? c.data.clients || [] : [];
    this.subs = s.ok ? s.data.subscriptions || [] : [];
  }

  private setFlag(id: string) { this.flag = id; this.items = null; this.load(); }
  private setClient(e: Event) { this.client = (e.target as HTMLSelectElement).value; this.items = null; this.load(); }

  private async retryNow() {
    this.retrying = true;
    const r = await this.host.api('POST', `${API}/deliveries/retry`);
    this.retrying = false;
    this.host.toast(r.ok ? tr('Sent again') : tr('Not available right now'), r.ok ? 'success' : 'danger');
    window.setTimeout(() => this.load(), 1500);
  }

  private renderStats() {
    const s = this.summary; if (!s) return nothing;
    return html`<hxk-stat .items=${[
      { label: tr('Today'), value: s.total, open: () => this.setFlag('') },
      { label: tr('Not delivered'), value: s.failed, tone: s.failed ? 'danger' : 'neutral', open: () => this.setFlag('failed') },
      { label: tr('Waiting for you'), value: s.pending, open: () => this.setFlag('pending') },
      { label: tr('Held back'), value: s.held, hint: tr('while you were busy'), open: () => this.setFlag('held') },
    ]}></hxk-stat>`;
  }

  /** What happened, in one sentence, with its tone. */
  private sentence(n: any): { text: string; tone: string; retry?: boolean } {
    const clients = Object.entries(n.clients || {}) as Array<[string, any]>;
    const failed = clients.filter(([, c]) => c.state === 'failed' || c.state === 'dead');
    const got = clients.filter(([, c]) => c.state === 'delivered').map(([name]) => clientName(name));
    const f = n.flags || {};
    if (failed.length) {
      const where = joinNames(failed.map(([name]) => clientName(name)));
      const why = plainError(failed[0][1].detail || '');
      const also = got.length ? ' ' + tr('It did arrive on {0}.', joinNames(got)) : '';
      return { text: tr('Not delivered to {0}: {1}.', where, why) + also, tone: 'danger', retry: true };
    }
    if (n.answer) return { text: tr('You answered «{0}» {1}.', n.answer.label || n.answer.action_id || '–', when(n.answer.at)), tone: 'success' };
    if (f.superseded) return { text: tr('Replaced by a newer one.'), tone: 'neutral' };
    if (f.retracted) return { text: tr('Removed from the chat once it was handled.'), tone: 'neutral' };
    if (f.held) return { text: f.held_released ? tr('Held back while you were busy, then sent in the summary.')
      : tr('Held back while you were busy: it is in the list.'), tone: 'neutral' };
    if (f.quiet) return { text: tr('Only in the list, without a notice: you had already seen it in the chat.'), tone: 'neutral' };
    const base = got.length ? tr('Delivered to {0}.', joinNames(got)) : tr('No device reached: it is in the list.');
    if (f.pending) return { text: `${base} ${tr('Waiting for your answer.')}`, tone: 'accent' };
    return { text: base + (n.seen?.at ? ' ' + tr('Seen {0}.', when(n.seen.at)) : ''), tone: 'neutral' };
  }

  private renderItem(n: any) {
    const isOpen = this.open === n.id;
    const st = this.sentence(n);
    const clients = Object.entries(n.clients || {}) as Array<[string, any]>;
    const area = n.area || { icon: 'bell', label: 'Notifications' };
    return html`<div class="n">
      <span class="ic" data-tone=${st.tone} title=${tr(area.label)}><hxk-icon name=${st.tone === 'danger' ? 'alert' : area.icon} size="16"></hxk-icon></span>
      <div class="top"><span class="t">${n.title || n.preview || tr('Notification')}</span><span class="time">${when(n.created_at)}</span></div>
      <div class="st" data-tone=${st.tone}>${st.text}</div>
      <div class="acts">
        ${st.retry ? html`<hxk-button size="sm" variant="ghost" icon="refresh" ?loading=${this.retrying} @click=${() => this.retryNow()}>${tr('Try again now')}</hxk-button>` : nothing}
        <hxk-button size="sm" variant="ghost" @click=${() => (this.open = isOpen ? '' : n.id)}>${isOpen ? tr('Less') : tr('Details')}</hxk-button>
      </div>
      ${isOpen ? html`<div class="det" style="grid-column: 2">
        ${n.title && n.preview ? html`<div class="pv">${n.preview}</div>` : nothing}
        <div>${tr('Area')}: ${tr(area.label)}</div>
        ${clients.map(([name, c]) => html`<div>${clientName(name)}: ${c.state || '–'} · ${when(c.at)}${c.attempts > 1 ? ` · ${tr('{0} attempts', c.attempts)}` : ''}${c.detail ? html` · <code>${c.detail}</code>` : nothing}</div>`)}
        ${n.actions?.length && !n.answer ? html`<div>${tr('Possible answers')}: ${n.actions.join(' · ')}</div>` : nothing}
        ${n.repeat?.count > 1 ? html`<div>${tr('time {0}', n.repeat.count)}</div>` : nothing}
        <div>${tr('Type')} <code>${n.event_type}</code> · <code>${n.state}</code> · id <code>${n.id}</code></div>
      </div>` : nothing}
    </div>`;
  }

  private renderList() {
    if (this.items === null) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!this.items.length) return html`<hxk-state kind="empty" text=${tr('Nothing with this filter')}></hxk-state>`;
    const out: unknown[] = [];
    let last = '';
    for (const n of this.items) {
      const k = dayKey(n.created_at);
      if (k !== last) { out.push(html`<div class="day">${dayLabel(n.created_at)}</div>`); last = k; }
      out.push(this.renderItem(n));
    }
    return html`<div class="card">${out}
      ${this.next ? html`<div style="padding-top:8px"><hxk-button size="sm" ?loading=${this.more} @click=${() => this.load(true)}>${tr('Load more')}</hxk-button></div>` : nothing}</div>`;
  }

  /** Which events become notifications: technical, so behind a closed section. */
  private renderSubs() {
    if (this.subs === null) return nothing;
    return html`<details class="how card"><summary>${tr('How notifications are chosen')}</summary>
      ${this.subs.length ? this.subs.map(s => html`<div class="subrow">
          <b>${s.domain || '*'}</b> · <code>${s.event_type || '*'}</code>
          → ${(s.channels || []).map((c: any) => c.type === 'client' ? tr('only {0}', clientName(c.client)) : tr('all devices')).join(', ') || tr('all devices')}
        </div>`) : html`<div class="subrow muted">${tr('No active subscription')}</div>`}
      <div class="subrow muted">${tr('Reached now:')} ${this.clients.length ? joinNames(this.clients.map(clientName)) : tr('none')}</div>
    </details>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>${tr('Deliveries')}</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>${tr('Deliveries')}</h1><span class="sub">${tr('What was sent to you, where it arrived and how it went')}</span></div>
      ${this.renderStats()}
      <div class="row wrap">
        <div class="chips grow">${FILTERS.map(f => html`<button class="chip" aria-pressed=${this.flag === f.id} @click=${() => this.setFlag(f.id)}>${f.label}</button>`)}</div>
        ${this.clients.length > 1 ? html`<select aria-label=${tr('Where')} @change=${(e: Event) => this.setClient(e)}>
          <option value="">${tr('Everywhere')}</option>${this.clients.map(c => html`<option value=${c} ?selected=${this.client === c}>${clientName(c)}</option>`)}</select>` : nothing}
      </div>
      ${this.renderList()}
      ${this.renderSubs()}
    </div>`;
  }
}
