/**
 * <chronos-cal-month> — month grid: chips per day (windows first, as thin bars), rules grouped ×N, "+N altri",
 * HTML5 drag of a chip to another day. Events: cal-select {ev, rect} · cal-create (Date) · cal-move {ev,start,end} · cal-day (Date).
 */
import { LitElement, css, html, nothing, tokens } from '@hestia/webui-sdk';
import { type CalEvent, type CalWeather, NO_WEATHER, fire } from '../models';
import { DAY_MS, addDays, dayKey, fmt, isSameDay, isToday, monthGrid, startOfDay } from '../date';
import { calStyles, wxChip } from '../ui';

const MAX_CHIPS = 3;

/** Tooltip lines for a day: Marko's own located events with the weather there at their hour. */
export function extLines(w: CalWeather, k: string): string[] {
  return w.external.filter(x => x.start.slice(0, 10) === k).map(x =>
    `${x.start.slice(11, 16)} ${x.title} · ${x.place || x.location}${x.hour ? `: ${x.hour.temp_c}°, ${x.hour.condition}` : ''}`);
}
const WD = ['Lun', 'Mar', 'Mer', 'Gio', 'Ven', 'Sab', 'Dom'];
type Split = { wins: CalEvent[]; groups: { ev: CalEvent; count: number }[] };

export class ChronosCalMonth extends LitElement {
  static properties = { anchor: { attribute: false }, events: { attribute: false }, weather: { attribute: false }, dropKey: { state: true } };
  declare anchor: Date; declare events: CalEvent[]; declare weather: CalWeather; declare dropKey: string | null;
  private dragged: CalEvent | null = null;
  private split = new Map<string, Split>();
  static styles = [tokens, calStyles, css`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .wds { display: grid; grid-template-columns: repeat(7, 1fr); border-bottom: 1px solid var(--border); }
    .wds div { padding: 8px 10px; font-size: 11.5px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; }
    .grid { flex: 1; display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); grid-template-rows: repeat(6, minmax(84px, 1fr)); min-height: 0; overflow-y: auto; }
    .cell { border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); padding: 4px; min-height: 0; overflow: hidden;
            display: flex; flex-direction: column; gap: 2px; cursor: cell; }
    .cell:nth-child(7n) { border-right: 0; }
    .cell.out { background: color-mix(in srgb, var(--surface-2) 40%, transparent); }
    .cell.out .num { color: var(--text-3); }
    .cell.drop { background: var(--accent-soft); }
    .num { align-self: flex-start; width: 26px; height: 26px; border-radius: 50%; font-size: 12.5px; color: var(--text-2); }
    .num:hover { background: var(--surface-2); }
    .top { display: flex; align-items: center; justify-content: space-between; gap: 4px; min-width: 0; }
    .wx { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums; white-space: nowrap; }
    .today .num { background: var(--accent); color: var(--accent-contrast); font-weight: 600; }
    .cell.sel { box-shadow: inset 0 0 0 2px var(--accent); }
    .chips { display: flex; flex-direction: column; gap: 2px; min-height: 0; }
    .chip { display: flex; align-items: center; gap: 5px; font-size: 11.5px; padding: 1px 6px; border-radius: var(--radius-xs, 4px);
            cursor: pointer; color: var(--text); min-width: 0; }
    .chip:hover { background: var(--surface-2); }
    .chip.failed { color: var(--danger); } .chip.failed .dot { background: var(--danger); }
    .chip .tt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
    .wins { display: flex; flex-direction: column; gap: 2px; padding: 0 2px 2px; }
    .win { display: block; height: 4px; border-radius: 2px; background: color-mix(in srgb, var(--c) 55%, transparent); cursor: pointer; }
    .win:hover { height: 6px; background: var(--c); }
    .win.skipped { background: repeating-linear-gradient(90deg, var(--c) 0 4px, transparent 4px 7px); opacity: .6; }
    .win.paused { filter: grayscale(1); opacity: .5; }
    .x { margin-left: auto; font-size: 10.5px; color: var(--text-3); flex-shrink: 0; padding-left: 4px; }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--c); flex-shrink: 0; }
    .t { color: var(--text-3); flex-shrink: 0; }
    .chip.skipped { text-decoration: line-through; opacity: .55; }
    .chip.done { opacity: .55; }
    .chip.paused { filter: grayscale(.8); }
    .more { font-size: 11.5px; color: var(--text-2); text-align: left; padding: 1px 6px; border-radius: 4px; font-weight: 500; }
    .more:hover { background: var(--surface-2); }
    @media (max-width: 600px) { .chip .t, .wds div { font-size: 10px; } .chip { padding: 1px 2px; } .cell { padding: 2px; } .wds div { padding: 6px 2px; text-align: center; } }
  `];
  constructor() { super(); this.anchor = new Date(); this.events = []; this.weather = NO_WEATHER; this.dropKey = null; }

