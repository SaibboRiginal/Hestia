/**
 * <hecate-devices> — «Dispositivi»: Garmin (connected or not; «Collega Garmin» opens the form right in the card:
 * email and password go straight to the login and are never stored, then the two-step code in the same card, so no
 * notification to chase and the password never passes through the assistant, «Leggi adesso», «Scollega», last reading and error) and the Android phone as a
 * sensor (configured or not, last state at home / charging / battery, home Wi-Fi names and apps passed on, how to
 * set it up). Calls /api/gateway/garmin/* and /api/gateway/phone/status. Dossier 2026-10-24-tutto-brainstorm-cindy
 * B10 + Cindy 32 (W4) + W7.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/gateway';

function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '–' : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export class HecateDevices extends HestiaElement {
  static properties = { ...HestiaElement.properties, garmin: { state: true }, phone: { state: true },
                        error: { state: true }, busy: { state: true }, form: { state: true }, formError: { state: true } };
  declare garmin: any; declare phone: any; declare error: string; declare busy: string;
  /** The Garmin form in the card: '' closed, 'login' email + password, 'code' the two-step code. */
  declare form: '' | 'login' | 'code'; declare formError: string;
  private email = ''; private password = ''; private code = '';

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); align-items: start; }
    dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 8px 0; font-size: 13px; }
    dt { color: var(--text-3); }
    dd { margin: 0; overflow-wrap: anywhere; }
    code { font-family: var(--font-mono); font-size: 12px; background: var(--surface-2); padding: 1px 4px; border-radius: var(--radius-sm); }
    .form { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
    ol { margin: 6px 0 0 18px; padding: 0; font-size: 13px; color: var(--text-2); }
  `];

  constructor() { super(); this.garmin = null; this.phone = null; this.error = ''; this.busy = ''; this.form = ''; this.formError = ''; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const [g, p] = await Promise.all([this.host.api('GET', `${API}/garmin/status`), this.host.api('GET', `${API}/phone/status`)]);
    if (!g.ok && !p.ok) { this.error = g.status === 0 ? 'Non raggiungibile' : g.error || 'Non raggiungibile'; return; }
    this.error = '';
    this.garmin = g.ok ? g.data : null;
    this.phone = p.ok ? p.data : null;
  }

  private async run(id: string, method: 'POST' | 'DELETE', path: string, ok: string, body?: unknown) {
    this.busy = id;
    const r = await this.host.api(method, `${API}${path}`, body === undefined ? undefined : { body });
    this.busy = '';
    if (!r.ok || r.data?.status === 'error') { this.host.toast(r.data?.detail || r.data?.message || r.error || 'Non riuscito', 'warning'); return; }
    this.host.toast(r.data?.message || ok, 'success');
    this.load();
  }

  /** Email + password, or the code: straight to Hecate's login (``direct``: the code is asked here, not by a notification). */
  private async login() {
    const values = this.form === 'code' ? { code: this.code.trim() } : { email: this.email.trim(), password: this.password };
    this.busy = 'login';
    this.formError = '';
    const r = await this.host.api('POST', `${API}/garmin/login`, { body: { direct: true, values } });
    this.busy = '';
    this.password = '';
    if (!r.ok) { this.formError = r.data?.detail || r.error || 'Garmin non ha accettato l\'accesso, riprova'; return; }
    if (r.data?.status === 'needs_code') { this.form = 'code'; this.code = ''; return; }
    this.form = '';
    this.email = '';
    this.host.toast(r.data?.message || 'Garmin collegato', 'success');
    this.load();
  }

  private garminForm() {
    const code = this.form === 'code';
    return html`<div class="form">
      ${code ? html`<div class="small">Garmin ti ha mandato un codice (mail o SMS): scrivilo qui.</div>
        <hxk-field label="Codice di Garmin" placeholder="123456" .value=${this.code} @change=${(e: CustomEvent) => { this.code = String(e.detail); }}></hxk-field>`
      : html`<hxk-field label="Email di Garmin Connect" type="email" .value=${this.email} @change=${(e: CustomEvent) => { this.email = String(e.detail); }}></hxk-field>
        <hxk-field label="Password" type="password" .value=${this.password} @change=${(e: CustomEvent) => { this.password = String(e.detail); }}></hxk-field>
        <div class="small muted">Le uso una volta sola per collegare l'orologio e non le salvo: resta solo l'accesso che dà Garmin.</div>`}
      ${this.formError ? html`<div class="small" style="color:var(--danger)">${this.formError}</div>` : nothing}
      <div class="row wrap">
        <hxk-button variant="primary" icon="link" ?loading=${this.busy === 'login'} @click=${() => this.login()}>${code ? 'Conferma' : 'Collega'}</hxk-button>
        <hxk-button variant="ghost" @click=${() => { this.form = ''; this.formError = ''; this.password = ''; }}>Annulla</hxk-button>
      </div>
    </div>`;
  }

  private async forget() {
    if (!(await this.host.confirm('Scollegare Garmin?', 'Non leggerò più sonno e attività. Per ricollegarlo servirà di nuovo l\'accesso.', { label: 'Scollega', danger: true }))) return;
    this.run('forget', 'DELETE', '/garmin', 'Garmin scollegato');
  }

  private garminCard() {
    const g = this.garmin;
    if (!g) return html`<hxk-card heading="Garmin"><hxk-state kind="error" text="Stato non disponibile"></hxk-state></hxk-card>`;
    const days = (g.last_sync?.days || []).join(', ');
    return html`<hxk-card heading="Garmin" subtitle=${g.connected ? 'Collegato' : g.waiting_code ? 'Aspetto il codice' : 'Non collegato'}>
      <div class="small muted">Ogni mattina leggo dall'orologio il sonno (nel diario) e le attività (in Allenamento); se salti il
        check-in del mattino lo riempio io.</div>
      <dl>
        <dt>Stato</dt><dd><hxk-badge tone=${g.connected ? 'success' : g.waiting_code ? 'warning' : 'neutral'}>${g.connected ? 'collegato' : g.waiting_code ? 'serve il codice' : 'non collegato'}</hxk-badge></dd>
        <dt>Ultima lettura</dt><dd>${g.last_sync ? `${when(g.last_sync.at)}${days ? ` · ${days}` : ''}` : '–'}</dd>
        ${g.last_error ? html`<dt>Errore</dt><dd style="color:var(--danger)">${g.last_error}</dd>` : nothing}
      </dl>
      <div class="row wrap">
        ${g.connected ? html`
          <hxk-button icon="refresh" ?loading=${this.busy === 'sync'} @click=${() => this.run('sync', 'POST', '/garmin/sync', 'Letto', { days: 2 })}>Leggi adesso</hxk-button>
          ${g.tokens ? html`<hxk-button variant="ghost" icon="trash" ?loading=${this.busy === 'forget'} @click=${() => this.forget()}>Scollega</hxk-button>` : nothing}`
        : this.form ? nothing
        : html`<hxk-button variant="primary" icon="link" @click=${() => { this.form = g.waiting_code ? 'code' : 'login'; }}>${g.waiting_code ? 'Scrivi il codice' : 'Collega Garmin'}</hxk-button>`}
      </div>
      ${!g.connected && this.form ? this.garminForm() : nothing}
    </hxk-card>`;
  }

  private phoneCard() {
    const p = this.phone;
    if (!p) return html`<hxk-card heading="Telefono"><hxk-state kind="error" text="Stato non disponibile"></hxk-state></hxk-card>`;
    const l = p.last || {};
    const apps: string[] = p.apps || [];
    return html`<hxk-card heading="Telefono" subtitle=${p.configured ? (l.at ? `Ultimo segnale ${when(l.at)}` : 'Configurato, nessun segnale ancora') : 'Non configurato'}>
      <div class="small muted">Il telefono Android dice da solo se sei a casa e se è in carica; le notifiche delle app scelte
        (per esempio la banca) diventano spese da rivedere.</div>
      ${p.configured ? html`<dl>
        <dt>A casa</dt><dd>${l.home === true ? 'sì' : l.home === false ? 'no' : '–'}</dd>
        <dt>In carica</dt><dd>${l.charging === true ? 'sì' : l.charging === false ? 'no' : '–'}${l.battery !== undefined && l.battery !== null ? ` · batteria ${l.battery}%` : ''}</dd>
        <dt>Wi-Fi di casa</dt><dd>${p.home_wifi ? `${p.home_wifi} ${p.home_wifi === 1 ? 'rete' : 'reti'}` : 'nessuna: decide il telefono'}</dd>
        <dt>App</dt><dd>${apps.length ? apps.join(', ') : 'tutte quelle che il telefono manda'}</dd>
      </dl><div class="small muted">Reti e app si cambiano nelle impostazioni, gruppo Telefono.</div>`
      : html`<ol>
        <li>Nel file di configurazione del server metti il segreto del telefono (la guida di installazione dice dove).</li>
        <li>Su Tasker o MacroDroid crea un'azione HTTP POST verso <code>/api/gateway/phone/push</code> con l'intestazione
          <code>X-Hestia-Phone-Token</code>: quando cambia il Wi-Fi o la carica, e alle notifiche delle app che vuoi.</li>
        <li>Torna qui: vedrai l'ultimo segnale.</li></ol>`}
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>Dispositivi</h1><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.garmin && !this.phone) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>Dispositivi</h1><span class="sub">L'orologio e il telefono che mandano dati da soli</span></div>
      <div class="cols">${this.garminCard()}${this.phoneCard()}</div>
    </div>`;
  }
}
