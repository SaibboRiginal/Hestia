import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { IconComponent } from '../../ui';

/** One component of a ```hestia-ui block (hestia_common.ui_blocks, Cindy 9). */
export interface UiComp {
  c: 'card' | 'stat' | 'table' | 'list' | 'chart' | 'checklist' | 'button';
  title?: string; text?: string; tone?: string; icon?: string;
  label?: string; value?: string | number; hint?: string;
  cols?: string[]; rows?: string[][];
  items?: Array<{ title?: string; meta?: string | string[]; tone?: string; label?: string; done?: boolean }>;
  kind?: 'bar' | 'line'; labels?: string[]; values?: number[]; unit?: string;
  send?: string;
}
export type AnswerPart = { html: string } | { comps: UiComp[] };

const FENCES = [
  /<pre[^>]*>\s*<code[^>]*class="[^"]*language-hestia-ui[^"]*"[^>]*>([\s\S]*?)<\/code>\s*<\/pre>/gi,
  /```hestia-ui[ \t]*(?:\n|<br\s*\/?>)([\s\S]*?)```/gi,
];
const COMPONENTS = new Set(['card', 'stat', 'table', 'list', 'chart', 'checklist', 'button']);
const TONES = new Set(['primary', 'success', 'warning', 'danger', 'info']);

function decode(s: string): string {
  const t = document.createElement('textarea');
  t.innerHTML = s.replace(/<br\s*\/?>/gi, '\n').replace(/<\/?(p|div|span|code)[^>]*>/gi, '\n');
  return t.value;
}

function parseLines(raw: string): UiComp[] {
  const out: UiComp[] = [];
  for (const line of decode(raw).split('\n')) {
    const l = line.trim();
    if (!l.startsWith('{')) continue;
    try {
      const o = JSON.parse(l);
      const c = String(o.c || o.type || '').toLowerCase();
      if (!COMPONENTS.has(c)) continue;
      out.push({ ...o, c, tone: TONES.has(o.tone) ? o.tone : '' });
    } catch { /* a broken line is dropped, the rest stays */ }
  }
  return out;
}

/** Splits an answer (HTML) into prose and component blocks; no block = one HTML part. */
export function splitAnswer(content: string): AnswerPart[] {
  if (!content || !/hestia-ui/.test(content)) return [{ html: content }];
  const marks: Array<{ start: number; end: number; comps: UiComp[] }> = [];
  for (const re of FENCES) {
    re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(content))) {
      if (marks.some(x => m!.index < x.end && m!.index + m![0].length > x.start)) continue;
      marks.push({ start: m.index, end: m.index + m[0].length, comps: parseLines(m[1]) });
    }
  }
  if (!marks.length) return [{ html: content }];
  marks.sort((a, b) => a.start - b.start);
  const parts: AnswerPart[] = [];
  let at = 0;
  for (const k of marks) {
    const before = content.slice(at, k.start).trim();
    if (before) parts.push({ html: before });
    if (k.comps.length) parts.push({ comps: k.comps });
    at = k.end;
  }
  const rest = content.slice(at).trim();
  if (rest) parts.push({ html: rest });
  return parts;
}

/**
 * Components inside a chat answer (Cindy 9): card, stat, table, list, chart, checklist, button — drawn with the
 * WebUI's own tokens (tone = role colour, stroke icons, no emoji). A button never runs anything: it sends its text
 * as your message (`send` output).
 */
