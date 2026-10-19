/**
 * <hephaestus-repo> — read-only repository browser: commit graph, commit detail, files at any ref, branches,
 * compare, tags, dossiers. Port of the WebUI forge/repo-browser.component; `nav` = navigation request from the
 * page (a task's branch / commit), event 'open-task' (detail = task id) for a Forge branch.
 */
import { LitElement, css, html, nothing, svg, kitStyles, tokens } from '@hestia/webui-sdk';
import type { HestiaHost } from '@hestia/webui-sdk';
import { icon } from './icons';
import { layoutGraph, type GraphRow } from './graph';
import { Branch, Commit, CommitDetail, Compare, Dossier, FileStat, ForgeApi, RepoFile, Tag, TreeEntry, ago, errText, fileSize, shortDate } from './models';

export type RepoView = 'log' | 'commit' | 'files' | 'branches' | 'compare' | 'tags' | 'dossiers';
export interface RepoNav { view: RepoView; ref?: string; path?: string; sha?: string; base?: string; head?: string; }

const LANE = 14, ROW = 34;
const TABS: { id: RepoView; label: string; icon: string }[] = [
  { id: 'log', label: 'Commit', icon: 'commit' }, { id: 'files', label: 'File', icon: 'folder' },
  { id: 'branches', label: 'Rami', icon: 'branch' }, { id: 'compare', label: 'Confronta', icon: 'diff' },
  { id: 'tags', label: 'Tag', icon: 'tag' }, { id: 'dossiers', label: 'Dossier', icon: 'list' },
];

export class HephaestusRepo extends LitElement {
  static properties = {
    host: { attribute: false }, nav: { attribute: false },
    view: { state: true }, ref: { state: true }, loading: { state: true }, branches: { state: true }, baseBranch: { state: true },
    commits: { state: true }, hasMore: { state: true }, allRefs: { state: true }, logPath: { state: true }, commit: { state: true },
    onlyFile: { state: true }, path: { state: true }, tree: { state: true }, file: { state: true }, mdMode: { state: true },
    cmp: { state: true }, tags: { state: true }, dossiers: { state: true }, cmpBase: { state: true }, cmpHead: { state: true },
  };
  declare host: HestiaHost; declare nav: RepoNav | null;
  declare view: RepoView; declare ref: string; declare loading: boolean; declare branches: Branch[]; declare baseBranch: string;
  declare commits: Commit[]; declare hasMore: boolean; declare allRefs: boolean; declare logPath: string; declare commit: CommitDetail | null;
  declare onlyFile: string | null; declare path: string; declare tree: TreeEntry[]; declare file: RepoFile | null; declare mdMode: 'render' | 'source';
  declare cmp: Compare | null; declare tags: Tag[]; declare dossiers: Dossier[]; declare cmpBase: string; declare cmpHead: string;
  private api!: ForgeApi;
  private graph: GraphRow[] = [];
  private graphFrom: Commit[] | null = null;
  private lastNav: RepoNav | null = null;

  constructor() {
    super();
    this.nav = null; this.view = 'log'; this.ref = 'HEAD'; this.loading = false; this.branches = []; this.baseBranch = 'main';
    this.commits = []; this.hasMore = false; this.allRefs = false; this.logPath = ''; this.commit = null; this.onlyFile = null;
    this.path = ''; this.tree = []; this.file = null; this.mdMode = 'render'; this.cmp = null; this.tags = []; this.dossiers = [];
    this.cmpBase = 'main'; this.cmpHead = 'HEAD';
  }