  willUpdate(ch: Map<string, unknown>) {
    if (!ch.has('events') && !ch.has('anchor')) return;
    // day key → events overlapping that day (windows first, then by time)
    const cells = monthGrid(this.anchor), first = cells[0], last = addDays(cells[41], 1);
    const map = new Map<string, CalEvent[]>();
    for (const ev of this.events) {
      const end = ev.end ?? ev.start;
      let d = startOfDay(ev.start < first ? first : ev.start);
      while (d < last && d.getTime() <= end.getTime()) {
        const k = dayKey(d);
        // a window ending exactly at midnight does not belong to the next day
        if (!(ev.end && ev.end.getTime() === d.getTime() && ev.start < d)) (map.get(k) ?? map.set(k, []).get(k)!).push(ev);
        d = new Date(d.getTime() + DAY_MS);
        if (!ev.end) break;
      }
    }
    this.split = new Map();
    for (const [k, list] of map) {
      list.sort((a, b) => (a.occ.type === 'window' ? 0 : 1) - (b.occ.type === 'window' ? 0 : 1) || a.start.getTime() - b.start.getTime());
      const wins: CalEvent[] = [];
      const byKey = new Map<string, { ev: CalEvent; count: number }>();
      for (const ev of list) {
        if (ev.occ.type === 'window') { wins.push(ev); continue; }
        const g = byKey.get(ev.occ.key);
        g ? g.count++ : byKey.set(ev.occ.key, { ev, count: 1 });
      }
      this.split.set(k, { wins: wins.slice(0, 5), groups: [...byKey.values()] });
    }
  }

  private sel(e: Event, ev: CalEvent) { e.stopPropagation(); fire(this, 'cal-select', { ev, rect: (e.currentTarget as HTMLElement).getBoundingClientRect() }); }
  private at9(d: Date) { const x = startOfDay(d); x.setHours(9); return x; }
  private dragStart(e: DragEvent, ev: CalEvent) {
    this.dragged = ev;
    e.dataTransfer?.setData('text/plain', ev.id);
    if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move';
  }
  private drop(e: DragEvent, day: Date) {
    e.preventDefault();
    this.dropKey = null;
    const ev = this.dragged;
    this.dragged = null;
    if (!ev) return;
    const days = Math.round((startOfDay(day).getTime() - startOfDay(ev.start).getTime()) / DAY_MS);
    if (!days) return;
    fire(this, 'cal-move', { ev, start: addDays(ev.start, days), end: ev.end ? addDays(ev.end, days) : null });
  }

  private cell(d: Date) {
    const k = dayKey(d), s = this.split.get(k), groups = s?.groups ?? [], hidden = Math.max(0, groups.length - MAX_CHIPS);
    return html`<div class="cell ${d.getMonth() !== this.anchor.getMonth() ? 'out' : ''} ${isToday(d) ? 'today' : ''} ${isSameDay(d, this.anchor) ? 'sel' : ''} ${this.dropKey === k ? 'drop' : ''}"
        @click=${() => fire(this, 'cal-create', this.at9(d))}
        @dragover=${(e: DragEvent) => { e.preventDefault(); this.dropKey = k; }} @dragleave=${() => (this.dropKey = null)}
        @drop=${(e: DragEvent) => this.drop(e, d)}>
      <div class="top"><button class="num" @click=${(e: Event) => { e.stopPropagation(); fire(this, 'cal-day', d); }} title="Apri il giorno">${d.getDate()}</button>
        ${wxChip(this.weather.days[k], extLines(this.weather, k))}</div>
      ${s?.wins.length ? html`<div class="wins">${s.wins.map(w => html`<span class="win ${w.occ.skipped ? 'skipped' : ''} ${w.occ.status === 'paused' ? 'paused' : ''}"
          style="--c:${w.color}" title=${`Finestra ${fmt.time(w.start)}${w.end ? '–' + fmt.time(w.end) : ''} · ${w.occ.title}`}
          @click=${(e: Event) => this.sel(e, w)}></span>`)}</div>` : nothing}
      <div class="chips">
        ${groups.slice(0, MAX_CHIPS).map(({ ev, count }) => html`<div class="chip ${ev.occ.skipped ? 'skipped' : ''} ${ev.occ.run?.ok === false ? 'failed' : ''}
            ${ev.occ.status === 'completed' || ev.occ.status === 'cancelled' ? 'done' : ''} ${ev.occ.status === 'paused' ? 'paused' : ''}"
            style="--c:${ev.color}" draggable="true" @dragstart=${(e: DragEvent) => this.dragStart(e, ev)} @dragend=${() => (this.dropKey = null)}
            @click=${(e: Event) => this.sel(e, ev)} title=${ev.occ.title + (count > 1 ? ` (${count} volte oggi)` : '')}>
          <span class="dot"></span><span class="t">${fmt.time(ev.start)}</span><span class="tt">${ev.occ.title}</span>
          ${count > 1 ? html`<span class="x">×${count}</span>` : (ev.failedCount ?? 0) > 1 ? html`<span class="x">fallito ×${ev.failedCount}</span>` : nothing}
        </div>`)}
        ${hidden ? html`<button class="more" @click=${(e: Event) => { e.stopPropagation(); fire(this, 'cal-day', d); }}>+${hidden} altri</button>` : nothing}
      </div></div>`;
  }

  render() {
    return html`<div class="wds">${WD.map(w => html`<div>${w}</div>`)}</div>
      <div class="grid">${monthGrid(this.anchor).map(d => this.cell(d))}</div>`;
  }
}
