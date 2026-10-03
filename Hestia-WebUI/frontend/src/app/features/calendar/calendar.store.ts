import { Injectable, computed, inject, signal } from '@angular/core';
import { AgendaApi } from './agenda.api';
import { AgendaItem, AgendaOccurrence, AgendaType, CalEvent, CalView, CalendarSource } from './calendar.models';
import { DAY_MS, addDays, addMonths, monthGrid, startOfDay, startOfWeek } from './date-utils';
import { shiftByDay } from './rrule';
import { ToastService } from '../../ui';

const PREFS_KEY = 'hestia_calendar_prefs';
const FIXED_COLORS: Record<string, number> = { user: 1, hephaestus: 2, athena: 4, scout: 3, chronos: 6, metis: 5, argus: 7 };

/** State of the calendar page (signals). Views read; actions go through here. */
@Injectable({ providedIn: 'root' })
export class CalendarStore {
  private api = inject(AgendaApi);
  private toast = inject(ToastService);

  // ── view state ─────────────────────────────────────────────────────────
  // Phones: week columns are too narrow → start on the day view.
  readonly view = signal<CalView>(window.innerWidth < 720 && (this.prefs().view ?? 'week') === 'week' ? 'day' : (this.prefs().view ?? 'week'));
  readonly anchor = signal<Date>(startOfDay(new Date()));
  readonly hiddenOwners = signal<Set<string>>(new Set(this.prefs().hiddenOwners ?? []));
  readonly hiddenTypes = signal<Set<AgendaType>>(new Set(this.prefs().hiddenTypes ?? []));
  readonly showSkipped = signal<boolean>(this.prefs().showSkipped ?? true);
  readonly showDone = signal<boolean>(this.prefs().showDone ?? false);
  readonly search = signal('');
  /** Layers: only the AI agenda today; external calendars will be added here. */
  readonly sources = signal<CalendarSource[]>([{ id: 'hestia', label: 'Agenda di Hestia', kind: 'ai', enabled: true }]);

  // ── data ───────────────────────────────────────────────────────────────
  readonly occurrences = signal<AgendaOccurrence[]>([]);
  readonly items = signal<Map<string, AgendaItem>>(new Map());
  readonly loading = signal(false);
  readonly error = signal('');
  private loadSeq = 0;

  readonly range = computed<{ start: Date; end: Date }>(() => {
    const a = this.anchor();
    switch (this.view()) {
      case 'month': { const g = monthGrid(a); return { start: g[0], end: addDays(g[41], 1) }; }
      case 'week': { const s = startOfWeek(a); return { start: s, end: addDays(s, 7) }; }
      case 'day': return { start: startOfDay(a), end: addDays(startOfDay(a), 1) };
      case 'list': return { start: startOfDay(a), end: addDays(startOfDay(a), 31) };
    }
  });

  readonly owners = computed(() => {
    const set = new Map<string, number>();
    for (const it of this.items().values()) set.set(it.owner, (set.get(it.owner) ?? 0) + 1);
    for (const o of this.occurrences()) if (!set.has(o.owner)) set.set(o.owner, 0);
    return [...set.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([owner, count]) => ({ owner, count, color: this.colorFor(owner) }));
  });

  readonly events = computed<CalEvent[]>(() => {
    const items = this.items();
    const hidO = this.hiddenOwners(), hidT = this.hiddenTypes();
    const q = this.search().trim().toLowerCase();
    if (!this.sources().find(s => s.id === 'hestia')?.enabled) return [];
    return this.occurrences()
      .filter(o => !hidO.has(o.owner) && !hidT.has(o.type))
      .filter(o => this.showSkipped() || !o.skipped)
      .filter(o => this.showDone() || !['completed', 'cancelled'].includes(o.status ?? ''))
      .filter(o => !q || o.title.toLowerCase().includes(q) || o.key.toLowerCase().includes(q) || o.owner.includes(q))
      .map(o => ({
        id: `${o.key}|${o.occurrence}`, occ: o, item: items.get(o.key),
        start: new Date(o.start), end: o.end ? new Date(o.end) : null,
        color: this.colorFor(o.owner), source: 'hestia',
      }));
  });

