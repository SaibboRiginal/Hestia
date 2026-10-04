/** Diff viewer: <hx-diff [diff]="unifiedDiffText" [only]="path?" /> — unified or split, per-file collapsible. */
import { ChangeDetectionStrategy, Component, computed, input, signal } from '@angular/core';
import { IconComponent } from './icon.component';

export interface DiffLine { kind: 'ctx' | 'add' | 'del' | 'meta'; text: string; old?: number; new?: number; }
export interface DiffHunk { header: string; lines: DiffLine[]; }
export interface DiffFile {
  path: string; oldPath: string; status: 'A' | 'M' | 'D' | 'R'; binary: boolean;
  added: number; deleted: number; hunks: DiffHunk[];
}
interface SplitRow { left?: DiffLine; right?: DiffLine; hunk?: string; }

/** Parse `git diff` output into files → hunks → lines. */
export function parseDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let f: DiffFile | null = null;
  let h: DiffHunk | null = null;
  let o = 0, n = 0;
  for (const line of (text || '').split('\n')) {
    if (line.startsWith('diff --git ')) {
      const m = /^diff --git a\/(.*) b\/(.*)$/.exec(line);
      f = { path: m?.[2] ?? line.slice(11), oldPath: m?.[1] ?? '', status: 'M', binary: false, added: 0, deleted: 0, hunks: [] };
      files.push(f); h = null; continue;
    }
    if (!f) continue;
    if (!h) {
      if (line.startsWith('new file mode')) f.status = 'A';
      else if (line.startsWith('deleted file mode')) f.status = 'D';
      else if (line.startsWith('rename from ')) { f.status = 'R'; f.oldPath = line.slice(12); }
      else if (line.startsWith('rename to ')) f.path = line.slice(10);
      else if (line.startsWith('Binary files')) f.binary = true;
    }
    if (line.startsWith('@@')) {
      const m = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(line);
      o = m ? +m[1] : 0; n = m ? +m[2] : 0;
      h = { header: line, lines: [] }; f.hunks.push(h); continue;
    }
    if (!h) continue;
    if (line.startsWith('+')) { h.lines.push({ kind: 'add', text: line.slice(1), new: n++ }); f.added++; }
    else if (line.startsWith('-')) { h.lines.push({ kind: 'del', text: line.slice(1), old: o++ }); f.deleted++; }
    else if (line.startsWith('\\')) h.lines.push({ kind: 'meta', text: line.slice(2) });
    else if (line.startsWith(' ') || line === '') h.lines.push({ kind: 'ctx', text: line.slice(1), old: o++, new: n++ });
  }
  return files;
}

function toSplit(hunks: DiffHunk[]): SplitRow[] {
  const rows: SplitRow[] = [];
  for (const h of hunks) {
    rows.push({ hunk: h.header });
    let dels: DiffLine[] = [], adds: DiffLine[] = [];
    const flush = () => {
      for (let i = 0; i < Math.max(dels.length, adds.length); i++) rows.push({ left: dels[i], right: adds[i] });
      dels = []; adds = [];
    };
    for (const l of h.lines) {
      if (l.kind === 'del') dels.push(l);
      else if (l.kind === 'add') adds.push(l);
      else { flush(); if (l.kind === 'ctx') rows.push({ left: l, right: l }); }
    }
    flush();
  }
  return rows;
}

const MODE_KEY = 'hestia_diff_mode';
const BIG = 600;

