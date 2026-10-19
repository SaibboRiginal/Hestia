/**
 * <iris-email> — «Email»: one look at the mailbox for all of Hestia (Hecate), Iris hands each module the mails it
 * subscribed to. Shows the watcher (last check, Gmail push), the subscriptions per module and the last deliveries.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/email';

function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString()
    ? d.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function every(seconds?: number): string {
  if (!seconds) return '–';
  return seconds < 3600 ? `ogni ${Math.round(seconds / 60)} min` : `ogni ${Math.round(seconds / 3600)} h`;
}

function rule(s: any): string {
  const parts: string[] = [];
  if (s.senders?.length) parts.push(`da ${s.senders.join(', ')}`);
  if (s.subject_contains?.length) parts.push(`oggetto con ${s.subject_contains.join(' / ')}`);
  if (s.labels?.length) parts.push(`etichetta ${s.labels.join(', ')}`);
  if (s.queries?.length) parts.push(`ricerche: ${s.queries.join(' · ')}`);
  return parts.join(' · ') || 'nessuna regola';
}

export class IrisEmail extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true }, busy: { state: true } };
  declare data: any; declare error: string; declare busy: string;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .r { display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .r:first-child { border-top: 0; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    .det { font-size: 12px; color: var(--text-2); overflow-wrap: anywhere; }
    .tnum { font-variant-numeric: tabular-nums; }
    code { font-size: 12px; background: var(--surface-2); padding: 0 4px; border-radius: 4px; }
  `];

  constructor() { super(); this.data = null; this.error = ''; this.busy = ''; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
  }

  private async load() {
    const r = await this.host.api('GET', `${API}/dispatch`);
    if (!r.ok) { this.error = r.status === 0 ? 'Iris non raggiungibile' : r.error || 'Iris non raggiungibile'; return; }
    this.error = ''; this.data = r.data;
  }

  private async check() {
    this.busy = 'check';
    const r = await this.host.api('POST', `${API}/check`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Controllo non avviato', 'danger'); return; }
    const d = r.data || {};
    const text = d.status === 'ok' ? (d.new ? `${d.new} email nuove passate ai moduli` : 'Nessuna email nuova')
      : d.status === 'skipped' ? 'Gmail non collegato: ricollega Google' : d.status === 'busy' ? 'Controllo già in corso'
      : d.status === 'initialized' ? 'Controllo avviato: da ora vedo le email nuove' : d.error || 'Controllo fallito';
    this.host.toast(text, d.status === 'ok' || d.status === 'initialized' || d.status === 'busy' ? 'success' : 'warning');
    this.load();
  }

  private async backfill(s: any) {
    this.busy = s.id;
    const r = await this.host.api('POST', `${API}/subscriptions/${encodeURIComponent(s.owner)}/${encodeURIComponent(s.key)}/backfill`, { body: {} });
    this.busy = '';
    if (!r.ok || r.data?.status === 'error') { this.host.toast(r.data?.error || r.error || 'Non riuscito', 'danger'); return; }
    this.host.toast(`${s.title || s.key}: ${r.data.found} email trovate negli ultimi ${r.data.days} giorni`, 'success');
    this.load();
  }

  private renderWatcher(w: any) {
    if (!w) return html`<hxk-card heading="Controllo della casella"><hxk-state kind="offline" text="Hecate non raggiungibile"></hxk-state></hxk-card>`;
    const st = w.watcher || {};
    const push = w.push || {};
    const auth = st.last_error === 'gmail_not_authorized' || String(st.last_error || '').includes('Re-authorize');
    return html`<hxk-card heading="Controllo della casella" subtitle="Uno solo per tutta Hestia, in Hecate">
      <div class="col" style="gap:6px">
        <div class="row wrap">
          ${push.active ? html`<hxk-badge tone="success">Gmail push attivo</hxk-badge>`
            : push.configured ? html`<hxk-badge tone="warning" title=${push.error || ''}>Gmail push configurato, non connesso</hxk-badge>`
            : html`<hxk-badge tone="neutral" title="Si attiva con il setup Pub/Sub (vedi documentazione di Hecate)">Gmail push spento</hxk-badge>`}
          <hxk-badge tone="info">${every(w.interval_seconds)}</hxk-badge>
          ${auth ? html`<hxk-badge tone="danger">Ricollega Google</hxk-badge>` : st.last_error ? html`<hxk-badge tone="danger" title=${st.last_error}>errore</hxk-badge>` : nothing}
        </div>
        <div class="small muted tnum">Ultimo controllo ${when(st.last_check)} · riuscito ${when(st.last_ok)} · ${st.last_new ?? 0} nuove · ${st.pushed_total ?? 0} in tutto</div>
        ${st.last_error && !auth ? html`<div class="det">${st.last_error}</div>` : nothing}
      </div>
    </hxk-card>`;
  }

  private renderSubs(subs: any[]) {
    return html`<hxk-card heading="Chi riceve cosa" subtitle="Ogni modulo chiede le sue email con le sue regole">
      ${!subs.length ? html`<hxk-state kind="empty" text="Nessun modulo iscritto"></hxk-state>` : subs.map(s => html`<div class="r">
        <div class="grow col" style="gap:3px">
          <div class="row wrap"><span class="t">${s.title || s.key}</span><hxk-badge tone="accent">${s.owner}</hxk-badge>
            ${s.last_ring === 'failed' ? html`<hxk-badge tone="warning" title="Il modulo non ha risposto: le email lo aspettano nell'archivio">in attesa</hxk-badge>` : nothing}</div>
          <div class="det">${rule(s)}</div>
          <div class="small muted tnum">${s.delivered_total || 0} consegnate · ultima ${when(s.last_delivery_at)}</div>
        </div>
        <hxk-button size="sm" variant="ghost" icon="refresh" ?loading=${this.busy === s.id} @click=${() => this.backfill(s)}
          title="Ripassa al modulo le email degli ultimi giorni">Ripassa</hxk-button>
      </div>`)}
    </hxk-card>`;
  }

  private renderLog(rows: any[]) {
    return html`<hxk-card heading="Ultime consegne">
      ${!rows.length ? html`<hxk-state kind="empty" text="Ancora nessuna consegna da quando Iris è partito"></hxk-state>` : rows.map(d => html`<div class="r">
        <div class="grow col" style="gap:3px">
          <div class="row wrap"><span class="t">${d.count} → ${d.owner}</span>
            ${d.ring_ok === false ? html`<hxk-badge tone="warning">modulo non raggiungibile</hxk-badge>` : nothing}
            ${d.source === 'backfill' ? html`<hxk-badge tone="neutral">ripassate</hxk-badge>` : nothing}</div>
          ${d.subjects?.length ? html`<div class="det">${d.subjects.join(' · ')}</div>` : nothing}
        </div>
        <span class="small muted tnum">${when(d.at)}</span>
      </div>`)}
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>Email</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    const d = this.data;
    return html`<div class="page">
      <div class="head"><h1>Email</h1><span class="sub">Le email arrivano ai moduli da sole: niente controlli per modulo</span>
        <span class="grow"></span>
        <hxk-button icon="refresh" ?loading=${this.busy === 'check'} @click=${() => this.check()}>Controlla ora</hxk-button></div>
      ${!d ? html`<hxk-state kind="loading"></hxk-state>` : html`
        <hxk-stat .items=${[
          { label: 'Moduli iscritti', value: new Set((d.subscriptions || []).map((s: any) => s.owner)).size },
          { label: 'Email viste', value: d.stats?.incoming_messages ?? 0 },
          { label: 'Non per nessuno', value: d.stats?.unmatched ?? 0 },
        ]}></hxk-stat>
        ${this.renderWatcher(d.watcher)}
        ${this.renderSubs(d.subscriptions || [])}
        ${this.renderLog(d.deliveries || [])}`}
    </div>`;
  }
}
