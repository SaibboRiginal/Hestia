/**
 * <hub-map> — "Mappa": every service registered on Hub (and Hub itself): online by heartbeat, node, version,
 * last heartbeat, topology tags, registry revision; "Verifica salute" also probes each health endpoint.
 * <hub-online-widget> — "Servizi online": n / total, the offline ones by name.
 * SPEC docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/ui';
const HEALTH: Record<string, [string, string]> = {
  healthy: ['success', 'risponde'], degraded: ['warning', 'degradato'], unavailable: ['danger', 'non risponde'],
};

function ago(epoch?: number | null): string {
  if (!epoch) return '–';
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch));
  if (s < 60) return `${s} s fa`;
  if (s < 3600) return `${Math.round(s / 60)} min fa`;
  if (s < 86400) return `${Math.round(s / 3600)} h fa`;
  return new Date(epoch * 1000).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export class HubMap extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true }, busy: { state: true },
                        filter: { state: true }, group: { state: true } };
  declare data: any; declare error: string; declare busy: boolean; declare filter: string; declare group: string;
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .tools { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    .tools input { flex: 1; min-width: 140px; }
    .grp { display: flex; gap: 4px; flex-wrap: wrap; }
    .chip { font-size: 12px; padding: 4px 10px; border-radius: var(--radius-full); border: 1px solid var(--border-strong);
      background: transparent; color: var(--text-2); cursor: pointer; font: inherit; }
    .chip[aria-pressed='true'] { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .layer { display: flex; flex-direction: column; gap: 8px; }
    .layer h3 { text-transform: capitalize; }
    .svc { display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .svc:first-of-type { border-top: 0; }
    .dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 5px; flex: none; background: var(--danger); }
    .dot.on { background: var(--success); }
    .tags { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
    .tag { font-size: 11px; padding: 1px 7px; border-radius: var(--radius-full); background: var(--surface-2); color: var(--text-2); }
    .meta { display: flex; gap: 4px 12px; flex-wrap: wrap; font-size: 12px; color: var(--text-3); }
    .tnum { font-variant-numeric: tabular-nums; }
  `];
  constructor() { super(); this.data = null; this.error = ''; this.busy = false; this.filter = ''; this.group = 'layer'; }

  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }

  private async load(probe = false) {
    this.busy = probe;
    const r = await this.host.api('GET', `${API}/map`, { query: probe ? { probe: 'true' } : undefined });
    this.busy = false;
    if (!r.ok) { this.error = r.error === 'offline' ? 'Sei offline' : 'Hub non raggiungibile'; return; }
    this.error = ''; this.data = r.data;
  }

  private groups(list: any[]): Array<[string, any[]]> {
    const out = new Map<string, any[]>();
    for (const s of list) {
      const k = this.group === 'node' ? s.node || 'nodo sconosciuto' : this.group === 'type' ? s.service_type || 'altro'
        : s.topology?.layer || 'senza layer';
      if (!out.has(k)) out.set(k, []);
      out.get(k)!.push(s);
    }
    return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }

  private row(s: any) {
    const h = s.health ? HEALTH[s.health] : null;
    return html`<div class="svc">
      <span class="dot ${s.online ? 'on' : ''}" title=${s.online ? 'online' : 'offline'}></span>
      <div class="grow">
        <div class="row wrap"><b>${s.name}</b>
          ${s.online ? nothing : html`<hxk-badge tone="danger">non raggiungibile</hxk-badge>`}
          ${h ? html`<hxk-badge tone=${h[0]}>${h[1]}</hxk-badge>` : nothing}
          ${s.instances > 1 ? html`<hxk-badge tone="info">${s.instances} istanze</hxk-badge>` : nothing}
          ${s.has_ui ? html`<hxk-badge>interfaccia</hxk-badge>` : nothing}${s.has_mcp ? html`<hxk-badge>MCP</hxk-badge>` : nothing}</div>
        <div class="meta"><span>nodo ${s.node || '–'}</span><span>v${s.version || '?'}</span><span>${s.service_type || ''}</span>
          <span class="tnum">ultimo segnale ${s.self ? 'adesso' : ago(s.last_heartbeat)}</span></div>
        ${(s.topology_tags || []).length ? html`<div class="tags">${s.topology_tags.map((t: string) => html`<span class="tag">${t}</span>`)}</div>` : nothing}
      </div></div>`;
  }

  render() {
    if (this.error && !this.data) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.data) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const d = this.data;
    const q = this.filter.trim().toLowerCase();
    const list = (d.services || []).filter((s: any) => !q || [s.name, s.node, ...(s.topology_tags || []), ...(s.tags || [])]
      .some((v: string) => String(v || '').toLowerCase().includes(q)));
    const groups: Array<[string, string]> = [['layer', 'Per layer'], ['node', 'Per nodo'], ['type', 'Per tipo']];
    return html`<div class="page">
      <div class="head"><h1>Mappa</h1><span class="sub">Revisione registro ${d.revision} · aggiornata ${ago(d.updated_at)}</span>
        <span class="grow"></span>
        <hxk-button icon="check" ?loading=${this.busy} @click=${() => this.load(true)}>Verifica salute</hxk-button>
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>Aggiorna</hxk-button></div>
      ${this.error ? html`<hxk-state kind="error" text="${this.error}: mostro l'ultima mappa" @retry=${() => this.load()}></hxk-state>` : nothing}
      <hxk-stat .items=${[
        { label: 'Servizi', value: d.services_count },
        { label: 'Online', value: d.online_count, tone: 'success' },
        { label: 'Offline', value: d.offline_count, tone: d.offline_count ? 'danger' : 'neutral',
          delta: d.offline_count ? 'nessun segnale da 3 min' : '', hint: `Online = registrato negli ultimi ${Math.round(d.online_window_seconds / 60)} minuti` },
        { label: 'Revisione', value: d.revision, hint: 'Cresce a ogni registrazione o modifica di un servizio' },
      ]}></hxk-stat>
      <div class="tools"><input type="search" placeholder="Cerca servizio, nodo o tag" .value=${this.filter}
          @input=${(e: any) => (this.filter = e.target.value)}>
        <div class="grp">${groups.map(([k, l]) => html`<button class="chip" aria-pressed=${this.group === k}
          @click=${() => (this.group = k)}>${l}</button>`)}</div></div>
      ${list.length ? this.groups(list).map(([name, items]) => html`<div class="card layer">
          <h3>${name} <span class="small muted">${items.filter(s => s.online).length}/${items.length}</span></h3>
          <div>${items.map(s => this.row(s))}</div></div>`)
        : html`<hxk-state kind="empty" text=${q ? 'Nessun servizio corrisponde' : 'Nessun servizio registrato'}></hxk-state>`}
    </div>`;
  }
}

export class HubOnlineWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true } };
  declare data: any; declare error: boolean;
  static styles = [...HestiaElement.styles, css`
    :host { display: block; height: 100%; }
    .w { display: flex; flex-direction: column; gap: 6px; height: 100%; padding: 2px; cursor: pointer; }
    .big { font-size: 24px; font-weight: 650; line-height: 1.1; font-variant-numeric: tabular-nums; }
  `];
  constructor() { super(); this.data = null; this.error = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  private async load() {
    const r = await this.host.api('GET', `${API}/map`);
    this.error = !r.ok; if (r.ok) this.data = r.data;
  }
  render() {
    if (this.error && !this.data) return html`<hxk-state kind="offline" text="Mappa non raggiungibile" @retry=${() => this.load()}></hxk-state>`;
    if (!this.data) return html`<hxk-state kind="loading"></hxk-state>`;
    const d = this.data;
    const off = (d.services || []).filter((s: any) => !s.online).map((s: any) => s.name);
    const small = this.ctx?.size === 's';
    return html`<div class="w" @click=${() => this.host.navigate('mappa')}>
      <span class="small muted">Servizi online</span>
      <div class="big">${d.online_count}<span class="muted" style="font-size:15px"> / ${d.services_count}</span></div>
      ${off.length ? html`<div class="row wrap">${(small ? off.slice(0, 2) : off.slice(0, 6)).map((n: string) => html`<hxk-badge tone="danger">${n}</hxk-badge>`)}
          ${off.length > (small ? 2 : 6) ? html`<span class="small muted">+${off.length - (small ? 2 : 6)}</span>` : nothing}</div>`
        : html`<hxk-badge tone="success">tutti online</hxk-badge>`}
    </div>`;
  }
}