  static styles = [tokens, kitStyles, css`
    :host { display: flex; flex-direction: column; min-height: 0; flex: 1; }
    button { font: inherit; background: none; border: 0; color: inherit; cursor: pointer; padding: 0; text-align: left; }
    .tabs { display: flex; align-items: center; gap: 2px; padding: 8px 14px; border-bottom: 1px solid var(--border); flex-wrap: wrap; }
    .tabs > button { display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 10px; border-radius: var(--radius-md); font-size: 13px; color: var(--text-2); }
    .tabs > button:hover { background: var(--surface-2); color: var(--text); }
    .tabs > button.on { background: var(--surface-3); color: var(--text); font-weight: 500; }
    .refsel { display: inline-flex; align-items: center; gap: 6px; color: var(--text-3); }
    .refsel select { height: 30px; font-size: 12.5px; max-width: 220px; padding: 2px 8px; }
    .body { flex: 1; overflow: auto; padding: 14px 18px 30px; position: relative; }
    .toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
    .toolbar select { height: 32px; max-width: 240px; }
    .chip { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; background: var(--surface-2); padding: 3px 4px 3px 10px; border-radius: var(--radius-full); }
    .chip button { display: grid; place-items: center; width: 20px; height: 20px; border-radius: 50%; }
    .log { display: flex; flex-direction: column; }
    .crow { display: flex; align-items: center; gap: 10px; min-height: 34px; padding: 0 8px 0 0; border-radius: var(--radius-sm); font-size: 13px; width: 100%; }
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
    .head h2 { font-size: 19px; line-height: 1.3; }
    .sub { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
    .body-msg { font-family: var(--font-mono); font-size: 12.5px; white-space: pre-wrap; background: var(--surface-2); padding: 10px 12px; border-radius: var(--radius-md); width: 100%; margin: 0; }
    .lnk { color: var(--accent); font-size: 12.5px; } .lnk:hover { text-decoration: underline; }
    .files { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: 12px; max-height: 260px; overflow: auto; }
    .frow { display: flex; align-items: center; gap: 8px; padding: 5px 10px; font-size: 12.5px; }
    .frow:hover { background: var(--surface-2); } .frow.on { background: var(--accent-soft); }
    .frow .mono { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .st { font: 600 10.5px var(--font-mono); width: 18px; height: 18px; border-radius: 4px; display: grid; place-items: center; background: var(--info-soft); color: var(--info); flex-shrink: 0; }
    .st[data-st=A], .st[data-st='?'] { background: var(--success-soft); color: var(--success); }
    .st[data-st=D] { background: var(--danger-soft); color: var(--danger); }
    .st[data-st=R] { background: var(--warning-soft); color: var(--warning); }
    .cnt { font-size: 12px; white-space: nowrap; }
    .a { color: var(--success); font-weight: 600; } .d { color: var(--danger); font-weight: 600; }
    .crumbs { font-family: var(--font-mono); font-size: 12.5px; margin-bottom: 10px; color: var(--text-3); }
    .tree { display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: hidden; }
    .trow { display: flex; align-items: center; gap: 9px; padding: 7px 12px; font-size: 13px; border-bottom: 1px solid var(--border); }
    .trow:last-child { border-bottom: 0; }
    .trow:hover:not(:disabled) { background: var(--surface-2); }
    .trow:disabled { opacity: .6; cursor: not-allowed; }
    .fhead { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; flex-wrap: wrap; }
    .seg { display: inline-flex; background: var(--surface-2); border-radius: var(--radius-md); padding: 2px; }
    .seg button { font-size: 12px; padding: 3px 9px; border-radius: calc(var(--radius-md) - 2px); color: var(--text-2); }
    .seg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); }
    .src { font-family: var(--font-mono); font-size: 12px; line-height: 1.55; border: 1px solid var(--border); border-radius: var(--radius-md); overflow: auto; background: var(--surface); }
    .src div { display: flex; white-space: pre; min-width: max-content; }
    .src i { font-style: normal; width: 48px; flex-shrink: 0; text-align: right; padding-right: 10px; color: var(--text-3); user-select: none; border-right: 1px solid var(--border); }
    .src span { padding: 0 12px; }
    .mdbox { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 16px 20px; background: var(--surface); }
    .note { font-size: 12.5px; color: var(--text-3); margin-top: 8px; }
    .list { display: flex; flex-direction: column; gap: 2px; }
    .brow, .drow { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-md); width: 100%; flex-wrap: wrap; }
    .brow:hover, .drow:hover { background: var(--surface-2); }
    .bname { font-size: 13.5px; font-weight: 500; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .min0 { min-width: 0; flex: 1; }
    .ab { font-size: 12px; white-space: nowrap; }
    .prog { width: 70px; height: 6px; border-radius: 3px; background: var(--surface-3); overflow: hidden; flex-shrink: 0; }
    .prog span { display: block; height: 100%; background: var(--success); }
    @media (max-width: 720px) {
      .body { padding: 10px 12px 24px; }
      .crow .hide-phone { display: none; }
    }
  `];

