/**
 * <hecate-devices> — «Dispositivi»: Garmin (connected or not, «Collega» sends the secret form so the password never
 * passes through the assistant, «Leggi adesso», «Scollega», last reading and error) and the Android phone as a
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
                        error: { state: true }, busy: { state: true } };
  declare garmin: any; declare phone: any; declare error: string; declare busy: string;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); align-items: start; }
    dl { display: grid; grid-template-columns: auto 1fr; gap: 4px 12px; margin: 8px 0; font-size: 13px; }
    dt { color: var(--text-3); }
    dd { margin: 0; overflow-wrap: anywhere; }
    code { font-family: var(--font-mono); font-size: 12px; background: var(--surface-2); padding: 1px 4px; border-radius: var(--radius-sm); }
    ol { margin: 6px 0 0 18px; padding: 0; font-size: 13px; color: var(--text-2); }
  `];

  constructor() { super(); this.garmin = null; this.phone = null; this.error = ''; this.busy = ''; }

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
        : html`<hxk-button variant="primary" icon="link" ?loading=${this.busy === 'connect'} @click=${() => this.run('connect', 'POST', '/garmin/connect', 'Ti ho mandato il modulo')}>Collega Garmin</hxk-button>`}
      </div>
      ${g.connected ? nothing : html`<div class="small muted" style="margin-top:8px">Ti arriva un modulo tra le notifiche: email e password vanno
        direttamente al collegamento e non vengono salvate (resta solo l'accesso di Garmin).</div>`}
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
