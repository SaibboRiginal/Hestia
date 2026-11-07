/**
 * <hecate-garmin> — «Garmin» card: connected or not; «Collega Garmin» opens the form right in the card (email and
 * password go straight to the login and are never stored, then the two-step code in the same card: no notification
 * to chase, the password never passes through the assistant), «Leggi adesso», «Scollega», last reading and error.
 * Used by the Dispositivi page and by the guided setup (plugin outlet). Calls /api/gateway/garmin/*.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/gateway';

function when(iso?: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  return isNaN(d.getTime()) ? '–' : d.toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export class HecateGarmin extends HestiaElement {
  static properties = { ...HestiaElement.properties, garmin: { state: true }, busy: { state: true },
                        form: { state: true }, formError: { state: true }, loaded: { state: true } };
  declare garmin: any; declare busy: string; declare loaded: boolean;
  /** The Garmin form in the card: '' closed, 'login' email + password, 'code' the two-step code. */
  declare form: '' | 'login' | 'code'; declare formError: string;
  private email = ''; private password = ''; private code = '';

  static styles = [...HestiaElement.styles, css`
    dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 8px 0; font-size: 13px; }
    dt { color: var(--text-3); }
    dd { margin: 0; overflow-wrap: anywhere; }
    .form { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
  `];

  constructor() { super(); this.garmin = null; this.busy = ''; this.form = ''; this.formError = ''; this.loaded = false; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const g = await this.host.api('GET', `${API}/garmin/status`);
    this.garmin = g.ok ? g.data : null;
    this.loaded = true;
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

  render() {
    if (!this.loaded) return html`<hxk-card heading="Garmin"><hxk-state kind="loading"></hxk-state></hxk-card>`;
    return this.garminCard();
  }
}
