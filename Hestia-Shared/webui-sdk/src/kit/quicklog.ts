import { LitElement, css, html, nothing } from 'lit';
import { tokens } from '../styles';
import { fillPath } from '../base';
import type { HestiaHost, HttpMethod, QuickChip } from '../types';

export interface QuickAction { method: HttpMethod; path: string; undo?: { method: HttpMethod; path: string } | null }

/**
 * One-tap logging (SPEC §4.2b): big chips, tap = done, toast with «Annulla», ⋯ = another day / note,
 * optional progress hint per chip ("2/3 questa settimana"). Same look as the WebUI Home quick-action strip.
 *
 *   <hxk-quicklog .host=${this.host} source="/api/ui/quick/routines"
 *                 .action=${{ method: 'POST', path: '/api/ui/routines/{id}/done', undo: { method: 'DELETE', path: '/api/ui/routines/{id}/done/today' } }}>
 *
 * `source` answers QuickChip[] or {items: QuickChip[]}. The chip id fills `{id}`. Body sent: {} or {date, note}.
 * Event 'logged' (detail {chip, undone}) after each change.
 */
export class HxkQuicklog extends LitElement {
  static properties = { host: { attribute: false }, source: {}, action: { attribute: false }, chips: { attribute: false },
                        compact: { type: Boolean, reflect: true }, _busy: { state: true }, _menu: { state: true }, _err: { state: true } };
  declare host: HestiaHost;
  declare source: string;
  declare action: QuickAction;
  declare chips: QuickChip[] | null;
  declare compact: boolean;
  declare _busy: string;
  declare _menu: string;
  declare _err: string;
  private _date = '';
  private _note = '';

  constructor() { super(); this.source = ''; this.chips = null; this.compact = false; this._busy = ''; this._menu = ''; this._err = ''; }

  static styles = [tokens, css`
    :host { display: flex; flex-wrap: wrap; gap: 8px; }
    .chip { position: relative; display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--border-strong);
      background: var(--surface); border-radius: var(--radius-full); padding: 9px 8px 9px 14px; cursor: pointer; font: inherit;
      color: var(--text); min-height: 44px; transition: background var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease); }
    :host([compact]) .chip { min-height: 34px; padding: 5px 6px 5px 10px; font-size: 13px; }
    .chip:hover { background: var(--surface-2); }
    .chip[data-state=done] { background: var(--success-soft); border-color: transparent; color: var(--success); }
    .chip[data-state=late] { border-color: var(--warning); }
    .chip[aria-busy=true] { opacity: .6; pointer-events: none; }
    .col { display: flex; flex-direction: column; align-items: flex-start; text-align: left; line-height: 1.25; min-width: 0; }
    .lab { font-weight: 500; } .hint { font-size: 11.5px; color: var(--text-3); }
    .chip[data-state=done] .hint { color: inherit; opacity: .8; }
    .more { border: none; background: transparent; color: var(--text-3); border-radius: 50%; width: 28px; height: 28px;
      display: grid; place-items: center; cursor: pointer; }
    .more:hover { background: var(--surface-3); color: var(--text); }
    .star { color: var(--warning); }
    .menu { position: absolute; z-index: 5; top: calc(100% + 6px); left: 0; background: var(--surface); border: 1px solid var(--border-strong);
      box-shadow: var(--shadow-2); border-radius: var(--radius-md); padding: 10px; display: flex; flex-direction: column; gap: 8px; min-width: 220px; cursor: default; }
    .menu input { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong); border-radius: var(--radius-sm); padding: 6px 8px; }
    .err { color: var(--text-3); font-size: 13px; }
  `];

  connectedCallback(): void {
    super.connectedCallback();
    if (this.chips === null && this.source) this.reload();
  }

  async reload() {
    if (!this.host || !this.source) return;
    const r = await this.host.api<QuickChip[] | { items: QuickChip[] }>('GET', this.source);
    if (!r.ok) { this._err = r.error === 'offline' ? 'Offline' : 'Non disponibile'; this.chips = this.chips ?? []; return; }
    this._err = '';
    this.chips = Array.isArray(r.data) ? r.data : r.data?.items ?? [];
  }