@Component({
  selector: 'hx-answer-blocks',
  imports: [IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="blocks">
      @for (b of comps(); track $index) {
        @switch (b.c) {
          @case ('card') {
            <div class="card" [attr.data-tone]="b.tone">
              @if (b.title) { <div class="ct">@if (b.icon) { <hx-icon [name]="b.icon" [size]="15" /> }{{ b.title }}</div> }
              @if (b.text) { <div class="cx">{{ b.text }}</div> }
            </div>
          }
          @case ('stat') {
            <div class="stat" [attr.data-tone]="b.tone"><span class="sl">{{ b.label }}</span><b>{{ b.value }}</b>
              @if (b.hint) { <span class="sh">{{ b.hint }}</span> }</div>
          }
          @case ('table') {
            <div class="tw"><table>
              @if (b.cols?.length) { <thead><tr>@for (c of b.cols; track $index) { <th>{{ c }}</th> }</tr></thead> }
              <tbody>@for (r of b.rows ?? []; track $index) { <tr>@for (v of r; track $index) { <td>{{ v }}</td> }</tr> }</tbody>
            </table></div>
          }
          @case ('list') {
            <ul class="list">@for (i of b.items ?? []; track $index) {
              <li [attr.data-tone]="i.tone"><span class="dot"></span><span class="lt">{{ i.title || i.label }}</span>
                @if (meta(i.meta); as mm) { <span class="lm">{{ mm }}</span> }</li>
            }</ul>
          }
          @case ('checklist') {
            <ul class="check">@for (i of b.items ?? []; track $index) {
              <li [class.done]="i.done"><hx-icon [name]="i.done ? 'check-circle' : 'square'" [size]="15" /><span>{{ i.label || i.title }}</span></li>
            }</ul>
          }
          @case ('chart') {
            <div class="chart">
              <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" preserveAspectRatio="none" role="img" [attr.aria-label]="b.title || 'Grafico'">
                @if (b.kind === 'line') {
                  <polyline [attr.points]="linePoints(b.values ?? [])" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke" />
                } @else {
                  @for (v of b.values ?? []; track $index; let i = $index) {
                    <rect [attr.x]="barX(i, b.values!.length)" [attr.width]="barW(b.values!.length)" [attr.y]="H - barH(v, b.values!)"
                          [attr.height]="barH(v, b.values!)" rx="2" fill="var(--accent)"><title>{{ (b.labels ?? [])[i] }}: {{ v }} {{ b.unit || '' }}</title></rect>
                  }
                }
              </svg>
              <div class="lbl"><span>{{ (b.labels ?? [])[0] }}</span><span>{{ max(b.values ?? []) }} {{ b.unit || '' }}</span><span>{{ (b.labels ?? []).slice(-1)[0] }}</span></div>
            </div>
          }
          @case ('button') {
            <button class="act" (click)="send.emit(b.send || b.label || '')">{{ b.label }}</button>
          }
        }
      }
    </div>`,
  styles: [`
    .blocks { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 10px; }
    .blocks > * { flex: 1 1 100%; }
    .blocks > .stat, .blocks > .act { flex: 0 1 auto; }
    [data-tone=primary] { --t: var(--accent); } [data-tone=success] { --t: var(--success); } [data-tone=warning] { --t: var(--warning); }
    [data-tone=danger] { --t: var(--danger); } [data-tone=info] { --t: var(--info, var(--accent)); }
    .card { border: 1px solid var(--border); border-left: 3px solid var(--t, var(--border-strong)); border-radius: var(--radius-md); padding: 10px 12px; background: var(--surface); }
    .ct { font-weight: 600; display: flex; gap: 6px; align-items: center; } .ct hx-icon { color: var(--t, var(--accent)); }
    .cx { font-size: 13.5px; color: var(--text-2); margin-top: 3px; white-space: pre-wrap; }
    .stat { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 12px; background: var(--surface); min-width: 120px; display: flex; flex-direction: column; }
    .stat b { font-size: 19px; color: var(--t, var(--text)); } .sl, .sh { font-size: 12px; color: var(--text-3); }
    .tw { overflow-x: auto; } table { border-collapse: collapse; font-size: 13px; width: 100%; }
    th, td { border: 1px solid var(--border); padding: 5px 9px; text-align: left; } th { background: var(--bg-subtle); font-weight: 600; }
    ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
    .list li { display: flex; gap: 8px; align-items: baseline; font-size: 13.5px; }
    .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--t, var(--text-3)); flex: none; transform: translateY(-1px); }
    .lm { color: var(--text-3); font-size: 12.5px; }
    .check li { display: flex; gap: 8px; align-items: center; font-size: 13.5px; } .check li.done { color: var(--text-3); text-decoration: line-through; }
    .check hx-icon { color: var(--accent); }
    .chart { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px; background: var(--surface); }
    svg { width: 100%; height: 110px; display: block; }
    .lbl { display: flex; justify-content: space-between; font-size: 11.5px; color: var(--text-3); margin-top: 4px; }
    .act { padding: 6px 14px; border-radius: var(--radius-full); border: 1px solid var(--accent); color: var(--accent); background: var(--surface); font: inherit; font-size: 13.5px; cursor: pointer; }
    .act:hover { background: var(--accent-soft); }
  `],
})
export class AnswerBlocksComponent {
  comps = input<UiComp[]>([]);
  send = output<string>();
  readonly W = 300;
  readonly H = 100;

  meta(m: string | string[] | undefined): string { return Array.isArray(m) ? m.join(' · ') : m || ''; }
  max(v: number[]): number { return v.length ? Math.max(...v) : 0; }
  barW(n: number): number { return Math.max(1, this.W / Math.max(1, n) - 3); }
  barX(i: number, n: number): number { return i * (this.W / Math.max(1, n)) + 1.5; }
  barH(v: number, all: number[]): number { const m = this.max(all); return m > 0 ? Math.max(1, (v / m) * (this.H - 4)) : 1; }
  linePoints(v: number[]): string {
    const m = this.max(v) || 1;
    const step = v.length > 1 ? this.W / (v.length - 1) : 0;
    return v.map((x, i) => `${(i * step).toFixed(1)},${(this.H - 2 - (x / m) * (this.H - 6)).toFixed(1)}`).join(' ');
  }
}

export const isComps = (p: AnswerPart): p is { comps: UiComp[] } => 'comps' in p;
