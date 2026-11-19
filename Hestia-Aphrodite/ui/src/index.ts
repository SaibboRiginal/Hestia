/**
 * Aphrodite («Look») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-whole-brainstorm-cindy W7). Page declared in Hestia-Aphrodite/app/main.py. The WebUI itself
 * draws the look (palette, effect, pet) from GET /api/appearance/now.
 */
import { HestiaElement, css, definePlugin, html, nothing, tr } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/appearance';
const EFFECT: Record<string, string> = { none: tr('None'), snow: tr('Snow'), leaves: tr('Leaves'), petals: tr('Petals'), sun: tr('alt::Sun'),
  hearts: tr('Hearts'), confetti: tr('Confetti'), pumpkins: tr('Pumpkins'), stars: tr('Stars') };
const POSE: Record<string, string> = { idle: tr('Calm'), happy: tr('Happy'), sleep: tr('Sleeping') };

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown, query?: Record<string, any>): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, { body, query });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? tr('Not reachable, try again') : r.error || tr('Error'), 'warning');
  return r;
}
const ddmm = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

const styles = css`
  .between { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
  .sw { width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--border-strong); display: inline-block; }
  .bg { width: 100%; max-height: 180px; object-fit: cover; border-radius: var(--radius-lg); }
  .pet { display: flex; gap: 12px; align-items: center; padding: 10px 2px; border-bottom: 1px solid var(--border); }
  .pet:last-child { border-bottom: 0; }
  .pose { width: 56px; height: 56px; border-radius: var(--radius-sm); background: var(--surface-2); display: grid; place-items: center;
    overflow: hidden; cursor: pointer; font-size: 10px; color: var(--text-3); text-align: center; }
  .pose img { width: 100%; height: 100%; object-fit: contain; }
  .prof { display: flex; gap: 10px; align-items: center; padding: 8px 2px; border-bottom: 1px solid var(--border); }
  .prof:last-child { border-bottom: 0; }
  .form { display: grid; gap: 10px; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); }
`;

