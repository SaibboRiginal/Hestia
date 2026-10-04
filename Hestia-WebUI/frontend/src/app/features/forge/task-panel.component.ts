import { ChangeDetectionStrategy, Component, computed, effect, inject, output, signal } from '@angular/core';
import { DiffComponent, MarkdownComponent, UI } from '../../ui';
import { ForgeStore, SidePanel } from './forge.store';
import { ENGINE_LABEL, FILE_STATUS, STATE_META } from './forge.models';
import { duration, shortDate } from './forge-format';

/** Context panel of a task (right side, Codex-style): overview, files, diff, dossier, tests, logs, branch. */
@Component({
  selector: 'forge-task-panel',
  imports: [...UI, DiffComponent, MarkdownComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="tabs" role="tablist">
      @for (t of tabs; track t.id) {
        <button role="tab" [class.on]="store.panel() === t.id" (click)="store.setPanel(t.id)" [attr.title]="t.label">
          <hx-icon [name]="t.icon" [size]="14" /><span>{{ t.label }}</span>
          @if (t.id === 'files' && store.files()?.files?.length) { <i>{{ store.files()!.files.length }}</i> }
        </button>
      }
    </div>
    <div class="body">
      @if (store.task(); as t) {
        @switch (store.panel()) {
          @case ('overview') {
            <dl class="kv">
              <dt>Stato</dt><dd><hx-badge [tone]="meta().tone">{{ meta().label }}</hx-badge></dd>
              <dt>Motore</dt><dd>{{ engine() }}@if (t.engine_requested && t.engine_requested !== 'auto' && t.engine_requested !== t.engine) { <span class="muted"> (richiesto {{ t.engine_requested }})</span> }</dd>
              <dt>Origine</dt><dd>{{ t.requested_by || 'utente' }} via {{ t.source || 'hestia' }}</dd>
              @if (t.services?.length) { <dt>Servizi</dt><dd>{{ t.services!.join(', ') }}</dd> }
              @if (t.workdoc) { <dt>Dossier</dt><dd><button class="lnk mono" (click)="store.setPanel('dossier')">{{ t.workdoc }}</button></dd> }
              @if (t.parent_task) { <dt>Segue</dt><dd><button class="lnk mono" (click)="store.select(t.parent_task!)">{{ t.parent_task!.slice(0, 6) }}</button></dd> }
              @if (t.turns) { <dt>Turni</dt><dd>{{ t.turns }}</dd> }
              @if (t.cost_usd != null) { <dt>Costo</dt><dd>\${{ t.cost_usd!.toFixed(3) }}</dd> }
              @if (t.engine_ms) { <dt>Durata</dt><dd>{{ dur(t.engine_ms) }}</dd> }
              @if (store.files()?.totals; as tot) {
                <dt>Modifiche</dt><dd><button class="lnk" (click)="store.setPanel('files')">{{ tot.files }} file</button> · <b class="a">+{{ tot.added }}</b> <b class="d">−{{ tot.deleted }}</b></dd>
              }
              @if (t.tests) {
                <dt>Test</dt><dd><button class="lnk" (click)="store.setPanel('tests')">{{ t.tests.ok === true ? '✅ passati' : t.tests.ok === false ? '❌ falliti' : '➖ nessun test' }}</button></dd>
              }
              @if (t.branch) { <dt>Ramo</dt><dd><button class="lnk mono" (click)="store.setPanel('branch')">{{ t.branch }}</button></dd> }
              @if (t.merge_sha) { <dt>Merge</dt><dd><button class="lnk mono" (click)="openRepo.emit({ view: 'commit', sha: t.merge_sha! })">{{ t.merge_sha!.slice(0, 8) }}</button></dd> }
              <dt>Creato</dt><dd>{{ date(t.created_at) }}</dd>
            </dl>
            @if (t.error) { <div class="err"><hx-icon name="alert" [size]="14" /> {{ t.error }}</div> }
            @if (t.deploy_plan; as d) {
              <h4>Piano di deploy</h4>
              <p class="small">
                @if (d.restart.length) { Riavvio: <b>{{ d.restart.join(', ') }}</b>. }
                @if (d.rebuild.length) { Da ricostruire a mano: <code>up-all.bat --build {{ d.rebuild.join(' ') }}</code>. }
                @if (d.restart_self) { Hephaestus si riavvia da solo per ultimo. }
                @if (!d.restart.length && !d.rebuild.length && !d.restart_self) { Nessun servizio da riavviare. }
              </p>
            }
            <h4>Cronologia</h4>
            <ol class="timeline">
              @for (h of history(); track $index) {
                <li><span class="dot" [attr.data-tone]="stateTone(h.state)"></span>
                  <div><b>{{ stateLabel(h.state) }}</b>&nbsp; <span class="muted">{{ date(h.ts) }}</span>
                    @if (h.note) { <div class="note">{{ h.note }}</div> }</div></li>
              }
            </ol>
          }
          @case ('files') {
            @if (store.files(); as f) {
              @if (f.live) { <p class="small muted">Modifiche in corso nella cartella di lavoro del task (si aggiornano da sole).</p> }
              @for (x of f.files; track x.path) {
                <button class="frow" (click)="focus.set(x.path); store.setPanel('diff')">
                  <span class="st" [attr.data-st]="x.status" [attr.title]="fileStatus(x.status)">{{ x.status }}</span>
                  <span class="mono hx-truncate">{{ x.path }}</span>
                  <span class="cnt">@if (x.binary) { bin } @else if (x.added !== null) { <b class="a">+{{ x.added }}</b> <b class="d">−{{ x.deleted }}</b> }</span>
                </button>
              } @empty { <hx-empty icon="file" title="Nessun file modificato" /> }
              @if (f.error) { <div class="err">{{ f.error }}</div> }
            } @else { <hx-spinner /> }
          }
          @case ('diff') {
            @if (store.files(); as f) {
              @if (focus()) { <button class="lnk" (click)="focus.set(null)">← Tutti i file</button> }
              <hx-diff [diff]="f.diff" [only]="focus()" [truncated]="!!f.truncated" />
            } @else { <hx-spinner /> }
          }
          @case ('dossier') {
            @if (store.workdoc(); as w) {
              @if (w.docs.length) {
                <div class="docnav">
                  @for (d of w.docs; track d.path) {
                    <button [class.on]="doc() === d.path || (!doc() && $first)" (click)="doc.set(d.path)" [attr.title]="d.path">
                      {{ d.group === 'changed' ? '✎ ' : '' }}{{ d.name }}
                    </button>
                  }
                </div>
                @if (currentDoc(); as d) {
                  <div class="docpath mono">{{ d.path }}</div>
                  <hx-markdown [text]="d.content" />
                }
              } @else { <hx-empty icon="list" title="Nessun dossier">Questo task non ha (ancora) un dossier in docs/work.</hx-empty> }
            } @else { <hx-spinner /> }
          }
          @case ('tests') {
            @if (store.tests(); as tt) {
              @if (!tt.ran) { <hx-empty icon="flask" title="Test non ancora eseguiti">Forge esegue i test dopo il lavoro del motore.</hx-empty> }
              @else {
                <div class="tsum">
                  <hx-badge [tone]="tt.ok === true ? 'success' : tt.ok === false ? 'danger' : 'neutral'">{{ tt.ok === true ? 'passati' : tt.ok === false ? 'falliti' : 'nessun test' }}</hx-badge>
                  @for (k of summaryKeys(tt.summary); track k) { <span class="small">{{ tt.summary[k] }} {{ k }}</span> }
                </div>
                @if (tt.summary['failed_tests']?.length) {
                  <ul class="failed">@for (f of tt.summary['failed_tests']; track f) { <li class="mono">{{ f }}</li> }</ul>
                }
                <pre class="log">{{ tt.output }}</pre>
              }
            } @else { <hx-spinner /> }
          }
          @case ('logs') {
            @if (store.logs(); as l) {
              @if (l.error) { <h4>Errore</h4><pre class="log err-log">{{ l.error }}</pre> }
              <h4>Motore</h4><pre class="log">{{ l.engine || '(vuoto)' }}</pre>
              @if (l.deploy) { <h4>Deploy</h4><pre class="log">{{ l.deploy }}</pre> }
              <p class="small muted">{{ l.hint }}</p>
            } @else { <hx-spinner /> }
          }
          @case ('branch') {
            <dl class="kv">
              <dt>Ramo</dt><dd class="mono">{{ t.branch || '—' }}</dd>
              <dt>Base</dt><dd class="mono">{{ t.base_branch || '—' }}@if (t.base_sha) { &#64; {{ t.base_sha!.slice(0, 8) }} }</dd>
              @if (t.commit_sha) { <dt>Commit</dt><dd><button class="lnk mono" (click)="openRepo.emit({ view: 'commit', sha: t.commit_sha! })">{{ t.commit_sha!.slice(0, 8) }}</button></dd> }
              @if (t.merge_sha) { <dt>Merge</dt><dd><button class="lnk mono" (click)="openRepo.emit({ view: 'commit', sha: t.merge_sha! })">{{ t.merge_sha!.slice(0, 8) }}</button></dd> }
            </dl>
            <div class="row-btns">
              @if (t.branch && t.base_branch && !['rejected', 'no_changes'].includes(t.state)) {
                <button hx-btn size="sm" icon="diff" (click)="openRepo.emit({ view: 'compare', base: t.base_branch!, head: t.merge_sha ? t.merge_sha! : t.branch! })">Confronta nel repository</button>
              }
              <button hx-btn size="sm" variant="ghost" icon="branch" (click)="openRepo.emit({ view: 'branches' })">Tutti i rami</button>
            </div>
            @if (t.diff_stat) { <h4>Riepilogo</h4><pre class="log">{{ t.diff_stat }}</pre> }
          }
        }
      }
    </div>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; min-height: 0; flex: 1; background: var(--bg-subtle); }
    .tabs { display: flex; flex-wrap: wrap; gap: 2px; padding: 8px 10px; border-bottom: 1px solid var(--border); flex-shrink: 0; }
    .tabs button { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 9px; border-radius: var(--radius-md); font-size: 12.5px; color: var(--text-2); white-space: nowrap; }
    .tabs button:hover { background: var(--surface-2); color: var(--text); }
    .tabs button.on { background: var(--surface); color: var(--text); font-weight: 500; box-shadow: var(--shadow-1); }
    .tabs i { font-style: normal; font-size: 11px; background: var(--surface-3); border-radius: var(--radius-full); padding: 0 6px; }
    .body { flex: 1; overflow: auto; padding: 14px 16px 24px; font-size: 13px; }
    .kv { display: grid; grid-template-columns: 90px 1fr; gap: 7px 10px; }
    .kv dt { color: var(--text-3); } .kv dd { min-width: 0; word-wrap: break-word; }
    .muted { color: var(--text-3); } .small { font-size: 12.5px; color: var(--text-2); }
    .mono { font-family: var(--font-mono); font-size: 12px; }
    .lnk { color: var(--accent); font-size: inherit; text-align: left; } .lnk:hover { text-decoration: underline; }
    .a { color: var(--success); font-weight: 600; } .d { color: var(--danger); font-weight: 600; }
    h4 { font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin: 18px 0 8px; font-weight: 600; }
    .err { display: flex; gap: 6px; margin-top: 12px; padding: 8px 10px; background: var(--danger-soft); color: var(--danger); border-radius: var(--radius-md); white-space: pre-wrap; word-break: break-word; }
    .timeline { list-style: none; display: flex; flex-direction: column; gap: 10px; border-left: 2px solid var(--border); margin-left: 4px; padding-left: 14px; }
    .timeline li { position: relative; }
    .timeline .dot { position: absolute; left: -20px; top: 4px; width: 10px; height: 10px; border-radius: 50%; background: var(--text-3); border: 2px solid var(--bg-subtle); }
    .dot[data-tone=success] { background: var(--success); } .dot[data-tone=danger] { background: var(--danger); }
    .dot[data-tone=warning] { background: var(--warning); } .dot[data-tone=accent] { background: var(--accent); } .dot[data-tone=info] { background: var(--info); }
    .note { font-size: 12px; color: var(--text-2); font-family: var(--font-mono); word-break: break-word; }
    .frow { display: flex; align-items: center; gap: 8px; padding: 6px 6px; width: 100%; text-align: left; border-radius: var(--radius-sm, 6px); }
    .frow:hover { background: var(--surface-2); }
    .frow .mono { flex: 1; min-width: 0; }
    .st { font: 600 10.5px var(--font-mono); width: 18px; height: 18px; border-radius: 4px; display: grid; place-items: center; background: var(--info-soft); color: var(--info); flex-shrink: 0; }
    .st[data-st=A], .st[data-st='?'] { background: var(--success-soft); color: var(--success); }
    .st[data-st=D] { background: var(--danger-soft); color: var(--danger); }
    .st[data-st=R] { background: var(--warning-soft); color: var(--warning); }
    .cnt { font-size: 12px; white-space: nowrap; }
    .docnav { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 10px; }
    .docnav button { font-size: 12px; padding: 3px 9px; border-radius: var(--radius-full); background: var(--surface-2); color: var(--text-2); }
    .docnav button.on { background: var(--accent-soft); color: var(--accent); font-weight: 500; }
    .docpath { color: var(--text-3); margin-bottom: 10px; }
    .tsum { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
    .failed { margin: 0 0 10px 18px; color: var(--danger); }
    .log { font-family: var(--font-mono); font-size: 11.5px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; background: var(--surface);
           border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; max-height: 60vh; overflow: auto; margin: 0; }
    .err-log { color: var(--danger); }
    .row-btns { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
    hx-diff { margin-top: 8px; }
  `],
})
export class TaskPanelComponent {
  readonly store = inject(ForgeStore);
  openRepo = output<{ view: 'commit' | 'compare' | 'branches'; sha?: string; base?: string; head?: string }>();

  readonly tabs: { id: SidePanel; label: string; icon: string }[] = [
    { id: 'overview', label: 'Panoramica', icon: 'info' }, { id: 'files', label: 'File', icon: 'file' },
    { id: 'diff', label: 'Diff', icon: 'diff' }, { id: 'dossier', label: 'Dossier', icon: 'list' },
    { id: 'tests', label: 'Test', icon: 'flask' }, { id: 'logs', label: 'Log', icon: 'terminal' },
    { id: 'branch', label: 'Ramo', icon: 'branch' },
  ];
  readonly focus = signal<string | null>(null);
  readonly doc = signal<string | null>(null);

  readonly meta = computed(() => STATE_META[this.store.task()?.state ?? 'new'] ?? STATE_META['new']);
  readonly engine = computed(() => { const t = this.store.task(); return ENGINE_LABEL[t?.engine ?? ''] ?? t?.engine ?? '—'; });
  readonly history = computed(() => [...(this.store.task()?.history ?? [])].reverse());
  readonly currentDoc = computed(() => {
    const docs = this.store.workdoc()?.docs ?? [];
    return docs.find(d => d.path === this.doc()) ?? docs[0] ?? null;
  });

  constructor() {
    effect(() => { this.store.selectedId(); this.focus.set(null); this.doc.set(null); });
  }

  date = shortDate;
  dur = duration;
  stateLabel(s: string) { return STATE_META[s]?.label ?? s; }
  stateTone(s: string) { return STATE_META[s]?.tone ?? 'neutral'; }
  fileStatus(s?: string) { return FILE_STATUS[s ?? 'M']?.label ?? s; }
  summaryKeys(s: Record<string, any>) { return Object.keys(s).filter(k => k !== 'failed_tests'); }
}
