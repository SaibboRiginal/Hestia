/**
 * <hecate-google> — «Google» card: Calendar, Gmail and the backup folder on Drive, connected by hand from the page
 * (no chat needed). One card, used by the Dispositivi page and by the guided setup (screen «Calendario, mail e
 * dispositivi», mounted through the plugin outlet), so the two never differ.
 *
 * Steps: 1. the OAuth client of Google Cloud (id + secret, or the downloaded JSON; kept by Hecate, never shown again);
 * 2. «Collega Google» opens Google's consent page in a new tab and the card waits; when Google can come back here by
 * itself (a public address, or the browser on the computer running Hestia) it completes alone, otherwise the user
 * pastes the address of the last page (or only the code). Calls /api/gateway/auth/google[/client],
 * /api/gateway/auth/initiate|poll|complete/google. Dossier 2026-10-30-setup-un-click, round 6.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/gateway/auth';
const CONSOLE = 'https://console.cloud.google.com/apis/credentials';

export class HecateGoogle extends HestiaElement {
  static properties = { ...HestiaElement.properties, st: { state: true }, busy: { state: true }, err: { state: true },
                        editClient: { state: true }, waiting: { state: true }, paste: { state: true } };
  declare st: any; declare busy: string; declare err: string; declare editClient: boolean;
  /** Google's page is open in another tab: the card polls until the account is linked. */
  declare waiting: boolean;
  /** Show the «paste the address» box (the return page does not load on a phone without a public address). */
  declare paste: boolean;
  private clientId = ''; private clientSecret = ''; private clientJson = ''; private code = '';
  private timer: ReturnType<typeof setInterval> | null = null;

  static styles = [...HestiaElement.styles, css`
    .form { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
    ol { margin: 6px 0 0 18px; padding: 0; font-size: 13px; color: var(--text-2); line-height: 1.5; }
    code { font-family: var(--font-mono); font-size: 12px; background: var(--surface-2); padding: 1px 4px; border-radius: var(--radius-sm); overflow-wrap: anywhere; }
    a { color: var(--accent); }
  `];

  constructor() { super(); this.st = null; this.busy = ''; this.err = ''; this.editClient = false; this.waiting = false; this.paste = false; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  disconnectedCallback() { super.disconnectedCallback(); this.stop(); }

  private async load() {
    const r = await this.host.api('GET', `${API}/google`);
    if (!r.ok) { this.err = r.status === 0 ? 'Non raggiungibile' : r.error || 'Non raggiungibile'; return; }
    this.err = '';
    this.st = r.data;
    if (this.st.linked) { this.stop(); this.waiting = false; this.paste = false; }
  }

  private stop() { if (this.timer) { clearInterval(this.timer); this.timer = null; } }

  private async saveClient() {
    this.busy = 'client';
    const r = await this.host.api('POST', `${API}/google/client`,
      { body: { client_id: this.clientId.trim(), client_secret: this.clientSecret.trim(), json: this.clientJson.trim() } });
    this.busy = '';
    this.clientSecret = '';
    this.clientJson = '';
    if (!r.ok) { this.host.toast(r.data?.detail || r.error || 'Non salvato', 'warning'); return; }
    this.editClient = false;
    this.clientId = '';
    this.host.toast('Client salvato', 'success');
    await this.load();
  }

  /** Open Google's consent page and wait here; the account shows as linked as soon as Google answers. */
  private async connect() {
    this.busy = 'connect';
    const r = await this.host.api('POST', `${API}/initiate/google`);
    this.busy = '';
    const url = r.data?.auth_url;
    if (!r.ok || !url) { this.host.toast(r.data?.detail?.error || r.data?.detail || r.error || 'Google non risponde', 'warning'); return; }
    window.open(url, '_blank', 'noopener');
    this.waiting = true;
    this.paste = !r.data?.public_redirect && !['localhost', '127.0.0.1'].includes(location.hostname);
    this.stop();
    let left = 120;   // ~10 minutes, then the card stops asking (the link lasts 15)
    this.timer = setInterval(async () => {
      if (--left <= 0) { this.stop(); return; }
      const p = await this.host.api('GET', `${API}/poll/google`);
      if (p.ok && p.data?.status === 'authorized') { this.host.toast('Google collegato', 'success'); await this.load(); }
    }, 5000);
  }

  private async complete() {
    if (!this.code.trim()) return;
    this.busy = 'complete';
    const r = await this.host.api('POST', `${API}/complete/google`, { body: { code: this.code.trim() } });
    this.busy = '';
    this.code = '';
    if (!r.ok) { this.host.toast(r.data?.detail?.error || r.data?.detail || r.error || 'Google non ha accettato il codice', 'warning'); return; }
    this.host.toast('Google collegato', 'success');
    await this.load();
  }

  private async cancel() {
    this.stop();
    this.waiting = false;
    this.paste = false;
    await this.host.api('DELETE', `${API}/initiate/google`);
    await this.load();
  }

  private clientForm() {
    return html`<div class="form">
      <ol>
        <li>Apri <a href=${CONSOLE} target="_blank" rel="noopener">Google Cloud, Credenziali</a> (gratis) e crea un progetto se non ne hai uno.</li>
        <li>Attiva Google Calendar API, Gmail API e Google Drive API.</li>
        <li>«Crea credenziali» → «ID client OAuth» → tipo <b>App desktop</b>.</li>
        <li>Copia qui l'ID client e il segreto (oppure incolla il file JSON che fa scaricare).</li>
      </ol>
      <hxk-field label="ID client" placeholder="…apps.googleusercontent.com" .value=${this.clientId} @change=${(e: CustomEvent) => { this.clientId = String(e.detail); }}></hxk-field>
      <hxk-field label="Segreto del client" type="password" .value=${this.clientSecret} @change=${(e: CustomEvent) => { this.clientSecret = String(e.detail); }}></hxk-field>
      <hxk-field label="Oppure il file JSON" type="textarea" .value=${this.clientJson} @change=${(e: CustomEvent) => { this.clientJson = String(e.detail); }}></hxk-field>
      <div class="row wrap">
        <hxk-button variant="primary" icon="check" ?loading=${this.busy === 'client'} @click=${() => this.saveClient()}>Salva</hxk-button>
        ${this.st?.client_set ? html`<hxk-button variant="ghost" @click=${() => { this.editClient = false; }}>Annulla</hxk-button>` : nothing}
      </div>
    </div>`;
  }

  render() {
    if (this.err) return html`<hxk-card heading="Google"><hxk-state kind="offline" text=${this.err} @retry=${() => this.load()}></hxk-state></hxk-card>`;
    const s = this.st;
    if (!s) return html`<hxk-card heading="Google"><hxk-state kind="loading"></hxk-state></hxk-card>`;
    const sub = s.linked ? 'Collegato' : this.waiting ? 'Aspetto Google' : s.client_set ? 'Non collegato' : 'Da preparare';
    return html`<hxk-card heading="Google" subtitle=${sub}>
      <div class="small muted">Calendario e Gmail (leggo e mando le mail che mi chiedi), più una cartella su Drive solo per i backup.</div>
      ${s.linked ? html`<div class="row wrap">
          <hxk-badge tone="success">collegato</hxk-badge>
          <hxk-button variant="ghost" icon="refresh" ?loading=${this.busy === 'connect'} @click=${() => this.connect()}>Collega di nuovo</hxk-button>
        </div>`
      : !s.client_set || this.editClient ? this.clientForm()
      : this.waiting ? html`<div class="form">
          <div class="small">Ho aperto la pagina di Google in un'altra scheda: scegli l'account e concedi l'accesso. Qui si aggiorna da solo.</div>
          ${this.paste ? html`<div class="small muted">Se alla fine la pagina non si apre (succede dal telefono), copia l'indirizzo dalla barra e incollalo qui.</div>
            <hxk-field label="Indirizzo dell'ultima pagina (o solo il codice)" .value=${this.code} @change=${(e: CustomEvent) => { this.code = String(e.detail); }}></hxk-field>
            <div class="row wrap"><hxk-button variant="primary" icon="check" ?loading=${this.busy === 'complete'} @click=${() => this.complete()}>Conferma</hxk-button></div>`
          : html`<button class="small" style="background:none;border:0;color:var(--accent);padding:0;text-align:left" @click=${() => { this.paste = true; }}>La pagina finale non si apre?</button>`}
          <div class="row wrap"><hxk-button variant="ghost" icon="x" @click=${() => this.cancel()}>Annulla</hxk-button></div>
        </div>`
      : html`<div class="row wrap">
          <hxk-button variant="primary" icon="link" ?loading=${this.busy === 'connect'} @click=${() => this.connect()}>Collega Google</hxk-button>
          <hxk-button variant="ghost" @click=${() => { this.editClient = true; }}>Cambia client</hxk-button>
        </div>
        ${s.error && !s.error.startsWith('Google not authorized') ? html`<div class="small" style="color:var(--danger)">${s.error}</div>` : nothing}`}
    </hxk-card>`;
  }
}
