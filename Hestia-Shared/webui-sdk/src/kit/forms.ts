import { LitElement, css, html, nothing } from 'lit';
import { tokens } from '../styles';
import type { HestiaHost, Upload } from '../types';

/**
 * One labelled control: type text | textarea | int | float | bool | enum | date | time | list.
 * Same types as Themis settings / manifest params. Emits 'change' with detail = new value.
 */
export class HxkField extends LitElement {
  static properties = { label: {}, type: {}, value: { attribute: false }, options: { attribute: false },
                        placeholder: {}, unit: {}, help: {} };
  declare label: string;
  declare type: string;
  declare value: any;
  declare options: Array<string | { value: string; label: string }>;
  declare placeholder: string;
  declare unit: string;
  declare help: string;
  constructor() { super(); this.label = ''; this.type = 'text'; this.value = ''; this.options = []; this.placeholder = ''; this.unit = ''; this.help = ''; }

  static styles = [tokens, css`
    :host { display: flex; flex-direction: column; gap: 4px; }
    label { font-size: 12px; color: var(--text-2); font-weight: 500; }
    .ctl { display: flex; align-items: center; gap: 6px; }
    input, select, textarea { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm); padding: 7px 10px; outline: none; width: 100%; min-width: 0; }
    input:focus, select:focus, textarea:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
    input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--accent); }
    .u { color: var(--text-3); font-size: 13px; } .h { color: var(--text-3); font-size: 12px; }
  `];

  private emit(v: any) {
    this.value = v;
    this.dispatchEvent(new CustomEvent('change', { detail: v, bubbles: true, composed: true }));
  }

  private control() {
    const v = this.value ?? '';
    switch (this.type) {
      case 'textarea': case 'text_long':
        return html`<textarea rows="3" .value=${String(v)} placeholder=${this.placeholder} @input=${(e: any) => this.emit(e.target.value)}></textarea>`;
      case 'bool':
        return html`<input type="checkbox" .checked=${!!v} @change=${(e: any) => this.emit(e.target.checked)}>`;
      case 'enum':
        return html`<select @change=${(e: any) => this.emit(e.target.value)}>
          ${this.options.map(o => { const val = typeof o === 'string' ? o : o.value; const lab = typeof o === 'string' ? o : o.label;
            return html`<option value=${val} ?selected=${val === v}>${lab}</option>`; })}</select>`;
      case 'int': case 'float':
        return html`<input type="number" step=${this.type === 'int' ? '1' : 'any'} .value=${String(v)} placeholder=${this.placeholder}
          @input=${(e: any) => this.emit(e.target.value === '' ? null : Number(e.target.value))}>`;
      case 'date': case 'time':
        return html`<input type=${this.type} .value=${String(v)} @change=${(e: any) => this.emit(e.target.value)}>`;
      case 'list':
        return html`<input .value=${Array.isArray(v) ? v.join(', ') : String(v)} placeholder=${this.placeholder || 'a, b, c'}
          @change=${(e: any) => this.emit(String(e.target.value).split(',').map((s: string) => s.trim()).filter(Boolean))}>`;
      default:
        return html`<input .value=${String(v)} placeholder=${this.placeholder} @input=${(e: any) => this.emit(e.target.value)}>`;
    }
  }

  render() {
    return html`${this.label ? html`<label>${this.label}</label>` : nothing}
      <div class="ctl">${this.control()}${this.unit ? html`<span class="u">${this.unit}</span>` : nothing}</div>
      ${this.help ? html`<div class="h">${this.help}</div>` : nothing}`;
  }
}

/** Photo picker: uses host.upload (resized on the device), shows thumbnails; 'change' detail = Upload[]. */
export class HxkImagePicker extends LitElement {
  static properties = { host: { attribute: false }, value: { attribute: false }, multiple: { type: Boolean }, label: {} };
  declare host: HestiaHost;
  declare value: Upload[];
  declare multiple: boolean;
  declare label: string;
  constructor() { super(); this.value = []; this.multiple = false; this.label = 'Aggiungi foto'; }
  static styles = [tokens, css`
    :host { display: flex; flex-wrap: wrap; gap: 8px; }
    .th { position: relative; width: 84px; height: 84px; border-radius: var(--radius-md); overflow: hidden; background: var(--surface-2); }
    .th img { width: 100%; height: 100%; object-fit: cover; }
    .th button { position: absolute; top: 4px; right: 4px; border: none; border-radius: 50%; width: 22px; height: 22px;
      background: var(--overlay); color: #fff; cursor: pointer; display: grid; place-items: center; }
    .add { width: 84px; height: 84px; border: 1px dashed var(--border-strong); border-radius: var(--radius-md); background: transparent;
      color: var(--text-2); cursor: pointer; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; font: inherit; font-size: 11.5px; }
    .add:hover { background: var(--surface-2); }
  `];
  private async pick() {
    const files = await this.host.upload({ accept: 'image/*', multiple: this.multiple });
    if (!files.length) return;
    this.value = this.multiple ? [...this.value, ...files] : files.slice(0, 1);
    this.dispatchEvent(new CustomEvent('change', { detail: this.value, bubbles: true, composed: true }));
  }
  private removeAt(i: number) {
    this.value = this.value.filter((_, j) => j !== i);
    this.dispatchEvent(new CustomEvent('change', { detail: this.value, bubbles: true, composed: true }));
  }
  render() {
    return html`${this.value.map((u, i) => html`<div class="th"><img src="data:${u.mime};base64,${u.data_b64}" alt="">
        <button title="Rimuovi" @click=${() => this.removeAt(i)}><hxk-icon name="x" size="12"></hxk-icon></button></div>`)}
      ${this.multiple || !this.value.length ? html`<button class="add" @click=${this.pick}><hxk-icon name="camera" size="20"></hxk-icon>${this.label}</button>` : nothing}`;
  }
}
