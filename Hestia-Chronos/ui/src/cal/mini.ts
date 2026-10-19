/** <chronos-cal-mini> — small month navigator for the sidebar: today, selected day, days with items. Event `cal-pick` (Date). */
import { LitElement, css, html, nothing, tokens } from '@hestia/webui-sdk';
import { addMonths, dayKey, fmt, isSameDay, isToday, monthGrid } from './date';
import { calStyles, ic } from './ui';
import { fire } from './models';

export class ChronosCalMini extends LitElement {
  static properties = { selected: { attribute: false }, marked: { attribute: false }, month: { state: true } };
  declare selected: Date; declare marked: Set<string>; declare month: Date;
  static styles = [tokens, calStyles, css`
    :host { display: block; }
    .hd { display: flex; align-items: center; gap: 2px; padding: 0 2px 6px 6px; font-size: 13px; font-weight: 600; }
    .hd span { flex: 1; }
    .hd button { width: 26px; height: 26px; display: grid; place-items: center; border-radius: var(--radius-sm); color: var(--text-3); }
    .hd button:hover { background: var(--surface-2); color: var(--text); }
    .grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; }
    .wd { font-size: 10.5px; color: var(--text-3); text-align: center; padding: 2px 0; }
    .d { position: relative; height: 28px; border-radius: 50%; font-size: 12px; color: var(--text-2); }
    .d:hover { background: var(--surface-2); }
    .d.out { color: var(--text-3); opacity: .6; }
    .d.today { color: var(--accent); font-weight: 700; }
    .d.sel { background: var(--accent); color: var(--accent-contrast); }
    .d i { position: absolute; bottom: 3px; left: 50%; width: 4px; height: 4px; margin-left: -2px; border-radius: 50%; background: var(--accent); }
    .d.sel i { background: var(--accent-contrast); }
  `];
  private shown = 0;
  constructor() { super(); this.selected = new Date(); this.marked = new Set(); this.month = new Date(); }
  willUpdate(ch: Map<string, unknown>) {
    // follow the selected day (like the Angular effect), keep manual month browsing otherwise
    if (ch.has('selected') && this.selected.getTime() !== this.shown) { this.shown = this.selected.getTime(); this.month = new Date(this.selected); }
  }
  render() {
    const m = this.month;
    return html`<div class="hd"><span>${fmt.monthYear(m)}</span>
        <button @click=${() => (this.month = addMonths(m, -1))} aria-label="Mese precedente">${ic('chevron-left', 15)}</button>
        <button @click=${() => (this.month = addMonths(m, 1))} aria-label="Mese successivo">${ic('chevron-right', 15)}</button></div>
      <div class="grid">${['L', 'M', 'M', 'G', 'V', 'S', 'D'].map(w => html`<span class="wd">${w}</span>`)}
        ${monthGrid(m).map(d => html`<button class="d ${d.getMonth() !== m.getMonth() ? 'out' : ''} ${isToday(d) ? 'today' : ''} ${isSameDay(d, this.selected) ? 'sel' : ''}"
          @click=${() => fire(this, 'cal-pick', d)}>${d.getDate()}${this.marked.has(dayKey(d)) ? html`<i></i>` : nothing}</button>`)}</div>`;
  }
}