  readonly title = computed(() => {
    const a = this.anchor();
    const r = this.range();
    const fmtMonth = (d: Date) => d.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' });
    switch (this.view()) {
      case 'month': return cap(fmtMonth(a));
      case 'day': return cap(a.toLocaleDateString('it-IT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }));
      case 'week': {
        const e = addDays(r.end, -1);
        return r.start.getMonth() === e.getMonth()
          ? `${r.start.getDate()}–${e.getDate()} ${e.toLocaleDateString('it-IT', { month: 'long', year: 'numeric' })}`
          : `${r.start.toLocaleDateString('it-IT', { day: 'numeric', month: 'short' })} – ${e.toLocaleDateString('it-IT', { day: 'numeric', month: 'short', year: 'numeric' })}`;
      }
      case 'list': return `Dal ${a.toLocaleDateString('it-IT', { day: 'numeric', month: 'long' })}`;
    }
  });

  // ── navigation ─────────────────────────────────────────────────────────
  setView(v: CalView) { this.view.set(v); this.savePrefs(); void this.load(); }
  today() { this.anchor.set(startOfDay(new Date())); void this.load(); }
  goto(d: Date) { this.anchor.set(startOfDay(d)); void this.load(); }
  step(dir: 1 | -1) {
    const a = this.anchor();
    const next = { month: addMonths(a, dir), week: addDays(a, 7 * dir), day: addDays(a, dir), list: addDays(a, 30 * dir) }[this.view()];
    this.anchor.set(next);
    void this.load();
  }
  toggleOwner(o: string) { this.hiddenOwners.update(s => toggled(s, o)); this.savePrefs(); }
  onlyOwner(o: string) { this.hiddenOwners.set(new Set(this.owners().map(x => x.owner).filter(x => x !== o))); this.savePrefs(); }
  toggleType(t: AgendaType) { this.hiddenTypes.update(s => toggled(s, t)); this.savePrefs(); }
  setShowSkipped(v: boolean) { this.showSkipped.set(v); this.savePrefs(); }
  setShowDone(v: boolean) { this.showDone.set(v); this.savePrefs(); }

  colorFor(owner: string): string {
    const fixed = FIXED_COLORS[owner];
    if (fixed) return `var(--cal-${fixed})`;
    let h = 0;
    for (const c of owner) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return `var(--cal-${(h % 8) + 1})`;
  }

  // ── data loading ───────────────────────────────────────────────────────
  async load(): Promise<void> {
    const seq = ++this.loadSeq;
    const { start, end } = this.range();
    this.loading.set(true);
    this.error.set('');
    try {
      const [occ, items] = await Promise.all([this.api.occurrences(start, end), this.api.items()]);
      if (seq !== this.loadSeq) return;
      this.occurrences.set(occ);
      this.items.set(new Map(items.map(i => [i.key, i])));
    } catch (e: any) {
      if (seq === this.loadSeq) this.error.set(e?.error?.detail || e?.message || 'Agenda non raggiungibile');
    } finally {
      if (seq === this.loadSeq) this.loading.set(false);
    }
  }

  // ── actions (each reloads; errors → toast) ─────────────────────────────
  private async act<T>(fn: () => Promise<T>, ok?: string, undo?: () => Promise<unknown>): Promise<T | null> {
    try {
      const r = await fn();
      if (ok) this.toast.show(ok, 'success', undo ? { label: 'Annulla', run: () => void undo().then(() => this.load()) } : undefined);
      await this.load();
      return r;
    } catch (e: any) {
      this.toast.error(e?.error?.detail || e?.message || 'Operazione non riuscita');
      return null;
    }
  }

  create(body: Record<string, unknown>) {
    return this.act(() => this.api.create(body as never), 'Aggiunto all\'agenda');
  }
  update(key: string, changes: Record<string, unknown>, msg = 'Aggiornato') {
    return this.act(() => this.api.update(key, changes), msg);
  }
  cancel(ev: CalEvent) {
    return this.act(() => this.api.cancel(ev.occ.key), 'Regola annullata',
      () => this.api.update(ev.occ.key, { status: 'confirmed' }));
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
    if (r) r.ok ? this.toast.success('Eseguito') : this.toast.error(`Esecuzione fallita: ${r.detail}`);
  }
  resetMove(ev: CalEvent) {
    return this.act(() => this.api.move(ev.occ.key, ev.occ.occurrence, null, null, true), 'Orario originale ripristinato');
  }

  /** Move an occurrence: 'one' = exception for this occurrence, 'all' = shift the whole rule. */
  async move(ev: CalEvent, newStart: Date, newEnd: Date | null, scope: 'one' | 'all') {
    const delta = newStart.getTime() - ev.start.getTime();
    const durationChange = newEnd && ev.end ? (newEnd.getTime() - ev.end.getTime()) - delta : 0;
    if (scope === 'one' || !ev.occ.recurring || !ev.item) {
      return this.act(() => this.api.move(ev.occ.key, ev.occ.occurrence, newStart.toISOString(),
        newEnd ? newEnd.toISOString() : null), 'Spostato');
    }
    const it = ev.item;
    const s0 = new Date(it.start_at);
    const changes: Record<string, unknown> = { start_at: new Date(s0.getTime() + delta).toISOString() };
    if (it.end_at) changes['end_at'] = new Date(new Date(it.end_at).getTime() + delta + durationChange).toISOString();
    const dayShift = Math.round((startOfDay(newStart).getTime() - startOfDay(ev.start).getTime()) / DAY_MS);
    if (dayShift && it.recurrence?.includes('BYDAY')) changes['recurrence'] = shiftByDay(it.recurrence, dayShift);
    return this.update(it.key, changes, 'Serie spostata');
  }

  // ── prefs ──────────────────────────────────────────────────────────────
  private prefs(): { view?: CalView; hiddenOwners?: string[]; hiddenTypes?: AgendaType[]; showSkipped?: boolean; showDone?: boolean } {
    try { return JSON.parse(localStorage.getItem(PREFS_KEY) || '{}'); } catch { return {}; }
  }
  private savePrefs() {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify({
        view: this.view(), hiddenOwners: [...this.hiddenOwners()], hiddenTypes: [...this.hiddenTypes()],
        showSkipped: this.showSkipped(), showDone: this.showDone(),
      }));
    } catch { /* private mode */ }
  }
}

function toggled<T>(s: Set<T>, v: T): Set<T> { const n = new Set(s); n.has(v) ? n.delete(v) : n.add(v); return n; }
function cap(s: string) { return s.charAt(0).toUpperCase() + s.slice(1); }
