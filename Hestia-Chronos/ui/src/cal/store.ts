/**
 * State of the calendar page (plain class, the page re-renders on `onChange`). Views read the derived
 * `events()` / `hiddenByPolicy()` (memoised per state version); actions reload and toast. Ported from the
 * WebUI CalendarStore (signals → version counter).
 */
import type { HestiaHost } from '@hestia/webui-sdk';
import { AgendaApi, type TemplateBody } from './api';
import type { AgendaItem, AgendaOccurrence, AgendaType, CalEvent, CalView, CalWeather, CalendarSource, EventClass } from './models';
import { NO_WEATHER, colorFor } from './models';
import { DAY_MS, addDays, addMonths, dayKey, monthGrid, startOfDay, startOfWeek } from './date';
import { type CalendarPrefs, DEFAULT_PREFS, type SavedPrefs, perDayFromRRule, savePrefs } from './prefs';
import { shiftByDay } from './rrule';

export class CalStore {
  readonly api: AgendaApi;
  // view state
  view: CalView = 'week';
  anchor: Date = startOfDay(new Date());
  hiddenOwners = new Set<string>();
  hiddenTypes = new Set<AgendaType>();
  showSkipped = true;
  showDone = false;
  search = '';
  vp: CalendarPrefs = { ...DEFAULT_PREFS };
  sideW = 256;
  /** Layers: only the AI agenda today; external calendars will be added here. */
  sources: CalendarSource[] = [{ id: 'hestia', label: 'Agenda di Hestia', kind: 'ai', enabled: true }];
  // data
  occurrences: AgendaOccurrence[] = [];
  /** Weather of the visible range (empty when the weather service is away or the range is past/far). */
  weather: CalWeather = NO_WEATHER;
  items = new Map<string, AgendaItem>();
  loading = false;
  error = '';
  offline = false;
  loaded = false;

  private seq = 0;
  private version = 0;
  private memo: { v: number; events: CalEvent[]; hidden: number } | null = null;

  constructor(private host: HestiaHost, private onChange: () => void) { this.api = new AgendaApi(host); }

  /** Apply saved prefs (phones start on the day view instead of the week). */
  applyPrefs(p: SavedPrefs, phone: boolean) {
    const v = p.view ?? 'week';
    this.view = phone && v === 'week' ? 'day' : v;
    this.hiddenOwners = new Set(p.hiddenOwners ?? []);
    this.hiddenTypes = new Set(p.hiddenTypes ?? []);
    this.showSkipped = p.showSkipped ?? true;
    this.showDone = p.showDone ?? false;
    this.vp = { ...DEFAULT_PREFS, ...(p.vp ?? {}) };
    if (p.sideW) this.sideW = p.sideW;
    this.changed();
  }

  changed() { this.version++; this.onChange(); }
  private save() {
    void savePrefs(this.host, { view: this.view, hiddenOwners: [...this.hiddenOwners], hiddenTypes: [...this.hiddenTypes],
      showSkipped: this.showSkipped, showDone: this.showDone, vp: this.vp, sideW: this.sideW });
  }

  range(): { start: Date; end: Date } {
    const a = this.anchor;
    switch (this.view) {
      case 'month': { const g = monthGrid(a); return { start: g[0], end: addDays(g[41], 1) }; }
      case 'week': { const s = startOfWeek(a); return { start: s, end: addDays(s, 7) }; }
      case 'day': return { start: startOfDay(a), end: addDays(startOfDay(a), 1) };
      default: return { start: startOfDay(a), end: addDays(startOfDay(a), 31) };
    }
  }

  owners(): { owner: string; count: number; color: string }[] {
    const set = new Map<string, number>();
    for (const it of this.items.values()) set.set(it.owner, (set.get(it.owner) ?? 0) + 1);
    for (const o of this.occurrences) if (!set.has(o.owner)) set.set(o.owner, 0);
    return [...set.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([owner, count]) => ({ owner, count, color: colorFor(owner) }));
  }

  /** Occurrences per day of each rule (frequent ≥ vp.frequentPerDay). */
  private perDay(): Map<string, number> {
    const out = new Map<string, number>();
    const counted = new Map<string, Map<string, number>>();
    for (const o of this.occurrences) {
      const m = counted.get(o.key) ?? counted.set(o.key, new Map()).get(o.key)!;
      const k = dayKey(new Date(o.start));
      m.set(k, (m.get(k) ?? 0) + 1);
    }
    for (const [key, days] of counted) out.set(key, perDayFromRRule(this.items.get(key)?.recurrence) ?? Math.max(...days.values()));
    return out;
  }

