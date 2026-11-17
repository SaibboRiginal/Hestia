/**
 * <chronos-routines> — «Routine»: what the assistant does by itself, written in words, by time or when a mail
 * arrives; the ready-made gallery (radar notizie, case nuove, spese, settimana, mail da un mittente); «Esegui
 * adesso», pause, delete. The result goes as a notification or into the evening recap.
 * Reads GET /api/agenda/routines(+/templates); POST /api/agenda/routines, /routines/from-template/{id};
 * the agenda item routes for run / pause / delete. Dossier 2026-10-24-tutto-brainstorm-cindy W2 + W7.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, when } from './util';

const DAYS = [['MO', tr('abbr::Mon')], ['TU', tr('abbr::Tue')], ['WE', tr('abbr::Wed')], ['TH', tr('abbr::Thu')], ['FR', tr('abbr::Fri')], ['SA', tr('abbr::Sat')], ['SU', tr('abbr::Sun')]];
const DELIVER = [{ value: 'hermes', label: tr('Notification') }, { value: 'recap', label: tr('In the evening recap') }];
const TRIGGER = [{ value: 'daily', label: tr('Every day') }, { value: 'weekly', label: tr('Every week') },
                 { value: 'mail', label: tr('When an email arrives') }];

/** «Ogni giorno alle 07:30», «Ogni lun, ven alle 18:00», «Quando arriva una mail da …». */
export function describeRoutine(r: any): string {
  if (r.on?.mail) return tr("When an email arrives from {0}", r.on.mail.senders || tr('a sender'));
  if (r.on) return tr('When something happens');
  const parts: Record<string, string> = {};
  for (const kv of String(r.recurrence || '').replace(/^RRULE:/i, '').split(';')) {
    const [k, v] = kv.split('=');
    if (k && v) parts[k.toUpperCase()] = v;
  }
  let hh = parts['BYHOUR'], mm = parts['BYMINUTE'];
  if (hh === undefined && r.start_at) {
    const d = new Date(r.start_at);
    hh = String(d.getHours()); mm = String(d.getMinutes());
  }
  const at = hh !== undefined ? tr(" at {0}:{1}", hh.padStart(2, '0'), (mm || '0').padStart(2, '0')) : '';
  if (parts['FREQ'] === 'WEEKLY') {
    const days = (parts['BYDAY'] || '').split(',').map(d => DAYS.find(x => x[0] === d)?.[1]).filter(Boolean);
    return tr("Every {0}{1}", days.length ? days.join(', ') : tr('week'), at);
  }
  if (parts['FREQ'] === 'DAILY') return tr("Every day{0}", at);
  if (parts['FREQ'] === 'MONTHLY') return tr("Every month{0}", at);
  return r.recurrence ? tr('f::Repeated') : tr('Once');
}

function todayAt(hhmm: string): string {
  const [h, m] = hhmm.split(':').map(n => parseInt(n, 10) || 0);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d.toISOString();
}

