import { ChangeDetectionStrategy, Component, DestroyRef, HostListener, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { AssistantService } from '../../services/assistant.service';
import { AgendaApi, LogsResult } from './agenda.api';
import { FormsModule } from '@angular/forms';
import { CalendarStore } from './calendar.store';
import { AgendaType, CalEvent, CalView, TYPE_META, ownerLabel } from './calendar.models';
import { addDays, addMinutes, dayKey, fmt, startOfWeek } from './date-utils';
import { TimeGridComponent, MoveRequest, SelectRequest } from './views/time-grid.component';
import { MonthViewComponent } from './views/month-view.component';
import { ListViewComponent } from './views/list-view.component';
import { MiniCalendarComponent } from './mini-calendar.component';
import { DetailAction, EventDetailsComponent } from './event-details.component';
import { EditorAsk, EditorResult, EditorSeed, EventEditorComponent } from './event-editor.component';
import { TemplateCreate, TemplateWizardComponent } from './template-wizard.component';
import {
  ButtonComponent, DialogService, FieldComponent, IconComponent, MenuComponent, MenuItem, ModalComponent, PopoverComponent, SegmentedComponent, SegmentOption, SpinnerComponent,
  ToastService, ToggleComponent,
} from '../../ui';

/**
 * Hestia's own calendar (assistant agenda): month / week / day / list, sidebar with mini calendar,
 * layers and filters, popover details, editor, drag & drop. Keys: T oggi · M/W/D/L viste · N nuovo · ←/→.
 */
@Component({
  selector: 'app-calendar-page',
  imports: [
    FormsModule, ButtonComponent, IconComponent, SegmentedComponent, FieldComponent, SpinnerComponent, ToggleComponent, PopoverComponent, ModalComponent,
    MenuComponent, TemplateWizardComponent, TimeGridComponent, MonthViewComponent, ListViewComponent, MiniCalendarComponent, EventDetailsComponent, EventEditorComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="page">
      <aside class="side" [class.open]="sideOpen()">
        <div class="new-wrap">
          <button hx-btn variant="primary" icon="plus" class="new" (click)="newAt(defaultStart())" title="Nuovo evento libero (N)">Nuovo</button>
          <hx-menu [items]="newMenu" (select)="onNew($event)">
            <button hx-btn variant="primary" icon="chevron-down" iconOnly class="new-more" trigger aria-label="Altri modi di creare"></button>
          </hx-menu>
        </div>
        <div class="quick" [class.busy]="quickBusy()" title="Scrivi a parole, es. &quot;domani alle 15 dentista&quot; o &quot;ogni lunedì alle 9 controlla le case&quot;: si apre l'editor già compilato">
          @if (quickBusy()) { <hx-spinner [size]="14" /> } @else { <hx-icon name="sparkle" [size]="15" /> }
          <input class="hx-input" placeholder="Aggiungi rapido: domani alle 15…" [(ngModel)]="quickText" (keydown.enter)="quickAdd()" [disabled]="quickBusy()" />
        </div>
        <cal-mini [selected]="store.anchor()" [marked]="markedDays()" (pick)="store.focusDay($event)" />

        <section>
          <h4>Calendari</h4>
          @for (s of store.sources(); track s.id) {
            <label class="flt"><input type="checkbox" class="hx-check" [checked]="s.enabled" (change)="toggleSource(s.id)" />
              <span class="sw ai"></span><span class="hx-grow">{{ s.label }}</span></label>
          }
          <p class="hint">I tuoi calendari Google/Outlook arriveranno qui come livelli separati.</p>
        </section>

        <section>
          <h4>Moduli</h4>
          @for (o of store.owners(); track o.owner) {
            <label class="flt" [title]="'Doppio clic: mostra solo ' + label(o.owner)" (dblclick)="store.onlyOwner(o.owner)">
              <input type="checkbox" class="hx-check" [style.accent-color]="o.color"
                     [checked]="!store.hiddenOwners().has(o.owner)" (change)="store.toggleOwner(o.owner)" />
              <span class="sw" [style.background]="o.color"></span>
              <span class="hx-grow hx-truncate">{{ label(o.owner) }}</span>
              <span class="cnt">{{ o.count }}</span>
            </label>
          } @empty { <p class="hint">Nessun modulo ha ancora pianificato nulla.</p> }
        </section>

        <section>
          <h4>Tipi</h4>
          @for (t of types; track t) {
            <label class="flt"><input type="checkbox" class="hx-check" [checked]="!store.hiddenTypes().has(t)" (change)="store.toggleType(t)" />
              <hx-icon [name]="typeIcon(t)" [size]="14" /><span class="hx-grow">{{ typeLabel(t) }}</span></label>
          }
        </section>

        <section class="opts">
          <hx-toggle label="Mostra occorrenze saltate" [checked]="store.showSkipped()" (changed)="store.setShowSkipped($event)" />
          <hx-toggle label="Mostra completate/annullate" [checked]="store.showDone()" (changed)="store.setShowDone($event)" />
        </section>
      </aside>
      <div class="scrim" (click)="sideOpen.set(false)"></div>

      <section class="main">
        <header class="bar">
          <button hx-btn variant="ghost" icon="sidebar" iconOnly class="side-btn" aria-label="Filtri" (click)="sideOpen.set(!sideOpen())"></button>
          <button hx-btn variant="secondary" size="sm" (click)="store.today()">Oggi</button>
          <div class="nav">
            <button hx-btn variant="ghost" size="sm" icon="chevron-left" iconOnly [attr.aria-label]="stepLabel(-1)" [attr.title]="stepLabel(-1) + ' (←)'" (click)="store.step(-1)"></button>
            <button hx-btn variant="ghost" size="sm" icon="chevron-right" iconOnly [attr.aria-label]="stepLabel(1)" [attr.title]="stepLabel(1) + ' (→)'" (click)="store.step(1)"></button>
          </div>
          <h2>{{ store.title() }}</h2>
          @if (store.loading()) { <hx-spinner [size]="16" /> }
          <div class="hx-grow"></div>
          <div class="search">
            <hx-icon name="search" [size]="15" />
            <input class="hx-input" placeholder="Cerca…" [ngModel]="store.search()" (ngModelChange)="store.search.set($event)" />
          </div>
          <button hx-btn variant="ghost" size="sm" icon="refresh" iconOnly aria-label="Aggiorna" title="Aggiorna" (click)="store.load()"></button>
          <button hx-btn variant="ghost" size="sm" icon="settings" iconOnly aria-label="Vista" title="Vista: finestre, ricorrenze, cosa mostrare"
                  (click)="vistaRect.set($any($event.currentTarget).getBoundingClientRect()); vistaOpen.set(!vistaOpen())"></button>
          <hx-segmented [options]="viewOptions" [value]="store.view()" (changed)="store.setView($event)" />
        </header>

        @if (store.error()) {
          <div class="err"><hx-icon name="alert" [size]="16" /> {{ store.error() }}
            <button hx-btn size="sm" variant="ghost" (click)="store.load()">Riprova</button></div>
        }

        @if (store.vp().focused && store.hiddenByPolicy() > 0) {
          <div class="hint-bar">
            <hx-icon name="filter" [size]="14" />
            <span>{{ store.hiddenByPolicy() }} prossime voci dei moduli nascoste dalla <b>vista focalizzata</b> (oltre l'orizzonte impostato).</span>
            <button class="lnk" (click)="store.setVp({ focused: false })">Mostra tutto</button>
            <button class="lnk" (click)="vistaRect.set($any($event.currentTarget).getBoundingClientRect()); vistaOpen.set(true)">Regole…</button>
          </div>
        }

        @switch (store.view()) {
          @case ('month') {
            <cal-month-view [anchor]="store.anchor()" [events]="store.events()" (selected)="select($event)"
                            (createAt)="newAt($event)" (moved)="onMove($event)" (dayClick)="openDay($event)" />
          }
          @case ('list') { <cal-list-view [events]="store.events()" (selected)="select($event)" /> }
          @default {
            <cal-time-grid [days]="gridDays()" [events]="store.events()" (selected)="select($event)"
                           [windowsMode]="store.vp().windowsMode" [frequentMode]="store.vp().frequentMode"
                           [focusDay]="store.anchor()" [scrollHour]="store.vp().scrollHour" [workHours]="workHours()"
                           (createAt)="newAt($event)" (moved)="onMove($event)" (dayClick)="openDay($event)" />
          }
        }
      </section>
    </div>

    <hx-popover [open]="!!sel()" [anchor]="selRect()" [width]="360" (closed)="sel.set(null)">
      @if (sel(); as s) { <cal-event-details [ev]="s" (act)="onAction($event)" (pick)="sel.set($event)" (close)="sel.set(null)" /> }
    </hx-popover>

    <hx-popover [open]="vistaOpen()" [anchor]="vistaRect()" [width]="340" (closed)="vistaOpen.set(false)">
      @let vp = store.vp();
      <div class="vista">
        <h4>Vista del calendario</h4>
        <hx-field label="Finestre (es. Athena quando sei inattivo)">
          <hx-segmented [options]="windowOpts" [value]="vp.windowsMode" (changed)="store.setVp({ windowsMode: $any($event) })" />
        </hx-field>
        <hx-field label="Ricorrenze frequenti" [hint]="'Regole con almeno ' + vp.frequentPerDay + ' esecuzioni al giorno'">
          <hx-segmented [options]="frequentOpts" [value]="vp.frequentMode" (changed)="store.setVp({ frequentMode: $any($event) })" />
        </hx-field>
        <label class="num">Frequente da <input class="hx-input" type="number" min="2" max="96" [ngModel]="vp.frequentPerDay" (ngModelChange)="num('frequentPerDay', $event)" /> volte al giorno</label>
        <hx-toggle label="Vista focalizzata (meno affollata)" [checked]="vp.focused" (changed)="store.setVp({ focused: $event })" />
        @if (vp.focused) {
          <div class="rules">
            <p>Le voci create da te e il giorno selezionato si vedono sempre.</p>
            <label class="num">Ricorrenze frequenti: prossimi <input class="hx-input" type="number" min="1" max="60" [ngModel]="vp.frequentDays" (ngModelChange)="num('frequentDays', $event)" /> giorni</label>
            <label class="num">Ricorrenze rare: prossime <input class="hx-input" type="number" min="1" max="50" [ngModel]="vp.rareCount" (ngModelChange)="num('rareCount', $event)" /> volte o <input class="hx-input" type="number" min="1" max="60" [ngModel]="vp.rareDays" (ngModelChange)="num('rareDays', $event)" /> giorni (il primo che arriva)</label>
            <label class="num">Passato: solo errori degli ultimi <input class="hx-input" type="number" min="0" max="90" [ngModel]="vp.pastDays" (ngModelChange)="num('pastDays', $event)" /> giorni, uno per regola</label>
          </div>
        }
        <label class="num">Scorri all'apertura alle <input class="hx-input" type="number" min="0" max="23" [ngModel]="vp.scrollHour" (ngModelChange)="num('scrollHour', $event)" />:00</label>
        <label class="num">Orario di lavoro (lun–ven) <input class="hx-input" type="number" min="0" max="24" [ngModel]="vp.workStart" (ngModelChange)="num('workStart', $event)" />–<input class="hx-input" type="number" min="0" max="24" [ngModel]="vp.workEnd" (ngModelChange)="num('workEnd', $event)" />: fuori è ombreggiato</label>
        <div class="hx-row"><div class="hx-grow"></div><button hx-btn size="sm" variant="ghost" (click)="store.resetVp()">Ripristina predefinite</button></div>
      </div>
    </hx-popover>

    <cal-event-editor [seed]="editor()" (saved)="onSave($event)" (ask)="askFromEditor($event)" (cancel)="editor.set(null)" />

    <hx-modal [open]="!!logs()" [title]="'Log · ' + (logs()?.title || '')" size="lg" (closed)="logs.set(null)">

      @if (logs(); as l) {

        <div class="logs-bar">

          <select class="hx-select" [ngModel]="l.service" (ngModelChange)="loadLogs({ service: $event })">

            @for (s of l.services; track s) { <option [value]="s">{{ s }}</option> }

          </select>

          <span>±</span>

          <select class="hx-select" [ngModel]="l.minutes" (ngModelChange)="loadLogs({ minutes: +$event })">

            @for (m of [2, 5, 15, 60]; track m) { <option [value]="m">{{ m }} min</option> }

          </select>

          <span class="lt">attorno a {{ l.when }}</span>

          <div class="hx-grow"></div>

          @if (l.loading) { <hx-spinner [size]="15" /> }

        </div>

        @if (l.error) { <p class="logs-err">{{ l.error }}</p> }

        @else if (l.result) {

          @if (!l.result.logs.length) {

            <p class="logs-empty">Nessuna riga in questo intervallo.

              @if (l.result.oldest) { Il modulo tiene in memoria solo le ultime righe (dalle {{ rel(l.result.oldest) }}). }</p>

          } @else {

            <div class="logs">

              @for (r of l.result.logs; track $index) {

                <div class="lr" [attr.data-l]="r.level"><span class="lts">{{ logTime(r.ts) }}</span><span class="llv">{{ r.level }}</span><span class="lm">{{ r.message }}</span></div>

              }

            </div>

          }

        }

      }

    </hx-modal>


    <hx-modal [open]="icsOpen()" title="Agenda sul telefono" size="md" (closed)="icsOpen.set(false)">

      <p class="ics-p">Feed iCalendar di sola lettura dell'agenda di Hestia (eventi, task e finestre; i job periodici restano qui).</p>

      @if (icsUrl()) {

        <div class="ics-url"><code>{{ icsUrl() }}</code><button hx-btn size="sm" icon="copy" (click)="copyIcs()">Copia</button></div>

        <p class="ics-p small">Aggiungilo come calendario "da URL" (Google Calendar, Apple Calendario). Chi ha il link vede l'agenda: non condividerlo.</p>

      } @else {

        <p class="ics-p small">Per l'abbonamento dal telefono imposta <code>WEBUI_ICS_KEY</code> (almeno 16 caratteri) nel servizio WebUI. Intanto puoi scaricare il file.</p>

      }

      <ng-container footer>

        <button hx-btn variant="primary" icon="external" (click)="downloadIcs()">Scarica .ics</button>

      </ng-container>

    </hx-modal>
    <cal-template-wizard [seed]="wizard()" (done)="onTemplate($event)" (cancel)="wizard.set(null)" />
  `,
  styles: [`
    :host { display: flex; flex: 1; min-height: 0; }
    .page { display: flex; flex: 1; min-height: 0; }
    .side { width: 256px; flex-shrink: 0; border-right: 1px solid var(--border); padding: 14px 12px; overflow-y: auto;
            display: flex; flex-direction: column; gap: 16px; background: var(--bg); }
    .new-wrap { display: flex; align-self: flex-start; box-shadow: var(--shadow-1); border-radius: var(--radius-lg); }
    .new { padding: 0 18px; height: 40px; border-radius: var(--radius-lg) 0 0 var(--radius-lg); }
    .new-more { height: 40px; width: 34px; border-radius: 0 var(--radius-lg) var(--radius-lg) 0;
                border-left: 1px solid color-mix(in srgb, var(--accent-contrast) 25%, transparent); }
    section h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); font-weight: 600; margin: 0 0 6px 4px; }
    .flt { display: flex; align-items: center; gap: 8px; padding: 4px 6px; border-radius: var(--radius-sm); font-size: 13.5px; cursor: pointer; user-select: none; }
    .flt:hover { background: var(--surface-2); }
    .sw { width: 10px; height: 10px; border-radius: 3px; flex-shrink: 0; }
    .sw.ai { background: linear-gradient(135deg, var(--cal-1), var(--cal-2)); }
    .cnt { font-size: 11.5px; color: var(--text-3); }
    .hint { font-size: 12px; color: var(--text-3); padding: 2px 6px; }
    .opts { display: flex; flex-direction: column; gap: 10px; padding: 0 4px; }
    .opts hx-toggle ::ng-deep .lbl { font-size: 13px; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .bar h2 { font-family: var(--font-serif); font-weight: 500; font-size: 20px; white-space: nowrap; }
    .nav { display: flex; }
    .search { position: relative; width: 200px; }
    .search hx-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search .hx-input { padding-left: 30px; height: 32px; }
    .side-btn { display: none; }
    .err { margin: 10px 16px 0; padding: 8px 12px; border-radius: var(--radius-md); background: var(--danger-soft); color: var(--danger);
           display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
    .scrim { display: none; }
    .hint-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin: 8px 16px 0; padding: 6px 12px; font-size: 12.5px;
                color: var(--text-2); background: var(--bg-subtle); border: 1px solid var(--border); border-radius: var(--radius-md); }
    .hint-bar hx-icon { color: var(--text-3); }
    .lnk { color: var(--accent); font-weight: 500; font-size: 12.5px; }
    .lnk:hover { text-decoration: underline; }
    .vista { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
    .vista h4 { font-size: 14px; font-weight: 600; }
    .vista .num { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 13px; color: var(--text-2); }
    .vista .num .hx-input { width: 58px; height: 28px; padding: 2px 6px; text-align: center; }
    .vista .rules { display: flex; flex-direction: column; gap: 8px; padding: 8px 10px; border-radius: var(--radius-md); background: var(--bg-subtle); }
    .vista .rules p { font-size: 12px; color: var(--text-3); }
    @media (max-width: 1100px) {
      .side { position: fixed; z-index: 700; inset: 0 auto 0 0; transform: translateX(-100%); transition: transform var(--dur) var(--ease); box-shadow: var(--shadow-3); }
      .side.open { transform: none; }
      .side.open + .scrim { display: block; position: fixed; inset: 0; background: var(--overlay); z-index: 690; }
      .side-btn { display: inline-flex; }
      .search { width: 140px; }
    }
    .quick { display: flex; align-items: center; position: relative; margin: -4px 0 12px; }
    .quick hx-icon, .quick hx-spinner { position: absolute; left: 9px; color: var(--accent); pointer-events: none; }
    .quick .hx-input { width: 100%; height: 32px; padding-left: 30px; font-size: 12.5px; }
    .logs-bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; font-size: 13px; color: var(--text-2); }
    .logs-bar .hx-select { width: auto; height: 30px; padding-top: 3px; padding-bottom: 3px; }
    .logs-bar .lt { color: var(--text-3); }
    .logs { font-family: var(--font-mono); font-size: 11.5px; max-height: 60vh; overflow: auto; border: 1px solid var(--border); border-radius: var(--radius-md); }
    .lr { display: grid; grid-template-columns: 62px 64px 1fr; gap: 8px; padding: 3px 8px; border-bottom: 1px solid var(--border); }
    .lr:last-child { border-bottom: 0; }
    .lr[data-l=WARNING] { background: var(--warning-soft, color-mix(in srgb, var(--warning) 10%, transparent)); }
    .lr[data-l=ERROR], .lr[data-l=CRITICAL] { background: var(--danger-soft); }
    .lts { color: var(--text-3); font-variant-numeric: tabular-nums; } .llv { color: var(--text-3); }
    .lm { white-space: pre-wrap; word-break: break-word; color: var(--text); }
    .logs-empty, .logs-err { font-size: 13px; color: var(--text-3); padding: 8px 0; } .logs-err { color: var(--danger); }
    .ics-p { font-size: 13.5px; color: var(--text-2); margin-bottom: 10px; line-height: 1.5; } .ics-p.small { font-size: 12.5px; color: var(--text-3); }
    .ics-url { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
    .ics-url code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11.5px;
                    background: var(--surface-2); padding: 6px 8px; border-radius: var(--radius-sm); }
    @media (max-width: 720px) { .bar { padding: 10px 10px 10px 50px; } .bar h2 { font-size: 16px; } .search { display: none; } }
  `],
})
export class CalendarPageComponent implements OnInit {
  store = inject(CalendarStore);
  private dialogs = inject(DialogService);

  readonly types: AgendaType[] = ['event', 'task', 'job', 'window'];
  readonly viewOptions: SegmentOption<CalView>[] = [
    { value: 'day', label: 'Giorno', title: 'Giorno (D)' },
    { value: 'week', label: 'Settimana', title: 'Settimana (W)' },
    { value: 'month', label: 'Mese', title: 'Mese (M)' },
    { value: 'list', label: 'Elenco', icon: 'list', title: 'Elenco (L)' },
  ];

  sideOpen = signal(false);
  wizard = signal<Date | null>(null);
  private assistant = inject(AssistantService);
  private api = inject(AgendaApi);
  private toast = inject(ToastService);
  private destroyRef = inject(DestroyRef);
  readonly newMenu: MenuItem[] = [
    { id: 'free', label: 'Evento libero', icon: 'edit' },
    { id: 'module', label: 'Da un modulo…', icon: 'zap' },
    { id: 'ai', label: 'Crea con Hestia…', icon: 'sparkle' },
    { id: 'd', label: '', divider: true },
    { id: 'ics', label: 'Feed ICS (telefono)…', icon: 'external' },
  ];
  onNew(id: string) {
    if (id === 'module') { this.sel.set(null); this.wizard.set(this.defaultStart()); }
    else if (id === 'ai') this.askCreate();
    else if (id === 'ics') void this.openIcs();
    else this.newAt(this.defaultStart());
  }
  readonly workHours = computed<[number, number]>(() => [this.store.vp().workStart, this.store.vp().workEnd]);

  // ── "Crea con Hestia" (B1) ─────────────────────────────────────────────
  askCreate(at?: Date, prompt = '') {
    const d = at ?? this.store.anchor();
    this.sel.set(null);
    this.assistant.open({
      page: 'calendar', intent: 'create', prompt,
      label: `Agenda · ${fmt.dayLong(d)}${at ? ', ' + fmt.time(at) : ''}`,
      hints: { giorno: dayKey(d), ora: at ? fmt.time(at) : undefined, vista: this.store.view(), agenda: 'agenda di Hestia (strumenti agenda_assistente_*)' },
    });
  }
  askFromEditor(a: EditorAsk) {
    this.editor.set(null);
    this.askCreate(a.start ?? undefined, a.title ? `${a.title} ` : '');
  }
  private askAbout(ev: CalEvent) {
    const it = ev.item;
    this.assistant.open({
      page: 'calendar', intent: 'modify', label: `“${ev.occ.title}” · ${fmt.dayLong(ev.start)} ${fmt.time(ev.start)}`,
      hints: { voce: ev.occ.key, titolo: ev.occ.title, modulo: ev.occ.owner, tipo: ev.occ.type, occorrenza: ev.occ.occurrence,
               regola: it?.recurrence ?? undefined, stato: ev.occ.status, ultimo_esito: it?.last_result ? (it.last_result.ok ? 'ok' : 'fallito: ' + (it.last_result.detail || '')) : undefined },
      suggestions: ev.occ.recurring
        ? ['Spiegami cosa fa questa regola', 'Sposta solo questa occorrenza di un\'ora', 'Cambia la frequenza…', 'Perché è fallita?']
        : ['Spiegami cosa fa', 'Spostala a domani alla stessa ora', 'Perché è fallita?'],
    });
  }

  // ── A9 natural-language quick add ─────────────────────────────────────
  quickText = '';
  quickBusy = signal(false);
  async quickAdd() {
    const text = this.quickText.trim();
    if (!text || this.quickBusy()) return;
    this.quickBusy.set(true);
    try {
      const d = await this.api.parse(text);
      const start = new Date(d.start_at);
      this.sel.set(null);
      this.editor.set({ start, end: d.end_at ? new Date(d.end_at) : null, type: d.type,
                        prefill: { title: d.title, description: d.description ?? undefined, recurrence: d.recurrence } });
      this.quickText = '';
    } catch (e: any) {
      this.toast.error(`Non ho capito la data (${e?.error?.detail || e?.message || 'errore'}): completa tu`);
      this.editor.set({ start: this.defaultStart(), end: addMinutes(this.defaultStart(), 60), type: 'event', prefill: { title: text } });
      this.quickText = '';
    } finally {
      this.quickBusy.set(false);
    }
  }

  // ── A9 occurrence "Log" (module logs ± minutes) ───────────────────────
  logs = signal<{ title: string; when: string; at: string; service: string; services: string[]; minutes: number;
                  key: string; loading: boolean; result: LogsResult | null; error: string } | null>(null);
  private logsSeq = 0;
  openLogs(ev: CalEvent) {
    const svc = (ev.item?.action?.service || ev.occ.owner || 'chronos').toLowerCase();
    const services = [...new Set([svc, 'chronos', 'hub'].filter(s => s && s !== 'user'))];
    const at = ev.occ.run?.at || ev.start.toISOString();
    this.logs.set({ title: ev.occ.title, when: fmt.dateTime(new Date(at)), at, service: services[0], services, minutes: 5,
                    key: ev.occ.key, loading: false, result: null, error: '' });
    void this.loadLogs({});
  }
  async loadLogs(change: { service?: string; minutes?: number }) {
    const cur = this.logs();
    if (!cur) return;
    const next = { ...cur, ...change, loading: true, error: '' };
    const seq = ++this.logsSeq;
    this.logs.set(next);
    try {
      const r = await this.api.logs(next.service, next.at, next.minutes);
      if (seq === this.logsSeq && this.logs()) this.logs.set({ ...next, loading: false, result: r });
    } catch (e: any) {
      if (seq === this.logsSeq && this.logs()) this.logs.set({ ...next, loading: false, result: null, error: e?.error?.detail || e?.message || 'Log non disponibili' });
    }
  }
  logTime(ts: string) { return fmt.time(new Date(ts)) + ':' + String(new Date(ts).getSeconds()).padStart(2, '0'); }
  rel(iso: string) { return fmt.relative(new Date(iso)); }

  // ── A9 ICS feed ───────────────────────────────────────────────────────
  icsOpen = signal(false);
  icsUrl = signal('');
  async openIcs() {
    this.icsOpen.set(true);
    try {
      const f = await this.api.feedInfo();
      this.icsUrl.set(f.key ? `${location.origin}${f.path}?key=${encodeURIComponent(f.key)}` : '');
    } catch { this.icsUrl.set(''); }
  }
  async copyIcs() {
    try { await navigator.clipboard.writeText(this.icsUrl()); this.toast.success('Link copiato'); } catch { /* */ }
  }
  async downloadIcs() {
    try {
      const blob = await this.api.feedFile();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'hestia-agenda.ics';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    } catch (e: any) { this.toast.error(e?.error?.detail || 'Download non riuscito'); }
  }
  async onTemplate(r: TemplateCreate) {
    this.wizard.set(null);
    await this.store.createFromTemplate(r.tpl.owner, r.tpl.id, r.body);
  }
  vistaOpen = signal(false);
  vistaRect = signal<DOMRect | null>(null);
  readonly windowOpts: SegmentOption[] = [{ value: 'lane', label: 'Corsia' }, { value: 'band', label: 'Banda' }, { value: 'hidden', label: 'Nascoste' }];
  readonly frequentOpts: SegmentOption[] = [{ value: 'compact', label: 'Compatte' }, { value: 'full', label: 'Complete' }, { value: 'hidden', label: 'Nascoste' }];
  num(key: 'frequentPerDay' | 'frequentDays' | 'rareCount' | 'rareDays' | 'pastDays' | 'scrollHour' | 'workStart' | 'workEnd', v: unknown) {
    const n = Math.round(Number(v));
    if (Number.isFinite(n) && n >= 0) this.store.setVp({ [key]: n });
  }
  stepLabel(dir: 1 | -1) {
    const unit = { day: ['Giorno precedente', 'Giorno successivo'], week: ['Settimana precedente', 'Settimana successiva'],
                   month: ['Mese precedente', 'Mese successivo'], list: ['30 giorni prima', '30 giorni dopo'] }[this.store.view()];
    return unit[dir < 0 ? 0 : 1];
  }
  sel = signal<CalEvent | null>(null);
  selRect = signal<DOMRect | null>(null);
  editor = signal<EditorSeed | null>(null);

  gridDays = computed(() => {
    const a = this.store.anchor();
    if (this.store.view() === 'day') return [a];
    const s = startOfWeek(a);
    return Array.from({ length: 7 }, (_, i) => addDays(s, i));
  });
  markedDays = computed(() => new Set(this.store.events().map(e => dayKey(e.start))));

  ngOnInit() {
    void this.store.load();
    // The assistant (drawer or chat) planned/changed something: show it live.
    this.assistant.changed$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => void this.store.load());
  }

  label = ownerLabel;
  typeIcon = (t: AgendaType) => TYPE_META[t].icon;
  typeLabel = (t: AgendaType) => TYPE_META[t].label;

  toggleSource(id: string) {
    this.store.sources.update(list => list.map(s => s.id === id ? { ...s, enabled: !s.enabled } : s));
  }

  defaultStart(): Date {
    const d = new Date(this.store.anchor());
    const now = new Date();
    d.setHours(now.getHours() + 1, 0, 0, 0);
    return d;
  }

  select(r: SelectRequest) { this.selRect.set(r.rect); this.sel.set(r.ev); }
  openDay(d: Date) { this.store.anchor.set(d); this.store.setView('day'); }
  newAt(d: Date) { this.sel.set(null); this.editor.set({ start: d, end: addMinutes(d, 60), type: 'event' }); }

  async onMove(m: MoveRequest) {
    let scope: 'one' | 'all' = 'one';
    if (m.ev.occ.recurring) {
      const r = await this.dialogs.choose<'one' | 'all'>('Spostare la voce ricorrente', `"${m.ev.occ.title}"`, [
        { value: 'one', label: 'Solo questa', variant: 'secondary' },
        { value: 'all', label: 'Tutta la serie', variant: 'primary' },
      ]);
      if (!r) return;
      scope = r;
    }
    await this.store.move(m.ev, m.start, m.end, scope);
  }

  async onAction(a: DetailAction) {
    const ev = this.sel();
    if (!ev) return;
    switch (a) {
      case 'edit': if (ev.item) this.editor.set({ start: ev.start, end: ev.end, item: ev.item }); break;
      case 'duplicate': if (ev.item) this.editor.set({ start: ev.start, end: ev.end, item: ev.item, duplicate: true }); break;
      case 'skip': await this.store.skip(ev); break;
      case 'unskip': await this.store.unskip(ev); break;
      case 'run': await this.store.run(ev); break;
      case 'pause': await this.store.pause(ev, true); break;
      case 'resume': await this.store.pause(ev, false); break;
      case 'restore': await this.store.update(ev.occ.key, { status: 'confirmed' }, 'Regola ripristinata'); break;
      case 'reset-move': await this.store.resetMove(ev); break;
      case 'ask': this.askAbout(ev); break;
      case 'logs': this.openLogs(ev); break;
      case 'cancel': {
        const ok = await this.dialogs.confirm(ev.occ.recurring ? 'Annullare tutta la regola?' : 'Annullare la voce?',
          ev.occ.recurring ? 'Nessuna occorrenza futura verrà eseguita. Per saltarne solo una usa "Salta questa".' : '',
          'Annulla regola', true);
        if (ok) await this.store.cancel(ev);
        break;
      }
    }
    if (a !== 'edit' && a !== 'duplicate') this.sel.set(null);
    else this.sel.set(null);
  }

  async onSave(r: EditorResult) {
    this.editor.set(null);
    if (r.key) await this.store.update(r.key, r.body, 'Modifiche salvate');
    else await this.store.create(r.body);
  }

  @HostListener('document:keydown', ['$event'])
  onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement;
    if (e.ctrlKey || e.metaKey || e.altKey || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName) || this.editor()) return;
    const map: Record<string, () => void> = {
      t: () => this.store.today(), m: () => this.store.setView('month'), w: () => this.store.setView('week'),
      d: () => this.store.setView('day'), l: () => this.store.setView('list'), n: () => this.newAt(this.defaultStart()),
      ArrowLeft: () => this.store.step(-1), ArrowRight: () => this.store.step(1),
    };
    const fn = map[e.key];
    if (fn) { e.preventDefault(); fn(); }
  }
}
