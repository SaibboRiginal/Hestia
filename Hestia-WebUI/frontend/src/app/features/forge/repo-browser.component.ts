import { ChangeDetectionStrategy, Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DiffComponent, MarkdownComponent, UI, ToastService } from '../../ui';
import { ForgeApi } from './forge.api';
import { Branch, Commit, CommitDetail, Compare, Dossier, RepoFile, Tag, TreeEntry } from './forge.models';
import { GraphRow, layoutGraph } from './graph';
import { ago, shortDate } from './forge-format';

export type RepoView = 'log' | 'commit' | 'files' | 'branches' | 'compare' | 'tags' | 'dossiers';
export interface RepoNav { view: RepoView; ref?: string; path?: string; sha?: string; base?: string; head?: string; }

const LANE = 14, ROW = 34;

/** Read-only repository browser: commit graph, commit detail, files at any ref, branches, compare, tags, dossiers. */
@Component({
  selector: 'forge-repo',
  imports: [...UI, FormsModule, NgTemplateOutlet, DiffComponent, MarkdownComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="tabs">
      @for (t of tabs; track t.id) {
        <button [class.on]="view() === t.id || (t.id === 'log' && view() === 'commit')" (click)="go({ view: t.id })">
          <hx-icon [name]="t.icon" [size]="14" /> {{ t.label }}
        </button>
      }
      <span class="hx-grow"></span>
      <label class="ref" title="Ramo o commit mostrato">
        <hx-icon name="branch" [size]="14" />
        <select class="hx-select" [ngModel]="ref()" (ngModelChange)="setRef($event)">
          @for (b of branches(); track b.name) { <option [value]="b.name">{{ b.name }}</option> }
          @if (!isBranch(ref())) { <option [value]="ref()">{{ ref() }}</option> }
        </select>
      </label>
    </div>

    <div class="body">
      @if (loading()) { <div class="center"><hx-spinner /></div> }
      @switch (view()) {
        <!-- ── commit log with graph ── -->
        @case ('log') {
          <div class="toolbar">
            <hx-toggle [checked]="allRefs()" (changed)="allRefs.set($event); loadLog()" label="Tutti i rami" />
            @if (logPath()) { <span class="chip">Solo <code>{{ logPath() }}</code> <button (click)="logPath.set(''); loadLog()"><hx-icon name="x" [size]="12" /></button></span> }
          </div>
          <div class="log">
            @for (c of commits(); track c.sha; let i = $index) {
              @let g = graph()[i];
              <button class="crow" (click)="go({ view: 'commit', sha: c.sha })">
                <svg class="graph" [attr.width]="gw()" [attr.height]="row" [attr.viewBox]="'0 0 ' + gw() + ' ' + row">
                  @for (s of g.segs; track $index) {
                    <path [attr.d]="seg(s)" [attr.stroke]="'var(--cal-' + (s.c + 1) + ')'" fill="none" stroke-width="2" />
                  }
                  <circle [attr.cx]="x(g.lane)" [attr.cy]="row / 2" r="4.5" [attr.fill]="c.parents.length > 1 ? 'var(--surface)' : 'var(--cal-' + (g.color + 1) + ')'"
                          [attr.stroke]="'var(--cal-' + (g.color + 1) + ')'" stroke-width="2" />
                </svg>
                <span class="subj">
                  @for (r of c.refs; track r) { <span class="refb" [class.cur]="r.startsWith('HEAD')" [class.forge]="r.includes('auto/forge/')">{{ r.replace('HEAD -> ', '') }}</span> }
                  {{ c.subject }}
                </span>
                <span class="meta">{{ c.author }}</span>
                <span class="meta mono">{{ c.short }}</span>
                <span class="meta" [title]="c.date">{{ ago(c.date) }}</span>
              </button>
            }
            @if (hasMore()) { <button hx-btn variant="ghost" size="sm" (click)="loadLog(true)">Carica altri</button> }
            @if (!commits().length && !loading()) { <hx-empty icon="commit" title="Nessun commit" /> }
          </div>
        }

        <!-- ── commit detail ── -->
        @case ('commit') {
          @if (commit(); as c) {
            <div class="head">
              <button hx-btn variant="ghost" size="sm" icon="arrow-left" (click)="go({ view: 'log' })">Commit</button>
              <h2>{{ c.subject }}</h2>
              <div class="sub">
                <span class="mono">{{ c.short }}</span> · {{ c.author }} · {{ shortDate(c.date) }}
                @if (c.parents.length > 1) { · <hx-badge tone="info">merge</hx-badge> }
                @for (r of c.refs; track r) { <span class="refb">{{ r }}</span> }
              </div>
              @if (c.body) { <pre class="body-msg">{{ c.body }}</pre> }
              <div class="sub">
                @for (p of c.parents; track p) { <button class="lnk mono" (click)="go({ view: 'commit', sha: p })">genitore {{ p.slice(0, 8) }}</button> }
                <button class="lnk" (click)="go({ view: 'files', ref: c.sha, path: '' })">Sfoglia i file a questo commit</button>
              </div>
            </div>
            <ng-container *ngTemplateOutlet="fileList; context: { $implicit: c.files, ref: c.sha }" />
            <hx-diff [diff]="c.diff" [truncated]="c.truncated" [only]="onlyFile()" />
          }
        }

        <!-- ── file browser ── -->
        @case ('files') {
          <div class="crumbs">
            <button class="lnk" (click)="openPath('')">{{ ref() }}</button>
            @for (p of crumbs(); track p.path) { / <button class="lnk" (click)="openPath(p.path)">{{ p.name }}</button> }
          </div>
          @if (file(); as f) {
            <div class="fhead">
              <span class="mono">{{ f.path }}</span>
              <span class="meta">{{ size(f.size) }}</span>
              <span class="hx-grow"></span>
              @if (isMd(f.path)) { <hx-segmented [options]="mdOpts" [(value)]="mdMode" /> }
              <button hx-btn variant="ghost" size="sm" icon="commit" (click)="logPath.set(f.path); go({ view: 'log' })">Storia</button>
            </div>
            @if (f.binary) { <hx-empty icon="file" title="File binario" /> }
            @else if (isMd(f.path) && mdMode() === 'render') { <div class="mdbox"><hx-markdown [text]="f.content" /></div> }
            @else {
              <div class="src">@for (l of srcLines(); track $index) {<div><i>{{ $index + 1 }}</i><span>{{ l }}</span></div>}</div>
            }
            @if (f.truncated) { <div class="note">File troncato: troppo grande da mostrare per intero.</div> }
          } @else {
            <div class="tree">
              @for (e of tree(); track e.path) {
                <button class="trow" [disabled]="e.secret" (click)="e.type === 'tree' ? openPath(e.path) : openFile(e.path)">
                  <hx-icon [name]="e.type === 'tree' ? 'folder' : 'file'" [size]="15" />
                  <span>{{ e.name }}</span>
                  @if (e.secret) { <hx-badge tone="warning">segreto, non mostrato</hx-badge> }
                  <span class="hx-grow"></span>
                  <span class="meta">{{ e.size !== null ? size(e.size) : '' }}</span>
                </button>
              }
            </div>
          }
        }

        <!-- ── branches ── -->
        @case ('branches') {
          <div class="list">
            @for (b of branches(); track b.name) {
              <div class="brow">
                <hx-icon name="branch" [size]="15" />
                <div class="hx-grow min0">
                  <div class="bname">{{ b.name }}
                    @if (b.base) { <hx-badge tone="accent">base</hx-badge> }
                    @if (b.current) { <hx-badge tone="success">attivo</hx-badge> }
                    @if (b.forge_task) { <hx-badge tone="info">Forge</hx-badge> }
                  </div>
                  <div class="meta hx-truncate">{{ b.subject }} · {{ b.author }} · {{ ago(b.date) }}</div>
                </div>
                @if (!b.base) {
                  <span class="ab" title="Commit avanti / indietro rispetto al ramo base"><b class="a">↑{{ b.ahead }}</b> <b class="d">↓{{ b.behind }}</b></span>
                }
                <button hx-btn variant="ghost" size="sm" (click)="go({ view: 'log', ref: b.name })">Storia</button>
                @if (!b.base) { <button hx-btn variant="ghost" size="sm" (click)="go({ view: 'compare', base: baseBranch(), head: b.name })">Confronta</button> }
                @if (b.forge_task) { <button hx-btn variant="ghost" size="sm" icon="terminal" (click)="openTask.emit(b.forge_task!)">Task</button> }
              </div>
            }
          </div>
        }

        <!-- ── compare ── -->
        @case ('compare') {
          <div class="toolbar">
            <select class="hx-select" [(ngModel)]="cmpBase">@for (b of branches(); track b.name) { <option [value]="b.name">{{ b.name }}</option> }</select>
            <span>…</span>
            <select class="hx-select" [(ngModel)]="cmpHead">@for (b of branches(); track b.name) { <option [value]="b.name">{{ b.name }}</option> }</select>
            <button hx-btn size="sm" variant="primary" (click)="loadCompare()">Confronta</button>
          </div>
          @if (compare(); as c) {
            <p class="meta">{{ c.head }} è <b>{{ c.ahead }}</b> commit avanti e <b>{{ c.behind }}</b> indietro rispetto a {{ c.base }}.</p>
            @for (k of c.commits; track k.sha) {
              <button class="crow small" (click)="go({ view: 'commit', sha: k.sha })"><span class="mono meta">{{ k.short }}</span><span class="subj">{{ k.subject }}</span><span class="meta">{{ ago(k.date) }}</span></button>
            }
            <ng-container *ngTemplateOutlet="fileList; context: { $implicit: c.files, ref: c.head }" />
            <hx-diff [diff]="c.diff" [truncated]="c.truncated" [only]="onlyFile()" />
          }
        }

        <!-- ── tags ── -->
        @case ('tags') {
          @for (t of tags(); track t.name) {
            <button class="crow small" (click)="go({ view: 'commit', sha: t.sha })"><hx-icon name="tag" [size]="14" /><span class="subj">{{ t.name }} <span class="meta">{{ t.subject }}</span></span><span class="meta">{{ ago(t.date) }}</span></button>
          } @empty { <hx-empty icon="tag" title="Nessun tag">Il repository non ha ancora tag.</hx-empty> }
        }

        <!-- ── dossiers (docs/work) + changelog ── -->
        @case ('dossiers') {
          <div class="toolbar"><button hx-btn variant="ghost" size="sm" icon="file" (click)="openFileAt('CHANGELOG.md')">CHANGELOG generale</button></div>
          @for (d of dossiers(); track d.name) {
            <button class="drow" (click)="openPath(d.path); view.set('files')">
              <div class="hx-grow min0">
                <div class="bname hx-truncate">{{ d.title || d.name }}</div>
                <div class="meta hx-truncate">{{ d.name }}@if (d.source) { · {{ d.source }} }</div>
              </div>
              @if (d.version) { <hx-badge>v{{ d.version }}</hx-badge> }
              @if (d.status) { <hx-badge tone="info">{{ d.status }}</hx-badge> }
              @if (d.progress; as p) {
                <span class="prog" [title]="p.done + ' su ' + p.total + ' punti fatti'"><span [style.width.%]="p.total ? 100 * p.done / p.total : 0"></span></span>
                <span class="meta">{{ p.done }}/{{ p.total }}</span>
              }
            </button>
          } @empty { <hx-empty icon="folder" title="Nessun dossier" /> }
        }
      }
    </div>

    <ng-template #fileList let-files let-ref="ref">
      <div class="files">
        <button class="frow" [class.on]="!onlyFile()" (click)="onlyFile.set(null)"><b>Tutti i file</b> <span class="meta">({{ files.length }})</span></button>
        @for (f of files; track f.path) {
          <button class="frow" [class.on]="onlyFile() === f.path" (click)="onlyFile.set(f.path)">
            <span class="st" [attr.data-st]="f.status">{{ f.status }}</span>
            <span class="mono hx-truncate">{{ f.path }}</span>
            <span class="cnt">@if (f.binary) { bin } @else { <b class="a">+{{ f.added }}</b> <b class="d">−{{ f.deleted }}</b> }</span>
          </button>
        }
      </div>
    </ng-template>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; min-height: 0; flex: 1; }
    .tabs { display: flex; align-items: center; gap: 2px; padding: 8px 14px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .tabs > button { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border-radius: var(--radius-md); font-size: 13px; color: var(--text-2); }
    .tabs > button:hover { background: var(--surface-2); color: var(--text); }
    .tabs > button.on { background: var(--surface-3); color: var(--text); font-weight: 500; }
    .ref { display: inline-flex; align-items: center; gap: 6px; color: var(--text-3); }
    .ref select { height: 30px; font-size: 12.5px; max-width: 220px; }
    .body { flex: 1; overflow: auto; padding: 14px 18px 30px; position: relative; }
    .center { display: grid; place-items: center; padding: 30px; }
    .toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
    .toolbar select { height: 32px; max-width: 240px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; background: var(--surface-2); padding: 3px 4px 3px 10px; border-radius: var(--radius-full); }
    .chip button { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; }
    .chip button:hover { background: var(--surface-3); }
    .log { display: flex; flex-direction: column; }
    .crow { display: flex; align-items: center; gap: 10px; text-align: left; min-height: 34px; padding: 0 8px 0 0; border-radius: var(--radius-sm, 6px); font-size: 13px; width: 100%; }
    .crow.small { min-height: 30px; padding: 0 8px; }
    .crow:hover { background: var(--surface-2); }
    .graph { flex-shrink: 0; }
    .subj { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
    .meta { color: var(--text-3); font-size: 12px; white-space: nowrap; }
    .mono { font-family: var(--font-mono); font-size: 12px; }
    .refb { display: inline-block; font-size: 11px; padding: 0 6px; margin-right: 5px; border-radius: var(--radius-full); border: 1px solid var(--border-strong); color: var(--text-2); line-height: 17px; }
    .refb.cur { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
    .refb.forge { background: var(--info-soft); color: var(--info); border-color: transparent; }
    .head { margin-bottom: 14px; display: flex; flex-direction: column; gap: 6px; align-items: flex-start; }
    .head h2 { font-family: var(--font-serif); font-weight: 500; font-size: 19px; line-height: 1.3; }
    .sub { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
    .body-msg { font-family: var(--font-mono); font-size: 12.5px; white-space: pre-wrap; background: var(--surface-2); padding: 10px 12px; border-radius: var(--radius-md); width: 100%; margin: 0; }
    .lnk { color: var(--accent); font-size: 12.5px; }
    .lnk:hover { text-decoration: underline; }
    .files { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: 12px; max-height: 260px; overflow: auto; }
    .frow { display: flex; align-items: center; gap: 8px; padding: 5px 10px; font-size: 12.5px; text-align: left; }
    .frow:hover { background: var(--surface-2); } .frow.on { background: var(--accent-soft); }
    .frow .mono { flex: 1; min-width: 0; }
    .st { font: 600 10.5px var(--font-mono); width: 18px; height: 18px; border-radius: 4px; display: grid; place-items: center; background: var(--info-soft); color: var(--info); flex-shrink: 0; }
    .st[data-st=A], .st[data-st='?'] { background: var(--success-soft); color: var(--success); }
    .st[data-st=D] { background: var(--danger-soft); color: var(--danger); }
    .st[data-st=R] { background: var(--warning-soft); color: var(--warning); }
    .cnt { font-size: 12px; white-space: nowrap; }
    .a { color: var(--success); font-weight: 600; } .d { color: var(--danger); font-weight: 600; }
    .crumbs { font-family: var(--font-mono); font-size: 12.5px; margin-bottom: 10px; color: var(--text-3); }
    .tree { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
    .trow { display: flex; align-items: center; gap: 9px; padding: 7px 12px; font-size: 13px; text-align: left; border-bottom: 1px solid var(--border); }
    .trow:last-child { border-bottom: 0; }
    .trow:hover:not(:disabled) { background: var(--surface-2); }
    .trow hx-icon { color: var(--text-3); }
    .trow:disabled { opacity: .6; cursor: not-allowed; }
    .fhead { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
    .src { font-family: var(--font-mono); font-size: 12px; line-height: 1.55; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: auto; background: var(--surface); }
    .src div { display: flex; white-space: pre; min-width: max-content; }
    .src i { font-style: normal; width: 48px; flex-shrink: 0; text-align: right; padding-right: 10px; color: var(--text-3); user-select: none; border-right: 1px solid var(--border); }
    .src span { padding: 0 12px; }
    .mdbox { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px 20px; background: var(--surface); }
    .note { font-size: 12.5px; color: var(--text-3); margin-top: 8px; }
    .list { display: flex; flex-direction: column; gap: 2px; }
    .brow, .drow { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-md); text-align: left; width: 100%; }
    .brow:hover, .drow:hover { background: var(--surface-2); }
    .brow > hx-icon { color: var(--text-3); }
    .bname { font-size: 13.5px; font-weight: 500; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .min0 { min-width: 0; }
    .ab { font-size: 12px; white-space: nowrap; }
    .prog { width: 70px; height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; flex-shrink: 0; }
    .prog span { display: block; height: 100%; background: var(--success); }
    @media (max-width: 720px) {
      .body { padding: 10px 12px 24px; }
      .crow .meta:nth-of-type(1), .crow .meta:nth-of-type(2) { display: none; }
    }
  `],
})
export class RepoBrowserComponent {
  private api = inject(ForgeApi);
  private toast = inject(ToastService);

  /** Navigation requests from the page (e.g. "Branch" tab of a task, "Storia" of a file). */
  nav = input<RepoNav | null>(null);
  openTask = output<string>();

  readonly tabs: { id: RepoView; label: string; icon: string }[] = [
    { id: 'log', label: 'Commit', icon: 'commit' }, { id: 'files', label: 'File', icon: 'folder' },
    { id: 'branches', label: 'Rami', icon: 'branch' }, { id: 'compare', label: 'Confronta', icon: 'diff' },
    { id: 'tags', label: 'Tag', icon: 'tag' }, { id: 'dossiers', label: 'Dossier', icon: 'list' },
  ];
  readonly mdOpts = [{ value: 'render', label: 'Anteprima' }, { value: 'source', label: 'Sorgente' }];
  readonly row = ROW;

  readonly view = signal<RepoView>('log');
  readonly ref = signal('HEAD');
  readonly loading = signal(false);
  readonly branches = signal<Branch[]>([]);
  readonly baseBranch = signal('main');
  readonly commits = signal<Commit[]>([]);
  readonly hasMore = signal(false);
  readonly allRefs = signal(false);
  readonly logPath = signal('');
  readonly commit = signal<CommitDetail | null>(null);
  readonly onlyFile = signal<string | null>(null);
  readonly path = signal('');
  readonly tree = signal<TreeEntry[]>([]);
  readonly file = signal<RepoFile | null>(null);
  readonly mdMode = signal<string | null>('render');
  readonly compare = signal<Compare | null>(null);
  readonly tags = signal<Tag[]>([]);
  readonly dossiers = signal<Dossier[]>([]);
  cmpBase = 'main';
  cmpHead = 'HEAD';

  readonly graph = computed<GraphRow[]>(() => layoutGraph(this.commits()));
  readonly gw = computed(() => Math.max(1, ...this.graph().map(g => g.width)) * LANE + 8);
  readonly crumbs = computed(() => {
    const parts = this.path().split('/').filter(Boolean);
    return parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }));
  });
  readonly srcLines = computed(() => (this.file()?.content ?? '').split('\n'));

  readonly ago = ago;
  readonly shortDate = shortDate;

  constructor() {
    this.loadBranches();
    effect(() => {
      const n = this.nav();
      if (n) untracked(() => this.go(n));
    });
  }

  isBranch(name: string) { return this.branches().some(b => b.name === name); }
  isMd(p: string) { return /\.md$/i.test(p); }
  size(n: number) { return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1048576).toFixed(1)} MB`; }
  x(lane: number) { return 8 + lane * LANE; }
  seg(s: GraphRow['segs'][number]): string {
    const y = (v: number) => v === 0 ? 0 : v === 1 ? ROW / 2 : ROW;
    const x1 = this.x(s.x1), x2 = this.x(s.x2), y1 = y(s.y1), y2 = y(s.y2);
    if (x1 === x2) return `M${x1} ${y1}L${x2} ${y2}`;
    const my = (y1 + y2) / 2;
    return `M${x1} ${y1}C${x1} ${my} ${x2} ${my} ${x2} ${y2}`;
  }

  go(n: RepoNav) {
    if (n.ref) this.ref.set(n.ref);
    this.view.set(n.view);
    this.onlyFile.set(null);
    switch (n.view) {
      case 'log': this.loadLog(); break;
      case 'commit': if (n.sha) this.loadCommit(n.sha); break;
      case 'files':
        if (n.path !== undefined) this.path.set(n.path);
        if (n.sha) this.ref.set(n.sha);
        this.file.set(null);
        this.loadTree(); break;
      case 'branches': this.loadBranches(); break;
      case 'compare':
        this.cmpBase = n.base || this.baseBranch();
        this.cmpHead = n.head || (this.ref() !== 'HEAD' ? this.ref() : this.cmpHead);
        if (n.base || n.head) this.loadCompare(); else this.compare.set(null);
        break;
      case 'tags': this.run(async () => this.tags.set(await this.api.tags())); break;
      case 'dossiers': this.run(async () => this.dossiers.set(await this.api.dossiers())); break;
    }
  }

  setRef(ref: string) {
    this.ref.set(ref);
    if (this.view() === 'files') { this.file.set(null); this.loadTree(); }
    else if (this.view() === 'log' || this.view() === 'commit') this.go({ view: 'log' });
  }

  private async run(fn: () => Promise<void>) {
    this.loading.set(true);
    try { await fn(); }
    catch (e: any) { this.toast.error(e?.error?.detail || 'Repository non raggiungibile'); }
    finally { this.loading.set(false); }
  }

  loadBranches() {
    this.run(async () => {
      const r = await this.api.branches();
      this.branches.set(r.branches);
      this.baseBranch.set(r.base);
      if (this.ref() === 'HEAD') this.ref.set(r.current || r.base);
      this.cmpBase = r.base;
      if (!this.commits().length && this.view() === 'log') await this.fetchLog(false);
    });
  }

  loadLog(more = false) { this.run(() => this.fetchLog(more)); }
  private async fetchLog(more: boolean) {
    const skip = more ? this.commits().length : 0;
    const r = await this.api.log({ ref: this.ref(), path: this.logPath(), limit: 100, skip, all: this.allRefs() });
    this.commits.set(more ? [...this.commits(), ...r.commits] : r.commits);
    this.hasMore.set(r.has_more);
  }

  loadCommit(sha: string) {
    this.commit.set(null);
    this.run(async () => this.commit.set(await this.api.commit(sha)));
  }

  loadTree() {
    this.run(async () => this.tree.set((await this.api.tree(this.ref(), this.path())).entries));
  }
  openPath(path: string) { this.path.set(path); this.file.set(null); this.loadTree(); }
  openFile(path: string) {
    this.run(async () => {
      this.file.set(await this.api.file(this.ref(), path));
      this.path.set(path.split('/').slice(0, -1).join('/'));
    });
  }
  openFileAt(path: string) { this.view.set('files'); this.openFile(path); }

  loadCompare() {
    this.onlyFile.set(null);
    this.run(async () => this.compare.set(await this.api.compare(this.cmpBase, this.cmpHead)));
  }

}
