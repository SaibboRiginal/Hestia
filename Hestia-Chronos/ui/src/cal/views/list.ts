/**
 * <chronos-cal-list> — agenda list grouped by day (31 days from the anchor). The «Adesso» divider marks the
 * current time (the list scrolls to it once); past rows show the outcome of their run (ok / fallito + detail).
 * Event: cal-select {ev, rect}.
 */
import { LitElement, css, html, nothing, tokens } from '@hestia/webui-sdk';
import type { TemplateResult } from '@hestia/webui-sdk';
import { type CalEvent, type CalWeather, NO_WEATHER, STATUS_META, TYPE_META, dur, fire, ownerLabel } from '../models';
import { extLines } from './month';
import { dayKey, fmt, isSameDay, isToday } from '../date';
import { describeRRule } from '../rrule';
import { calStyles, ic, wxChip } from '../ui';

type Tone = 'neutral' | 'success' | 'warning' | 'danger' | 'info' | 'accent';
interface Outcome { label: string; tone: Tone; detail?: string; }
interface Group { key: string; label: string; today: boolean; events: CalEvent[]; nowBefore: boolean; nowAt: string | null; nowAfter: boolean; }

/** Divider position: before the first item that has not started yet (exported for tests/reuse). */
export function groupByDay(events: CalEvent[], from: Date, now: number): Group[] {
  const map = new Map<string, Group>();
  const sorted = [...events].sort((a, b) => a.start.getTime() - b.start.getTime());
  for (const ev of sorted) {
    const day = ev.start < from ? from : ev.start;   // began before the list (e.g. a window from yesterday)
    const k = dayKey(day);
    if (!map.has(k)) map.set(k, { key: k, label: fmt.dayLong(day), today: isToday(day), events: [], nowBefore: false, nowAt: null, nowAfter: false });
    map.get(k)!.events.push(ev);
  }
  const groups = [...map.values()];
  if (!groups.length || from.getTime() > now) return groups;   // list starts in the future: no "now"
  const first = sorted.find(e => e.start.getTime() > now);
  const today = groups.find(g => g.today);
  if (!first) groups[groups.length - 1].nowAfter = true;
  else {
    const g = groups.find(x => x.events.includes(first))!;
    if (g.today) g.nowAt = first.id;
    else if (today) today.nowAfter = true;
    else g.nowBefore = true;
  }
  return groups;
}

/** Badge (+ detail line) for a row: the run result for past items, the state for upcoming ones. */
export function outcome(ev: CalEvent, now: number): Outcome | null {
  const o = ev.occ;
  if (o.skipped) return { label: 'saltata', tone: 'neutral' };
  const started = ev.start.getTime() <= now, ended = (ev.end ?? ev.start).getTime() < now;
  if (o.run) {
    if (!o.run.ok) return { label: 'fallito' + ((ev.failedCount ?? 0) > 1 ? ' ×' + ev.failedCount : ''), tone: 'danger', detail: o.run.detail || undefined };
    return { label: 'ok' + (o.run.duration_ms ? ' · ' + dur(o.run.duration_ms) : ''), tone: 'success', detail: o.run.detail || undefined };
  }
  if (o.status && o.status !== 'confirmed') {
    const s = STATUS_META[o.status] ?? STATUS_META.confirmed;
    return { label: s.label, tone: s.tone };
  }
  if (started && !ended) return { label: 'in corso', tone: 'accent' };
  if (ended) {
    if (!ev.item?.action) return { label: 'concluso', tone: 'neutral' };
    const lr = !o.recurring ? ev.item.last_result : null;   // one-off item: its result is the rule's last result
    if (lr) return lr.ok ? { label: 'ok', tone: 'success', detail: lr.detail || undefined } : { label: 'fallito', tone: 'danger', detail: lr.detail || undefined };
    return { label: 'nessun esito', tone: 'warning' };
  }
  if (o.moved) return { label: 'spostata', tone: 'info' };
  return null;
}

