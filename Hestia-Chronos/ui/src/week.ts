/**
 * <chronos-week> — «La tua settimana»: the weekly plan the coaches asked for, placed in the free time around the
 * calendar. Seven columns (one day at a time on a phone), blocks with their area's icon, slots as chips, targets,
 * «Non entra», last week's review. Drag a block to another day (or «Sposta») = the user's move, never undone.
 * SPEC docs/work/2026-10-20-coach-di-ogni-tipo §6. Endpoints: /api/agenda/coach/*.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API } from './util';

const C = `${API}/coach`;
/** Area icon from the coach's domain (generic: unknown domains get the target icon). */
const DOMAIN_ICON: Record<string, string> = { fitness: 'dumbbell', selfcare: 'heart', finance: 'wallet', wardrobe: 'shirt' };
export const areaIcon = (domain?: string) => DOMAIN_ICON[domain || ''] || 'target';
const STATUS: Record<string, { text: string; tone: string }> = {
  done: { text: 'fatto', tone: 'success' }, skipped: { text: 'saltato', tone: 'neutral' },
};

export const hhmm = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : '';
const dayLabel = (iso: string) => new Date(`${iso}T12:00:00`).toLocaleDateString('it-IT', { weekday: 'short', day: 'numeric' });
const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const addDays = (iso: string, n: number) => { const d = new Date(`${iso}T12:00:00`); d.setDate(d.getDate() + n); return isoDay(d); };
/** Local wall time `YYYY-MM-DDTHH:MM` → ISO with the browser's offset (Chronos reads any offset). */
function localIso(value: string): string {
  const d = new Date(value);
  const off = -d.getTimezoneOffset(), sign = off >= 0 ? '+' : '-', a = Math.abs(off);
  return `${value.length === 16 ? `${value}:00` : value}${sign}${String(Math.floor(a / 60)).padStart(2, '0')}:${String(a % 60).padStart(2, '0')}`;
}
/** hxk-button lives in its own shadow root and cannot submit a form: submit the closest one by hand. */
const submit = (e: Event) => (e.currentTarget as HTMLElement).closest('form')?.requestSubmit();
const wall = (iso: string) => { const d = new Date(iso); return `${isoDay(d)}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; };

export class ChronosWeek extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, error: { state: true }, ref: { state: true },
                        day: { state: true }, busy: { state: true }, editing: { state: true }, adding: { state: true },
                        review: { state: true }, over: { state: true } };
  declare data: any; declare error: string; declare ref: string; declare day: string; declare busy: string;
  declare editing: string; declare adding: boolean; declare review: any[] | null; declare over: string;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .text { color: var(--text-2); font-size: 14px; line-height: 1.45; white-space: pre-line; }
    .grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 8px; }
    .col { display: flex; flex-direction: column; gap: 6px; min-height: 120px; padding: 8px; border-radius: var(--radius-md);
      border: 1px solid var(--border); background: var(--surface); }
    .col.today { border-color: var(--accent); }
    .col.over { background: var(--accent-soft); }
    .dh { font-size: 12.5px; font-weight: 600; color: var(--text-2); text-transform: capitalize; }
    .b { display: flex; flex-direction: column; gap: 3px; padding: 6px 8px; border-radius: var(--radius-sm);
      background: var(--surface-2); border-left: 3px solid var(--accent); cursor: grab; }
    .b.done { border-left-color: var(--success); opacity: .8; }
    .b.skipped { border-left-color: var(--border-strong); opacity: .6; text-decoration: line-through; }
    .b .t { font-size: 13px; font-weight: 550; overflow-wrap: anywhere; display: flex; gap: 5px; align-items: center; }
    .b .m { font-size: 11.5px; color: var(--text-3); font-variant-numeric: tabular-nums; }
    .busyb { font-size: 11.5px; color: var(--text-3); padding: 4px 6px; border: 1px dashed var(--border-strong); border-radius: var(--radius-sm);
      display: flex; gap: 4px; align-items: center; }
    .chips { display: flex; gap: 4px; flex-wrap: wrap; }
    .chip { font: inherit; font-size: 12px; padding: 2px 8px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); display: inline-flex; gap: 4px; align-items: center; }
    button.chip { cursor: pointer; }
    button.chip[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
    .acts { display: flex; gap: 4px; flex-wrap: wrap; }
    .days { display: none; }
    .r { display: flex; gap: 8px; align-items: flex-start; padding: 8px 0; border-top: 1px solid var(--border); }
    .r:first-child { border-top: 0; }
    .bar { height: 6px; border-radius: 99px; background: var(--surface-2); overflow: hidden; }
    .bar > span { display: block; height: 100%; background: var(--accent); }
    .bar.over > span { background: var(--danger); }
    form { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; }
    label { display: flex; flex-direction: column; gap: 3px; font-size: 12px; color: var(--text-2); }
    input { font: inherit; padding: 6px 8px; border-radius: var(--radius-sm); border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text); }
    @media (max-width: 760px) {
      .grid { grid-template-columns: 1fr; }
      .grid .col:not(.sel) { display: none; }
      .days { display: flex; gap: 4px; overflow-x: auto; }
    }
  `];

  constructor() {
    super(); this.data = null; this.error = ''; this.ref = ''; this.day = isoDay(new Date()); this.busy = '';
    this.editing = ''; this.adding = false; this.review = null; this.over = '';
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const r = await this.host.api('GET', `${C}/week`, { query: this.ref ? { date: this.ref } : {} });
    if (!r.ok) { this.error = r.status === 0 ? 'Non disponibile' : r.error || 'Non disponibile'; return; }
    this.error = ''; this.data = r.data;
    if (!r.data.days.some((d: any) => d.date === this.day)) this.day = r.data.days[0]?.date || this.day;
    if (this.review === null) this.loadReview();
  }

  private async loadReview() {
    const r = await this.host.api('GET', `${C}/review`, { query: this.data ? { date: this.data.start } : {} });
    this.review = r.ok && Array.isArray(r.data?.modules) ? r.data.modules : [];
  }

  private week(n: number) {
    const start = this.data?.start || isoDay(new Date());
    this.ref = addDays(start, 7 * n); this.data = null; this.review = null; this.load();
  }

  private async act(id: string, method: 'POST' | 'DELETE', path: string, body?: unknown, ok?: string) {
    this.busy = id;
    const r = await this.host.api(method, path, body === undefined ? {} : { body });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return false; }
    if (ok) this.host.toast(ok, 'success');
    await this.load();
    return true;
  }

  private replan() {
    return this.act('replan', 'POST', `${C}/replan`, {}, 'Piano rifatto per i prossimi giorni');
  }

  private move(i: any, startAt: string) {
    const mins = Number(i.minutes) || 0;
    const end = mins ? new Date(new Date(startAt).getTime() + mins * 60000).toISOString() : undefined;
    return this.act(i.key, 'POST', `${C}/items/${encodeURIComponent(i.key)}/move`, { start_at: startAt, end_at: end },
                    `${i.title}: spostato`);
  }

  private skip(i: any) {
    return this.act(i.key, 'POST', `${C}/items/${encodeURIComponent(i.key)}/skip`, {}, `${i.title}: saltato`);
  }

  private onDrop(e: DragEvent, date: string) {
    e.preventDefault(); this.over = '';
    const key = e.dataTransfer?.getData('text/plain');
    const i = this.data?.days.flatMap((d: any) => d.items).find((x: any) => x.key === key);
    if (!i || i.date === date || !i.start_at) return;
    const t = new Date(i.start_at);
    this.move(i, localIso(`${date}T${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`));
  }

  private async addBusy(e: Event) {
    e.preventDefault();
    const f = new FormData(e.target as HTMLFormElement);
    const date = String(f.get('date') || ''), from = String(f.get('from') || ''), to = String(f.get('to') || '');
    if (!date || !from || !to || to <= from) { this.host.toast('Indica giorno, inizio e fine', 'warning'); return; }
    const ok = await this.act('busy', 'POST', `${C}/busy`, { start_at: localIso(`${date}T${from}`), end_at: localIso(`${date}T${to}`),
                                                            title: String(f.get('title') || '') }, 'Impegno aggiunto: piano rifatto');
    if (ok) this.adding = false;
  }

  private open(link: string, module: string) {
    if (link) this.host.navigate(link, {}, module);
  }

  private renderItem(i: any) {
    const st = STATUS[i.status];
    if (i.kind === 'slot') {
      return html`<span class="chip" title=${i.reason || ''}><hxk-icon name=${areaIcon(i.domain)} size="12"></hxk-icon>${i.title}
        ${st ? html` · ${st.text}` : nothing}</span>`;
    }
    const editing = this.editing === i.key;
    return html`<div class="b ${i.status}" draggable=${i.status === 'planned' ? 'true' : 'false'}
        @dragstart=${(e: DragEvent) => e.dataTransfer?.setData('text/plain', i.key)}>
      <div class="t"><hxk-icon name=${areaIcon(i.domain)} size="14"></hxk-icon><span class="grow">${i.title}</span></div>
      <div class="m">${hhmm(i.start_at)}${i.end_at ? `–${hhmm(i.end_at)}` : ''} · ${i.label}${i.moved_by_user ? ' · spostato da te' : ''}</div>
      ${i.variant?.note ? html`<div class="m">${i.variant.note}</div>` : nothing}
      ${st ? html`<hxk-badge tone=${st.tone}>${st.text}</hxk-badge>` : nothing}
      ${editing ? html`<form @submit=${(e: Event) => { e.preventDefault(); const v = (e.target as HTMLFormElement).querySelector('input')!.value;
          if (v) this.move(i, localIso(v)).then(() => (this.editing = '')); }}>
          <input type="datetime-local" aria-label="Nuovo orario" .value=${i.start_at ? wall(i.start_at) : ''}>
          <hxk-button size="sm" @click=${submit} ?loading=${this.busy === i.key}>Salva</hxk-button>
          <hxk-button size="sm" variant="ghost" @click=${() => (this.editing = '')}>Annulla</hxk-button></form>`
        : i.status === 'planned' ? html`<div class="acts">
          <hxk-button size="sm" variant="ghost" icon="clock" @click=${() => (this.editing = i.key)}>Sposta</hxk-button>
          <hxk-button size="sm" variant="ghost" icon="skip" ?loading=${this.busy === i.key} @click=${() => this.skip(i)}>Salta</hxk-button>
          ${i.link ? html`<hxk-button size="sm" variant="ghost" icon="external" @click=${() => this.open(i.link, i.module)}>Apri</hxk-button>` : nothing}
        </div>` : nothing}
    </div>`;
  }

  private renderDay(d: any, today: string) {
    const slots = d.items.filter((i: any) => i.kind === 'slot');
    const blocks = d.items.filter((i: any) => i.kind !== 'slot');
    const busy = (this.data.busy || []).filter((b: any) => b.start_at && isoDay(new Date(b.start_at)) === d.date);
    return html`<div class="col ${d.date === today ? 'today' : ''} ${d.date === this.day ? 'sel' : ''} ${this.over === d.date ? 'over' : ''}"
        @dragover=${(e: DragEvent) => { e.preventDefault(); this.over = d.date; }} @dragleave=${() => (this.over = '')}
        @drop=${(e: DragEvent) => this.onDrop(e, d.date)}>
      <div class="dh">${dayLabel(d.date)}</div>
      ${blocks.map((i: any) => this.renderItem(i))}
      ${slots.length ? html`<div class="chips">${slots.map((i: any) => this.renderItem(i))}</div>` : nothing}
      ${busy.map((b: any) => html`<div class="busyb"><hxk-icon name="pin" size="12"></hxk-icon>
        <span class="grow">${b.title || 'Impegno'} ${hhmm(b.start_at)}–${hhmm(b.end_at)}</span>
        <hxk-button size="sm" variant="ghost" icon="x" aria-label="Togli impegno" ?loading=${this.busy === b.key}
          @click=${() => this.act(b.key, 'DELETE', `${C}/busy/${encodeURIComponent(b.key)}`, undefined, 'Impegno tolto')}></hxk-button></div>`)}
      ${!d.items.length && !busy.length ? html`<span class="small muted">Libero</span>` : nothing}
    </div>`;
  }

  private renderTargets(targets: any[]) {
    if (!targets.length) return nothing;
    return html`<hxk-card heading="Obiettivi della settimana">
      ${targets.map(t => { const p = Math.max(0, Number(t.progress) || 0);
        return html`<div class="r"><hxk-icon name=${areaIcon(t.domain)} size="16"></hxk-icon><div class="grow" style="display:flex;flex-direction:column;gap:4px">
          <div><b>${t.title}</b>${t.value !== null && t.value !== undefined ? html` · ${t.value} ${t.unit || ''}` : nothing}</div>
          ${t.progress !== null && t.progress !== undefined ? html`<div class="bar ${p > 1 ? 'over' : ''}"><span style="width:${Math.min(100, Math.round(p * 100))}%"></span></div>` : nothing}
          ${t.reason ? html`<div class="small muted">${t.reason}</div>` : nothing}</div></div>`; })}
    </hxk-card>`;
  }

  private renderUnplaced(rows: any[]) {
    if (!rows.length) return nothing;
    return html`<hxk-card heading="Non entra" subtitle="Cosa non ho trovato posto nel tempo libero">
      ${rows.map(u => html`<div class="r"><hxk-icon name=${areaIcon(u.domain)} size="16"></hxk-icon><div class="grow">
        <b>${u.title}</b> <span class="small muted">${u.missing} su ${u.of}</span><div class="small muted">${u.reason}</div></div>
        ${u.link ? html`<hxk-button size="sm" variant="ghost" icon="external" @click=${() => this.open(u.link, u.module)}>Apri</hxk-button>` : nothing}</div>`)}
    </hxk-card>`;
  }

  private renderReview() {
    const rows = (this.review || []).filter(r => r.done || r.missed || r.notes?.length);
    if (!rows.length) return nothing;
    return html`<hxk-card heading="Com'è andata la settimana prima">
      ${rows.map(r => html`<div class="r"><hxk-icon name=${areaIcon(r.domain)} size="16"></hxk-icon><div class="grow">
        <b>${r.label}</b> <span class="small muted">${r.done} fatti${r.missed ? ` · ${r.missed} saltati` : ''}</span>
        ${(r.notes || []).map((n: string) => html`<div class="small muted">${n}</div>`)}</div></div>`)}
    </hxk-card>`;
  }

  private renderAdd() {
    if (!this.adding) return nothing;
    return html`<hxk-card heading="Aggiungi impegno" subtitle="Un periodo da lasciare libero: rifaccio il piano attorno">
      <form @submit=${(e: Event) => this.addBusy(e)}>
        <label>Giorno<input name="date" type="date" .value=${this.day} min=${this.data.start} max=${addDays(this.data.end, -1)}></label>
        <label>Dalle<input name="from" type="time" value="09:00"></label>
        <label>Alle<input name="to" type="time" value="18:00"></label>
        <label class="grow">Cosa<input name="title" placeholder="Es. fuori città"></label>
        <hxk-button @click=${submit} ?loading=${this.busy === 'busy'}>Aggiungi</hxk-button>
        <hxk-button variant="ghost" @click=${() => (this.adding = false)}>Annulla</hxk-button>
      </form></hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>La tua settimana</h1><hxk-state kind="offline" text=${this.error}></hxk-state></div>`;
    const d = this.data;
    if (!d) return html`<div class="page"><h1>La tua settimana</h1><hxk-state kind="loading"></hxk-state></div>`;
    const today = isoDay(new Date());
    const c = d.counts || {};
    return html`<div class="page">
      <div class="head"><h1 class="grow">La tua settimana</h1>
        <hxk-button variant="ghost" icon="chevron-left" aria-label="Settimana prima" @click=${() => this.week(-1)}></hxk-button>
        <span class="sub">${dayLabel(d.start)} – ${dayLabel(addDays(d.end, -1))}</span>
        <hxk-button variant="ghost" icon="chevron-right" aria-label="Settimana dopo" @click=${() => this.week(1)}></hxk-button>
      </div>
      <div class="row wrap">
        <hxk-button icon="refresh" ?loading=${this.busy === 'replan'} @click=${() => this.replan()}>Rifai il piano</hxk-button>
        <hxk-button variant="ghost" icon="plus" @click=${() => (this.adding = !this.adding)}>Aggiungi impegno</hxk-button>
        <span class="sub grow">${c.planned || 0} da fare · ${c.done || 0} fatti${c.skipped ? ` · ${c.skipped} saltati` : ''}</span>
      </div>
      ${this.renderAdd()}
      ${d.text ? html`<div class="text">${d.text}</div>` : nothing}
      ${!d.planned && !d.days.some((x: any) => x.items.length) ? html`<hxk-state kind="empty"
          text="Nessun piano per questa settimana: «Rifai il piano» lo prepara adesso"></hxk-state>` : nothing}
      <div class="days" role="tablist">${d.days.map((x: any) => html`<button class="chip" role="tab" aria-pressed=${x.date === this.day}
          @click=${() => (this.day = x.date)}>${dayLabel(x.date)}${x.items.length ? ` · ${x.items.length}` : ''}</button>`)}</div>
      <div class="grid">${d.days.map((x: any) => this.renderDay(x, today))}</div>
      ${this.renderTargets(d.targets || [])}
      ${this.renderUnplaced(d.unplaced || [])}
      ${this.renderReview()}
      <p class="small muted">Trascina un blocco su un altro giorno per spostarlo: i tuoi spostamenti restano. Gli impegni del calendario vengono sempre prima.</p>
    </div>`;
  }
}