  connectedCallback() {
    super.connectedCallback();
    this.api = new ForgeApi(this.host);
    this.loadBranches();
  }

  willUpdate(changed: Map<string, unknown>) {
    if (changed.has('nav') && this.nav && this.nav !== this.lastNav) { this.lastNav = this.nav; this.go(this.nav); }
  }

  private isBranch(name: string) { return this.branches.some(b => b.name === name); }
  private isMd(p: string) { return /\.md$/i.test(p); }
  private x(lane: number) { return 8 + lane * LANE; }
  private seg(s: GraphRow['segs'][number]): string {
    const y = (v: number) => v === 0 ? 0 : v === 1 ? ROW / 2 : ROW;
    const x1 = this.x(s.x1), x2 = this.x(s.x2), y1 = y(s.y1), y2 = y(s.y2);
    if (x1 === x2) return `M${x1} ${y1}L${x2} ${y2}`;
    const my = (y1 + y2) / 2;
    return `M${x1} ${y1}C${x1} ${my} ${x2} ${my} ${x2} ${y2}`;
  }

  go(n: RepoNav) {
    if (n.ref) this.ref = n.ref;
    this.view = n.view;
    this.onlyFile = null;
    switch (n.view) {
      case 'log': this.loadLog(); break;
      case 'commit': if (n.sha) this.loadCommit(n.sha); break;
      case 'files':
        if (n.path !== undefined) this.path = n.path;
        if (n.sha) this.ref = n.sha;
        this.file = null;
        this.loadTree(); break;
      case 'branches': this.loadBranches(); break;
      case 'compare':
        this.cmpBase = n.base || this.baseBranch;
        this.cmpHead = n.head || (this.ref !== 'HEAD' ? this.ref : this.cmpHead);
        if (n.base || n.head) this.loadCompare(); else this.cmp = null;
        break;
      case 'tags': this.run(async () => { this.tags = await this.api.tags(); }); break;
      case 'dossiers': this.run(async () => { this.dossiers = await this.api.dossiers(); }); break;
    }
  }

  private setRef(ref: string) {
    this.ref = ref;
    if (this.view === 'files') { this.file = null; this.loadTree(); }
    else if (this.view === 'log' || this.view === 'commit') this.go({ view: 'log' });
  }

  private async run(fn: () => Promise<void>) {
    this.loading = true;
    try { await fn(); } catch (e) { this.host.toast(errText(e, 'Repository non raggiungibile'), 'danger'); }
    finally { this.loading = false; }
  }

  private loadBranches() {
    this.run(async () => {
      const r = await this.api.branches();
      this.branches = r.branches; this.baseBranch = r.base;
      if (this.ref === 'HEAD') this.ref = r.current || r.base;
      this.cmpBase = r.base;
      if (!this.commits.length && this.view === 'log') await this.fetchLog(false);
    });
  }
  private loadLog(more = false) { this.run(() => this.fetchLog(more)); }
  private async fetchLog(more: boolean) {
    const skip = more ? this.commits.length : 0;
    const r = await this.api.log({ ref: this.ref, path: this.logPath, limit: 100, skip, all: this.allRefs });
    this.commits = more ? [...this.commits, ...r.commits] : r.commits;
    this.hasMore = r.has_more;
  }
  private loadCommit(sha: string) { this.commit = null; this.run(async () => { this.commit = await this.api.commit(sha); }); }
  private loadTree() { this.run(async () => { this.tree = (await this.api.tree(this.ref, this.path)).entries; }); }
  private openPath(path: string) { this.path = path; this.file = null; this.loadTree(); }
  private openFile(path: string) {
    this.run(async () => { this.file = await this.api.file(this.ref, path); this.path = path.split('/').slice(0, -1).join('/'); });
  }
  private loadCompare() { this.onlyFile = null; this.run(async () => { this.cmp = await this.api.compare(this.cmpBase, this.cmpHead); }); }