export class ChronosCalList extends LitElement {
  static properties = { events: { attribute: false }, from: { attribute: false }, weather: { attribute: false }, now: { state: true } };
  declare weather: CalWeather; declare events: CalEvent[]; declare from: Date; declare now: number;
  private timer: ReturnType<typeof setInterval> | null = null;
  private scrolled = false;
  static styles = [tokens, calStyles, css`
    :host { display: block; position: relative; overflow-y: auto; flex: 1; min-height: 0; padding: 8px 24px 40px; }
    section { max-width: 920px; margin: 0 auto 18px; }
    h3 { font-family: var(--font-sans); font-size: 13px; font-weight: 600; color: var(--text-2); padding: 10px 4px 6px; margin: 0;
      position: sticky; top: -8px; background: var(--bg); z-index: 1; }
    h3.today { color: var(--accent); }
    .row { width: 100%; display: flex; align-items: center; gap: 12px; padding: 9px 10px; border-radius: var(--radius-md); text-align: left; }
    .row:hover { background: var(--surface-2); }
    .time { width: 104px; flex-shrink: 0; font-size: 12.5px; color: var(--text-2); font-variant-numeric: tabular-nums; }
    .bar { width: 4px; align-self: stretch; border-radius: 2px; flex-shrink: 0; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .title { font-size: 14px; display: flex; align-items: center; gap: 6px; color: var(--text); }
    .meta { font-size: 12px; color: var(--text-3); }
    .wx { display: inline-flex; align-items: center; gap: 3px; font-size: 11px; color: var(--text-3); font-variant-numeric: tabular-nums; white-space: nowrap; }
    h3 .wx { margin-left: 8px; font-weight: 400; }
    .detail { font-size: 12px; color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .detail.err { color: var(--danger); }
    .row.past .time, .row.past .title { color: var(--text-3); }
    .row.skipped .title { text-decoration: line-through; }
    .row.skipped, .row.done { opacity: .6; }
    .now { max-width: 920px; margin: 4px auto; display: flex; align-items: center; gap: 8px; padding: 2px 4px; }
    .now .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--danger); flex-shrink: 0; }
    .now .lbl { font-size: 12px; font-weight: 600; color: var(--danger); white-space: nowrap; font-variant-numeric: tabular-nums; }
    .now .line { flex: 1; border-top: 2px solid var(--danger); }
    @media (max-width: 720px) { :host { padding: 6px 10px 30px; } .time { width: 76px; } .row { gap: 8px; padding: 8px 4px; } }
  `];
  constructor() { super(); this.events = []; this.from = new Date(); this.weather = NO_WEATHER; this.now = Date.now(); }
  connectedCallback() { super.connectedCallback(); this.timer = setInterval(() => (this.now = Date.now()), 60_000); }
  disconnectedCallback() { super.disconnectedCallback(); if (this.timer) clearInterval(this.timer); }
  updated() {
    // first time the divider appears, bring it near the top (a few past rows stay visible above it)
    const el = this.renderRoot.querySelector('.now') as HTMLElement | null;
    if (!el || this.scrolled) return;
    this.scrolled = true;
    this.scrollTop = Math.max(0, el.offsetTop - 140);
  }

  private time(ev: CalEvent) {
    const s = ev.start < this.from && !isSameDay(ev.start, this.from) ? fmt.dateTime(ev.start) : fmt.time(ev.start);
    return `${s}${ev.end ? ' – ' + fmt.time(ev.end) : ''}`;
  }

  private nowLine(): TemplateResult {
    return html`<div class="now"><span class="dot"></span><span class="lbl">Adesso · ${fmt.time(new Date(this.now))}</span><span class="line"></span></div>`;
  }

  private row(ev: CalEvent) {
    const o = outcome(ev, this.now), past = (ev.end ?? ev.start).getTime() < this.now;
    const meta = TYPE_META[ev.occ.type];
    return html`<button class="row ${past ? 'past' : ''} ${ev.occ.skipped ? 'skipped' : ''} ${ev.occ.status === 'completed' || ev.occ.status === 'cancelled' ? 'done' : ''}"
        @click=${(e: Event) => fire(this, 'cal-select', { ev, rect: (e.currentTarget as HTMLElement).getBoundingClientRect() })}>
      <span class="time">${this.time(ev)}</span>
      <span class="bar" style="background:${ev.color}"></span>
      <span class="main">
        <span class="title">${ic(meta?.icon ?? 'event', 14)} ${ev.occ.title}</span>
        ${this.evWx(ev)}
        <span class="meta">${ownerLabel(ev.occ.owner)} · ${meta?.label ?? ev.occ.type}${ev.occ.recurring ? ` · ${describeRRule(ev.item?.recurrence)}` : ''}</span>
        ${o?.detail ? html`<span class="detail ${o.tone === 'danger' ? 'err' : ''}" title=${o.detail}>${o.detail}</span>` : nothing}
      </span>
      ${o ? html`<hxk-badge tone=${o.tone}>${o.label}</hxk-badge>` : nothing}
    </button>`;
  }

  /** Weather at the place and hour of an item that has one (e.g. a planned run). */
  private evWx(ev: CalEvent) {
    const w = this.weather.events[ev.id];
    if (!w?.hour) return nothing;
    const wet = ['rain', 'drizzle', 'storm', 'snow'].includes(w.hour.icon);
    return html`<span class="wx"><hxk-icon name=${w.hour.icon || 'cloud'} size=${13} tone=${wet ? 'info' : 'warning'}></hxk-icon>${w.place ? w.place + ': ' : ''}${w.hour.temp_c}°, ${w.hour.condition}${w.hour.rain_prob ? ` (pioggia ${w.hour.rain_prob}%)` : ''}</span>`;
  }

  render() {
    const groups = groupByDay(this.events, this.from, this.now);
    if (!groups.length) return html`<hxk-state kind="empty" text="Niente in programma: nessuna voce nel periodo con i filtri attuali."></hxk-state>`;
    return groups.map(g => html`${g.nowBefore ? this.nowLine() : nothing}
      <section><h3 class=${g.today ? 'today' : ''}>${g.label}${wxChip(this.weather.days[g.key], extLines(this.weather, g.key))}</h3>
        ${g.events.map(ev => html`${g.nowAt === ev.id ? this.nowLine() : nothing}${this.row(ev)}`)}
        ${g.nowAfter ? this.nowLine() : nothing}</section>`);
  }
}
