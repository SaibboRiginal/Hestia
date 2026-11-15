/**
 * <plutus-overview> — the budget month: spent vs budget and pace, categories, latest movements, payments coming,
 *                     what needs a look (to review, PayPal check, statement import).
 */
import { HestiaElement, html, nothing, plural, tr } from '@hestia/webui-sdk';
import { API, PERIOD, addMonths, budgetBar, call, dayLabel, meta, money, plutusStyles, txRow } from './util';

export class PlutusOverview extends HestiaElement {
  static properties = { ...HestiaElement.properties, s: { state: true }, latest: { state: true }, m: { state: true }, month: { state: true },
    form: { state: true }, checking: { state: true } };
  declare s: any;
  declare latest: any[];
  declare m: any;
  declare month: string;
  declare form: boolean;
  declare checking: boolean;
  static styles = [...HestiaElement.styles, plutusStyles];
  constructor() { super(); this.s = undefined; this.latest = []; this.m = null; this.month = ''; this.form = false; this.checking = false; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private async load() {
    this.m = await meta(this.host);
    const q = this.month ? { month: this.month } : {};
    const [s, t] = await Promise.all([this.host.api('GET', `${API}/summary`, { query: q }),
      this.host.api('GET', `${API}/transactions`, { query: { ...q, month: this.month || this.m?.month || '', limit: 8 } })]);
    this.s = s.ok ? s.data : null;
    this.latest = t.ok ? t.data.items : [];
    if (s.ok && !this.month) this.month = s.data.month;
  }
  private shift(n: number) { this.month = addMonths(this.month, n); this.s = undefined; this.load(); }
  private async checkMail() {
    this.checking = true;
    const r = await call(this.host, 'POST', `${API}/mail/check`, { body: { days: 7 } });
    this.checking = false;
    if (r.ok) this.host.toast(tr('Ricontrollo le email PayPal degli ultimi 7 giorni'), 'info');
    setTimeout(() => this.load(), 4000);
  }
  render() {
    const s = this.s;
    if (s === undefined) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    if (s === null) return html`<div class="page"><hxk-state kind="offline" @retry=${() => this.load()}></hxk-state></div>`;
    const cur = s.currency;
    const pct = s.budget ? Math.round(100 * s.spent / s.budget) : null;
    const running = s.days_gone < s.days_total;
    return html`<div class="page">
      <div class="between wrap"><div class="head"><h1>${tr("Spese")}</h1>
          <hxk-button size="sm" variant="ghost" icon="chevron-left" @click=${() => this.shift(-1)}></hxk-button>
          <b>${s.label}</b><hxk-button size="sm" variant="ghost" icon="chevron-right" @click=${() => this.shift(1)}></hxk-button></div>
        <div class="row wrap"><hxk-button variant="primary" icon="plus" @click=${() => (this.form = true)}>${tr("Spesa")}</hxk-button>
          <hxk-button icon="upload" @click=${() => this.host.navigate('importa')}>${tr("Estratto conto")}</hxk-button></div></div>
      ${s.to_review ? html`<div class="note warning between click" @click=${() => this.host.navigate('movimenti', { rivedere: '1' })}>
        <span>${plural(s.to_review, 'movimento', 'movimenti')} ${tr("con la categoria da controllare")}</span><span class="link">${tr("Rivedi ›")}</span></div>` : nothing}
      <hxk-stat .items=${[
        { label: tr('Speso'), value: money(s.spent, cur), hint: s.linked ? tr("{0} collegati contati una volta", plural(s.linked, 'movimento', 'movimenti')) : '' },
        { label: tr('Entrate'), value: money(s.income, cur) },
        s.budget ? { label: tr('Rimane'), value: money(s.left, cur), tone: s.left < 0 ? 'danger' : 'success', delta: tr("{0}% del budget", pct) }
          : { label: tr('Budget'), value: '–', hint: tr('Imposta un budget nella pagina Budget') },
        running && s.spent ? { label: tr('A questo ritmo'), value: money(s.pace, cur), hint: tr("giorno {0} di {1}", s.days_gone, s.days_total),
          tone: s.budget && s.pace > s.budget ? 'danger' : 'neutral', delta: s.budget && s.pace > s.budget ? tr('sopra il budget') : '' }
          : { label: tr('Saldo'), value: money(s.net, cur, true) }]}></hxk-stat>
      ${s.budget ? html`<div class="card col"><div class="between"><span class="small muted">${tr("Budget del mese")}</span>
        <span class="small tnum">${money(s.spent, cur)} / ${money(s.budget, cur)}</span></div>${budgetBar(pct)}</div>` : nothing}
      <div class="card col"><div class="between"><h2>${tr("Categorie")}</h2><button class="link" @click=${() => this.host.navigate('budget')}>${tr("Budget ›")}</button></div>
        ${s.categories.length ? html`<div class="list">${s.categories.map((c: any, i: number) => html`<div class="li" @click=${() => this.host.navigate('movimenti', { categoria: c.id, mese: s.month })}>
          <span class="dot" style="background:var(--cal-${(i % 8) + 1})" title=${tr("stesso colore del grafico")}></span><div class="grow col" style="gap:4px"><div class="between"><span class="truncate">${c.label}</span>
            <span class="tnum small">${money(c.spent, cur)}${c.budget ? html`<span class="muted"> / ${money(c.budget, cur)}</span>` : nothing}</span></div>
            ${budgetBar(c.pct)}</div></div>`)}</div>` : html`<div class="empty">${tr("Nessuna spesa in questo mese.")}</div>`}
      </div>
      ${s.categories.length > 1 ? html`<div class="card col"><h2>${tr("Dove vanno i soldi")}</h2>
        <hxk-chart type="donut" height="180" unit=${cur === 'EUR' ? '€' : cur} .labels=${s.categories.map((c: any) => c.label)}
          .series=${[{ name: tr('Speso'), values: s.categories.map((c: any) => c.spent) }]}></hxk-chart></div>` : nothing}
      <div class="card col"><div class="between"><h2>${tr("Ultimi movimenti")}</h2><button class="link" @click=${() => this.host.navigate('movimenti', { mese: s.month })}>${tr("Tutti ›")}</button></div>
        ${this.latest.length ? html`<div class="list">${this.latest.map(t => txRow(this.host, t, cur))}</div>` : html`<div class="empty">${tr("Ancora niente: le email PayPal arrivano da sole, il resto lo aggiungi qui o in chat.")}</div>`}</div>
      ${s.recurring_next.length ? html`<div class="card col"><div class="between"><h2>${tr("In arrivo")}</h2><button class="link" @click=${() => this.host.navigate('abbonamenti')}>${tr("Abbonamenti ›")}</button></div>
        <div class="list">${s.recurring_next.map((r: any) => html`<div class="li" @click=${() => this.host.navigate('abbonamenti')}>
          <div class="grow"><b>${r.merchant}</b><div class="small muted">${PERIOD[r.period] || r.period} · ${dayLabel(r.next)}</div></div>
          <span class="tnum amt">${money(-r.amount, cur, true)}</span></div>`)}</div></div>` : nothing}
      ${s.top_merchants.length ? html`<div class="card col"><h2>${tr("Esercenti principali")}</h2>
        ${s.top_merchants.map((x: any) => html`<div class="between small" style="padding:3px 0"><span class="truncate">${x.merchant}</span><span class="tnum">${money(x.spent, cur)}</span></div>`)}</div>` : nothing}
      <div class="row wrap"><hxk-button variant="ghost" icon="refresh" ?loading=${this.checking} @click=${() => this.checkMail()}>${tr("Ricontrolla email PayPal")}</hxk-button>
        <hxk-button variant="ghost" icon="chart" @click=${() => this.host.navigate('statistiche')}>${tr("Statistiche")}</hxk-button>
        <hxk-button variant="ghost" icon="sparkle" @click=${() => this.host.assistant({ label: tr("Spese di {0}", s.label), hints: { month: s.month },
          suggestions: [tr('Com\'è andato il mese?'), tr('Dove posso risparmiare?'), tr('Quanto ho speso al ristorante?')] })}>${tr("Chiedi")}</hxk-button></div>
      ${this.form ? html`<plutus-tx-form .host=${this.host} @close=${() => { this.form = false; this.load(); }}></plutus-tx-form>` : nothing}
    </div>`;
  }
}