  private classOf(o: AgendaOccurrence, perDay: Map<string, number>, item?: AgendaItem): EventClass {
    if ((o.created_by ?? item?.created_by) === 'user' || o.owner === 'user') return 'manual';
    if (!o.recurring) return 'oneoff';
    return (perDay.get(o.key) ?? 0) >= this.vp.frequentPerDay ? 'frequent' : 'rare';
  }

  /** All occurrences as view models, after filters (owner/type/search/skip/done) — no visibility policy. */
  private allEvents(): CalEvent[] {
    const vp = this.vp, q = this.search.trim().toLowerCase();
    if (!this.sources.find(s => s.id === 'hestia')?.enabled) return [];
    const perDay = this.perDay();
    return this.occurrences
      .filter(o => !this.hiddenOwners.has(o.owner) && !this.hiddenTypes.has(o.type))
      .filter(o => this.showSkipped || !o.skipped)
      .filter(o => this.showDone || !['completed', 'cancelled'].includes(o.status ?? ''))
      .filter(o => !q || o.title.toLowerCase().includes(q) || o.key.toLowerCase().includes(q) || o.owner.includes(q))
      .filter(o => vp.windowsMode !== 'hidden' || o.type !== 'window')
      .map(o => {
        const item = this.items.get(o.key);
        return { id: `${o.key}|${o.occurrence}`, occ: o, item, start: new Date(o.start), end: o.end ? new Date(o.end) : null,
                 color: colorFor(o.owner), source: 'hestia', cls: this.classOf(o, perDay, item) } as CalEvent;
      })
      .filter(e => vp.frequentMode !== 'hidden' || e.cls !== 'frequent' || e.occ.run?.ok === false);
  }

  /** Visibility policy (focused view) + clip to the visible range. */
  private visible(): { events: CalEvent[]; hidden: number } {
    if (this.memo && this.memo.v === this.version) return this.memo;
    const all = this.allEvents();
    const { start: rs, end: re } = this.range();
    const inRange = (e: CalEvent) => e.start < re && (e.end ?? e.start) >= rs;
    const vp = this.vp;
    let res: { events: CalEvent[]; hidden: number };
    if (!vp.focused) res = { events: all.filter(inRange), hidden: 0 };
    else {
      const now = Date.now();
      const fd0 = startOfDay(this.anchor).getTime(), fd1 = fd0 + DAY_MS;
      const onFocus = (e: CalEvent) => e.start.getTime() < fd1 && (e.end ?? e.start).getTime() >= fd0;
      // rare rules: cutoff = min(now + rareDays, start of the N-th upcoming occurrence)
      const upcoming = new Map<string, number[]>();
      for (const e of all) {
        if (e.cls !== 'rare' || (e.end ?? e.start).getTime() < now) continue;
        (upcoming.get(e.occ.key) ?? upcoming.set(e.occ.key, []).get(e.occ.key)!).push(e.start.getTime());
      }
      const cutoff = new Map<string, number>();
      for (const [k, starts] of upcoming) {
        starts.sort((a, b) => a - b);
        const nth = starts[Math.min(starts.length, vp.rareCount) - 1] ?? Infinity;
        cutoff.set(k, Math.min(now + vp.rareDays * DAY_MS, nth));
      }
      const pastFailed = new Map<string, CalEvent>();
      const out: CalEvent[] = [];
      let hidden = 0;
      for (const e of all) {
        const visibleNow = inRange(e);
        let keep: boolean;
        if (e.cls === 'manual' || onFocus(e)) keep = true;
        else if ((e.end ?? e.start).getTime() < now) {
          const failed = e.occ.run?.ok === false || (!e.occ.recurring && e.occ.status === 'failed');
          keep = false;
          if (failed && (e.end ?? e.start).getTime() >= now - vp.pastDays * DAY_MS) {
            const prev = pastFailed.get(e.occ.key);
            if (!prev || prev.start < e.start) pastFailed.set(e.occ.key, { ...e, failedCount: (prev?.failedCount ?? 0) + 1 });
            else prev.failedCount = (prev.failedCount ?? 1) + 1;
            continue;
          }
        } else if (e.cls === 'oneoff') keep = true;
        else if (e.cls === 'frequent') keep = e.start.getTime() <= now + vp.frequentDays * DAY_MS;
        else keep = e.start.getTime() <= (cutoff.get(e.occ.key) ?? now + vp.rareDays * DAY_MS);
        if (!visibleNow) continue;
        if (keep) out.push(e);
        else if ((e.end ?? e.start).getTime() >= now) hidden++;   // the hint counts upcoming items only
      }
      for (const e of pastFailed.values()) if (inRange(e)) out.push(e);
      res = { events: out, hidden };
    }
    this.memo = { v: this.version, ...res };
    return res;
  }