  private async log(chip: QuickChip, body: Record<string, unknown> = {}) {
    if (!this.action) return;
    this._busy = chip.id;
    const prev = chip.state;
    const r = await this.host.api(this.action.method, fillPath(this.action.path, { id: chip.id }), { body });
    this._busy = '';
    if (!r.ok) {
      // 409/422: the module says why (e.g. «già segnata oggi»), better than a generic failure.
      const said = (r.status === 409 || r.status === 422) && r.error && !r.error.startsWith('HTTP') ? r.error : '';
      this.host.toast(r.error === 'offline' ? 'Sei offline: riprova quando torni in linea' : said || 'Non sono riuscito a segnarlo', 'danger');
      return;
    }
    this.setState(chip, 'done');
    const undo = this.action.undo;
    this.host.toast(chip.label, 'success', undo ? { label: 'Annulla', run: () => this.undo(chip, prev) } : undefined);
    this.dispatchEvent(new CustomEvent('logged', { detail: { chip, undone: false }, bubbles: true, composed: true }));
    this.reload();
  }

  private async undo(chip: QuickChip, prev?: QuickChip['state']) {
    const u = this.action.undo;
    if (!u) return;
    const r = await this.host.api(u.method, fillPath(u.path, { id: chip.id }));
    if (!r.ok) { this.host.toast('Annullamento non riuscito', 'danger'); return; }
    this.setState(chip, prev ?? 'todo');
    this.dispatchEvent(new CustomEvent('logged', { detail: { chip, undone: true }, bubbles: true, composed: true }));
    this.reload();
  }

  private setState(chip: QuickChip, state: QuickChip['state']) {
    this.chips = (this.chips ?? []).map(c => (c.id === chip.id ? { ...c, state } : c));
  }

  private openMenu(e: Event, chip: QuickChip) {
    e.stopPropagation();
    this._date = new Date().toISOString().slice(0, 10);
    this._note = '';
    this._menu = this._menu === chip.id ? '' : chip.id;
  }

  render() {
    if (this.chips === null) return html`<hxk-state kind="loading"></hxk-state>`;
    if (!this.chips.length) return html`<span class="err">${this._err || 'Niente da segnare oggi'}</span>`;
    return this.chips.map(c => html`
      <div class="chip" role="button" tabindex="0" data-state=${c.state ?? 'todo'} aria-busy=${this._busy === c.id}
           @click=${() => this.log(c)} @keydown=${(e: KeyboardEvent) => (e.key === 'Enter' || e.key === ' ') && this.log(c)}>
        ${c.favorite ? html`<hxk-icon class="star" name="star" size="14"></hxk-icon>` : nothing}
        ${c.state === 'done' ? html`<hxk-icon name="check" size="16"></hxk-icon>` : c.icon ? html`<hxk-icon name=${c.icon} size="16"></hxk-icon>` : nothing}
        <span class="col"><span class="lab">${c.label}</span>${c.hint ? html`<span class="hint">${c.hint}</span>` : nothing}</span>
        <button class="more" title="Altro giorno o dettagli" @click=${(e: Event) => this.openMenu(e, c)}><hxk-icon name="more"></hxk-icon></button>
        ${this._menu === c.id ? html`<div class="menu" @click=${(e: Event) => e.stopPropagation()}>
            <label class="hint">Giorno</label><input type="date" .value=${this._date} @change=${(e: any) => (this._date = e.target.value)}>
            <label class="hint">Nota</label><input .value=${this._note} placeholder="facoltativa" @input=${(e: any) => (this._note = e.target.value)}>
            <hxk-button variant="primary" size="sm" icon="check"
              @click=${() => { this._menu = ''; this.log(c, { date: this._date, ...(this._note ? { note: this._note } : {}) }); }}>Segna</hxk-button>
          </div>` : nothing}
      </div>`);
  }
}