  private fileList(files: FileStat[]) {
    return html`<div class="files">
      <button class="frow ${this.onlyFile ? '' : 'on'}" @click=${() => (this.onlyFile = null)}><b>Tutti i file</b> <span class="meta">(${files.length})</span></button>
      ${files.map(f => html`<button class="frow ${this.onlyFile === f.path ? 'on' : ''}" @click=${() => (this.onlyFile = f.path)}>
        <span class="st" data-st=${f.status ?? 'M'}>${f.status}</span><span class="mono">${f.path}</span>
        <span class="cnt">${f.binary ? 'bin' : html`<b class="a">+${f.added}</b> <b class="d">−${f.deleted}</b>`}</span></button>`)}</div>`;
  }

  private logView() {
    if (this.graphFrom !== this.commits) { this.graph = layoutGraph(this.commits); this.graphFrom = this.commits; }
    const gw = Math.max(1, ...this.graph.map(g => g.width)) * LANE + 8;
    return html`<div class="toolbar">
        <label class="row small"><input type="checkbox" .checked=${this.allRefs} @change=${(e: any) => { this.allRefs = e.target.checked; this.loadLog(); }}> Tutti i rami</label>
        ${this.logPath ? html`<span class="chip">Solo <code>${this.logPath}</code><button @click=${() => { this.logPath = ''; this.loadLog(); }}>${icon('x', 12)}</button></span>` : nothing}
      </div>
      <div class="log">${this.commits.map((c, i) => {
        const g = this.graph[i];
        return html`<button class="crow" @click=${() => this.go({ view: 'commit', sha: c.sha })}>
          <svg class="graph" width=${gw} height=${ROW} viewBox="0 0 ${gw} ${ROW}">
            ${g.segs.map(s => svg`<path d=${this.seg(s)} stroke="var(--cal-${s.c + 1}, var(--accent))" fill="none" stroke-width="2"></path>`)}
            ${svg`<circle cx=${this.x(g.lane)} cy=${ROW / 2} r="4.5" fill=${c.parents.length > 1 ? 'var(--surface)' : `var(--cal-${g.color + 1}, var(--accent))`}
              stroke="var(--cal-${g.color + 1}, var(--accent))" stroke-width="2"></circle>`}
          </svg>
          <span class="subj">${c.refs.map(r => html`<span class="refb ${r.startsWith('HEAD') ? 'cur' : ''} ${r.includes('auto/forge/') ? 'forge' : ''}">${r.replace('HEAD -> ', '')}</span>`)}${c.subject}</span>
          <span class="meta hide-phone">${c.author}</span><span class="meta mono hide-phone">${c.short}</span>
          <span class="meta" title=${c.date}>${ago(c.date)}</span></button>`;
      })}
        ${this.hasMore ? html`<div><hxk-button variant="ghost" size="sm" @click=${() => this.loadLog(true)}>Carica altri</hxk-button></div>` : nothing}
        ${!this.commits.length && !this.loading ? html`<hxk-state kind="empty" text="Nessun commit"></hxk-state>` : nothing}
      </div>`;
  }

  private commitView() {
    const c = this.commit;
    if (!c) return nothing;
    return html`<div class="head">
        <hxk-button variant="ghost" size="sm" @click=${() => this.go({ view: 'log' })}>${icon('arrow-left', 14)} Commit</hxk-button>
        <h2>${c.subject}</h2>
        <div class="sub"><span class="mono">${c.short}</span> · ${c.author} · ${shortDate(c.date)}
          ${c.parents.length > 1 ? html` · <hxk-badge tone="info">merge</hxk-badge>` : nothing}
          ${c.refs.map(r => html`<span class="refb">${r}</span>`)}</div>
        ${c.body ? html`<pre class="body-msg">${c.body}</pre>` : nothing}
        <div class="sub">${c.parents.map(p => html`<button class="lnk mono" @click=${() => this.go({ view: 'commit', sha: p })}>genitore ${p.slice(0, 8)}</button>`)}
          <button class="lnk" @click=${() => this.go({ view: 'files', ref: c.sha, path: '' })}>Sfoglia i file a questo commit</button></div>
      </div>
      ${this.fileList(c.files)}
      <hephaestus-diff .diff=${c.diff} ?truncated=${c.truncated} .only=${this.onlyFile}></hephaestus-diff>`;
  }

