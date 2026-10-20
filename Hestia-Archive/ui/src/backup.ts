/**
 * <archive-backup-panel> — Impostazioni → Sistema → Archive → «Backup»: state, history of the backups on Google
 * Drive, «Ripristina» on each one, «Annulla ripristino», «Esegui backup ora», «Verifica ora».
 * SPEC docs/work/2026-10-20-backup-drive §2. The texts name no module.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';

const API = '/api/backup';

const STEP: Record<string, string> = {
  start: 'inizio', dump: 'copia dei dati', encrypt: 'cifratura', upload: 'caricamento su Drive', retention: 'pulizia',
  download: 'scaricamento', decrypt: 'apertura', restore: 'ripristino in prova', migrate: 'aggiornamento',
  compare: 'controllo', swap: 'sostituzione dei dati',
};
const JOB: Record<string, string> = { backup: 'Backup', verify: 'Verifica', restore: 'Ripristino', undo: 'Annullamento' };

function when(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function size(n?: number): string {
  if (!n) return '–';
  return n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`;
}

export class ArchiveBackupPanel extends HestiaElement {
  static properties = { ...HestiaElement.properties, st: { state: true }, list: { state: true }, error: { state: true },
                        busy: { state: true } };
  declare st: any; declare list: any; declare error: string; declare busy: string;
  private timer = 0;

  static styles = [...HestiaElement.styles, css`
    :host { display: block; }
    .box { display: flex; flex-direction: column; gap: 12px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .grow { flex: 1; min-width: 0; }
    .muted { color: var(--text-3); }
    .small { font-size: 12.5px; }
    .note { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; border-radius: var(--radius-md, 8px);
            background: var(--surface-2); font-size: 13px; }
    .note[data-tone=danger] { background: color-mix(in srgb, var(--danger) 12%, transparent); }
    .note[data-tone=warning] { background: color-mix(in srgb, var(--warning) 14%, transparent); }
    .note[data-tone=success] { background: color-mix(in srgb, var(--success) 12%, transparent); }
    .item { display: flex; gap: 10px; align-items: center; padding: 9px 0; border-top: 1px solid var(--border); }
    .item:first-child { border-top: 0; }
    .t { font-weight: 550; }
    .tnum { font-variant-numeric: tabular-nums; }
    h4 { margin: 4px 0 0; font-size: 13px; font-weight: 600; color: var(--text-2); }
  `];

  constructor() { super(); this.st = null; this.list = null; this.error = ''; this.busy = ''; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
    this.addEventListener('retry', () => this.load());
  }

  disconnectedCallback() { super.disconnectedCallback(); window.clearTimeout(this.timer); }

  private async load(fresh = false) {
    const [s, l] = await Promise.all([this.host.api('GET', `${API}/status`, { query: fresh ? { fresh: true } : {} }),
                                      this.host.api('GET', `${API}/list`)]);
    if (!s.ok) { this.error = 'Backup non raggiungibile'; return; }
    this.error = ''; this.st = s.data; this.list = l.ok ? l.data : { items: [], pending: [], error: l.error };
    window.clearTimeout(this.timer);
    if (this.st.job) this.timer = window.setTimeout(() => this.load(), 2500);   // follow a job in progress
  }

  private async act(path: string, body: unknown, done: string) {
    this.busy = path;
    const r = await this.host.api('POST', `${API}/${path}`, { body });
    this.busy = '';
    if (!r.ok) { this.host.toast((r.data?.detail?.message) || r.error || 'Non riuscito', 'danger'); return; }
    this.host.toast(done, 'info');
    this.load();
  }

  private async connect() {
    this.busy = 'connect';
    const r = await this.host.api('POST', `${API}/drive/connect`, { body: {} });
    this.busy = '';
    if (!r.ok || !r.data?.ok || !r.data.auth_url) { this.host.toast(r.data?.message || 'Collegamento non disponibile', 'danger'); return; }
    window.open(r.data.auth_url, '_blank', 'noopener');
    this.host.toast(r.data.user_code ? `Codice: ${r.data.user_code}` : 'Concedi l\'accesso nella pagina di Google, poi torna qui', 'info');
    window.setTimeout(() => this.load(true), 20000);
  }

  private async restore(item: any) {
    const ok = await this.host.confirm('Ripristinare questo backup?',
      `I dati tornano al ${when(item.created_at)}. Tutto quello che è cambiato dopo viene sostituito. ` +
      'Puoi annullare finché non fai un altro ripristino.', { label: 'Ripristina', danger: true });
    if (ok) this.act('restore', { file_id: item.id, confirm: true }, 'Ripristino avviato');
  }

  private async undo() {
    const r = this.st?.last_restore;
    const text = r?.undone ? 'I dati tornano a quelli del backup ripristinato.' : 'I dati tornano com\'erano subito prima del ripristino.';
    const ok = await this.host.confirm(r?.undone ? 'Rifare il ripristino?' : 'Annullare il ripristino?', text,
      { label: r?.undone ? 'Rifai' : 'Annulla ripristino', danger: true });
    if (ok) this.act('undo', { confirm: true }, 'Fatto');
  }

  private notes() {
    const st = this.st, out = [];
    if (!st.passphrase_set) out.push(html`<div class="note" data-tone="danger"><hxk-icon name="alert" size="16" tone="danger"></hxk-icon>
      <span>Manca la passphrase dei backup: aggiungi <code>HESTIA_BACKUP_PASSPHRASE</code> al file .env e riavvia. Salvala anche in un
      password manager: senza, i backup non si aprono.</span></div>`);
    if (st.drive && !st.drive.connected || st.drive && st.drive.scope_ok === false) out.push(html`<div class="note" data-tone="warning">
      <hxk-icon name="unlock" size="16" tone="warning"></hxk-icon><span class="grow">Google Drive non collegato${st.drive.error ? html`: ${st.drive.error}` : nothing}.
      Ricollega Google concedendo l'accesso a Drive (vede solo i file che crea Hestia).</span>
      <hxk-button size="sm" icon="link" ?loading=${this.busy === 'connect'} @click=${() => this.connect()}>Collega Google Drive</hxk-button></div>`);
    if (st.problem) out.push(html`<div class="note" data-tone=${st.problem.code === 'drive' ? 'warning' : 'danger'}>
      <hxk-icon name="alert" size="16" tone=${st.problem.code === 'drive' ? 'warning' : 'danger'}></hxk-icon><span>${st.problem.text}</span></div>`);
    const r = st.last_restore;
    if (r && r.ok === false) out.push(html`<div class="note" data-tone="danger"><hxk-icon name="x" size="16" tone="danger"></hxk-icon>
      <span>Ultimo ripristino non riuscito (${when(r.at)}): ${r.error}. I dati non sono cambiati.</span></div>`);
    return out;
  }

  render() {
    if (this.error) return html`<hxk-state kind="offline" text=${this.error}></hxk-state>`;
    const st = this.st;
    if (!st) return html`<hxk-state kind="loading"></hxk-state>`;
    const last = st.last_backup, ver = st.last_verify, job = st.job, items = this.list?.items || [], pending = this.list?.pending || [];
    const r = st.last_restore;
    return html`<div class="box">
      ${this.notes()}
      ${job ? html`<div class="note"><hxk-icon name="hourglass" size="16"></hxk-icon>
        <span>${JOB[job.kind] || job.kind} in corso: ${STEP[job.step] || job.step}…</span></div>` : nothing}
      <div class="row">
        <div class="grow">
          <div class="t">${last ? html`Ultimo backup ${when(last.created_at)}` : 'Nessun backup ancora'}</div>
          <div class="small muted">
            ${last ? html`${size(last.size)} · ${last.uploaded ? 'su Google Drive' : 'in attesa di Drive'}` : nothing}
            ${ver ? html` · verifica ${ver.ok ? html`riuscita il ${when(ver.verified_at)}` : html`fallita il ${when(ver.verified_at)}`}` : nothing}
          </div>
        </div>
        <hxk-button icon="upload" ?loading=${this.busy === 'run'} ?disabled=${!!job || !st.passphrase_set}
          @click=${() => this.act('run', {}, 'Backup avviato')}>Esegui backup ora</hxk-button>
        <hxk-button variant="ghost" icon="check" ?loading=${this.busy === 'verify'} ?disabled=${!!job || !items.length}
          @click=${() => this.act('verify', {}, 'Verifica avviata')}>Verifica ora</hxk-button>
      </div>
      ${st.undo_available && r?.ok ? html`<div class="note" data-tone="success"><hxk-icon name="history" size="16" tone="success"></hxk-icon>
        <span class="grow">${r.undone ? html`Ripristino annullato il ${when(r.undo_at)}.` : html`Dati ripristinati al ${when(r.backup_created_at)} (il ${when(r.at)}).`}</span>
        <hxk-button size="sm" variant="ghost" icon="undo" ?disabled=${!!job} @click=${() => this.undo()}>${r.undone ? 'Rifai ripristino' : 'Annulla ripristino'}</hxk-button></div>` : nothing}
      <h4>Storico su Google Drive</h4>
      ${this.list?.error ? html`<div class="small muted">${this.list.error}</div>` : nothing}
      ${!items.length && !pending.length && !this.list?.error ? html`<div class="small muted">Ancora nessun backup su Drive.</div>` : nothing}
      <div>
        ${pending.map((p: any) => html`<div class="item"><hxk-icon name="clock" size="16" tone="warning"></hxk-icon>
          <div class="grow"><div class="tnum">${when(p.created_at)}</div><div class="small muted">${size(p.size)} · sul PC, in attesa di Drive</div></div></div>`)}
        ${items.map((it: any) => html`<div class="item">
          <hxk-icon name=${it.verify === 'ok' ? 'check-circle' : it.verify === 'fail' ? 'x-circle' : 'history'} size="16"
            tone=${it.verify === 'ok' ? 'success' : it.verify === 'fail' ? 'danger' : 'neutral'}></hxk-icon>
          <div class="grow"><div class="tnum">${when(it.created_at)}</div>
            <div class="small muted">${size(it.size)}${it.monthly ? ' · mensile' : ''}${it.verify === 'ok' ? html` · verificato il ${when(it.verified_at)}`
              : it.verify === 'fail' ? ' · verifica fallita' : ''}</div></div>
          <hxk-button size="sm" variant="ghost" icon="undo" ?disabled=${!!job || !st.passphrase_set} @click=${() => this.restore(it)}>Ripristina</hxk-button>
        </div>`)}
      </div>
      <div class="small muted">Ne tengo ${st.settings?.keep_daily ?? 3} recenti e ${st.settings?.keep_monthly ?? 3} mensili (impostazioni qui sopra).
        Orario e frequenza sono nell'agenda: «Backup» e «Verifica backup».</div>
    </div>`;
  }
}
