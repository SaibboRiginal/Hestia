/**
 * <chronos-special> — «Eventi speciali»: birthdays, anniversaries and the dates that matter, with how many days
 * before the notice comes; who added them (you, Persone, a proposal you confirmed). Your birthday comes from the
 * personal settings. Reads GET /api/agenda/special; POST /api/agenda/special; DELETE /api/agenda/special/{key}.
 * Dossier 2026-10-24-tutto-brainstorm-cindy B6 (W2) + W7.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API } from './util';

const KINDS = [{ value: 'birthday', label: 'Compleanno' }, { value: 'anniversary', label: 'Anniversario' },
               { value: 'custom', label: 'Evento importante' }];
const ICON: Record<string, string> = { birthday: 'star', anniversary: 'heart', custom: 'event' };
const SOURCE: Record<string, string> = { utente: '', persone: 'da Persone', "proposta dell'assistente": 'proposto e confermato',
                                         'impostazioni personali': 'dalle impostazioni personali' };

function dayLabel(iso?: string | null): string {
  if (!iso) return '';
  return new Date(`${iso}T12:00:00`).toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric', month: 'long' });
}

function inDays(n: number | null): string {
  if (n === null || n === undefined) return 'passato';
  return n === 0 ? 'oggi' : n === 1 ? 'domani' : `tra ${n} giorni`;
}

export class ChronosSpecial extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, error: { state: true },
                        busy: { state: true }, form: { state: true } };
  declare items: any[] | null; declare error: string; declare busy: string; declare form: any;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .r { display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .r:first-child { border-top: 0; }
    .r hxk-icon { flex: none; margin-top: 2px; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    h2 { font-size: 15px; margin: 0; }
  `];

  constructor() { super(); this.items = null; this.error = ''; this.busy = ''; this.form = null; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const r = await this.host.api('GET', `${API}/special`);
    if (!r.ok) { this.error = r.status === 0 ? 'Calendario non raggiungibile' : r.error || 'Calendario non raggiungibile'; return; }
    this.error = '';
    this.items = r.data?.items || [];
  }

  private set(k: string, v: unknown) { this.form = { ...this.form, [k]: v }; }

  private async add() {
    const f = this.form;
    if (!f.title.trim() || !f.day) { this.host.toast('Servono il nome e il giorno', 'warning'); return; }
    this.busy = 'add';
    const r = await this.host.api('POST', `${API}/special`, { body: {
      title: f.title.trim(), day: f.day, kind: f.kind, lead_days: Number(f.lead_days) || 0, person: f.person.trim(),
      note: f.note.trim(), yearly: !!f.yearly } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non salvato', 'danger'); return; }
    this.host.toast(`${f.title.trim()}: nel calendario`, 'success');
    this.form = null;
    this.load();
  }

  private async dropEvent(s: any) {
    if (!(await this.host.confirm('Togliere l\'evento?', `«${s.title}» non avrà più avvisi.`, { label: 'Togli', danger: true }))) return;
    this.busy = s.key;
    const r = await this.host.api('DELETE', `${API}/special/${encodeURIComponent(s.key)}`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non tolto', 'danger'); return; }
    this.host.toast(`${s.title}: tolto`, 'success');
    this.load();
  }

  private row(s: any) {
    const src = SOURCE[s.source] ?? '';
    return html`<div class="r">
      <hxk-icon name=${ICON[s.kind] || 'event'} tone=${s.in_days === 0 ? 'success' : 'accent'} size="16"></hxk-icon>
      <div class="grow col" style="gap:3px">
        <div class="row wrap"><span class="t">${s.title}</span>
          <hxk-badge tone=${s.in_days === 0 ? 'success' : s.in_days !== null && s.in_days <= s.lead_days ? 'warning' : 'neutral'}>${inDays(s.in_days)}</hxk-badge></div>
        <div class="small muted">${s.kind_label}${s.person ? ` · ${s.person}` : ''} · ${dayLabel(s.next)}${s.yearly ? ' · ogni anno' : ''}
          · ${s.lead_days ? `avviso ${s.lead_days} giorni prima` : 'avviso solo il giorno'}${src ? ` · ${src}` : ''}</div>
        ${s.note ? html`<div class="small muted">${s.note}</div>` : nothing}
      </div>
      ${s.source === 'impostazioni personali' ? nothing
        : html`<hxk-button size="sm" variant="ghost" icon="trash" ?loading=${this.busy === s.key} @click=${() => this.dropEvent(s)}>Togli</hxk-button>`}
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>Eventi speciali</h1><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.items) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const f = this.form;
    return html`<div class="page">
      <div class="head"><h1>Eventi speciali</h1><span class="sub">Compleanni, anniversari e le date che contano, con l'avviso qualche giorno prima</span>
        <span class="grow"></span><hxk-button icon="plus" @click=${() => (this.form = { title: '', day: '', kind: 'birthday', lead_days: 3, person: '', note: '', yearly: true })}>Aggiungi</hxk-button></div>
      ${f ? html`<div class="card col">
        <h2>Nuovo evento</h2>
        <hxk-field label="Nome" .value=${f.title} placeholder="Es. Compleanno di Anna" @change=${(e: CustomEvent) => this.set('title', e.detail)}></hxk-field>
        <hxk-field label="Giorno" type="date" .value=${f.day} @change=${(e: CustomEvent) => this.set('day', e.detail)}></hxk-field>
        <hxk-field label="Tipo" type="enum" .options=${KINDS} .value=${f.kind}
          @change=${(e: CustomEvent) => (this.form = { ...f, kind: e.detail, yearly: e.detail !== 'custom' })}></hxk-field>
        <hxk-field label="Persona (facoltativo)" .value=${f.person} @change=${(e: CustomEvent) => this.set('person', e.detail)}></hxk-field>
        <hxk-field label="Avviso quanti giorni prima" type="int" .value=${f.lead_days} @change=${(e: CustomEvent) => this.set('lead_days', e.detail)}></hxk-field>
        <hxk-field label="Ogni anno" type="bool" .value=${f.yearly} @change=${(e: CustomEvent) => this.set('yearly', e.detail)}></hxk-field>
        <hxk-field label="Nota (facoltativo)" .value=${f.note} @change=${(e: CustomEvent) => this.set('note', e.detail)}></hxk-field>
        <div class="row"><hxk-button variant="primary" icon="check" ?loading=${this.busy === 'add'} @click=${() => this.add()}>Salva</hxk-button>
          <hxk-button variant="ghost" @click=${() => (this.form = null)}>Annulla</hxk-button></div>
      </div>` : nothing}
      ${this.items.length ? html`<div class="card">${this.items.map(s => this.row(s))}</div>`
        : html`<hxk-state kind="empty" text="Nessun evento. Il tuo compleanno arriva dalle impostazioni personali; le date delle persone da Persone."></hxk-state>`}
    </div>`;
  }
}