  private filesView() {
    const parts = this.path.split('/').filter(Boolean);
    const crumbs = parts.map((name, i) => ({ name, path: parts.slice(0, i + 1).join('/') }));
    const f = this.file;
    return html`<div class="crumbs"><button class="lnk" @click=${() => this.openPath('')}>${this.ref}</button>
        ${crumbs.map(p => html` / <button class="lnk" @click=${() => this.openPath(p.path)}>${p.name}</button>`)}</div>
      ${f ? html`<div class="fhead"><span class="mono">${f.path}</span><span class="meta">${fileSize(f.size)}</span><span class="grow"></span>
            ${this.isMd(f.path) ? html`<div class="seg"><button class=${this.mdMode === 'render' ? 'on' : ''} @click=${() => (this.mdMode = 'render')}>Anteprima</button>
              <button class=${this.mdMode === 'source' ? 'on' : ''} @click=${() => (this.mdMode = 'source')}>Sorgente</button></div>` : nothing}
            <hxk-button variant="ghost" size="sm" @click=${() => { this.logPath = f.path; this.go({ view: 'log' }); }}>${icon('commit', 14)} Storia</hxk-button></div>
          ${f.binary ? html`<hxk-state kind="empty" text="File binario"></hxk-state>`
            : this.isMd(f.path) && this.mdMode === 'render' ? html`<div class="mdbox"><hephaestus-md .text=${f.content}></hephaestus-md></div>`
            : html`<div class="src">${f.content.split('\n').map((l, i) => html`<div><i>${i + 1}</i><span>${l}</span></div>`)}</div>`}
          ${f.truncated ? html`<div class="note">File troncato: troppo grande da mostrare per intero.</div>` : nothing}`
        : html`<div class="tree">${this.tree.map(e => html`<button class="trow" ?disabled=${e.secret}
            @click=${() => e.type === 'tree' ? this.openPath(e.path) : this.openFile(e.path)}>
            ${icon(e.type === 'tree' ? 'folder' : 'file', 15)}<span>${e.name}</span>
            ${e.secret ? html`<hxk-badge tone="warning">segreto, non mostrato</hxk-badge>` : nothing}
            <span class="grow"></span><span class="meta">${e.size !== null ? fileSize(e.size) : ''}</span></button>`)}</div>`}`;
  }

  private branchesView() {
    return html`<div class="list">${this.branches.map(b => html`<div class="brow">
      ${icon('branch', 15)}
      <div class="min0"><div class="bname">${b.name}
          ${b.base ? html`<hxk-badge tone="accent">base</hxk-badge>` : nothing}
          ${b.current ? html`<hxk-badge tone="success">attivo</hxk-badge>` : nothing}
          ${b.forge_task ? html`<hxk-badge tone="info">Forge</hxk-badge>` : nothing}</div>
        <div class="meta truncate">${b.subject} · ${b.author} · ${ago(b.date)}</div></div>
      ${!b.base ? html`<span class="ab" title="Commit avanti / indietro rispetto al ramo base"><b class="a">↑${b.ahead}</b> <b class="d">↓${b.behind}</b></span>` : nothing}
      <hxk-button variant="ghost" size="sm" @click=${() => this.go({ view: 'log', ref: b.name })}>Storia</hxk-button>
      ${!b.base ? html`<hxk-button variant="ghost" size="sm" @click=${() => this.go({ view: 'compare', base: this.baseBranch, head: b.name })}>Confronta</hxk-button>` : nothing}
      ${b.forge_task ? html`<hxk-button variant="ghost" size="sm" @click=${() => this.dispatchEvent(new CustomEvent('open-task', { detail: b.forge_task, bubbles: true, composed: true }))}>${icon('terminal', 14)} Task</hxk-button>` : nothing}
    </div>`)}</div>`;
  }