  events(): CalEvent[] { return this.visible().events; }
  /** Upcoming occurrences in the visible range hidden by the focused view ("N nascoste"). */
  hiddenByPolicy(): number { return this.visible().hidden; }

  title(): string {
    const a = this.anchor, r = this.range();
    switch (this.view) {
      case 'month': return cap(a.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' }));
      case 'day': return cap(a.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }));
      case 'week': {
        const e = addDays(r.end, -1);
        return r.start.getMonth() === e.getMonth()
          ? `${r.start.getDate()}–${e.getDate()} ${e.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' })}`
          : `${r.start.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })} – ${e.toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric' })}`;
      }
      default: return `Dal ${a.toLocaleDateString('it-IT', { day: 'numeric', month: 'long' })}`;
    }
  }

  // ── navigation ─────────────────────────────────────────────────────────
  setView(v: CalView) { this.view = v; this.save(); this.changed(); void this.load(); }
  today() { this.anchor = startOfDay(new Date()); this.changed(); void this.load(); }
  goto(d: Date) { this.anchor = startOfDay(d); this.changed(); void this.load(); }
  step(dir: 1 | -1) {
    const a = this.anchor;
    this.anchor = { month: addMonths(a, dir), week: addDays(a, 7 * dir), day: addDays(a, dir), list: addDays(a, 30 * dir) }[this.view];
    this.changed(); void this.load();
  }
  setSearch(q: string) { this.search = q; this.changed(); }
  toggleSource(id: string) { this.sources = this.sources.map(s => s.id === id ? { ...s, enabled: !s.enabled } : s); this.changed(); }
  toggleOwner(o: string) { this.hiddenOwners = toggled(this.hiddenOwners, o); this.save(); this.changed(); }
  onlyOwner(o: string) { this.hiddenOwners = new Set(this.owners().map(x => x.owner).filter(x => x !== o)); this.save(); this.changed(); }
  toggleType(t: AgendaType) { this.hiddenTypes = toggled(this.hiddenTypes, t); this.save(); this.changed(); }
  setShowSkipped(v: boolean) { this.showSkipped = v; this.save(); this.changed(); }
  setShowDone(v: boolean) { this.showDone = v; this.save(); this.changed(); }
  setSideW(w: number) { this.sideW = w; this.save(); this.changed(); }
  setVp(p: Partial<CalendarPrefs>) {
    const reload = p.focused !== undefined || p.pastDays !== undefined || p.frequentDays !== undefined || p.rareDays !== undefined;
    this.vp = { ...this.vp, ...p };
    this.save(); this.changed();
    if (reload) void this.load();
  }
  resetVp() { this.vp = { ...DEFAULT_PREFS }; this.save(); this.changed(); void this.load(); }
  /** Mini calendar / day number: focus a day. Month view jumps to that day (otherwise nothing visibly changes). */
  focusDay(d: Date) {
    this.anchor = startOfDay(d);
    if (this.view === 'month') { this.view = 'day'; this.save(); }
    this.changed(); void this.load();
  }

  // ── data loading ───────────────────────────────────────────────────────
  async load(): Promise<void> {
    const seq = ++this.seq;
    let { start, end } = this.range();
    if (this.vp.focused) {
      // the policy needs "now ± horizon" even when looking elsewhere (rare: N-th upcoming, past failures)
      const vp = this.vp, now = Date.now();
      start = new Date(Math.min(start.getTime(), now - vp.pastDays * DAY_MS));
      end = new Date(Math.max(end.getTime(), now + Math.max(vp.frequentDays, vp.rareDays) * DAY_MS));
    }
    this.loading = true; this.error = ''; this.onChange();
    try {
      const [occ, items] = await Promise.all([this.api.occurrences(start, end), this.api.items()]);
      if (seq !== this.seq) return;
      this.occurrences = occ;
      this.items = new Map(items.map(i => [i.key, i]));
      this.offline = false; this.loaded = true;
      void this.loadWeather(seq);
    } catch (e: any) {
      if (seq === this.seq) { this.error = e?.message || 'Chronos non raggiungibile'; this.offline = !!e?.offline; }
    } finally {
      if (seq === this.seq) { this.loading = false; this.changed(); }
    }
  }

  /** Weather after the occurrences (never blocks the calendar): items with `params.place` get their own. */
  private async loadWeather(seq: number) {
    const { start, end } = this.range();
    const located = this.occurrences.flatMap(o => {
      const place = this.items.get(o.key)?.params?.['place'];
      return typeof place === 'string' && place ? [{ key: `${o.key}|${o.occurrence}`, place, at: o.start }] : [];
    });
    try {
      const w = await this.api.weather(start, end, located);
      if (seq !== this.seq) return;
      this.weather = { days: w?.days ?? {}, events: w?.events ?? {}, external: w?.external ?? [] };
      this.changed();
    } catch { /* no weather: the calendar works as before */ }
  }

  // ── actions (each reloads; errors → toast) ─────────────────────────────
  private async act<T>(fn: () => Promise<T>, ok?: string, undo?: () => Promise<unknown>): Promise<T | null> {
    try {
      const r = await fn();
      if (ok) this.host.toast(ok, 'success', undo ? { label: 'Annulla', run: () => void undo().then(() => this.load()) } : undefined);
      await this.load();
      return r;
    } catch (e: any) {
      this.host.toast(e?.message || 'Operazione non riuscita', 'danger');
      return null;
    }
  }

  create(body: Record<string, unknown>) { return this.act(() => this.api.create(body), 'Aggiunto all\'agenda'); }
  createFromTemplate(owner: string, id: string, body: TemplateBody) { return this.act(() => this.api.fromTemplate(owner, id, body), 'Creato dal modulo'); }
  update(key: string, changes: Record<string, unknown>, msg = 'Aggiornato') { return this.act(() => this.api.update(key, changes), msg); }
  cancel(ev: CalEvent) {
    return this.act(() => this.api.cancel(ev.occ.key), 'Regola annullata', () => this.api.update(ev.occ.key, { status: 'confirmed' }));
  }
  skip(ev: CalEvent) {
    return this.act(() => this.api.skip(ev.occ.key, ev.occ.occurrence), 'Occorrenza saltata',
      ev.occ.recurring ? () => this.api.unskip(ev.occ.key, ev.occ.occurrence) : undefined);
  }
  unskip(ev: CalEvent) { return this.act(() => this.api.unskip(ev.occ.key, ev.occ.occurrence), 'Occorrenza ripristinata'); }
  pause(ev: CalEvent, paused: boolean) {
    return this.update(ev.occ.key, { status: paused ? 'paused' : 'confirmed' }, paused ? 'In pausa' : 'Riattivato');
  }
  async run(ev: CalEvent) {
    const r = await this.act(() => this.api.run(ev.occ.key));
    if (r) this.host.toast(r.ok ? 'Eseguito' : `Esecuzione fallita: ${r.detail}`, r.ok ? 'success' : 'danger');
  }
  resetMove(ev: CalEvent) {
    return this.act(() => this.api.move(ev.occ.key, ev.occ.occurrence, null, null, true), 'Orario originale ripristinato');
  }

  /** Move an occurrence: 'one' = exception for this occurrence, 'all' = shift the whole rule. */
  async move(ev: CalEvent, newStart: Date, newEnd: Date | null, scope: 'one' | 'all') {
    const delta = newStart.getTime() - ev.start.getTime();
    const durationChange = newEnd && ev.end ? (newEnd.getTime() - ev.end.getTime()) - delta : 0;
    if (scope === 'one' || !ev.occ.recurring || !ev.item) {
      return this.act(() => this.api.move(ev.occ.key, ev.occ.occurrence, newStart.toISOString(), newEnd ? newEnd.toISOString() : null), 'Spostato');
    }
    const it = ev.item;
    const s0 = new Date(it.start_at);
    const changes: Record<string, unknown> = { start_at: new Date(s0.getTime() + delta).toISOString() };
    if (it.end_at) changes['end_at'] = new Date(new Date(it.end_at).getTime() + delta + durationChange).toISOString();
    const dayShift = Math.round((startOfDay(newStart).getTime() - startOfDay(ev.start).getTime()) / DAY_MS);
    if (dayShift && it.recurrence?.includes('BYDAY')) changes['recurrence'] = shiftByDay(it.recurrence, dayShift);
    return this.update(it.key, changes, 'Serie spostata');
  }
}

function toggled<T>(s: Set<T>, v: T): Set<T> { const n = new Set(s); n.has(v) ? n.delete(v) : n.add(v); return n; }
function cap(s: string) { return s.charAt(0).toUpperCase() + s.slice(1); }
