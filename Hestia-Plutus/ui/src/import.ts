/**
 * <plutus-import> — bank statement PDF (e.g. Hype «lista movimenti»): upload → preview (new / already there / linked to a
 *                   PayPal payment) → confirm; past imports can be undone. PayPal mails need nothing: they arrive alone.
 */
import { HestiaElement, html, nothing, plural, locale, tr } from '@hestia/webui-sdk';
import { API, call, dayLabel, meta, money, plutusStyles } from './util';

const STATE: Record<string, { text: string; cls: string }> = {
  new: { text: 'nuovo', cls: 'good' }, duplicate: { text: tr('already present'), cls: '' }, link: { text: tr('linked to PayPal'), cls: 'warn' },
};
const STATUS: Record<string, string> = { preview: tr('to confirm'), committed: 'importato', undone: 'annullato' };

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
      this.host.toast(tr("Imported {0}{1}", plural(r.data.added, 'transaction', 'transactions'), r.data.linked ? tr(', {0} linked to PayPal', r.data.linked) : ''), 'success',
        { label: tr('Cancel'), run: () => this.undo(r.data.id) });
      this.v = r.data; this.load();
    }
  }
  private async undo(id: string) {
    const r = await call(this.host, 'POST', `${API}/imports/${id}/undo`);
    if (r.ok) this.host.toast(tr("Removed {0}", plural(r.data.removed, 'transaction', 'transactions')), 'success');
    if (this.v?.id === id) this.open(id);
    this.load();
  }
  private preview() {
    const v = this.v;
    const cur = v.currency;
    const c = v.counts || {};
    return html`<div class="card col">
      <div class="between"><div><h2>${v.name}</h2><div class="small muted">${dayLabel(v.period[0])} → ${dayLabel(v.period[1])} · ${v.rows.length} ${tr("lines")}${v.how === 'oracle' ? tr(' · read with the AI') : ''}</div></div>
        <hxk-badge tone=${v.status === 'committed' ? 'success' : v.status === 'undone' ? 'neutral' : 'accent'}>${STATUS[v.status] || v.status}</hxk-badge></div>
      <div class="chips">${Object.entries(c).map(([k, n]) => html`<span class="pill ${STATE[k]?.cls || ''}">${n} ${STATE[k]?.text || k}</span>`)}
        <span class="pill">${tr("new expenses")} ${money(v.total_new_spent, cur)}</span></div>
      ${c.link ? html`<div class="note">${tr("Transactions «linked to PayPal» are payments that already arrived by email: I keep both but count them only once.")}</div>` : nothing}
      <div class="list" style="max-height:50vh;overflow:auto">${v.rows.map((r: any) => html`<div class="li" style="cursor:default">
        <span class="small muted tnum" style="min-width:64px">${dayLabel(r.date)}</span>
        <div class="grow"><div class="truncate">${r.merchant || r.description}</div><div class="small muted truncate">${r.description}</div></div>
        <span class="pill ${STATE[r.state]?.cls || ''}">${STATE[r.state]?.text || r.state}</span>
        <span class="tnum amt ${r.amount > 0 ? 'in' : ''}">${money(r.amount, cur, true)}</span></div>`)}</div>
      <div class="row wrap">
        ${v.status === 'preview' ? html`<hxk-button variant="primary" icon="check" ?loading=${this.busy === 'commit'} ?disabled=${!(c.new || c.link)}
          @click=${() => this.commit()}>${tr("Import")} ${plural((c.new || 0) + (c.link || 0), 'transaction', 'transactions')}</hxk-button>` : nothing}
        ${v.status === 'committed' ? html`<hxk-button variant="ghost" icon="undo" @click=${() => this.undo(v.id)}>${tr("Undo the import")}</hxk-button>` : nothing}
        <hxk-button variant="ghost" @click=${() => (this.v = null)}>${tr("Close")}</hxk-button></div>
    </div>`;
  }
  render() {
    const banks = (this.m?.accounts || []).filter((a: any) => a.kind === 'bank');
    return html`<div class="page">
      <div class="head"><button class="link" @click=${() => this.host.navigate('panoramica')}>${tr('‹ Expenses')}</button><h1>${tr("Import")}</h1></div>
      ${this.v ? this.preview() : html`<div class="card col">
        <h2>${tr("Bank statement (PDF)")}</h2>
        <div class="small muted">${tr("From the bank app download the transaction list as PDF (Hype: Transactions › Export) and upload it here, or send it in chat. You see the preview before confirming; uploading the same file twice adds nothing.")}</div>
        <div class="row wrap"><select class="in" @change=${(e: any) => (this.account = e.target.value)}>
            ${(banks.length ? banks : [{ id: 'hype', name: 'Hype' }]).map((a: any) => html`<option value=${a.id} ?selected=${a.id === this.account}>${a.name}</option>`)}</select>
          <hxk-button variant="primary" icon="upload" ?loading=${this.busy === 'preview'} @click=${() => this.pick()}>${tr("Choose the PDF")}</hxk-button></div></div>`}
      <div class="card col"><h2>${tr("PayPal emails")}</h2>
        <div class="small muted">${tr("They arrive by themselves: as soon as Gmail receives a PayPal receipt, Iris passes it to Expenses.")}
          ${this.mail?.last_run ? html`${tr("Last check")} ${new Date(this.mail.last_run).toLocaleString(locale(), { dateStyle: 'short', timeStyle: 'short' })}, ${this.mail.added} ${tr("recorded in total.")}` : nothing}</div>
        ${this.mail?.last_error ? html`<div class="note warning">${this.mail.last_error}</div>` : nothing}
        <div class="row wrap"><hxk-button icon="refresh" @click=${async () => { const r = await call(this.host, 'POST', `${API}/mail/check`, { body: { days: 30 } });
          if (r.ok) this.host.toast(tr('I go over the PayPal emails of the last 30 days'), 'info'); setTimeout(() => this.load(), 5000); }}>${tr("Go over the last 30 days")}</hxk-button>
          <hxk-button variant="ghost" icon="external" @click=${() => this.host.navigate('email', {}, 'iris')}>${tr("Email page")}</hxk-button></div></div>
      <h3>${tr("Imports done")}</h3>
      ${this.list === undefined ? html`<hxk-state kind="loading"></hxk-state>` : this.list === null ? html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`
        : !this.list.length ? html`<div class="empty">${tr("No statement yet.")}</div>` : html`<div class="card list">${this.list.map(i => html`<div class="li" @click=${() => this.open(i.id)}>
          <div class="grow"><div class="truncate"><b>${i.name}</b></div><div class="small muted">${i.period ? `${dayLabel(i.period[0])} → ${dayLabel(i.period[1])}` : ''} · ${i.source === 'chat' ? tr('from the chat') : tr('uploaded here')}${i.added !== undefined ? tr(' · {0} added', i.added) : ''}</div></div>
          <hxk-badge tone=${i.status === 'committed' ? 'success' : i.status === 'undone' ? 'neutral' : 'accent'}>${STATUS[i.status] || i.status}</hxk-badge></div>`)}</div>`}
    </div>`;
  }
}
