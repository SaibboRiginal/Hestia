import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AgendaApi } from './agenda.api';
import { AgendaTemplate, AgendaType, TYPE_META, ownerLabel } from './calendar.models';
import { addMinutes, fmt, fromLocalInput, toLocalInput } from './date-utils';
import {
  ButtonComponent, DateTimeFieldComponent, EmptyStateComponent, FieldComponent, IconComponent, ModalComponent,
  SegmentedComponent, SegmentOption, SpinnerComponent,
} from '../../ui';

export interface TemplateCreate {
  tpl: AgendaTemplate;
  body: { values: Record<string, unknown>; start_at: string; end_at?: string | null; recurrence?: string | null; type?: string };
}
type Freq = 'HOURLY' | 'DAILY' | 'WEEKLY' | 'MONTHLY';

/**
 * "Da un modulo…": modules declare what can be created for them (AgendaTemplate, registered via
 * hestia_common.agenda_client.template). Steps: 1 pick · 2 fields + when · 3 review.
 */
@Component({
  selector: 'cal-template-wizard',
  imports: [FormsModule, ModalComponent, ButtonComponent, FieldComponent, IconComponent, SegmentedComponent,
            DateTimeFieldComponent, EmptyStateComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-modal [open]="!!seed()" [title]="title()" size="lg" (closed)="cancel.emit()">
      <div class="steps">
        @for (s of stepNames; track $index) { <span [class.on]="step() === $index" [class.done]="step() > $index">{{ $index + 1 }} · {{ s }}</span> }
      </div>

      @switch (step()) {
        @case (0) {
          @if (loading()) { <div class="center"><hx-spinner /></div> }
          @else if (!templates().length) {
            <hx-empty icon="zap" title="Nessun modello dai moduli">I moduli dichiarano cosa puoi creare quando sono avviati (si aggiorna entro un'ora). Usa intanto "Evento libero".</hx-empty>
          } @else {
            @for (g of groups(); track g.owner) {
              <h4>{{ g.label }}</h4>
              <div class="cards">
                @for (t of g.items; track t.id) {
                  <button class="card" (click)="pick(t)">
                    <hx-icon [name]="t.icon || 'zap'" [size]="18" />
                    <span class="ct"><b>{{ t.label }}</b><span>{{ t.description }}</span></span>
                  </button>
                }
              </div>
            }
          }
        }
        @case (1) {
          @if (tpl(); as t) {
            <div class="form">
              @for (f of fieldList(); track f.name) {
                <hx-field [label]="f.label" [hint]="f.spec.description || ''" [required]="f.required">
                  @if (f.spec.enum?.length) {
                    <select class="hx-select" [ngModel]="values()[f.name] ?? ''" (ngModelChange)="setValue(f.name, $event)">
                      @for (o of f.spec.enum!; track o) { <option [value]="o">{{ o || '(predefinito)' }}</option> }
                    </select>
                  } @else if (f.spec.type === 'integer' || f.spec.type === 'number') {
                    <input class="hx-input" type="number" [ngModel]="values()[f.name]" (ngModelChange)="setValue(f.name, +$event)" />
                  } @else if (f.spec.type === 'boolean') {
                    <label class="chk"><input type="checkbox" class="hx-check" [ngModel]="!!values()[f.name]" (ngModelChange)="setValue(f.name, $event)" /> Sì</label>
                  } @else if (f.spec.format === 'textarea') {
                    <textarea class="hx-textarea" rows="3" [ngModel]="values()[f.name] ?? ''" (ngModelChange)="setValue(f.name, $event)"></textarea>
                  } @else {
                    <input class="hx-input" [ngModel]="values()[f.name] ?? ''" (ngModelChange)="setValue(f.name, $event)" />
                  }
                </hx-field>
              }
              @if (t.types.length > 1) {
                <hx-field label="Tipo">
                  <hx-segmented [options]="typeOpts()" [value]="type()" (changed)="type.set($any($event))" />
                </hx-field>
              }
              <div class="row2">
                <hx-field [label]="type() === 'window' ? 'Inizio finestra' : 'Quando'" required>
                  <hx-datetime [value]="start()" (valueChange)="start.set($event)" />
                </hx-field>
                @if (type() === 'window') {
                  <hx-field label="Fine finestra" required><hx-datetime [value]="end()" (valueChange)="end.set($event)" /></hx-field>
                }
              </div>
              @if (type() === 'job' || type() === 'window') {
                <hx-field label="Ripeti">
                  <div class="rep">
                    ogni <input class="hx-input" type="number" min="1" max="999" [ngModel]="interval()" (ngModelChange)="interval.set(+$event || 1)" />
                    <select class="hx-select" [ngModel]="freq()" (ngModelChange)="freq.set($event)">
                      <option value="HOURLY">ore</option><option value="DAILY">giorni</option>
                      <option value="WEEKLY">settimane</option><option value="MONTHLY">mesi</option>
                    </select>
                  </div>
                </hx-field>
              }
              @if (error()) { <p class="err">{{ error() }}</p> }
            </div>
          }
        }
        @case (2) {
          @if (tpl(); as t) {
            <dl class="review">
              <dt>Modulo</dt><dd>{{ owner(t.owner) }} · {{ t.label }}</dd>
              <dt>Tipo</dt><dd>{{ typeLabel(type()) }}</dd>
              <dt>Quando</dt><dd>{{ whenText() }}</dd>
              @for (f of fieldList(); track f.name) {
                @if (values()[f.name] !== undefined && values()[f.name] !== '') { <dt>{{ f.label }}</dt><dd class="v">{{ values()[f.name] }}</dd> }
              }
            </dl>
            <p class="hint">La voce sarà "tua" (sempre visibile, mai sovrascritta dal modulo) e il modulo la eseguirà all'orario indicato.</p>
          }
        }
      }

      <div footer class="foot">
        @if (step() > 0) { <button hx-btn variant="ghost" icon="chevron-left" (click)="back()">Indietro</button> }
        <div class="hx-grow"></div>
        <button hx-btn variant="ghost" (click)="cancel.emit()">Annulla</button>
        @if (step() === 1) { <button hx-btn variant="primary" (click)="next()">Avanti</button> }
        @if (step() === 2) { <button hx-btn variant="primary" icon="check" (click)="create()">Crea</button> }
      </div>
    </hx-modal>
  `,
  styles: [`
    .steps { display: flex; gap: 14px; font-size: 12px; color: var(--text-3); margin-bottom: 14px; flex-wrap: wrap; }
    .steps .on { color: var(--accent); font-weight: 600; } .steps .done { color: var(--text-2); }
    .center { display: grid; place-items: center; padding: 30px; }
    h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); margin: 10px 0 6px; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
    .card { display: flex; gap: 10px; align-items: flex-start; text-align: left; padding: 12px; border: 1px solid var(--border);
            border-radius: var(--radius-lg); background: var(--surface); }
    .card:hover { border-color: var(--accent); background: var(--accent-soft); }
    .card hx-icon { color: var(--accent); margin-top: 2px; flex-shrink: 0; }
    .ct { display: flex; flex-direction: column; gap: 3px; font-size: 13px; } .ct span { color: var(--text-3); font-size: 12px; }
    .form { display: flex; flex-direction: column; gap: 12px; }
    .row2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
    .rep { display: flex; align-items: center; gap: 8px; font-size: 13px; } .rep .hx-input { width: 70px; } .rep .hx-select { width: 140px; }
    .chk { display: flex; gap: 6px; align-items: center; font-size: 13px; }
    .err { color: var(--danger); font-size: 13px; }
    .review { display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; font-size: 13.5px; }
    .review dt { color: var(--text-3); } .review .v { white-space: pre-wrap; }
    .hint { font-size: 12.5px; color: var(--text-3); margin-top: 14px; }
    .foot { display: flex; gap: 8px; width: 100%; align-items: center; }
  `],
})
export class TemplateWizardComponent {
  private api = inject(AgendaApi);
  /** Opening seed: the suggested start (null = closed). */
  seed = input<Date | null>(null);
  done = output<TemplateCreate>();
  cancel = output<void>();

  readonly stepNames = ['Scegli', 'Dettagli', 'Conferma'];
  step = signal(0);
  loading = signal(false);
  templates = signal<AgendaTemplate[]>([]);
  tpl = signal<AgendaTemplate | null>(null);
  values = signal<Record<string, unknown>>({});
  type = signal<AgendaType>('task');
  start = signal('');
  end = signal('');
  freq = signal<Freq>('DAILY');
  interval = signal(1);
  error = signal('');

  constructor() {
    effect(() => {
      const s = this.seed();
      if (!s) return;
      this.step.set(0); this.tpl.set(null); this.error.set('');
      this.start.set(toLocalInput(s)); this.end.set(toLocalInput(addMinutes(s, 60)));
      void this.load();
    }, { allowSignalWrites: true });
  }

  title = computed(() => this.tpl() ? `${ownerLabel(this.tpl()!.owner)} · ${this.tpl()!.label}` : 'Crea da un modulo');
  groups = computed(() => {
    const m = new Map<string, AgendaTemplate[]>();
    for (const t of this.templates()) (m.get(t.owner) ?? m.set(t.owner, []).get(t.owner)!).push(t);
    return [...m.entries()].map(([owner, items]) => ({ owner, label: ownerLabel(owner), items }));
  });
  fieldList = computed(() => {
    const t = this.tpl();
    if (!t) return [];
    return Object.entries(t.fields ?? {}).map(([name, spec]) => ({
      name, spec, required: (t.required ?? []).includes(name),
      label: spec.label || (name.charAt(0).toUpperCase() + name.slice(1)).replace(/_/g, ' '),
    }));
  });
  typeOpts = computed<SegmentOption[]>(() => (this.tpl()?.types ?? []).map(t => ({
    value: t, label: t === 'task' ? 'Una volta' : t === 'job' ? 'Ripetuto' : TYPE_META[t].label })));
  owner = ownerLabel;
  typeLabel = (t: AgendaType) => TYPE_META[t].label;

  private async load() {
    this.loading.set(true);
    try { this.templates.set(await this.api.templates()); } catch { this.templates.set([]); }
    finally { this.loading.set(false); }
  }

  pick(t: AgendaTemplate) {
    this.tpl.set(t);
    const v: Record<string, unknown> = {};
    for (const [k, f] of Object.entries(t.fields ?? {})) if (f.default !== undefined) v[k] = f.default;
    this.values.set(v);
    this.type.set(t.type);
    if (t.type === 'window' && t.duration_minutes) {
      const s = fromLocalInput(this.start());
      if (s) this.end.set(toLocalInput(addMinutes(s, t.duration_minutes)));
    }
    this.step.set(1);
  }
  setValue(k: string, v: unknown) { this.values.update(x => ({ ...x, [k]: v })); }
  back() { this.step.update(s => Math.max(0, s - 1)); if (this.step() === 0) this.tpl.set(null); }

  next() {
    const t = this.tpl()!;
    const missing = (t.required ?? []).filter(k => this.values()[k] === undefined || this.values()[k] === '');
    const s = fromLocalInput(this.start()), e = fromLocalInput(this.end());
    if (missing.length) return this.error.set(`Compila: ${missing.join(', ')}`);
    if (!s) return this.error.set('Indica quando');
    if (this.type() === 'window' && (!e || e <= s)) return this.error.set('La fine della finestra deve essere dopo l\'inizio');
    this.error.set('');
    this.step.set(2);
  }

  rrule(): string | null {
    return this.type() === 'job' || this.type() === 'window' ? `FREQ=${this.freq()};INTERVAL=${this.interval()}` : null;
  }
  whenText = computed(() => {
    const s = fromLocalInput(this.start());
    if (!s) return '';
    const base = this.type() === 'window' && fromLocalInput(this.end())
      ? `${fmt.dateTime(s)} – ${fmt.time(fromLocalInput(this.end())!)}` : fmt.dateTime(s);
    const n = this.interval();
    const unit = n === 1 ? { HOURLY: 'ora', DAILY: 'giorno', WEEKLY: 'settimana', MONTHLY: 'mese' }[this.freq()]
                         : `${n} ${{ HOURLY: 'ore', DAILY: 'giorni', WEEKLY: 'settimane', MONTHLY: 'mesi' }[this.freq()]}`;
    return this.type() === 'task' ? base : `${base}, poi ogni ${unit}`;
  });

  create() {
    const t = this.tpl()!;
    const s = fromLocalInput(this.start())!;
    const e = this.type() === 'window' ? fromLocalInput(this.end()) : null;
    this.done.emit({ tpl: t, body: { values: this.values(), start_at: s.toISOString(), end_at: e ? e.toISOString() : null,
                                     recurrence: this.rrule(), type: this.type() } });
  }
}
