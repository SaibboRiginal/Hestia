/**
 * Hera («People») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-whole-cindy-brainstorm W7). Pages and widget declared in Hestia-Hera/app/main.py.
 */
import { HestiaElement, css, definePlugin, html, nothing, tr } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/people';
const RELATIONS = [
  { value: 'partner', label: tr('Partner') }, { value: 'family', label: tr('Family') }, { value: 'friend', label: tr('Friend') },
  { value: 'colleague', label: tr('alt::Link') }, { value: 'other', label: tr('Other') }];
const relLabel = (r: string) => RELATIONS.find(x => x.value === r)?.label || tr('Other');

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, body === undefined ? undefined : { body });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? tr('Not reachable, try again') : r.error || tr('Error'), 'warning');
  return r;
}
const ddmm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const inDays = (n: number) => n === 0 ? tr('today') : n === 1 ? tr('tomorrow') : tr("in {0} days", n);

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .click { cursor: pointer; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .chip { padding: 3px 10px; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); font-size: 13px; }
  .chip.no { text-decoration: line-through; color: var(--text-3); }
  .person { display: flex; gap: 12px; align-items: center; padding: 10px 4px; border-bottom: 1px solid var(--border); cursor: pointer; }
  .person:last-child { border-bottom: 0; }
  .avatar { width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; background: var(--accent-soft);
    color: var(--accent); font-weight: 600; flex: none; }
  .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); }
  .idea { display: flex; align-items: center; gap: 8px; padding: 4px 0; }