export class AphroditeLook extends HestiaElement {
  static properties = { ...HestiaElement.properties, now: { state: true }, pets: { state: true }, profiles: { state: true },
                        soon: { state: true }, petDraft: { state: true }, edit: { state: true } };
  declare now: any;
  declare pets: any[];
  declare profiles: any[];
  declare soon: any[];
  declare petDraft: any;
  declare edit: any;
  static styles = [...HestiaElement.styles, styles];
  constructor() { super(); this.now = undefined; this.pets = []; this.profiles = []; this.soon = []; this.petDraft = null; this.edit = null; }
  connectedCallback() { super.connectedCallback(); this.load(); this.onHost('refresh', () => this.load()); }
  async load() {
    const [n, p, pr, u] = await Promise.all([call(this.host, 'GET', '/now', undefined, { client: 'webui' }), call(this.host, 'GET', '/pets'),
      call(this.host, 'GET', '/profiles'), call(this.host, 'GET', '/upcoming', undefined, { days: 90 })]);
    this.now = n.ok ? n.data : null;
    this.pets = p.ok ? p.data.items : [];
    this.profiles = pr.ok ? pr.data.items : [];
    this.soon = u.ok ? u.data.items.slice(1, 8) : [];
  }
  private async choose(body: any) {
    const r = await call(this.host, 'PUT', '/choice/webui', body);
    if (r.ok) { this.host.toast(tr('Done: the site updates shortly'), 'success'); this.load(); }
  }
  private async savePet() {
    const d = this.petDraft;
    if (!d.name?.trim()) { this.host.toast(tr('What is its name?'), 'warning'); return; }
    const r = await call(this.host, 'POST', '/tools/pet_create', { name: d.name, species: d.species || 'cat', look: d.look || '' });
    if (r.ok) { this.petDraft = null; this.host.toast(tr('Pet created: the images arrive when they\'re ready'), 'success'); this.load(); }
  }
  private async uploadPose(pet: any, pose: string) {
    const files = await this.host.upload({ accept: 'image/*', maxSide: 512 });
    if (!files.length) return;
    const r = await call(this.host, 'POST', `/pets/${pet.id}/image/${pose}`, { mime: files[0].mime, data_b64: files[0].data_b64 });
    if (r.ok) this.load();
  }
  private async regenerate(target: 'pet' | 'profile', ref: string) {
    const r = await call(this.host, 'POST', '/tools/generate', { target, ref });
    if (r.ok) this.host.toast(r.data.jobs?.some((j: any) => j.status === 'failed') ? tr('The image generator is not ready') : tr('Requests: they arrive when ready'), 'info');
  }
  private async saveProfile() {
    const e = this.edit;
    const body = { name: e.name, effect: e.effect, prompt: e.prompt || '', palette: { accent: e.accent || undefined, accent2: e.accent2 || undefined },
      when: e.from && e.to ? { from: e.from, to: e.to } : null };
    const r = e.id ? await call(this.host, 'PUT', `/profiles/${e.id}`, body) : await call(this.host, 'POST', '/profiles', body);
    if (r.ok) { this.edit = null; this.load(); }
  }
  private profileEditor() {
    const e = this.edit;
    const set = (k: string) => (ev: any) => { this.edit = { ...this.edit, [k]: ev.detail ?? ev.target.value }; };
    return html`<div class="card col"><div class="form">
        <hxk-field label=${tr("Name")} .value=${e.name || ''} @change=${set('name')}></hxk-field>
        <hxk-field label=${tr("Effect")} type="enum" .options=${Object.entries(EFFECT).map(([value, label]) => ({ value, label }))} .value=${e.effect || 'none'} @change=${set('effect')}></hxk-field>
        <label class="col small">${tr("Colour")}<input type="color" .value=${e.accent || '#7C3AED'} @input=${set('accent')}></label>
        <label class="col small">${tr("Second colour")}<input type="color" .value=${e.accent2 || '#DB2777'} @input=${set('accent2')}></label>
        <hxk-field label=${tr("From (MM-DD)")} placeholder="12-08" .value=${e.from || ''} @change=${set('from')}></hxk-field>
        <hxk-field label=${tr("To (MM-DD)")} placeholder="01-06" .value=${e.to || ''} @change=${set('to')}></hxk-field></div>
      <hxk-field label=${tr("Background (description for the generator, in English)")} type="textarea" .value=${e.prompt || ''} @change=${set('prompt')}></hxk-field>
      <div class="row"><hxk-button variant="primary" @click=${() => this.saveProfile()}>${tr("Save")}</hxk-button><hxk-button variant="ghost" @click=${() => { this.edit = null; }}>${tr("Cancel")}</hxk-button></div></div>`;
  }
  render() {
    const n = this.now;
    if (n === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (n === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const p = n.profile;
    return html`<div class="page">
      <h1>${tr("Look")}</h1>
      <div class="card col">
        <div class="between"><div><h3>${p.name}</h3><div class="small muted">${n.why}</div></div>
          <hxk-field type="bool" label=${tr("Automatic themes")} .value=${n.auto} @change=${(e: any) => this.choose({ auto: e.detail })}></hxk-field></div>
        <div class="row">${p.palette.accent ? html`<span class="sw" style="background:${p.palette.accent}"></span>` : nothing}
          ${p.palette.accent2 ? html`<span class="sw" style="background:${p.palette.accent2}"></span>` : nothing}
          <span class="small muted">${tr("Effect:")} ${EFFECT[p.effect] || p.effect}</span></div>
        ${p.background ? html`<img class="bg" src=${this.host.image(`${API}/image/${p.background}`)} alt="">` : nothing}
        ${this.soon.length ? html`<div class="small muted">${tr("Next:")} ${this.soon.map(s => `${ddmm(s.date)} ${s.why}`).join(' · ')}</div>` : nothing}
      </div>
      <div class="card col">
        <div class="between"><h3>${tr("Mascot")}</h3><hxk-button size="sm" icon="plus" @click=${() => { this.petDraft = { species: 'cat' }; }}>${tr("New")}</hxk-button></div>
        <div class="small muted">${tr("It keeps you company on the site and shows what is happening: it thinks while the answer is prepared, talks while it is written or read aloud, listens to your voice, sleeps at night. Drag it where you like. The built-in ones are drawn and move by themselves; yours use pictures, made by the image module or uploaded.")}</div>
        <hxk-field label=${tr("On the site")} type="enum" .options=${[{ value: 'none', label: tr('None') }, ...this.pets.map(x => ({ value: x.id, label: x.name }))]}
          .value=${n.pet?.id || 'none'} @change=${(e: any) => this.choose({ pet: e.detail })}></hxk-field>
        ${this.petDraft ? html`<div class="form">
            <hxk-field label=${tr("Name")} .value=${this.petDraft.name || ''} @change=${(e: any) => { this.petDraft = { ...this.petDraft, name: e.detail }; }}></hxk-field>
            <hxk-field label=${tr("Which animal")} .value=${this.petDraft.species} @change=${(e: any) => { this.petDraft = { ...this.petDraft, species: e.detail }; }}></hxk-field>
            <hxk-field label=${tr("What it's like")} placeholder=${tr("E.g. orange, green eyes")} .value=${this.petDraft.look || ''} @change=${(e: any) => { this.petDraft = { ...this.petDraft, look: e.detail }; }}></hxk-field></div>
          <div class="row"><hxk-button variant="primary" @click=${() => this.savePet()}>${tr("Create")}</hxk-button><hxk-button variant="ghost" @click=${() => { this.petDraft = null; }}>${tr("Cancel")}</hxk-button></div>` : nothing}
        ${this.pets.filter(x => !x.builtin).map(x => html`<div class="pet"><div class="grow"><div>${x.name}</div><div class="small muted">${x.species}${x.look ? ` · ${x.look}` : ''}</div></div>
          ${Object.keys(POSE).map(pose => html`<div class="pose" title="${tr("{0}: tap to upload a picture of you", POSE[pose])}" @click=${() => this.uploadPose(x, pose)}>
            ${x.images?.[pose] ? html`<img src=${this.host.image(`${API}/image/${x.images[pose]}`)} alt=${POSE[pose]}>` : POSE[pose]}</div>`)}
          <hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.regenerate('pet', x.id)}></hxk-button>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${async () => { if (await this.host.confirm(tr('Delete the mascot?'), x.name, { label: tr('Delete'), danger: true })) { await call(this.host, 'DELETE', `/pets/${x.id}`); this.load(); } }}></hxk-button></div>`)}
      </div>
      <div class="card col">
        <div class="between"><h3>${tr("Profiles")}</h3><hxk-button size="sm" icon="plus" @click=${() => { this.edit = { effect: 'none' }; }}>${tr("New")}</hxk-button></div>
        <div class="small muted">${tr("They turn on by themselves: one of your special days, then the holidays, then the season. A profile with dates applies on those days.")}</div>
        ${this.edit ? this.profileEditor() : nothing}
        ${this.profiles.filter(x => x.id !== 'standard').map(x => html`<div class="prof">
          ${x.palette?.accent ? html`<span class="sw" style="background:${x.palette.accent}"></span>` : html`<span class="sw"></span>`}
          <div class="grow"><div>${x.name}${x.id === p.key ? html` <hxk-badge tone="accent">${tr("now")}</hxk-badge>` : nothing}</div>
            <div class="small muted">${EFFECT[x.effect] || x.effect}${x.when ? tr(" · from {0} to {1}", x.when.from, x.when.to) : ''}${x.background ? tr(' · with background') : ''}</div></div>
          ${x.prompt ? html`<hxk-button size="sm" variant="ghost" icon="refresh" title=${tr("Regenerate the background")} @click=${() => this.regenerate('profile', x.id)}></hxk-button>` : nothing}
          <hxk-button size="sm" variant="ghost" icon="edit" @click=${() => { this.edit = { ...x, accent: x.palette?.accent, accent2: x.palette?.accent2, from: x.when?.from, to: x.when?.to }; }}></hxk-button></div>`)}
      </div>
    </div>`;
  }
}

definePlugin({ 'aphrodite-look': AphroditeLook });
