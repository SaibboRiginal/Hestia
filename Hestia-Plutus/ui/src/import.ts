/**
 * <plutus-import> — bank statement PDF (e.g. Hype «lista movimenti»): upload → preview (new / already there / linked to a
 *                   PayPal payment) → confirm; past imports can be undone. PayPal mails need nothing: they arrive alone.
 */
import { HestiaElement, html, nothing } from '@hestia/webui-sdk';
import { API, call, dayLabel, meta, money, plutusStyles } from './util';

const STATE: Record<string, { text: string; cls: string }> = {
  new: { text: 'nuovo', cls: 'good' }, duplicate: { text: 'già presente', cls: '' }, link: { text: 'collegato a PayPal', cls: 'warn' },
};
const STATUS: Record<string, string> = { preview: 'da confermare', committed: 'importato', undone: 'annullato' };

export class PlutusImport extends HestiaElement {
  static properties = { ...HestiaElement.properties, list: { state: true }, mail: { state: true }, v: { state: true }, busy: { state: true },
    account: { state: true }, m: { state: true } };
  declare list: any[] | null | undefined;
  declare mail: any;
  declare v: any;
  declare busy: string;
  declare account: string;
  declare m: any;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.list = undefined; this.mail = null; this.v = null; this.busy = ''; this.account = 'hype'; this.m = null; }
  connectedCallback() {
    super.connectedCallback();
    this.load();
    if (this.ctx?.query?.id) this.open(this.ctx.query.id);
    this.onHost('refresh', () => this.load());
  }
  private async load() {
    this.m = await meta(this.host);
    const r = await this.host.api('GET', `${API}/imports`);
    this.list = r.ok ? r.data.items : null;
    this.mail = r.ok ? r.data.mail : null;
  }
  private async open(id: string) { const r = await this.host.api('GET', `${API}/imports/${id}`); if (r.ok) this.v = r.data; }
  private async pick() {
    const files = await this.host.upload({ accept: 'application/pdf' });
    if (!files.length) return;
    const f = files[0];
    this.busy = 'preview';
    const r = await call(this.host, 'POST', `${API}/imports`, { body: { name: f.name, mime: f.mime, data_b64: f.data_b64, account: this.account } });
    this.busy = '';
    if (r.ok) { this.v = r.data; this.load(); }
  }
  private async commit() {
    this.busy = 'commit';
    const r = await call(this.host, 'POST', `${API}/imports/${this.v.id}/commit`);
    this.busy = '';
    if (r.ok) {
      this.host.toast(`Importati ${r.data.added} movimenti${r.data.linked ? `, ${r.data.linked} collegati a PayPal` : ''}`, 'success',
        { label: 'Annulla', run: () => this.undo(r.data.id) });
      this.v = r.data; this.load();
    }
  }
  private async undo(id: string) {
    const r = await call(this.host, 'POST', `${API}/imports/${id}/undo`);
    if (r.ok) this.host.toast(`Tolti ${r.data.removed} movimenti`, 'success');
    if (this.v?.id === id) this.open(id);
    this.load();
  }
  private preview() {
    const v = this.v;
    const cur = v.currency;
    const c = v.counts || {};
    return html`<div class="card col">
      <div class="between"><div><h2>${v.name}</h2><div class="small muted">${dayLabel(v.period[0])} → ${dayLabel(v.period[1])} · ${v.rows.length} righe${v.how === 'oracle' ? ' · lette con l\'AI' : ''}</div></div>
        <hxk-badge tone=${v.status === 'committed' ? 'success' : v.status === 'undone' ? 'neutral' : 'accent'}>${STATUS[v.status] || v.status}</hxk-badge></div>
      <div class="chips">${Object.entries(c).map(([k, n]) => html`<span class="pill ${STATE[k]?.cls || ''}">${n} ${STATE[k]?.text || k}</span>`)}
        <span class="pill">spese nuove ${money(v.total_new_spent, cur)}</span></div>
      ${c.link ? html`<div class="note">I movimenti «collegati a PayPal» sono pagamenti già arrivati per email: li tengo entrambi ma li conto una volta sola.</div>` : nothing}
      <div class="list" style="max-height:50vh;overflow:auto">${v.rows.map((r: any) => html`<div class="li" style="cursor:default">
        <span class="small muted tnum" style="min-width:64px">${dayLabel(r.date)}</span>
        <div class="grow"><div class="truncate">${r.merchant || r.description}</div><div class="small muted truncate">${r.description}</div></div>
        <span class="pill ${STATE[r.state]?.cls || ''}">${STATE[r.state]?.text || r.state}</span>
        <span class="tnum amt ${r.amount > 0 ? 'in' : ''}">${money(r.amount, cur, true)}</span></div>`)}</div>
      <div class="row wrap">
        ${v.status === 'preview' ? html`<hxk-button variant="primary" icon="check" ?loading=${this.busy === 'commit'} ?disabled=${!(c.new || c.link)}
          @click=${() => this.commit()}>Importa ${(c.new || 0) + (c.link || 0)} movimenti</hxk-button>` : nothing}
        ${v.status === 'committed' ? html`<hxk-button variant="ghost" icon="undo" @click=${() => this.undo(v.id)}>Annulla l'import</hxk-button>` : nothing}
        <hxk-button variant="ghost" @click=${() => (this.v = null)}>Chiudi</hxk-button></div>
    </div>`;
  }
  render() {
    const banks = (this.m?.accounts || []).filter((a: any) => a.kind === 'bank');
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>‹ Spese</button><h1>Importa</h1></div>
      ${this.v ? this.preview() : html`<div class="card col">
        <h2>Estratto conto (PDF)</h2>
        <div class="small muted">Dall'app della banca scarica la lista movimenti in PDF (Hype: Movimenti › Esporta) e caricala qui,
          oppure mandala in chat. Vedi l'anteprima prima di confermare; caricare due volte lo stesso file non aggiunge niente.</div>
        <div class="row wrap"><select class="in" @change=${(e: any) => (this.account = e.target.value)}>
            ${(banks.length ? banks : [{ id: 'hype', name: 'Hype' }]).map((a: any) => html`<option value=${a.id} ?selected=${a.id === this.account}>${a.name}</option>`)}</select>
          <hxk-button variant="primary" icon="upload" ?loading=${this.busy === 'preview'} @click=${() => this.pick()}>Scegli il PDF</hxk-button></div></div>`}
      <div class="card col"><h2>Email PayPal</h2>
        <div class="small muted">Arrivano da sole: appena Gmail riceve una ricevuta PayPal, Iris la passa a Spese.
          ${this.mail?.last_run ? html`Ultimo controllo ${new Date(this.mail.last_run).toLocaleString('it-IT', { dateStyle: 'short', timeStyle: 'short' })}, ${this.mail.added} registrate in tutto.` : nothing}</div>
        ${this.mail?.last_error ? html`<div class="note warning">${this.mail.last_error}</div>` : nothing}
        <div class="row wrap"><hxk-button icon="refresh" @click=${async () => { const r = await call(this.host, 'POST', `${API}/mail/check`, { body: { days: 30 } });
          if (r.ok) this.host.toast('Ripasso le email PayPal degli ultimi 30 giorni', 'info'); setTimeout(() => this.load(), 5000); }}>Ripassa gli ultimi 30 giorni</hxk-button>
          <hxk-button variant="ghost" icon="external" @click=${() => this.host.navigate('email', {}, 'iris')}>Pagina Email</hxk-button></div></div>
      <h3>Import fatti</h3>
      ${this.list === undefined ? html`<hxk-state kind="loading"></hxk-state>` : this.list === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`
        : !this.list.length ? html`<div class="empty">Nessun estratto ancora.</div>` : html`<div class="card list">${this.list.map(i => html`<div class="li" @click=${() => this.open(i.id)}>
          <div class="grow"><div class="truncate"><b>${i.name}</b></div><div class="small muted">${i.period ? `${dayLabel(i.period[0])} → ${dayLabel(i.period[1])}` : ''} · ${i.source === 'chat' ? 'dalla chat' : 'caricato qui'}${i.added !== undefined ? ` · ${i.added} aggiunti` : ''}</div></div>
          <hxk-badge tone=${i.status === 'committed' ? 'success' : i.status === 'undone' ? 'neutral' : 'accent'}>${STATUS[i.status] || i.status}</hxk-badge></div>`)}</div>`}
    </div>`;
  }
}