`;

export class HeraPeople extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, soon: { state: true }, q: { state: true },
                        adding: { state: true }, draft: { state: true } };
  declare items: any[] | null | undefined;
  declare soon: any[];
  declare q: string;
  declare adding: boolean;
  declare draft: Record<string, any>;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.items = undefined; this.soon = []; this.q = ''; this.adding = false; this.draft = { relation: 'friend' }; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() {
    const [r, u] = await Promise.all([call(this.host, 'GET', ''), call(this.host, 'GET', '/upcoming')]);
    this.items = r.ok ? r.data.items : null;
    this.soon = u.ok ? u.data.items.slice(0, 6) : [];
  }
  private set(k: string, v: any) { this.draft = { ...this.draft, [k]: v }; }
  private async save() {
    if (!String(this.draft.name || '').trim()) { this.host.toast(tr('The name is needed'), 'warning'); return; }
    const r = await call(this.host, 'POST', '', this.draft);
    if (r.ok) { this.adding = false; this.draft = { relation: 'friend' }; this.host.toast(tr('{0} saved', r.data.name), 'success'); this.load(); }
  }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const q = this.q.trim().toLowerCase();
    const shown = this.items.filter(p => !q || p.name.toLowerCase().includes(q));
    return html`<div class="page">
      <div class="between"><h1>${tr("People")}</h1>
        <hxk-button variant="primary" icon="plus" @click=${() => { this.adding = !this.adding; }}>${tr("Add")}</hxk-button></div>
      ${this.adding ? html`<div class="card col">
        <div class="form">
          <hxk-field label=${tr("Name")} .value=${this.draft.name || ''} @change=${(e: any) => this.set('name', e.detail)}></hxk-field>
          <hxk-field label=${tr("Relationship")} type="enum" .options=${RELATIONS} .value=${this.draft.relation} @change=${(e: any) => this.set('relation', e.detail)}></hxk-field>
          <hxk-field label=${tr("Birthday")} placeholder=${tr("DD/MM or YYYY-MM-DD")} .value=${this.draft.birthday || ''} @change=${(e: any) => this.set('birthday', e.detail)}></hxk-field>
          <hxk-field label=${tr("Call her every")} type="int" unit=${tr("days")} .value=${this.draft.contact_every_days ?? ''} @change=${(e: any) => this.set('contact_every_days', e.detail)}></hxk-field>
        </div>
        <hxk-field label=${tr("What she likes")} type="list" .value=${this.draft.likes || []} @change=${(e: any) => this.set('likes', e.detail)}></hxk-field>
        <div class="row"><hxk-button variant="primary" @click=${() => this.save()}>${tr("Save")}</hxk-button>
          <hxk-button variant="ghost" @click=${() => { this.adding = false; }}>${tr("Cancel")}</hxk-button></div>
      </div>` : nothing}
      ${this.soon.length ? html`<div class="card col"><h3>${tr("Upcoming dates")}</h3>
        ${this.soon.map(s => html`<div class="between small"><span class="click" @click=${() => this.host.navigate('person/' + s.person_id)}>${tr("{0} of", s.label)} <b>${s.person}</b></span>
          <span class="muted">${ddmm(s.next)} · ${inDays(s.in_days)}</span></div>`)}</div>` : nothing}
      <input placeholder=${tr("Search")} .value=${this.q} @input=${(e: any) => { this.q = e.target.value; }}>
      <div class="card">${shown.length ? shown.map(p => html`<div class="person" @click=${() => this.host.navigate('person/' + p.id)}>
          <div class="avatar">${p.name.slice(0, 1).toUpperCase()}</div>
          <div class="grow"><div>${p.name}</div><div class="small muted">${relLabel(p.relation)}${p.dates.length ? ` · ${p.dates[0].label.toLowerCase()} ${ddmm(p.dates[0].next)}` : ''}</div></div>
          ${p.contact_due_in !== null && p.contact_due_in !== undefined && p.contact_due_in <= 0 ? html`<hxk-badge tone="warning">${tr("to call")}</hxk-badge>` : nothing}
        </div>`) : html`<hxk-state kind="empty" text=${this.items.length ? tr('No person with this name.') : tr('No person yet: add who is important to you.')}></hxk-state>`}</div>
    </div>`;
  }
}

export class HeraPerson extends HestiaElement {
  static properties = { ...HestiaElement.properties, p: { state: true }, idea: { state: true }, like: { state: true },
                        newDate: { state: true } };
  declare p: any;
  declare idea: string;
  declare like: string;
  declare newDate: Record<string, string>;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.p = undefined; this.idea = ''; this.like = ''; this.newDate = {}; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  private get pid() { return this.ctx?.params?.id || ''; }
  async load() { const r = await call(this.host, 'GET', `/${encodeURIComponent(this.pid)}`); this.p = r.ok ? r.data : null; }
  private async patch(body: any) { const r = await call(this.host, 'PUT', `/${this.pid}`, body); if (r.ok) this.p = r.data; }
  private async post(path: string, body: any = {}) { const r = await call(this.host, 'POST', `/${this.pid}${path}`, body); if (r.ok) this.p = r.data; return r.ok; }
  private async deletePerson() {
    if (!await this.host.confirm(tr('Delete the plan?'), tr("{0} and its dates also disappear from the calendar.", this.p.name), { label: tr('Delete'), danger: true })) return;
    const r = await call(this.host, 'DELETE', `/${this.pid}`);
    if (r.ok) { this.host.toast(tr('f::Deleted'), 'success'); this.host.navigate('people'); }
  }
  render() {
    const p = this.p;
    if (p === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (p === null) return html`<hxk-state kind="error" text=${tr("Person not found.")} @retry=${() => this.load()}></hxk-state>`;
    return html`<div class="page">
      <div class="between"><div class="row"><div class="avatar">${p.name.slice(0, 1).toUpperCase()}</div>
        <div><h1>${p.name}</h1><div class="small muted">${relLabel(p.relation)}${p.last_contact ? tr(" · talked on {0}", ddmm(p.last_contact)) : ''}</div></div></div>
        <div class="row"><hxk-button icon="check" variant="primary" @click=${async () => { if (await this.post('/contact')) this.host.toast(tr("Marked: you talked to her"), 'success'); }}>${tr("I talked to them")}</hxk-button>
          <hxk-button icon="chat" variant="ghost" @click=${() => this.host.assistant({ label: p.name, hints: { person: p.id }, suggestions: [tr('Gift ideas for her'), tr('What does she like?')] })}>${tr("Ask")}</hxk-button></div></div>
      <div class="grid" style="--min: 280px">
        <div class="card col"><h3>${tr("Dates")}</h3>
          ${p.dates.length ? p.dates.map((d: any) => html`<div class="between small"><span>${d.label}</span><span class="muted">${ddmm(d.next)} · ${inDays(d.in_days)} · ${tr("notice")} ${d.lead_days} ${tr("d before")}</span></div>`)
            : html`<div class="small muted">${tr("No dates.")}</div>`}
          <div class="row wrap">
            <input placeholder=${tr("E.g. Anniversary")} style="flex:1" .value=${this.newDate.label || ''} @input=${(e: any) => { this.newDate = { ...this.newDate, label: e.target.value }; }}>
            <input placeholder="GG/MM" style="width:90px" .value=${this.newDate.day || ''} @input=${(e: any) => { this.newDate = { ...this.newDate, day: e.target.value }; }}>
            <hxk-button icon="plus" @click=${async () => { if (this.newDate.label && this.newDate.day) { await this.patch({ dates: [{ ...this.newDate, kind: /anniversar|anniversary/i.test(this.newDate.label) ? 'anniversary' : 'custom' }] }); this.newDate = {}; } }}>${tr("Add")}</hxk-button></div>
          <div class="small muted">${tr("The dates go in the calendar with the advance notice.")}</div>
        </div>
        <div class="card col"><h3>${tr("Gift ideas")}</h3>
          ${p.gift_ideas.length ? p.gift_ideas.map((g: any) => html`<div class="idea"><span class="grow">${g.text}</span>
            <hxk-button size="sm" variant="ghost" icon="check" @click=${() => this.post(`/gift/${g.id}/done`)}>${tr("Done")}</hxk-button></div>`)
            : html`<div class="small muted">${tr("When in chat you say what she would like, the assistant notes it here.")}</div>`}
          <div class="row"><input class="grow" placeholder=${tr("New idea")} .value=${this.idea} @input=${(e: any) => { this.idea = e.target.value; }}
            @keydown=${(e: KeyboardEvent) => { if (e.key === 'Enter') this.addIdea(); }}>
            <hxk-button icon="plus" @click=${() => this.addIdea()}>${tr("Add")}</hxk-button></div>
        </div>
        <div class="card col"><h3>${tr("Tastes")}</h3>
          <div class="chips">${(p.likes || []).map((l: string) => html`<span class="chip">${l}</span>`)}${(p.dislikes || []).map((l: string) => html`<span class="chip no">${l}</span>`)}</div>
          <div class="row"><input class="grow" placeholder=${tr("She likes…")} .value=${this.like} @input=${(e: any) => { this.like = e.target.value; }}>
            <hxk-button size="sm" @click=${() => this.addLike(false)}>${tr("Likes")}</hxk-button>
            <hxk-button size="sm" variant="ghost" @click=${() => this.addLike(true)}>${tr("Dislikes")}</hxk-button></div>
        </div>
        <div class="card col"><h3>${tr("Notes and contact")}</h3>
          <hxk-field type="textarea" .value=${p.notes || ''} @change=${(e: any) => this.patch({ notes: e.detail })}></hxk-field>
          <hxk-field label=${tr("Call her every")} type="int" unit=${tr("days")} .value=${p.contact_every_days ?? ''} @change=${(e: any) => e.detail && this.patch({ contact_every_days: e.detail })}></hxk-field>
          <hxk-field label=${tr("Relationship")} type="enum" .options=${RELATIONS} .value=${p.relation} @change=${(e: any) => this.patch({ relation: e.detail })}></hxk-field>
        </div>
      </div>
      <div><hxk-button variant="danger" icon="trash" @click=${() => this.deletePerson()}>${tr("Delete plan")}</hxk-button></div>
    </div>`;
  }
  private async addIdea() { if (this.idea.trim() && await this.post('/gift', { idea: this.idea })) this.idea = ''; }
  private async addLike(dislike: boolean) { if (this.like.trim() && await this.post('/like', { text: this.like, dislike })) this.like = ''; }
}

export class HeraSoonWidget extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true } };
  declare items: any[] | null | undefined;
  static styles = [...HestiaElement.styles, styles, css`:host { display: block; height: 100%; }`];
  constructor() { super(); this.items = undefined; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); this.onHost('visible', () => this.load()); }
  async load() { const r = await call(this.host, 'GET', '/upcoming'); this.items = r.ok ? r.data.items : null; this.markEmpty(!!this.items && !this.items.length); }
  render() {
    if (this.items === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (this.items === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const n = this.ctx?.size === 's' ? 1 : this.ctx?.size === 'm' ? 3 : 6;
    return html`<div class="col" style="gap:6px">
      ${this.items.length ? this.items.slice(0, n).map(s => html`<div class="between small click" @click=${() => this.host.navigate('person/' + s.person_id)}>
        <span class="truncate">${tr("{0} of", s.label)} <b>${s.person}</b></span><span class="muted">${inDays(s.in_days)}</span></div>`)
        : html`<div class="small muted">${tr("Nothing in the next 30 days.")}</div>`}
    </div>`;
  }
}

definePlugin({ 'hera-people': HeraPeople, 'hera-person': HeraPerson, 'hera-soon-widget': HeraSoonWidget });
