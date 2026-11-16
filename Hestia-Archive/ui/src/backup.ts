/**
 * <archive-backup-panel> — Impostazioni → Sistema → Archive → «Backup»: state, history of the backups on Google
 * Drive, «Ripristina» on each one, «Annulla ripristino», «Esegui backup ora», «Verifica ora».
 * SPEC docs/work/2026-10-20-backup-drive §2. The texts name no module.
 */
import { HestiaElement, html, css, nothing, locale, tr } from '@hestia/webui-sdk';

const API = '/api/backup';

const STEP: Record<string, string> = {
  start: 'inizio', dump: tr('copy of the data'), encrypt: 'cifratura', upload: tr('uploading to Drive'), retention: 'pulizia',
  download: 'scaricamento', decrypt: 'apertura', restore: tr('restore on trial'), migrate: 'aggiornamento',
  compare: 'controllo', swap: tr('data replacement'),
};
const JOB: Record<string, string> = { backup: tr('Backup'), verify: tr('Check'), restore: tr('Restore'), undo: tr('Undo') };

function when(iso?: string | null): string {
  if (!iso) return '–';
  return new Date(iso).toLocaleString(locale(), { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
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
    if (!s.ok) { this.error = tr('Backup not reachable'); return; }
    this.error = ''; this.st = s.data; this.list = l.ok ? l.data : { items: [], pending: [], error: l.error };
    window.clearTimeout(this.timer);
    if (this.st.job) this.timer = window.setTimeout(() => this.load(), 2500);   // follow a job in progress
  }

  private async act(path: string, body: unknown, done: string) {
    this.busy = path;
    const r = await this.host.api('POST', `${API}/${path}`, { body });
    this.busy = '';
    if (!r.ok) { this.host.toast((r.data?.detail?.message) || r.error || tr('alt::Failed'), 'danger'); return; }
    this.host.toast(done, 'info');
    this.load();
  }

  private async connect() {
    this.busy = 'connect';
    const r = await this.host.api('POST', `${API}/drive/connect`, { body: {} });
    this.busy = '';
    if (!r.ok || !r.data?.ok || !r.data.auth_url) { this.host.toast(r.data?.message || tr('Link not available'), 'danger'); return; }
    window.open(r.data.auth_url, '_blank', 'noopener');
    this.host.toast(r.data.user_code ? `Codice: ${r.data.user_code}` : tr('Grant access on Google\'s page, then come back here'), 'info');
    window.setTimeout(() => this.load(true), 20000);
  }

  private async restore(item: any) {
    const ok = await this.host.confirm(tr('Restore this backup?'),
      tr("The data goes back to {0}. Everything that changed afterwards is replaced. ", when(item.created_at)) +
      tr('You can undo until you do another restore.'), { label: tr('f::Restore'), danger: true });
    if (ok) this.act('restore', { file_id: item.id, confirm: true }, tr('Restore started'));
  }

  private async undo() {
    const r = this.st?.last_restore;
    const text = r?.undone ? tr('The data goes back to that of the restored backup.') : tr('The data goes back to how it was right before the restore.');
    const ok = await this.host.confirm(r?.undone ? tr('Redo the restore?') : tr('Undo the restore?'), text,
      { label: r?.undone ? tr('Redo') : tr('Undo restore'), danger: true });
    if (ok) this.act('undo', { confirm: true }, tr('Done'));
  }

  private notes() {
    const st = this.st, out = [];
    if (!st.passphrase_set) out.push(html`<div class="note" data-tone="danger"><hxk-icon name="alert" size="16" tone="danger"></hxk-icon>
      <span>${tr("The backup passphrase is missing: add")} <code>HESTIA_BACKUP_PASSPHRASE</code> ${tr("to the .env file and restart. Save it in a password manager too: without it, backups cannot be opened.")}</span></div>`);
    if (st.drive && !st.drive.connected || st.drive && st.drive.scope_ok === false) out.push(html`<div class="note" data-tone="warning">
      <hxk-icon name="unlock" size="16" tone="warning"></hxk-icon><span class="grow">${tr("Google Drive not linked")}${st.drive.error ? html`: ${st.drive.error}` : nothing}${tr(". Link Google again granting access to Drive (it only sees the files Hestia creates).")}</span>
      <hxk-button size="sm" icon="link" ?loading=${this.busy === 'connect'} @click=${() => this.connect()}>${tr("Link Google Drive")}</hxk-button></div>`);
    if (st.problem) out.push(html`<div class="note" data-tone=${st.problem.code === 'drive' ? 'warning' : 'danger'}>
      <hxk-icon name="alert" size="16" tone=${st.problem.code === 'drive' ? 'warning' : 'danger'}></hxk-icon><span>${st.problem.text}</span></div>`);
    const r = st.last_restore;
    if (r && r.ok === false) out.push(html`<div class="note" data-tone="danger"><hxk-icon name="x" size="16" tone="danger"></hxk-icon>
      <span>${tr("Last restore failed (")}${when(r.at)}): ${r.error}${tr(". The data did not change.")}</span></div>`);
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
        <span>${JOB[job.kind] || job.kind} ${tr("running:")} ${STEP[job.step] || job.step}…</span></div>` : nothing}
      <div class="row">
        <div class="grow">
          <div class="t">${last ? html`${tr("Last backup")} ${when(last.created_at)}` : tr('No backup yet')}</div>
          <div class="small muted">
            ${last ? html`${size(last.size)} · ${last.uploaded ? tr('on Google Drive') : tr('waiting for Drive')}` : nothing}
            ${ver ? html` · ${tr("check")} ${ver.ok ? html`${tr("succeeded on")} ${when(ver.verified_at)}` : html`${tr("failed on")} ${when(ver.verified_at)}`}` : nothing}
          </div>
        </div>
        <hxk-button icon="upload" ?loading=${this.busy === 'run'} ?disabled=${!!job || !st.passphrase_set}
          @click=${() => this.act('run', {}, tr('Backup started'))}>${tr("Run backup now")}</hxk-button>
        <hxk-button variant="ghost" icon="check" ?loading=${this.busy === 'verify'} ?disabled=${!!job || !items.length}
          @click=${() => this.act('verify', {}, tr('Check started'))}>${tr("alt::Check now")}</hxk-button>
      </div>
      ${st.undo_available && r?.ok ? html`<div class="note" data-tone="success"><hxk-icon name="history" size="16" tone="success"></hxk-icon>
        <span class="grow">${r.undone ? html`${tr("Restore undone on")} ${when(r.undo_at)}.` : html`${tr("Data restored to")} ${when(r.backup_created_at)} ${tr("(the")} ${when(r.at)}).`}</span>
        <hxk-button size="sm" variant="ghost" icon="undo" ?disabled=${!!job} @click=${() => this.undo()}>${r.undone ? tr('Redo restore') : tr('Undo restore')}</hxk-button></div>` : nothing}
      <h4>${tr("History on Google Drive")}</h4>
      ${this.list?.error ? html`<div class="small muted">${this.list.error}</div>` : nothing}
      ${!items.length && !pending.length && !this.list?.error ? html`<div class="small muted">${tr("No backup on Drive yet.")}</div>` : nothing}
      <div>
        ${pending.map((p: any) => html`<div class="item"><hxk-icon name="clock" size="16" tone="warning"></hxk-icon>
          <div class="grow"><div class="tnum">${when(p.created_at)}</div><div class="small muted">${size(p.size)} ${tr("· on the PC, waiting for Drive")}</div></div></div>`)}
        ${items.map((it: any) => html`<div class="item">
          <hxk-icon name=${it.verify === 'ok' ? 'check-circle' : it.verify === 'fail' ? 'x-circle' : 'history'} size="16"
            tone=${it.verify === 'ok' ? 'success' : it.verify === 'fail' ? 'danger' : 'neutral'}></hxk-icon>
          <div class="grow"><div class="tnum">${when(it.created_at)}</div>
            <div class="small muted">${size(it.size)}${it.monthly ? ' · mensile' : ''}${it.verify === 'ok' ? html` ${tr("· verified on")} ${when(it.verified_at)}`
              : it.verify === 'fail' ? tr(' · check failed') : ''}</div></div>
          <hxk-button size="sm" variant="ghost" icon="undo" ?disabled=${!!job || !st.passphrase_set} @click=${() => this.restore(it)}>${tr("f::Restore")}</hxk-button>
        </div>`)}
      </div>
      <div class="small muted">${tr("I keep")} ${st.settings?.keep_daily ?? 3} ${tr("recent and")} ${st.settings?.keep_monthly ?? 3} ${tr("monthly (settings above). Time and frequency are in the agenda: «Backup» and «Backup check».")}</div>
    </div>`;
  }
}