export class ChronosRoutines extends HestiaElement {
  static properties = { ...HestiaElement.properties, items: { state: true }, templates: { state: true },
                        error: { state: true }, busy: { state: true }, form: { state: true }, tpl: { state: true },
                        values: { state: true } };
  declare items: any[] | null; declare templates: any[]; declare error: string; declare busy: string;
  declare form: any; declare tpl: any; declare values: Record<string, string>;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    h2 { font-size: 15px; margin: 6px 0 0; }
    .r { display: flex; gap: 10px; align-items: flex-start; padding: 10px 0; border-top: 1px solid var(--border); }
    .r:first-child { border-top: 0; }
    .r hxk-icon { flex: none; margin-top: 2px; }
    .t { font-weight: 550; overflow-wrap: anywhere; }
    .ins { font-size: 13px; color: var(--text-2); white-space: pre-wrap; overflow-wrap: anywhere; }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
    .tpl { display: grid; gap: 8px; grid-template-columns: repeat(auto-fill, minmax(min(100%, 230px), 1fr)); }
    .tp { font: inherit; text-align: left; border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px;
      display: flex; gap: 8px; background: var(--surface); color: inherit; cursor: pointer; }
    .tp:hover { border-color: var(--border-strong); }
    .tp[aria-pressed=true] { border-color: var(--accent); background: var(--accent-soft); }
    .tp:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .days { display: flex; gap: 4px; flex-wrap: wrap; }
    .day { font: inherit; font-size: 13px; padding: 4px 9px; border-radius: 99px; border: 1px solid var(--border-strong);
      background: var(--surface); color: var(--text-2); cursor: pointer; }
    .day[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }
  `];

  constructor() {
    super();
    this.items = null; this.templates = []; this.error = ''; this.busy = ''; this.form = null; this.tpl = null;
    this.values = {};
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }

  private async load() {
    const [r, t] = await Promise.all([this.host.api('GET', `${API}/routines`), this.host.api('GET', `${API}/routines/templates`)]);
    if (!r.ok) { this.error = r.status === 0 ? tr('Agenda not reachable') : r.error || tr('Agenda not reachable'); return; }
    this.error = '';
    this.items = r.data?.items || [];
    this.templates = t.ok ? t.data?.templates || [] : [];
  }

  private async act(r: any, kind: 'run' | 'pause' | 'resume' | 'delete') {
    if (kind === 'delete' && !(await this.host.confirm(tr('Delete the routine?'), tr("«{0}» will not start any more.", r.title), { label: tr('Delete'), danger: true }))) return;
    this.busy = `${kind}:${r.key}`;
    const ref = encodeURIComponent(r.key);
    const res = kind === 'run' ? await this.host.api('POST', `${API}/items/${ref}/run`)
      : kind === 'delete' ? await this.host.api('DELETE', `${API}/items/${ref}`)
      : await this.host.api('PATCH', `${API}/items/${ref}`, { body: { status: kind === 'pause' ? 'paused' : 'confirmed' } });
    this.busy = '';
    if (!res.ok) { this.host.toast(res.error || tr('Failed, try again'), 'danger'); return; }
    const msg = { run: res.data?.ok === false ? tr("{0}: failed", r.title) : tr('{0}: started', r.title),
                  pause: tr("{0}: paused", r.title), resume: tr("{0}: active again", r.title), delete: tr("{0}: deleted", r.title) }[kind];
    this.host.toast(msg, kind === 'run' && res.data?.ok === false ? 'warning' : 'success');
    this.load();
  }

  private newForm() {
    this.tpl = null;
    this.form = { title: '', instruction: '', trigger: 'daily', at: '08:00', days: ['MO'], senders: '', deliver: 'hermes' };
  }

  private pickTemplate(t: any) {
    this.form = null;
    this.tpl = this.tpl?.id === t.id ? null : t;
    this.values = {};
  }

  private set(k: string, v: unknown) { this.form = { ...this.form, [k]: v }; }

  private async create() {
    const f = this.form;
    if (!f.instruction.trim()) { this.host.toast(tr('Write what it must do'), 'warning'); return; }
    if (f.trigger === 'mail' && !f.senders.trim()) { this.host.toast(tr('Write the sender'), 'warning'); return; }
    const body: any = { title: f.title.trim() || f.instruction.trim().slice(0, 40), instruction: f.instruction.trim(), deliver: f.deliver };
    if (f.trigger === 'mail') body.on = { mail: { senders: f.senders.trim() } };
    else {
      body.recurrence = f.trigger === 'weekly' ? `FREQ=WEEKLY;BYDAY=${(f.days.length ? f.days : ['MO']).join(',')}` : 'FREQ=DAILY';
      body.start_at = todayAt(f.at || '08:00');
    }
    this.busy = 'create';
    const r = await this.host.api('POST', `${API}/routines`, { body });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('Routine not created'), 'danger'); return; }
    this.host.toast(tr('{0}: created', body.title), 'success');
    this.form = null;
    this.load();
  }

  private async fromTemplate() {
    const t = this.tpl;
    for (const [name, spec] of Object.entries<any>(t.fields || {})) {
      if (spec.required && !(this.values[name] || '').trim()) { this.host.toast(tr('Needed: {0}', spec.label), 'warning'); return; }
    }
    this.busy = 'tpl';
    const r = await this.host.api('POST', `${API}/routines/from-template/${encodeURIComponent(t.id)}`, { body: { values: this.values } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('Routine not created'), 'danger'); return; }
    this.host.toast(tr('{0}: created', t.label), 'success');
    this.tpl = null;
    this.load();
  }

  private row(r: any) {
    const paused = r.status === 'paused';
    const last = r.last_run;
    return html`<div class="r">
      <hxk-icon name=${r.trigger === 'event' ? 'mail' : 'repeat'} tone=${paused ? 'neutral' : 'accent'} size="16"></hxk-icon>
      <div class="grow col" style="gap:3px">
        <div class="row wrap"><span class="t">${r.title}</span>
          ${paused ? html`<hxk-badge tone="warning">${tr("Paused")}</hxk-badge>` : nothing}
          ${r.deliver === 'recap' ? html`<hxk-badge tone="info">${tr("In the recap")}</hxk-badge>` : nothing}</div>
        <div class="small muted">${describeRoutine(r)}${r.precheck?.tool ? tr(' · check first whether there\'s something new') : ''}</div>
        <div class="ins">${r.instruction}</div>
        ${last ? html`<div class="small muted">${tr("Last time")} ${when(last.at)}: ${last.ok ? tr('f::succeeded') : tr('f::failed')}${last.detail && !last.ok ? ` · ${last.detail}` : ''}</div>` : nothing}
      </div>
      <div class="acts">
        <hxk-button size="sm" icon="play" ?loading=${this.busy === `run:${r.key}`} @click=${() => this.act(r, 'run')}>${tr("Run now")}</hxk-button>
        <hxk-button size="sm" variant="ghost" icon=${paused ? 'play' : 'pause'} ?loading=${this.busy === `pause:${r.key}` || this.busy === `resume:${r.key}`}
          @click=${() => this.act(r, paused ? 'resume' : 'pause')}>${paused ? tr('Turn back on') : tr('Pause')}</hxk-button>
        <hxk-button size="sm" variant="ghost" icon="trash" ?loading=${this.busy === `delete:${r.key}`} @click=${() => this.act(r, 'delete')}>${tr("Delete")}</hxk-button>
      </div>
    </div>`;
  }

  private formView() {
    const f = this.form;
    return html`<div class="card col">
      <h2>${tr("New routine")}</h2>
      <hxk-field label=${tr("What it must do")} type="textarea" .value=${f.instruction} placeholder=${tr("E.g. every morning tell me if it rains and what to wear")}
        @change=${(e: CustomEvent) => this.set('instruction', e.detail)}></hxk-field>
      <hxk-field label=${tr("Name (optional)")} .value=${f.title} @change=${(e: CustomEvent) => this.set('title', e.detail)}></hxk-field>
      <hxk-field label=${tr("When")} type="enum" .options=${TRIGGER} .value=${f.trigger} @change=${(e: CustomEvent) => this.set('trigger', e.detail)}></hxk-field>
      ${f.trigger === 'mail'
        ? html`<hxk-field label=${tr("Sender (address or domain)")} .value=${f.senders} @change=${(e: CustomEvent) => this.set('senders', e.detail)}></hxk-field>`
        : html`<label class="small muted">${tr("alt::Now")}</label>
          <input type="time" .value=${f.at} @change=${(e: Event) => this.set('at', (e.target as HTMLInputElement).value)}
            style="font:inherit;padding:6px 8px;border:1px solid var(--border-strong);border-radius:var(--radius-sm);background:var(--surface);color:inherit;max-width:140px">
          ${f.trigger === 'weekly' ? html`<div class="days">${DAYS.map(([d, l]) => html`<button class="day" aria-pressed=${f.days.includes(d)}
            @click=${() => this.set('days', f.days.includes(d) ? f.days.filter((x: string) => x !== d) : [...f.days, d])}>${l}</button>`)}</div>` : nothing}`}
      <hxk-field label=${tr("Result")} type="enum" .options=${DELIVER} .value=${f.deliver} @change=${(e: CustomEvent) => this.set('deliver', e.detail)}></hxk-field>
      <div class="row"><hxk-button variant="primary" icon="check" ?loading=${this.busy === 'create'} @click=${() => this.create()}>${tr("Create")}</hxk-button>
        <hxk-button variant="ghost" @click=${() => (this.form = null)}>${tr("Cancel")}</hxk-button></div>
    </div>`;
  }

  private templateView() {
    const t = this.tpl;
    const fields = Object.entries<any>(t.fields || {});
    return html`<div class="card col">
      <h2>${t.label}</h2><div class="small muted">${t.help}</div>
      ${fields.map(([name, spec]) => html`<hxk-field label=${spec.label + (spec.required ? '' : tr(' (optional)'))} .value=${this.values[name] || ''}
        @change=${(e: CustomEvent) => (this.values = { ...this.values, [name]: String(e.detail ?? '') })}></hxk-field>`)}
      <div class="small muted">${describeRoutine(t)} · ${t.deliver === 'recap' ? tr('in the evening recap') : tr('as a notification')}</div>
      <div class="row"><hxk-button variant="primary" icon="check" ?loading=${this.busy === 'tpl'} @click=${() => this.fromTemplate()}>${tr("Create")}</hxk-button>
        <hxk-button variant="ghost" @click=${() => (this.tpl = null)}>${tr("Cancel")}</hxk-button></div>
    </div>`;
  }

  render() {
    if (this.error) return html`<div class="page"><h1>${tr("Routine")}</h1><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (!this.items) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    return html`<div class="page">
      <div class="head"><h1>${tr("Routine")}</h1><span class="sub">${tr("What the assistant does by itself, at a time or when an email arrives")}</span>
        <span class="grow"></span><hxk-button icon="plus" @click=${() => this.newForm()}>${tr("New routine")}</hxk-button></div>
      ${this.form ? this.formView() : nothing}
      ${this.items.length ? html`<div class="card">${this.items.map(r => this.row(r))}</div>`
        : html`<hxk-state kind="empty" text=${tr("No routines. Write it in words, pick a ready one below or ask for it in chat.")}></hxk-state>`}
      ${this.templates.length ? html`<h2>${tr("Ready to use")}</h2>
        <div class="tpl">${this.templates.map(t => html`<button class="tp" aria-pressed=${this.tpl?.id === t.id} @click=${() => this.pickTemplate(t)}>
          <hxk-icon name=${t.icon || 'repeat'} tone="accent" size="16"></hxk-icon>
          <span class="col" style="gap:2px"><b>${t.label}</b><span class="small muted">${t.help}</span></span></button>`)}</div>
        ${this.tpl ? this.templateView() : nothing}` : nothing}
    </div>`;
  }
}
