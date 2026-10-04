import {
  ChangeDetectionStrategy, Component, ElementRef, HostListener, OnDestroy, OnInit, computed, effect, inject, signal, viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { DialogService, UI } from '../../ui';
import { ForgeStore } from './forge.store';
import { ForgeApi } from './forge.api';
import { Dossier, ENGINE_LABEL, ForgeTask, STATE_META } from './forge.models';
import { TranscriptComponent } from './transcript.component';
import { TaskPanelComponent } from './task-panel.component';
import { RepoBrowserComponent, RepoNav } from './repo-browser.component';
import { ago } from './forge-format';
import { AssistantService } from '../../services/assistant.service';

/**
 * Sviluppo — Forge tasks and the Hestia repository, Codex / Claude Code style:
 * left = tasks, centre = the engine conversation (+ ask a change), right = File · Diff · Dossier · Test · Log · Ramo.
 * Spec: docs/work/2026-10-04-calendar-skills-forge-ui/SPEC.md §C.
 */
@Component({
  selector: 'app-forge-page',
  imports: [...UI, FormsModule, TranscriptComponent, TaskPanelComponent, RepoBrowserComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Sviluppo" [subtitle]="subtitle()">
      <hx-segmented [options]="modeOpts" [value]="mode()" (changed)="setMode($any($event))" />
      <button hx-btn variant="ghost" icon="refresh" iconOnly aria-label="Aggiorna" title="Aggiorna" (click)="store.refresh()"></button>
      <button hx-btn variant="ghost" icon="sparkle" (click)="askHestia()" title="Descrivi a Hestia cosa serve: propone o crea lo sviluppo">Chiedi a Hestia</button>
      <button hx-btn variant="primary" icon="plus" (click)="openNew()">Nuovo sviluppo</button>
    </hx-page-header>

    @if (mode() === 'repo') {
      <forge-repo [nav]="repoNav()" (openTask)="openTaskFromRepo($event)" />
    } @else {
      <div class="layout" [attr.data-size]="size()" [class.has-sel]="!!store.selectedId()">
        <!-- ── tasks ── -->
        <aside class="list">
          <div class="lhead">
            <div class="search"><hx-icon name="search" [size]="15" />
              <input class="hx-input" placeholder="Cerca task…" [ngModel]="store.search()" (ngModelChange)="store.search.set($event)" /></div>
            <div class="chips">
              @for (f of filters; track f.id) {
                <button [class.on]="store.filter() === f.id" (click)="store.filter.set(f.id)">{{ f.label }}
                  @if (f.id === 'open' && store.counts().open) { <i>{{ store.counts().open }}</i> }</button>
              }
            </div>
          </div>
          <div class="rows">
            @if (store.loading() && !store.tasks().length) { <div class="center"><hx-spinner /></div> }
            @if (store.error()) { <div class="lerr"><hx-icon name="alert" [size]="14" /> {{ store.error() }}</div> }
            @for (t of store.visible(); track t.id) {
              <button class="trow" [class.on]="store.selectedId() === t.id" (click)="select(t.id)">
                <span class="sdot" [attr.data-tone]="meta(t).tone" [class.pulse]="['running', 'merging', 'approved'].includes(t.state)"></span>
                <div class="tmain">
                  <div class="treq">{{ t.request }}</div>
                  <div class="tmeta">
                    <span>{{ meta(t).label }}</span> · <span>{{ engineOf(t) }}</span> · <span>{{ ago(t.created_at) }}</span>
                    @if (t.parent_task) { · <span title="Segue un task precedente">↳</span> }
                  </div>
                </div>
              </button>
            } @empty {
              @if (!store.loading()) {
                <hx-empty icon="terminal" title="Nessun task">Chiedi a Forge di sviluppare qualcosa: lavora su un ramo separato e niente cambia finché non approvi.
                  <button hx-btn size="sm" variant="primary" icon="plus" (click)="openNew()">Nuovo sviluppo</button></hx-empty>
              }
            }
          </div>
        </aside>

        <!-- ── conversation ── -->
        <section class="center-col">
          @if (store.task(); as t) {
            <div class="thead">
              @if (size() === 'phone') { <button hx-btn variant="ghost" size="sm" icon="arrow-left" iconOnly aria-label="Indietro" (click)="select(null)"></button> }
              <div class="hx-grow min0">
                <div class="ttitle" [title]="t.request">{{ t.request }}</div>
                <div class="tsub">
                  <hx-badge [tone]="meta(t).tone">{{ meta(t).label }}</hx-badge>
                  <span class="mono">{{ t.id.slice(0, 6) }}</span> · {{ engineOf(t) }}
                  @if (t.workdoc) { · <span class="mono hx-truncate">{{ t.workdoc }}</span> }
                </div>
              </div>
              <div class="acts">
                @switch (t.state) {
                  @case ('proposed') {
                    <button hx-btn size="sm" variant="primary" icon="play" [loading]="store.busy()" (click)="store.act('approve')">Avvia</button>
                    <button hx-btn size="sm" variant="ghost" icon="x" (click)="reject()">Rifiuta</button>
                  }
                  @case ('scheduled') {
                    <button hx-btn size="sm" variant="primary" icon="play" [loading]="store.busy()" (click)="store.act('approve', { now: true })" title="Non aspettare la finestra Claude">Avvia ora</button>
                    <button hx-btn size="sm" variant="ghost" icon="x" (click)="reject()">Rifiuta</button>
                  }
                  @case ('awaiting_review') {
                    <button hx-btn size="sm" variant="primary" icon="check" [loading]="store.busy()" (click)="approve(t)">Approva e applica</button>
                    <button hx-btn size="sm" variant="ghost" icon="x" (click)="reject()">Rifiuta</button>
                  }
                  @case ('merged') { <button hx-btn size="sm" variant="ghost" icon="undo" (click)="rollback()">Rollback</button> }
                  @case ('deployed') { <button hx-btn size="sm" variant="ghost" icon="undo" (click)="rollback()">Rollback</button> }
                }
                @if (['failed', 'no_changes', 'rejected', 'rolled_back'].includes(t.state)) {
                  <button hx-btn size="sm" icon="refresh" [loading]="store.busy()" (click)="store.act('retry')">Riprova</button>
                }
              </div>
            </div>
            @if (size() !== 'wide') {
              <div class="ctabs"><hx-segmented [options]="centerOpts" [value]="centerTab()" (changed)="centerTab.set($any($event))" /></div>
            }
            @if (size() === 'wide' || centerTab() === 'chat') {
              <div class="chat" #chat (scroll)="onScroll()">
                @if (t.summary && !store.active()) {
                  <div class="summary"><hx-icon name="sparkle" [size]="15" /><div><b>Riepilogo del motore</b><div class="pre-wrap">{{ t.summary }}</div></div></div>
                }
                <forge-transcript [events]="store.transcript()" [working]="store.active() || store.transcriptLive()" />
              </div>
              <div class="composer">
                <textarea class="hx-textarea" rows="2" [(ngModel)]="followUp" (keydown)="composerKey($event)"
                          placeholder="Chiedi una modifica a questo lavoro… (nuovo task che continua lo stesso dossier)"></textarea>
                <div class="crow">
                  <select class="hx-select" [(ngModel)]="followEngine" title="Motore">
                    @for (e of engines; track e) { <option [value]="e">{{ engineLabel(e) }}</option> }
                  </select>
                  <span class="hint">Ctrl+Invio per inviare</span>
                  <span class="hx-grow"></span>
                  <button hx-btn size="sm" variant="primary" icon="send" [disabled]="followUp.trim().length < 8" [loading]="store.busy()" (click)="sendFollowUp(t)">Invia</button>
                </div>
              </div>
            } @else {
              <forge-task-panel (openRepo)="openRepo($event)" />
            }
          } @else {
            <div class="placeholder">
              <hx-empty icon="terminal" title="Seleziona un task">
                Qui vedi la conversazione completa del motore (ragionamento, comandi, file letti e modificati), il diff, il dossier, i test e i log.
              </hx-empty>
              @if (store.status(); as s) {
                <div class="engines">
                  @for (e of engineRows(); track e.name) {
                    <div class="eng"><span class="sdot" [attr.data-tone]="e.available ? 'success' : 'neutral'"></span>
                      <b>{{ engineLabel(e.name) }}</b>@if (e.name === s.engine_default) { <hx-badge tone="accent">predefinito</hx-badge> }
                      <span class="muted hx-truncate" [title]="e.detail">{{ e.detail }}</span></div>
                  }
                  <div class="eng muted">Repository: {{ s.repo_ok ? (s.base_branch || 'ok') : 'non montato' }} · in coda: {{ s.queue.length }}</div>
                </div>
              }
            </div>
          }
        </section>

        <!-- ── context panel ── -->
        @if (size() === 'wide' && store.task()) {
          <aside class="side"><forge-task-panel (openRepo)="openRepo($event)" /></aside>
        }
      </div>
    }

    <!-- ── new task ── -->
    <hx-modal [open]="newOpen()" title="Nuovo sviluppo" size="md" (closed)="newOpen.set(false)">
      <div class="form">
        <hx-field label="Cosa vuoi che Forge sviluppi o corregga?" required hint="Più dettagli dai, migliore il risultato. Forge lavora su un ramo separato: niente cambia finché non approvi.">
          <textarea class="hx-textarea" rows="5" [(ngModel)]="nReq" placeholder="Es. Nel calendario aggiungi l'export ICS dell'agenda…"></textarea>
        </hx-field>
        <div class="two">
          <hx-field label="Motore">
            <select class="hx-select" [(ngModel)]="nEngine">@for (e of engines; track e) { <option [value]="e">{{ engineLabel(e) }}</option> }</select>
          </hx-field>
          <hx-field label="Servizi coinvolti" hint="Facoltativo, separati da virgola">
            <input class="hx-input" [(ngModel)]="nServices" placeholder="chronos, webui" />
          </hx-field>
        </div>
        <hx-field label="Continua un dossier" hint="Facoltativo: Forge riprende SPEC e PROGRESS di un lavoro esistente">
          <select class="hx-select" [(ngModel)]="nWorkdoc">
            <option value="">Nuovo dossier</option>
            @for (d of dossiers(); track d.name) { <option [value]="d.name">{{ d.name }}{{ d.progress ? ' · ' + d.progress.done + '/' + d.progress.total : '' }}</option> }
          </select>
        </hx-field>
      </div>
      <ng-container footer>
        <button hx-btn variant="ghost" (click)="newOpen.set(false)">Annulla</button>
        <button hx-btn variant="primary" icon="send" [disabled]="nReq.trim().length < 8" [loading]="store.busy()" (click)="submitNew()">Avvia sviluppo</button>
      </ng-container>
    </hx-modal>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .layout { flex: 1; min-height: 0; display: grid; grid-template-columns: 300px minmax(0, 1fr); }
    .layout[data-size=wide] { grid-template-columns: 300px minmax(0, 1fr) minmax(360px, 34%); }
    .layout[data-size=phone] { grid-template-columns: 1fr; }
    .layout[data-size=phone].has-sel .list { display: none; }
    .layout[data-size=phone]:not(.has-sel) .center-col { display: none; }
    .list { border-right: 1px solid var(--border); display: flex; flex-direction: column; min-height: 0; background: var(--bg-subtle); }
    .lhead { padding: 10px 10px 6px; display: flex; flex-direction: column; gap: 8px; }
    .search { position: relative; } .search hx-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search input { padding-left: 32px; height: 34px; width: 100%; }
    .chips { display: flex; gap: 4px; flex-wrap: wrap; }
    .chips button { font-size: 12px; padding: 3px 10px; border-radius: var(--radius-full); color: var(--text-2); background: var(--surface-2); display: inline-flex; gap: 5px; align-items: center; }
    .chips button.on { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
    .chips i { font-style: normal; font-size: 10.5px; background: var(--accent); color: var(--accent-contrast); border-radius: var(--radius-full); padding: 0 5px; }
    .rows { flex: 1; overflow: auto; padding: 4px 6px 16px; display: flex; flex-direction: column; gap: 1px; }
    .center { display: grid; place-items: center; padding: 24px; }
    .lerr { display: flex; gap: 6px; font-size: 12.5px; color: var(--danger); padding: 8px; }
    .trow { display: flex; gap: 10px; padding: 9px 10px; border-radius: var(--radius-md); text-align: left; width: 100%; }
    .trow:hover { background: var(--surface-2); }
    .trow.on { background: var(--surface); box-shadow: var(--shadow-1); }
    .sdot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-3); flex-shrink: 0; margin-top: 6px; }
    .sdot[data-tone=success] { background: var(--success); } .sdot[data-tone=danger] { background: var(--danger); }
    .sdot[data-tone=warning] { background: var(--warning); } .sdot[data-tone=accent] { background: var(--accent); } .sdot[data-tone=info] { background: var(--info); }
    .sdot.pulse { animation: hx-pulse 1.4s infinite; }
    .tmain { min-width: 0; flex: 1; }
    .treq { font-size: 13.5px; color: var(--text); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.35; }
    .tmeta { font-size: 11.5px; color: var(--text-3); margin-top: 3px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .center-col { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
    .thead { display: flex; align-items: flex-start; gap: 10px; padding: 12px 18px 10px; border-bottom: 1px solid var(--border); }
    .min0 { min-width: 0; }
    .ttitle { font-size: 15px; font-weight: 600; line-height: 1.35; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .tsub { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); margin-top: 4px; min-width: 0; flex-wrap: wrap; }
    .mono { font-family: var(--font-mono); font-size: 11.5px; }
    .acts { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; flex-shrink: 0; }
    .ctabs { padding: 8px 18px 0; }
    .chat { flex: 1; overflow: auto; padding: 16px 22px 20px; }
    .summary { display: flex; gap: 10px; padding: 10px 12px; margin-bottom: 14px; border-radius: var(--radius-md); background: var(--accent-soft); font-size: 13.5px; }
    .summary hx-icon { color: var(--accent); margin-top: 2px; flex-shrink: 0; }
    .summary b { display: block; margin-bottom: 3px; }
    .pre-wrap { white-space: pre-wrap; word-break: break-word; }
    .composer { border-top: 1px solid var(--border); padding: 10px 18px 12px; display: flex; flex-direction: column; gap: 8px; background: var(--surface); }
    .composer textarea { resize: vertical; min-height: 52px; }
    .crow { display: flex; align-items: center; gap: 10px; }
    .crow select { font-size: 12.5px; max-width: 180px; width: auto; }
    .hint { font-size: 11.5px; color: var(--text-3); }
    .placeholder { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 20px; overflow: auto; }
    .engines { display: flex; flex-direction: column; gap: 6px; width: min(460px, 100%); font-size: 13px; border: 1px solid var(--border); border-radius: var(--radius-lg, 12px); padding: 12px 14px; }
    .eng { display: flex; align-items: center; gap: 8px; min-width: 0; }
    .eng .sdot { margin-top: 0; }
    .muted { color: var(--text-3); font-size: 12px; }
    .side { border-left: 1px solid var(--border); min-height: 0; display: flex; flex-direction: column; }
    .form { display: flex; flex-direction: column; gap: 14px; padding-bottom: 6px; }
    .two { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    @media (max-width: 860px) {
      :host ::ng-deep hx-page-header { padding-left: 56px; }
      .thead { padding: 10px 12px; flex-wrap: wrap; } .acts { flex-basis: 100%; justify-content: flex-start; } .chat { padding: 12px 12px 16px; } .composer { padding: 8px 12px 10px; }
      .ctabs { padding: 8px 12px 0; } .two { grid-template-columns: 1fr; } .hint { display: none; }
    }
  `],
})
export class ForgePageComponent implements OnInit, OnDestroy {
  readonly store = inject(ForgeStore);
  private api = inject(ForgeApi);
  private dialogs = inject(DialogService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  readonly modeOpts = [{ value: 'tasks', label: 'Task', icon: 'terminal' }, { value: 'repo', label: 'Repository', icon: 'branch' }];
  readonly centerOpts = [{ value: 'chat', label: 'Conversazione', icon: 'chat' }, { value: 'details', label: 'Dettagli', icon: 'info' }];
  readonly filters: { id: 'all' | 'open' | 'done' | 'failed'; label: string }[] = [
    { id: 'all', label: 'Tutti' }, { id: 'open', label: 'Aperti' }, { id: 'done', label: 'Applicati' }, { id: 'failed', label: 'Non riusciti' },
  ];
  readonly engines = ['', 'local', 'cloud', 'claude'];

  readonly mode = signal<'tasks' | 'repo'>('tasks');
  readonly width = signal(window.innerWidth);
  readonly size = computed<'wide' | 'mid' | 'phone'>(() => this.width() >= 1280 ? 'wide' : this.width() > 860 ? 'mid' : 'phone');
  readonly centerTab = signal<'chat' | 'details'>('chat');
  readonly repoNav = signal<RepoNav | null>(null);
  readonly newOpen = signal(false);
  readonly dossiers = signal<Dossier[]>([]);
  readonly subtitle = computed(() => {
    const c = this.store.counts();
    return c.review ? `${c.review} da rivedere · Forge sviluppa Hestia su rami separati` : 'Forge sviluppa Hestia su rami separati: niente cambia finché non approvi';
  });
  readonly engineRows = computed(() => Object.entries(this.store.status()?.engines ?? {}).map(([name, e]) => ({ name, ...e })));

  followUp = '';
  followEngine = '';
  nReq = ''; nEngine = ''; nServices = ''; nWorkdoc = '';

  private chatEl = viewChild<ElementRef<HTMLElement>>('chat');
  private stick = true;
  readonly ago = ago;

  constructor() {
    // Follow the conversation while it grows, unless the user scrolled up.
    effect(() => {
      this.store.transcript();
      const el = this.chatEl()?.nativeElement;
      if (el && this.stick) queueMicrotask(() => el.scrollTop = el.scrollHeight);
    });
  }

  ngOnInit() {
    this.store.start();
    const q = this.route.snapshot.queryParamMap;
    if (q.get('view') === 'repo') this.mode.set('repo');
    const task = q.get('task');
    if (task) this.select(task);
    else if (this.store.selectedId() && this.size() !== 'phone') this.select(this.store.selectedId());
  }
  ngOnDestroy() { this.store.stop(); this.changedSub?.unsubscribe(); }

  private assistant = inject(AssistantService);
  // The assistant created a Forge task (notice forge.task): show it in the list.
  private changedSub = this.assistant.changed$.subscribe(k => { if (k === 'forge.task' || k === 'action.done') void this.store.loadList(true); });

  /** "Crea con Hestia" with the selected task as context (explain it, or ask a follow-up). */
  askHestia() {
    const t = this.store.task();
    this.assistant.open(t ? {
      page: 'forge', intent: 'ask', label: `Sviluppo · ${t.request.slice(0, 60)}`,
      hints: { task: t.id, stato: t.state, workdoc: t.workdoc, servizi: (t.services ?? []).join(','), richiesta: t.request.slice(0, 300) },
      suggestions: ['Spiegami cosa ha cambiato questo task', 'Perché è fallito e cosa propongo?', 'Crea uno sviluppo di seguito che…'],
    } : {
      page: 'forge', intent: 'create', label: 'Sviluppo',
      suggestions: ['Aggiungi a Hestia un comando che…', 'Correggi questo problema: …', 'Cosa sta sviluppando Forge adesso?'],
    });
  }

  @HostListener('window:resize') onResize() { this.width.set(window.innerWidth); }

  meta(t: ForgeTask) { return STATE_META[t.state] ?? STATE_META['new']; }
  engineLabel(e: string) { return ENGINE_LABEL[e] ?? e; }
  engineOf(t: ForgeTask) { return ENGINE_LABEL[t.engine || t.engine_requested || ''] ?? t.engine ?? '—'; }

  select(id: string | null) {
    this.stick = true;
    this.centerTab.set('chat');
    this.store.select(id);
    this.router.navigate([], { queryParams: { task: id || null, view: null }, queryParamsHandling: 'merge', replaceUrl: true });
  }
  setMode(m: 'tasks' | 'repo') {
    this.mode.set(m);
    this.router.navigate([], { queryParams: { view: m === 'repo' ? 'repo' : null }, queryParamsHandling: 'merge', replaceUrl: true });
  }
  openRepo(nav: RepoNav) { this.repoNav.set({ ...nav }); this.setMode('repo'); }
  openTaskFromRepo(id: string) { this.setMode('tasks'); this.select(id); }

  onScroll() {
    const el = this.chatEl()?.nativeElement;
    if (el) this.stick = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  async approve(t: ForgeTask) {
    const tests = t.tests?.ok === false ? ' Attenzione: i test sono falliti.' : '';
    if (await this.dialogs.confirm('Applicare la modifica?', `Forge fa il merge del ramo e, se configurato, riavvia i servizi.${tests}`, 'Approva e applica')) {
      this.store.act('approve');
    }
  }
  async reject() {
    if (await this.dialogs.confirm('Rifiutare il task?', 'Il ramo viene eliminato e la modifica scartata.', 'Rifiuta', true)) this.store.act('reject');
  }
  async rollback() {
    if (await this.dialogs.confirm('Annullare la modifica?', 'Forge crea un commit di revert del merge e riavvia i servizi coinvolti.', 'Rollback', true)) {
      this.store.act('rollback');
    }
  }

  composerKey(e: KeyboardEvent) {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); const t = this.store.task(); if (t) this.sendFollowUp(t); }
  }
  async sendFollowUp(t: ForgeTask) {
    const text = this.followUp.trim();
    if (text.length < 8) return;
    if (await this.store.submit({ request: text, parent_task: t.id, engine: this.followEngine || undefined })) this.followUp = '';
  }

  async openNew() {
    this.newOpen.set(true);
    try { this.dossiers.set(await this.api.dossiers()); } catch { this.dossiers.set([]); }
  }
  async submitNew() {
    const services = this.nServices.split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
    const ok = await this.store.submit({ request: this.nReq.trim(), engine: this.nEngine || undefined, services, workdoc: this.nWorkdoc || undefined });
    if (ok) {
      this.newOpen.set(false);
      this.nReq = ''; this.nServices = ''; this.nWorkdoc = '';
      this.setMode('tasks');
    }
  }
}
