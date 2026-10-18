/** <hercules-picker>: search the local catalog (works offline) and pick an exercise → event 'pick' (detail = exercise). */
import { HestiaElement, html, css } from '@hestia/webui-sdk';
import { local } from './data';
import { EQUIPMENT, GROUPS, GROUP_LABEL, herculesStyles, muscleText, search } from './util';

export class HerculesPicker extends HestiaElement {
  static properties = { ...HestiaElement.properties, q: { state: true }, group: { state: true }, heading: {}, prefer: { attribute: false } };
  declare q: string;
  declare group: string;
  declare heading: string;
  declare prefer: string[];          // muscles to rank first (replace = same muscles)

  static styles = [...HestiaElement.styles, herculesStyles, css`
    :host { display: block; }
    .box { display: flex; flex-direction: column; gap: 10px; }
    .res { max-height: 360px; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-md); }
    .li { padding: 9px 12px; }
  `];

  constructor() { super(); this.q = ''; this.group = ''; this.heading = 'Aggiungi esercizio'; this.prefer = []; }

  firstUpdated() { (this.renderRoot.querySelector('input') as HTMLInputElement | null)?.focus(); }

  render() {
    const L = local(this.host);
    let items = L.list('exercise').filter(e => !e.archived);
    if (this.group) items = items.filter(e => (e.primary_muscles || []).some((m: string) => GROUPS[this.group]?.includes(m)));
    items = search(items, this.q);
    if (!this.q && this.prefer.length) {
      const pref = new Set(this.prefer);
      items = [...items.filter(e => (e.primary_muscles || []).some((m: string) => pref.has(m))), ...items.filter(e => !(e.primary_muscles || []).some((m: string) => pref.has(m)))];
    }
    return html`<div class="box card">
      <div class="between"><h2>${this.heading}</h2>
        <hxk-button variant="ghost" size="sm" icon="x" @click=${() => this.dispatchEvent(new CustomEvent('close'))}>Chiudi</hxk-button></div>
      <input class="in" placeholder="Cerca: panca, squat, dorsali…" .value=${this.q} @input=${(e: any) => (this.q = e.target.value)}>
      <div class="chips">
        <button class="chip" aria-pressed=${!this.group} @click=${() => (this.group = '')}>Tutti</button>
        ${Object.keys(GROUPS).map(g => html`<button class="chip" aria-pressed=${this.group === g} @click=${() => (this.group = this.group === g ? '' : g)}>${GROUP_LABEL[g]}</button>`)}
      </div>
      <div class="res list">
        ${items.slice(0, 60).map(e => html`<div class="li" @click=${() => this.dispatchEvent(new CustomEvent('pick', { detail: e }))}>
          <div class="grow"><div class="truncate">${e.name}</div><div class="small muted truncate">${muscleText(e)} · ${EQUIPMENT[e.equipment] || e.equipment}</div></div>
          <hxk-icon name="plus"></hxk-icon></div>`)}
        ${items.length ? '' : html`<div class="empty" style="padding:12px">Nessun esercizio. Puoi crearlo in Esercizi.</div>`}
      </div>
    </div>`;
  }
}
