/** <hephaestus-diff> — unified diff viewer (unified or side by side, per-file collapsible), port of the WebUI hx-diff. */
import { LitElement, css, html, nothing, tokens } from '@hestia/webui-sdk';
import { icon } from './icons';

interface DiffLine { kind: 'ctx' | 'add' | 'del' | 'meta'; text: string; old?: number; new?: number; }
interface DiffHunk { header: string; lines: DiffLine[]; }
interface DiffFile { path: string; oldPath: string; status: 'A' | 'M' | 'D' | 'R'; binary: boolean; added: number; deleted: number; hunks: DiffHunk[]; }
interface SplitRow { left?: DiffLine; right?: DiffLine; hunk?: string; }

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

export class HephaestusDiff extends LitElement {
  static properties = { diff: {}, only: {}, truncated: { type: Boolean }, mode: { state: true }, opened: { state: true }, closed: { state: true } };
  declare diff: string; declare only: string | null; declare truncated: boolean;
  declare mode: 'unified' | 'split'; declare opened: Set<string>; declare closed: Set<string>;
  private parsed: DiffFile[] = [];
  private parsedFrom: string | null = null;

  constructor() {
    super(); this.diff = ''; this.only = null; this.truncated = false; this.opened = new Set(); this.closed = new Set();
    let m: 'unified' | 'split' = 'unified';
    try { m = localStorage.getItem(MODE_KEY) === 'split' && window.innerWidth > 900 ? 'split' : 'unified'; } catch { /* private */ }
    this.mode = m;
  }

  static styles = [tokens, css`
    :host { display: block; font-size: 13px; }
    button { font: inherit; background: none; border: 0; color: inherit; cursor: pointer; padding: 0; }
    .bar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; flex-wrap: wrap; }
    .sum { color: var(--text-2); } .grow { flex: 1; }
    .a { color: var(--success); font-weight: 600; } .d { color: var(--danger); font-weight: 600; }
    .lnk { font-size: 12px; color: var(--text-3); } .lnk:hover { color: var(--text); }
    .seg { display: inline-flex; background: var(--surface-2); border-radius: var(--radius-md); padding: 2px; }
    .seg button { font-size: 12px; padding: 3px 9px; border-radius: calc(var(--radius-md) - 2px); color: var(--text-2); }
    .seg button.on { background: var(--surface); color: var(--text); box-shadow: var(--shadow-1); }
    .file { border: 1px solid var(--border); border-radius: var(--radius-md); margin-bottom: 10px; overflow: hidden; background: var(--surface); }
    header { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: var(--bg-subtle); cursor: pointer; border-bottom: 1px solid var(--border); }
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
    .ln i { font-style: normal; width: 44px; flex-shrink: 0; text-align: right; padding-right: 8px; color: var(--text-3); user-select: none; border-right: 1px solid var(--border); }
    .ln span { padding: 0 10px; }
    .split .ln span { overflow: hidden; text-overflow: ellipsis; }
    .ln[data-k=add] { background: color-mix(in srgb, var(--success) 12%, transparent); }
    .ln[data-k=del] { background: color-mix(in srgb, var(--danger) 12%, transparent); }
    .ln[data-k=meta] { color: var(--text-3); font-style: italic; }
    .ln[data-k=none] { background: var(--bg-subtle); }
    .empty { padding: 12px; color: var(--text-3); font-size: 13px; }
  `];

  private files(): DiffFile[] {
    if (this.parsedFrom !== this.diff) { this.parsed = parseDiff(this.diff); this.parsedFrom = this.diff; }
    return this.only ? this.parsed.filter(f => f.path === this.only || f.oldPath === this.only) : this.parsed;
  }
  private collapsed(f: DiffFile, count: number) {
    if (this.closed.has(f.path)) return true;
    return f.added + f.deleted > BIG && count > 1 && !this.opened.has(f.path);
  }
  private toggle(f: DiffFile, count: number) {
    const open = new Set(this.opened), closed = new Set(this.closed);
    if (this.collapsed(f, count)) { open.add(f.path); closed.delete(f.path); } else { closed.add(f.path); open.delete(f.path); }
    this.opened = open; this.closed = closed;
  }
  private setMode(m: 'unified' | 'split') {
    this.mode = m;
    try { localStorage.setItem(MODE_KEY, m); } catch { /* private */ }
  }
  private sign(l: DiffLine) { return l.kind === 'add' ? '+' : l.kind === 'del' ? '-' : ' '; }

  render() {
    const shown = this.files();
    const tot = shown.reduce((t, f) => ({ a: t.a + f.added, d: t.d + f.deleted }), { a: 0, d: 0 });
    return html`
      <div class="bar">
        <span class="sum">${shown.length} file · <b class="a">+${tot.a}</b> <b class="d">−${tot.d}</b></span>
        <span class="grow"></span>
        ${shown.length > 1 ? html`
          <button class="lnk" @click=${() => { this.closed = new Set(shown.map(f => f.path)); this.opened = new Set(); }}>Comprimi tutti</button>
          <button class="lnk" @click=${() => { this.opened = new Set(shown.map(f => f.path)); this.closed = new Set(); }}>Espandi tutti</button>` : nothing}
        <div class="seg">
          <button class=${this.mode === 'unified' ? 'on' : ''} @click=${() => this.setMode('unified')}>Unificato</button>
          <button class=${this.mode === 'split' ? 'on' : ''} @click=${() => this.setMode('split')}>Affiancato</button>
        </div>
      </div>
      ${!shown.length ? html`<div class="empty">Nessuna differenza.</div>` : nothing}
      ${shown.map(f => {
        const c = this.collapsed(f, shown.length);
        return html`<section class="file">
          <header @click=${() => this.toggle(f, shown.length)}>
            ${icon(c ? 'chevron-right' : 'chevron-down', 15)}
            <span class="st" data-st=${f.status}>${f.status}</span>
            <span class="path">${f.status === 'R' ? html`<s>${f.oldPath}</s> → ` : nothing}${f.path}</span>
            <span class="cnt"><b class="a">+${f.added}</b> <b class="d">−${f.deleted}</b></span>
          </header>
          ${c ? nothing : f.binary ? html`<div class="empty">File binario.</div>` : this.mode === 'unified'
            ? html`<div class="code">${f.hunks.map(h => html`<div class="hunk">${h.header}</div>${h.lines.map(l =>
                html`<div class="ln" data-k=${l.kind}><i>${l.old ?? ''}</i><i>${l.new ?? ''}</i><span>${this.sign(l)}${l.text}</span></div>`)}`)}</div>`
            : html`<div class="code split">${toSplit(f.hunks).map(r => r.hunk ? html`<div class="hunk wide">${r.hunk}</div>` : html`
                <div class="ln" data-k=${r.left ? (r.left.kind === 'ctx' ? 'ctx' : 'del') : 'none'}><i>${r.left?.old ?? ''}</i><span>${r.left?.text ?? ''}</span></div>
                <div class="ln" data-k=${r.right ? (r.right.kind === 'ctx' ? 'ctx' : 'add') : 'none'}><i>${r.right?.new ?? ''}</i><span>${r.right?.text ?? ''}</span></div>`)}</div>`}
        </section>`;
      })}
      ${this.truncated ? html`<div class="empty">Diff troncato: troppo grande da mostrare per intero.</div>` : nothing}`;
  }
}
