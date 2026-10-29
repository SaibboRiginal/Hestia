/**
 * Lares («Casa», Home Assistant) WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4;
 * dossier docs/work/2026-10-24-tutto-brainstorm-cindy W7). Page, widget and quick action in Hestia-Lares/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/home';
const STATE: Record<string, string> = { on: 'acceso', off: 'spento', open: 'aperta', closed: 'chiusa', locked: 'chiusa',
  unlocked: 'aperta', home: 'a casa', not_home: 'fuori', unavailable: 'non raggiungibile' };
const TABS = ['light', 'switch', 'cover', 'climate', 'fan', 'media_player', 'lock', 'scene', 'script', 'sensor', 'binary_sensor'];

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown, query?: Record<string, any>): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, { body, query });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? 'Non raggiungibile, riprova' : r.error || 'Errore', 'warning');
  return r;
}
const say = (e: any) => e.domain === 'sensor' ? `${e.state}${e.unit || ''}` : STATE[e.state] || e.state;

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .click { cursor: pointer; }
  .tabs { display: flex; gap: 6px; flex-wrap: wrap; }
  .tab { padding: 4px 12px; border-radius: 99px; border: 1px solid var(--border-strong); cursor: pointer; font-size: 13px; }
  .tab.on { background: var(--accent); color: var(--accent-contrast); border-color: var(--accent); }
  .dev { display: flex; gap: 10px; align-items: center; padding: 8px 2px; border-bottom: 1px solid var(--border); }
  .dev:last-child { border-bottom: 0; }
  .fav { display: flex; flex-direction: column; gap: 2px; padding: 12px; border-radius: var(--radius-lg); border: 1px solid var(--border);
    background: var(--surface); cursor: pointer; min-width: 120px; }
  .fav:hover { border-color: var(--accent); }
  .lit { color: var(--warning); }
`;

function controls(host: HestiaHost, e: any, done: () => void) {
  const run = async (cmd: string) => { const r = await call(host, 'POST', `/entities/${encodeURIComponent(e.id)}/${cmd}`); if (r.ok) done(); };
  switch (e.domain) {
    case 'light': case 'switch': case 'fan': case 'media_player':
      return html`<hxk-button size="sm" variant=${e.state === 'on' ? 'primary' : 'default'} @click=${() => run('toggle')}>${e.state === 'on' ? 'Spegni' : 'Accendi'}</hxk-button>`;
    case 'cover': return html`<hxk-button size="sm" @click=${() => run('open')}>Apri</hxk-button><hxk-button size="sm" @click=${() => run('close')}>Chiudi</hxk-button>`;
    case 'lock': return html`<hxk-button size="sm" @click=${() => run(e.state === 'locked' ? 'unlock' : 'lock')}>${e.state === 'locked' ? 'Apri' : 'Chiudi'}</hxk-button>`;
    case 'scene': case 'script': return html`<hxk-button size="sm" icon="play" @click=${() => run('on')}>Attiva</hxk-button>`;
    default: return nothing;
  }
}

export class LaresHome extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, items: { state: true }, labels: { state: true }, tab: { state: true }, q: { state: true } };
  declare s: any;
  declare items: any[];
  declare labels: Record<string, string>;
  declare tab: string;
  declare q: string;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.s = undefined; this.items = []; this.labels = {}; this.tab = 'light'; this.q = ''; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  async load() {
    const r = await call(this.host, 'GET', '/status');
    this.s = r.ok ? r.data : null;
    if (this.s?.connected) {
      const e = await call(this.host, 'GET', '/entities');
      if (e.ok) { this.items = e.data.items; this.labels = e.data.domains; }
    }
  }
  private async star(e: any) {
    const r = await call(this.host, 'POST', '/favorites', { entity: e.id, label: e.name, command: e.domain === 'scene' || e.domain === 'script' ? 'on' : 'toggle' });
    if (r.ok) { this.host.toast('Azione rapida salvata', 'success'); this.load(); }
  }
  render() {
    const s = this.s;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    if (!s.configured) return html`<div class="page"><h1>Casa</h1><div class="card col"><b>La casa non è ancora collegata.</b>
      <div class="small muted">Serve l'indirizzo di Home Assistant e un token di accesso (profilo › token a lunga durata) nel file di configurazione: LARES_HA_URL e LARES_HA_TOKEN. Poi riavvia questa parte.</div></div></div>`;
    if (!s.connected) return html`<div class="page"><h1>Casa</h1><hxk-state kind="error" text=${s.error || 'Home Assistant non risponde.'} @retry=${() => this.load()}></hxk-state></div>`;
    const tabs = TABS.filter(d => this.items.some(e => e.domain === d));
    const q = this.q.trim().toLowerCase();
    const shown = this.items.filter(e => e.domain === this.tab && (!q || e.name.toLowerCase().includes(q)));
    return html`<div class="page">
      <div class="between"><h1>Casa</h1>${s.person ? html`<hxk-badge tone=${s.person === 'home' ? 'success' : 'neutral'}>${STATE[s.person] || s.person}</hxk-badge>` : nothing}</div>
      <div class="grid" style="--min: 220px">
        <div class="card col"><h3>Luci</h3><div class="small">${s.lights_on.length ? html`<span class="lit">Accese:</span> ${s.lights_on.join(', ')}` : 'Tutte spente'}</div></div>
        ${s.temperatures.length ? html`<div class="card col"><h3>Temperature</h3>${s.temperatures.map((t: string) => html`<div class="small">${t}</div>`)}</div>` : nothing}
        <div class="card col"><h3>Porte e finestre</h3><div class="small">${s.open.length ? `Aperte: ${s.open.join(', ')}` : 'Tutto chiuso'}</div></div>
      </div>
      ${s.favorites.length ? html`<div class="col"><h3>Azioni rapide</h3><div class="row wrap">${s.favorites.map((f: any) => html`<div class="fav" @click=${async () => { const r = await call(this.host, 'POST', `/favorites/${f.id}/run`); if (r.ok) { this.host.toast(`${f.label}: fatto`, 'success'); this.load(); } }}>
        <b>${f.label}</b><span class="small muted">${f.room || ''}</span>
        <span class="small muted click" @click=${async (ev: Event) => { ev.stopPropagation(); if (await this.host.confirm('Togliere l\'azione rapida?', f.label, { label: 'Togli', danger: true })) { await call(this.host, 'DELETE', `/favorites/${f.id}`); this.load(); } }}>togli</span></div>`)}</div></div>` : nothing}
      <div class="card col"><div class="between"><h3>Dispositivi</h3><input placeholder="Cerca" .value=${this.q} @input=${(e: any) => { this.q = e.target.value; }}></div>
        <div class="tabs">${tabs.map(d => html`<span class="tab ${this.tab === d ? 'on' : ''}" @click=${() => { this.tab = d; }}>${this.labels[d] || d}</span>`)}</div>
        ${shown.length ? shown.map(e => html`<div class="dev"><div class="grow"><div>${e.name}</div><div class="small muted">${say(e)}${e.temperature ? ` · ${e.temperature}°` : ''}</div></div>
          ${controls(this.host, e, () => this.load())}
          ${['sensor', 'binary_sensor'].includes(e.domain) ? nothing : html`<hxk-button size="sm" variant="ghost" icon="star" @click=${() => this.star(e)}></hxk-button>`}</div>`)
          : html`<div class="small muted">Nessun dispositivo.</div>`}</div>
    </div>`;
  }
}

export class LaresWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true } };
  declare s: any;
  static styles = [...HestiaElement.styles, styles, css`:host { display: block; height: 100%; }`];
  constructor() { super(); this.s = undefined; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  async load() { const r = await call(this.host, 'GET', '/status'); this.s = r.ok ? r.data : null; }
  render() {
    const s = this.s;
    if (s === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (s === null || !s.configured || !s.connected) return html`<div class="small muted click" @click=${() => this.host.navigate('casa')}>${s && !s.configured ? 'Casa non collegata' : 'Casa non raggiungibile'}</div>`;
    const favs = this.ctx?.size === 's' ? [] : s.favorites.slice(0, this.ctx?.size === 'l' ? 6 : 3);
    return html`<div class="col" style="gap:6px">
      <div class="between click" @click=${() => this.host.navigate('casa')}><span class="small muted">Casa</span><span class="small">${s.lights_on.length ? `${s.lights_on.length} luci accese` : 'luci spente'}</span></div>
      ${s.temperatures.length ? html`<div class="small">${s.temperatures[0]}</div>` : nothing}
      ${favs.length ? html`<div class="row wrap">${favs.map((f: any) => html`<hxk-button size="sm" @click=${async () => { const r = await call(this.host, 'POST', `/favorites/${f.id}/run`); if (r.ok) this.load(); }}>${f.label}</hxk-button>`)}</div>` : nothing}
    </div>`;
  }
}

definePlugin({ 'lares-home': LaresHome, 'lares-widget': LaresWidget });
