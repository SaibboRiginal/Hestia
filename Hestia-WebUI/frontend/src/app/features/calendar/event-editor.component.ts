import { ChangeDetectionStrategy, Component, computed, effect, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AgendaItem, AgendaType, TYPE_META } from './calendar.models';
import { WEEKDAYS, WEEKDAY_LABELS, addMinutes, fromLocalInput, toLocalInput } from './date-utils';
import { Freq, RepeatModel, buildRRule, describeRRule, emptyRepeat, parseRRule } from './rrule';
import { ButtonComponent, DateFieldComponent, DateTimeFieldComponent, FieldComponent, ModalComponent, SegmentedComponent, SegmentOption } from '../../ui';

export interface EditorSeed {
  start: Date; end?: Date | null; type?: AgendaType; item?: AgendaItem; duplicate?: boolean;
  /** Natural-language quick add: fields Oracle understood (the user reviews them here). */
  prefill?: { title?: string; description?: string; recurrence?: string | null };
}
/** "Chiedi a Hestia" from the editor: what the user typed so far. */
export interface EditorAsk { title: string; start: Date | null; end: Date | null; type: AgendaType; }
export interface EditorResult { key?: string; body: Record<string, unknown>; }

/** Create / edit an agenda item (title, type, time, recurrence, description, action). */
@Component({
  selector: 'cal-event-editor',
  imports: [FormsModule, ModalComponent, ButtonComponent, FieldComponent, SegmentedComponent, DateFieldComponent, DateTimeFieldComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-modal [open]="!!seed()" [title]="editing() ? 'Modifica voce' : 'Nuova voce in agenda'" size="lg" (closed)="cancel.emit()">
      <form class="form" (ngSubmit)="save()" id="cal-editor">
        <hx-field label="Titolo" [required]="true" [error]="errors().title">
          <input class="hx-input title" name="title" [(ngModel)]="title" placeholder="Es. Controlla le email della banca" autofocus />
        </hx-field>

        <hx-field label="Tipo" [hint]="editing() ? 'Il tipo non si cambia: duplica la voce per crearne una di altro tipo.' : typeHint()">
          <hx-segmented [options]="typeOptions" [value]="type()" (changed)="!editing() && type.set($event)" />
        </hx-field>

        <div class="row2">
          <hx-field [label]="startLabel()" [required]="true" [error]="errors().start" [hint]="startHint()">
            <hx-datetime [value]="startStr" (valueChange)="onStart($event); startStr = $event" />
          </hx-field>
          @if (needsEnd()) {
            <hx-field label="Fine" [required]="type() === 'window'" [error]="errors().end">
              <hx-datetime [value]="endStr" (valueChange)="endStr = $event" />
            </hx-field>
          }
        </div>

        <hx-field label="Ripetizione" [hint]="ruleText()">
          <div class="rep">
            <select class="hx-select" name="freq" [ngModel]="rep().freq" (ngModelChange)="patchRep({ freq: $event })">
              <option value="none">Non si ripete</option>
              <option value="MINUTELY">Ogni N minuti</option>
              <option value="HOURLY">Ogni N ore</option>
              <option value="DAILY">Giornaliera</option>
              <option value="WEEKLY">Settimanale</option>
              <option value="MONTHLY">Mensile</option>
              <option value="YEARLY">Annuale</option>
              <option value="custom">Regola personalizzata (RRULE)</option>
            </select>
            @if (rep().freq !== 'none' && rep().freq !== 'custom') {
              <label class="inl">ogni
                <input class="hx-input num" type="number" min="1" name="interval" [ngModel]="rep().interval"
                       (ngModelChange)="patchRep({ interval: +$event || 1 })" />
              </label>
            }
          </div>
          @if (rep().freq === 'WEEKLY') {
            <div class="days">
              @for (d of weekdays; track d) {
                <button type="button" class="day" [class.on]="rep().byday.includes(d)" (click)="toggleDay(d)">{{ dayLabel[d] }}</button>
              }
            </div>
          }
          @if (rep().freq === 'custom') {
            <input class="hx-input mono" name="raw" [ngModel]="rep().raw" (ngModelChange)="patchRep({ raw: $event })"
                   placeholder="FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=3" />
          }
          @if (rep().freq !== 'none' && rep().freq !== 'custom') {
            <div class="rep end">
              <label class="inl">Fine:
                <hx-date [value]="rep().until || ''" (valueChange)="patchRep({ until: $event, count: null })" />
              </label>
              <label class="inl">oppure dopo
                <input class="hx-input num" type="number" min="1" name="count" [ngModel]="rep().count"
                       (ngModelChange)="patchRep({ count: +$event || null, until: '' })" /> volte
              </label>
            </div>
          }
        </hx-field>

        <hx-field label="Descrizione">
          <textarea class="hx-textarea" name="description" [(ngModel)]="description" rows="3"></textarea>
        </hx-field>

        @if (type() === 'task' || type() === 'job') {
          <details class="adv" [open]="!!actionService">
            <summary>Azione da eseguire (via Hub)</summary>
            <div class="row3">
              <hx-field label="Servizio"><input class="hx-input" name="svc" [(ngModel)]="actionService" placeholder="scout" /></hx-field>
              <hx-field label="Metodo">
                <select class="hx-select" name="method" [(ngModel)]="actionMethod">
                  <option>POST</option><option>GET</option><option>PUT</option><option>PATCH</option><option>DELETE</option>
                </select>
              </hx-field>
              <hx-field label="Percorso"><input class="hx-input mono" name="path" [(ngModel)]="actionPath" placeholder="/api/scout/cycle" /></hx-field>
            </div>
            <hx-field label="Body JSON" [error]="errors().body">
              <textarea class="hx-textarea mono" name="body" [(ngModel)]="actionBody" rows="3" placeholder='{"trigger": "agenda"}'></textarea>
            </hx-field>
          </details>
        }
        @if (editing() && seed()?.item?.created_by !== 'user') {
          <p class="note">Questa voce è di <b>{{ seed()?.item?.owner }}</b>: dopo la tua modifica il modulo non la sovrascriverà più.</p>
        }
      </form>
      <ng-container footer>
        @if (!editing()) {
          <button hx-btn variant="ghost" type="button" icon="sparkle" class="ask" (click)="askHestia()"
                  title="Descrivi a parole cosa vuoi: Hestia crea la voce con gli strumenti">Chiedi a Hestia</button>
        }
        <button hx-btn variant="ghost" type="button" (click)="cancel.emit()">Annulla</button>
        <button hx-btn variant="primary" type="submit" form="cal-editor">{{ editing() ? 'Salva' : 'Crea' }}</button>
      </ng-container>
    </hx-modal>
  `,
  styles: [`
    .form { display: flex; flex-direction: column; gap: 14px; padding-bottom: 6px; }
    .title { font-size: 16px; padding: 10px 12px; }
    .row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .row3 { display: grid; grid-template-columns: 1fr 110px 2fr; gap: 10px; margin-bottom: 10px; }
    .rep { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    .rep .hx-select { width: auto; min-width: 220px; }
    .rep.end { margin-top: 8px; }
    .inl { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-2); }
    .num { width: 74px; }
    .inl input[type=date] { width: auto; }
    .days { display: flex; gap: 5px; margin-top: 8px; flex-wrap: wrap; }
    .day { width: 42px; height: 30px; border-radius: var(--radius-full); border: 1px solid var(--border-strong); font-size: 12.5px; color: var(--text-2); }
    .day.on { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast); }
    .adv { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 12px; }
    .adv summary { cursor: pointer; font-size: 13px; color: var(--text-2); font-weight: 500; padding: 2px 0 6px; }
    .ask { margin-right: auto; color: var(--accent); }
    .note { font-size: 12.5px; color: var(--text-3); background: var(--surface-2); padding: 8px 10px; border-radius: var(--radius-md); }
    @media (max-width: 640px) { .row2, .row3 { grid-template-columns: 1fr; } }
  `],
})
export class EventEditorComponent {
  seed = input<EditorSeed | null>(null);
  saved = output<EditorResult>();
  cancel = output<void>();
  ask = output<EditorAsk>();

  readonly weekdays = [...WEEKDAYS];
  readonly dayLabel = WEEKDAY_LABELS;
  readonly typeOptions: SegmentOption<AgendaType>[] = (['event', 'task', 'job', 'window'] as AgendaType[])
    .map(t => ({ value: t, label: TYPE_META[t].label, icon: TYPE_META[t].icon, title: TYPE_META[t].hint }));

  title = '';
  description = '';
  startStr = '';
  endStr = '';
  actionService = '';
  actionMethod = 'POST';
  actionPath = '';
  actionBody = '';
  type = signal<AgendaType>('event');
  rep = signal<RepeatModel>(emptyRepeat());
  errors = signal<{ title?: string; start?: string; end?: string; body?: string }>({});

  editing = computed(() => !!this.seed()?.item && !this.seed()?.duplicate);
  needsEnd = computed(() => this.type() === 'window' || this.type() === 'event');
  typeHint = computed(() => TYPE_META[this.type()].hint);
  ruleText = computed(() => describeRRule(buildRRule(this.rep())));
  private seriesEdit = computed(() => this.editing() && this.rep().freq !== 'none');
  startLabel = computed(() => this.seriesEdit() ? 'Inizio della serie' : 'Inizio');
  startHint = computed(() => this.seriesEdit() ? "Prima occorrenza della regola: spostala per cambiare l'orario di tutte" : '');

  constructor() {
    effect(() => {
      const s = this.seed();
      if (!s) return;
      const it = s.item;
      this.errors.set({});
      this.title = it ? (s.duplicate ? `${it.title} (copia)` : it.title) : (s.prefill?.title ?? '');
      this.description = it?.description ?? s.prefill?.description ?? '';
      const start = it && !s.duplicate ? new Date(it.start_at) : s.start;
      const end = it && !s.duplicate ? (it.end_at ? new Date(it.end_at) : null) : (s.end ?? (it?.end_at ? new Date(s.start.getTime() + (new Date(it.end_at).getTime() - new Date(it.start_at).getTime())) : addMinutes(s.start, 60)));
      this.startStr = toLocalInput(start);
      this.endStr = end ? toLocalInput(end) : '';
      this.type.set(it?.type ?? s.type ?? 'event');
      this.rep.set(parseRRule(it?.recurrence ?? s.prefill?.recurrence));
      this.actionService = it?.action?.service ?? '';
      this.actionMethod = it?.action?.method ?? 'POST';
      this.actionPath = it?.action?.path ?? '';
      this.actionBody = it?.action?.body ? JSON.stringify(it.action.body, null, 2) : '';
    }, { allowSignalWrites: true });
  }

  askHestia() {
    this.ask.emit({ title: this.title.trim(), start: fromLocalInput(this.startStr), end: this.endStr ? fromLocalInput(this.endStr) : null, type: this.type() });
  }

  patchRep(p: Partial<RepeatModel>) {
    const next = { ...this.rep(), ...p } as RepeatModel;
    if (p.freq === 'WEEKLY' && !next.byday.length) {
      const d = fromLocalInput(this.startStr) ?? new Date();
      next.byday = [WEEKDAYS[(d.getDay() + 6) % 7]];
    }
    if (p.freq === 'custom' && !next.raw) next.raw = buildRRule({ ...this.rep(), freq: (this.rep().freq === 'custom' ? 'DAILY' : this.rep().freq) as Freq }) ?? '';
    this.rep.set(next);
  }

  toggleDay(d: string) {
    const r = this.rep();
    const byday = r.byday.includes(d) ? r.byday.filter(x => x !== d) : [...r.byday, d];
    this.rep.set({ ...r, byday: byday.length ? byday : r.byday });
  }

  onStart(v: string) {
    // keep the duration when the start moves
    const s = fromLocalInput(v), oldS = fromLocalInput(this.startStr), e = fromLocalInput(this.endStr);
    if (s && oldS && e) this.endStr = toLocalInput(new Date(e.getTime() + (s.getTime() - oldS.getTime())));
  }

  save() {
    const errs: { title?: string; start?: string; end?: string; body?: string } = {};
    const start = fromLocalInput(this.startStr);
    const end = this.needsEnd() ? fromLocalInput(this.endStr) : null;
    if (!this.title.trim()) errs.title = 'Serve un titolo';
    if (!start) errs.start = 'Data/ora non valida';
    if (this.type() === 'window' && !end) errs.end = 'Una finestra ha bisogno della fine';
    if (start && end && end <= start) errs.end = 'La fine deve essere dopo l\'inizio';
    let body: unknown = undefined;
    if (this.actionBody.trim()) {
      try { body = JSON.parse(this.actionBody); } catch { errs.body = 'JSON non valido'; }
    }
    this.errors.set(errs);
    if (Object.keys(errs).length) return;

    const action = (this.type() === 'task' || this.type() === 'job') && this.actionService.trim() && this.actionPath.trim()
      ? { service: this.actionService.trim(), path: this.actionPath.trim(), method: this.actionMethod, body: body ?? null }
      : undefined;
    const recurrence = this.type() === 'task' ? null : buildRRule(this.rep());
    const payload: Record<string, unknown> = {
      title: this.title.trim(),
      description: this.description.trim() || null,
      start_at: start!.toISOString(),
      end_at: end ? end.toISOString() : null,
      recurrence: recurrence ?? '',
    };
    if (action) payload['action'] = action;
    const it = this.seed()?.item;
    if (this.editing() && it) {
      this.saved.emit({ key: it.key, body: payload });
    } else {
      this.saved.emit({ body: { ...payload, type: this.type(), recurrence: recurrence ?? null, owner: 'user', created_by: 'user' } });
    }
  }
}