@Component({
  selector: 'hx-diff',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="bar">
      <span class="sum">{{ shown().length }} file · <b class="a">+{{ totals().added }}</b> <b class="d">−{{ totals().deleted }}</b></span>
      <span class="hx-grow"></span>
      @if (shown().length > 1) {
        <button class="lnk" (click)="collapseAll()">Comprimi tutti</button>
        <button class="lnk" (click)="expandAll()">Espandi tutti</button>
      }
      <div class="seg">
        <button [class.on]="mode() === 'unified'" (click)="setMode('unified')" title="Diff unificato">Unificato</button>
        <button [class.on]="mode() === 'split'" (click)="setMode('split')" title="Affiancato">Affiancato</button>
      </div>
    </div>
    @if (!shown().length) { <div class="empty">Nessuna differenza.</div> }
    @for (f of shown(); track f.path) {
      <section class="file">
        <header (click)="toggle(f)">
          <hx-icon [name]="isCollapsed(f) ? 'chevron-right' : 'chevron-down'" [size]="15" />
          <span class="st" [attr.data-st]="f.status">{{ f.status }}</span>
          <span class="path">@if (f.status === 'R') { <s>{{ f.oldPath }}</s> → } {{ f.path }}</span>
          <span class="cnt"><b class="a">+{{ f.added }}</b> <b class="d">−{{ f.deleted }}</b></span>
        </header>
        @if (!isCollapsed(f)) {
          @if (f.binary) { <div class="empty">File binario.</div> }
          @else if (mode() === 'unified') {
            <div class="code">
              @for (h of f.hunks; track $index) {
                <div class="hunk">{{ h.header }}</div>
                @for (l of h.lines; track $index) {
                  <div class="ln" [attr.data-k]="l.kind"><i>{{ l.old ?? '' }}</i><i>{{ l.new ?? '' }}</i><span>{{ sign(l) }}{{ l.text }}</span></div>
                }
              }
            </div>
          } @else {
            <div class="code split">
              @for (r of splitOf(f); track $index) {
                @if (r.hunk) { <div class="hunk wide">{{ r.hunk }}</div> }
                @else {
                  <div class="ln" [attr.data-k]="r.left ? (r.left.kind === 'ctx' ? 'ctx' : 'del') : 'none'"><i>{{ r.left?.old ?? '' }}</i><span>{{ r.left?.text ?? '' }}</span></div>
                  <div class="ln" [attr.data-k]="r.right ? (r.right.kind === 'ctx' ? 'ctx' : 'add') : 'none'"><i>{{ r.right?.new ?? '' }}</i><span>{{ r.right?.text ?? '' }}</span></div>
                }
              }
            </div>
          }
        }
      </section>
    }
    @if (truncated()) { <div class="empty">Diff troncato: troppo grande da mostrare per intero.</div> }
  `,
  styles: [`
    :host { display: block; font-size: 13px; }
    .bar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
    .sum { color: var(--text-2); }
    .a { color: var(--success); font-weight: 600; } .d { color: var(--danger); font-weight: 600; }
    .lnk { font-size: 12px; color: var(--text-3); } .lnk:hover { color: var(--text); }
    .seg { display: inline-flex; background: var(--surface-2); border-radius: var(--radius-md); padding: 2px; }
    .seg button { font-size: 12px; padding: 3px 9px; border-radius: calc(var(--radius-md) - 2px); color: var(--text-2); }
    .seg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); }
    .file { border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: 10px; overflow: hidden; background: var(--surface); }
    header { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: var(--bg-subtle); cursor: pointer;
             position: sticky; top: 0; z-index: 1; border-bottom: 1px solid var(--border); }
    .st { font: 600 10.5px var(--font-mono); width: 18px; height: 18px; border-radius: 4px; display: grid; place-items: center;
          background: var(--info-soft); color: var(--info); flex-shrink: 0; }
    .st[data-st=A] { background: var(--success-soft); color: var(--success); }
    .st[data-st=D] { background: var(--danger-soft); color: var(--danger); }
    .st[data-st=R] { background: var(--warning-soft); color: var(--warning); }
    .path { font-family: var(--font-mono); font-size: 12.5px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; direction: rtl; text-align: left; }
    .path s { color: var(--text-3); }
    .cnt { font-size: 12px; white-space: nowrap; }
    .code { font-family: var(--font-mono); font-size: 12px; line-height: 1.55; overflow-x: auto; }
    .code.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    .hunk { padding: 3px 10px; background: var(--accent-soft); color: var(--text-3); white-space: pre; }
    .hunk.wide { grid-column: 1 / -1; }
    .ln { display: flex; min-width: max-content; white-space: pre; }
    .split .ln { min-width: 0; overflow: hidden; }
    .ln i { font-style: normal; width: 44px; flex-shrink: 0; text-align: right; padding-right: 8px; color: var(--text-3); user-select: none;
            border-right: 1px solid var(--border); }
    .ln span { padding: 0 10px; }
    .split .ln span { overflow: hidden; text-overflow: ellipsis; }
    .ln[data-k=add] { background: color-mix(in srgb, var(--success) 12%, transparent); }
    .ln[data-k=del] { background: color-mix(in srgb, var(--danger) 12%, transparent); }
    .ln[data-k=meta] { color: var(--text-3); font-style: italic; }
    .ln[data-k=none] { background: var(--bg-subtle); }
    .empty { padding: 12px; color: var(--text-3); font-size: 13px; }
  `],
})
export class DiffComponent {
  diff = input('');
  /** Show one file only (path). */
  only = input<string | null>(null);
  truncated = input(false);

  readonly mode = signal<'unified' | 'split'>(this.loadMode());
  readonly opened = signal<Set<string>>(new Set());
  readonly closed = signal<Set<string>>(new Set());

  readonly files = computed(() => parseDiff(this.diff()));
  readonly shown = computed(() => {
    const only = this.only();
    return only ? this.files().filter(f => f.path === only || f.oldPath === only) : this.files();
  });
  readonly totals = computed(() => this.shown().reduce((t, f) => ({ added: t.added + f.added, deleted: t.deleted + f.deleted }), { added: 0, deleted: 0 }));
  private splitCache = new WeakMap<DiffFile, SplitRow[]>();

  isCollapsed(f: DiffFile): boolean {
    if (this.closed().has(f.path)) return true;
    // Big files start collapsed, unless it is the only one shown or the user opened it.
    return f.added + f.deleted > BIG && this.shown().length > 1 && !this.opened().has(f.path);
  }
  toggle(f: DiffFile) {
    const open = new Set(this.opened()), closed = new Set(this.closed());
    if (this.isCollapsed(f)) { open.add(f.path); closed.delete(f.path); } else { closed.add(f.path); open.delete(f.path); }
    this.opened.set(open); this.closed.set(closed);
  }
  collapseAll() { this.closed.set(new Set(this.shown().map(f => f.path))); this.opened.set(new Set()); }
  expandAll() { this.opened.set(new Set(this.shown().map(f => f.path))); this.closed.set(new Set()); }
  splitOf(f: DiffFile): SplitRow[] {
    let rows = this.splitCache.get(f);
    if (!rows) { rows = toSplit(f.hunks); this.splitCache.set(f, rows); }
    return rows;
  }
  sign(l: DiffLine) { return l.kind === 'add' ? '+' : l.kind === 'del' ? '-' : ' '; }
  setMode(m: 'unified' | 'split') {
    this.mode.set(m);
    try { localStorage.setItem(MODE_KEY, m); } catch { /* private mode */ }
  }
  private loadMode(): 'unified' | 'split' {
    try { return localStorage.getItem(MODE_KEY) === 'split' && window.innerWidth > 900 ? 'split' : 'unified'; } catch { return 'unified'; }
  }
}