  private branchSelect(value: string, set: (v: string) => void) {
    const names = this.branches.map(b => b.name);
    return html`<select @change=${(e: any) => set(e.target.value)}>
      ${names.map(n => html`<option value=${n} ?selected=${n === value}>${n}</option>`)}
      ${!names.includes(value) ? html`<option value=${value} selected>${value}</option>` : nothing}</select>`;
  }

  private compareView() {
    const c = this.cmp;
    return html`<div class="toolbar">${this.branchSelect(this.cmpBase, v => (this.cmpBase = v))}<span>…</span>
        ${this.branchSelect(this.cmpHead, v => (this.cmpHead = v))}
        <hxk-button size="sm" variant="primary" @click=${() => this.loadCompare()}>Confronta</hxk-button></div>
      ${c ? html`<p class="meta">${c.head} è <b>${c.ahead}</b> commit avanti e <b>${c.behind}</b> indietro rispetto a ${c.base}.</p>
        ${c.commits.map(k => html`<button class="crow small" @click=${() => this.go({ view: 'commit', sha: k.sha })}><span class="mono meta">${k.short}</span>
          <span class="subj">${k.subject}</span><span class="meta">${ago(k.date)}</span></button>`)}
        ${this.fileList(c.files)}
        <hephaestus-diff .diff=${c.diff} ?truncated=${c.truncated} .only=${this.onlyFile}></hephaestus-diff>` : nothing}`;
  }

  private tagsView() {
    return this.tags.length ? this.tags.map(t => html`<button class="crow small" @click=${() => this.go({ view: 'commit', sha: t.sha })}>${icon('tag', 14)}
        <span class="subj">${t.name} <span class="meta">${t.subject}</span></span><span class="meta">${ago(t.date)}</span></button>`)
      : html`<hxk-state kind="empty" text="Il repository non ha ancora tag."></hxk-state>`;
  }

  private dossiersView() {
    return html`<div class="toolbar"><hxk-button variant="ghost" size="sm" @click=${() => { this.view = 'files'; this.openFile('CHANGELOG.md'); }}>${icon('file', 14)} CHANGELOG generale</hxk-button></div>
      ${this.dossiers.length ? this.dossiers.map(d => html`<button class="drow" @click=${() => { this.view = 'files'; this.openPath(d.path); }}>
          <div class="min0"><div class="bname truncate">${d.title || d.name}</div><div class="meta truncate">${d.name}${d.source ? ` · ${d.source}` : ''}</div></div>
          ${d.version ? html`<hxk-badge>v${d.version}</hxk-badge>` : nothing}
          ${d.status ? html`<hxk-badge tone="info">${d.status}</hxk-badge>` : nothing}
          ${d.progress ? html`<span class="prog" title="${d.progress.done} su ${d.progress.total} punti fatti"><span style="width:${d.progress.total ? 100 * d.progress.done / d.progress.total : 0}%"></span></span>
            <span class="meta">${d.progress.done}/${d.progress.total}</span>` : nothing}</button>`)
        : html`<hxk-state kind="empty" text="Nessun dossier"></hxk-state>`}`;
  }

  render() {
    const v = this.view;
    return html`
      <div class="tabs">${TABS.map(t => html`<button class=${v === t.id || (t.id === 'log' && v === 'commit') ? 'on' : ''}
          @click=${() => this.go({ view: t.id })}>${icon(t.icon, 14)} ${t.label}</button>`)}
        <span class="grow"></span>
        <label class="refsel" title="Ramo o commit mostrato">${icon('branch', 14)}${this.branchSelect(this.ref, r => this.setRef(r))}</label>
      </div>
      <div class="body">
        ${this.loading ? html`<hxk-state kind="loading"></hxk-state>` : nothing}
        ${v === 'log' ? this.logView() : v === 'commit' ? this.commitView() : v === 'files' ? this.filesView()
          : v === 'branches' ? this.branchesView() : v === 'compare' ? this.compareView() : v === 'tags' ? this.tagsView() : this.dossiersView()}
      </div>`;
  }
}
