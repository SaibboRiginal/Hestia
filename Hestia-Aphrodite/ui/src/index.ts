/**
 * Aphrodite («Aspetto») WebUI plugin (plugin contract docs/work/2026-10-17-client-plugins/SPEC.md §4; dossier
 * docs/work/2026-10-24-tutto-brainstorm-cindy W7). Page declared in Hestia-Aphrodite/app/main.py. The WebUI itself
 * draws the look (palette, effect, pet) from GET /api/appearance/now.
 */
import { HestiaElement, css, definePlugin, html, nothing, tr } from '@hestia/webui-sdk';
import type { ApiResult, HestiaHost, HttpMethod } from '@hestia/webui-sdk';

const API = '/api/appearance';
const EFFECT: Record<string, string> = { none: tr('Nessuno'), snow: tr('Neve'), leaves: tr('Foglie'), petals: tr('Petali'), sun: tr('Sole'),
  hearts: tr('Cuori'), confetti: tr('Coriandoli'), pumpkins: tr('Zucche'), stars: tr('Stelle') };
const POSE: Record<string, string> = { idle: tr('Tranquillo'), happy: tr('Contento'), sleep: tr('Dorme') };

async function call<T = any>(host: HestiaHost, method: HttpMethod, path: string, body?: unknown, query?: Record<string, any>): Promise<ApiResult<T>> {
  const r = await host.api<T>(method, `${API}${path}`, { body, query });
  if (!r.ok && method !== 'GET') host.toast(r.status === 0 ? tr('Non raggiungibile, riprova') : r.error || tr('Errore'), 'warning');
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
    if (r.ok) { this.host.toast(tr('Fatto: il sito si aggiorna tra poco'), 'success'); this.load(); }
  }
  private async savePet() {
    const d = this.petDraft;
    if (!d.name?.trim()) { this.host.toast(tr('Come si chiama?'), 'warning'); return; }
    const r = await call(this.host, 'POST', '/tools/animale', { name: d.name, species: d.species || 'gatto', look: d.look || '' });
    if (r.ok) { this.petDraft = null; this.host.toast(tr('Animaletto creato: le immagini arrivano quando sono pronte'), 'success'); this.load(); }
  }
  private async uploadPose(pet: any, pose: string) {
    const files = await this.host.upload({ accept: 'image/*', maxSide: 512 });
    if (!files.length) return;
    const r = await call(this.host, 'POST', `/pets/${pet.id}/image/${pose}`, { mime: files[0].mime, data_b64: files[0].data_b64 });
    if (r.ok) this.load();
  }
  private async regenerate(target: 'pet' | 'profile', ref: string) {
    const r = await call(this.host, 'POST', '/tools/genera', { target, ref });
    if (r.ok) this.host.toast(r.data.jobs?.some((j: any) => j.status === 'failed') ? tr('Il generatore di immagini non è pronto') : tr('Richieste: arrivano quando sono pronte'), 'info');
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
        <hxk-field label=${tr("Nome")} .value=${e.name || ''} @change=${set('name')}></hxk-field>
        <hxk-field label=${tr("Effetto")} type="enum" .options=${Object.entries(EFFECT).map(([value, label]) => ({ value, label }))} .value=${e.effect || 'none'} @change=${set('effect')}></hxk-field>
        <label class="col small">${tr("Colore")}<input type="color" .value=${e.accent || '#7C3AED'} @input=${set('accent')}></label>
        <label class="col small">${tr("Secondo colore")}<input type="color" .value=${e.accent2 || '#DB2777'} @input=${set('accent2')}></label>
        <hxk-field label=${tr("Dal (MM-GG)")} placeholder="12-08" .value=${e.from || ''} @change=${set('from')}></hxk-field>
        <hxk-field label=${tr("Al (MM-GG)")} placeholder="01-06" .value=${e.to || ''} @change=${set('to')}></hxk-field></div>
      <hxk-field label=${tr("Sfondo (descrizione per il generatore, in inglese)")} type="textarea" .value=${e.prompt || ''} @change=${set('prompt')}></hxk-field>
      <div class="row"><hxk-button variant="primary" @click=${() => this.saveProfile()}>${tr("Salva")}</hxk-button><hxk-button variant="ghost" @click=${() => { this.edit = null; }}>${tr("Annulla")}</hxk-button></div></div>`;
  }
  render() {
    const n = this.now;
    if (n === undefined) return html`<hxk-state kind="loading"></hxk-state>`;
    if (n === null) return html`<hxk-state kind="offline" @retry=${() => this.load()}></hxk-state>`;
    const p = n.profile;
    return html`<div class="page">
      <h1>${tr("Aspetto")}</h1>
      <div class="card col">
        <div class="between"><div><h3>${p.name}</h3><div class="small muted">${n.why}</div></div>
          <hxk-field type="bool" label=${tr("Temi automatici")} .value=${n.auto} @change=${(e: any) => this.choose({ auto: e.detail })}></hxk-field></div>
        <div class="row">${p.palette.accent ? html`<span class="sw" style="background:${p.palette.accent}"></span>` : nothing}
          ${p.palette.accent2 ? html`<span class="sw" style="background:${p.palette.accent2}"></span>` : nothing}
          <span class="small muted">Effetto: ${EFFECT[p.effect] || p.effect}</span></div>
        ${p.background ? html`<img class="bg" src=${this.host.image(`${API}/image/${p.background}`)} alt="">` : nothing}
        ${this.soon.length ? html`<div class="small muted">Prossimi: ${this.soon.map(s => `${ddmm(s.date)} ${s.why}`).join(' · ')}</div>` : nothing}
      </div>
      <div class="card col">
        <div class="between"><h3>${tr("Animaletto")}</h3><hxk-button size="sm" icon="plus" @click=${() => { this.petDraft = { species: 'gatto' }; }}>${tr("Nuovo")}</hxk-button></div>
        <hxk-field label=${tr("Sul sito")} type="enum" .options=${[{ value: '', label: tr('Nessuno') }, ...this.pets.map(x => ({ value: x.id, label: x.name }))]}
          .value=${n.pet?.id || ''} @change=${(e: any) => this.choose({ pet: e.detail })}></hxk-field>
        ${this.petDraft ? html`<div class="form">
            <hxk-field label=${tr("Nome")} .value=${this.petDraft.name || ''} @change=${(e: any) => { this.petDraft = { ...this.petDraft, name: e.detail }; }}></hxk-field>
            <hxk-field label=${tr("Che animale")} .value=${this.petDraft.species} @change=${(e: any) => { this.petDraft = { ...this.petDraft, species: e.detail }; }}></hxk-field>
            <hxk-field label=${tr("Com'è fatto")} placeholder=${tr("Es. arancione, occhi verdi")} .value=${this.petDraft.look || ''} @change=${(e: any) => { this.petDraft = { ...this.petDraft, look: e.detail }; }}></hxk-field></div>
          <div class="row"><hxk-button variant="primary" @click=${() => this.savePet()}>${tr("Crea")}</hxk-button><hxk-button variant="ghost" @click=${() => { this.petDraft = null; }}>${tr("Annulla")}</hxk-button></div>` : nothing}
        ${this.pets.map(x => html`<div class="pet"><div class="grow"><div>${x.name}</div><div class="small muted">${x.species}${x.look ? ` · ${x.look}` : ''}</div></div>
          ${Object.keys(POSE).map(pose => html`<div class="pose" title="${POSE[pose]}: tocca per caricare una tua immagine" @click=${() => this.uploadPose(x, pose)}>
            ${x.images?.[pose] ? html`<img src=${this.host.image(`${API}/image/${x.images[pose]}`)} alt=${POSE[pose]}>` : POSE[pose]}</div>`)}
          <hxk-button size="sm" variant="ghost" icon="refresh" @click=${() => this.regenerate('pet', x.id)}></hxk-button>
          <hxk-button size="sm" variant="ghost" icon="trash" @click=${async () => { if (await this.host.confirm(tr('Eliminare l\'animaletto?'), x.name, { label: tr('Elimina'), danger: true })) { await call(this.host, 'DELETE', `/pets/${x.id}`); this.load(); } }}></hxk-button></div>`)}
      </div>
      <div class="card col">
        <div class="between"><h3>${tr("Profili")}</h3><hxk-button size="sm" icon="plus" @click=${() => { this.edit = { effect: 'none' }; }}>${tr("Nuovo")}</hxk-button></div>
        <div class="small muted">${tr("Si accendono da soli: un tuo giorno speciale, poi le feste, poi la stagione. Un profilo con le date vale in quei giorni.")}</div>
        ${this.edit ? this.profileEditor() : nothing}
        ${this.profiles.filter(x => x.id !== 'standard').map(x => html`<div class="prof">
          ${x.palette?.accent ? html`<span class="sw" style="background:${x.palette.accent}"></span>` : html`<span class="sw"></span>`}
          <div class="grow"><div>${x.name}${x.id === p.key ? html` <hxk-badge tone="accent">${tr("adesso")}</hxk-badge>` : nothing}</div>
            <div class="small muted">${EFFECT[x.effect] || x.effect}${x.when ? tr(" · dal {0} al {1}", x.when.from, x.when.to) : ''}${x.background ? tr(' · con sfondo') : ''}</div></div>
          ${x.prompt ? html`<hxk-button size="sm" variant="ghost" icon="refresh" title=${tr("Rigenera lo sfondo")} @click=${() => this.regenerate('profile', x.id)}></hxk-button>` : nothing}
          <hxk-button size="sm" variant="ghost" icon="edit" @click=${() => { this.edit = { ...x, accent: x.palette?.accent, accent2: x.palette?.accent2, from: x.when?.from, to: x.when?.to }; }}></hxk-button></div>`)}
      </div>
    </div>`;
  }
}

definePlugin({ 'aphrodite-look': AphroditeLook });
