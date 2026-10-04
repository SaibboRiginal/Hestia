import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { IconComponent, MarkdownComponent, SpinnerComponent } from '../../ui';
import { TranscriptEvent } from './forge.models';

/** One rendered row: a tool call is merged with its result. */
interface Row {
  key: string;
  kind: 'prompt' | 'user' | 'text' | 'thinking' | 'tool' | 'system' | 'result' | 'error';
  ev: TranscriptEvent;
  result?: TranscriptEvent;
}

const TOOL_ICON: Record<string, string> = {
  Read: 'file', read_file: 'file', Edit: 'edit', edit_file: 'edit', MultiEdit: 'edit', Write: 'edit', write_file: 'edit',
  Bash: 'terminal', run_tests: 'flask', Glob: 'search', Grep: 'search', search: 'search', list_files: 'folder',
  TodoWrite: 'list', finish: 'check',
};

/** Conversation of a Forge engine run, Claude Code style: messages, collapsible thinking, tool calls with I/O. */
@Component({
  selector: 'forge-transcript',
  imports: [IconComponent, MarkdownComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!rows().length) {
      <div class="none">
        @if (working()) { <hx-spinner [size]="16" /> Il motore sta partendo… }
        @else { Nessuna conversazione registrata per questo task (task precedente alla registrazione, o mai avviato). }
      </div>
    }
    @for (r of rows(); track r.key) {
      @switch (r.kind) {
        @case ('prompt') {
          <details class="card prompt">
            <summary><hx-icon name="user" [size]="14" /> <b>Istruzioni date al motore</b>
              <span class="muted">{{ firstLine(r.ev.text) }}</span></summary>
            <pre class="pre">{{ r.ev.text }}</pre>
          </details>
        }
        @case ('user') { <div class="user">{{ r.ev.text }}</div> }
        @case ('text') { <div class="text"><hx-markdown [text]="r.ev.text || ''" /></div> }
        @case ('thinking') {
          <details class="think">
            <summary><hx-icon name="brain" [size]="14" /> Ragionamento <span class="muted">{{ firstLine(r.ev.text) }}</span></summary>
            <div class="think-body">{{ r.ev.text }}</div>
          </details>
        }
        @case ('tool') {
          <details class="tool" [class.err]="r.result?.is_error" [class.pending]="!r.result">
            <summary>
              <hx-icon [name]="icon(r.ev.tool)" [size]="14" />
              <b>{{ r.ev.tool }}</b>
              <span class="arg">{{ brief(r.ev) }}</span>
              @if (!r.result && working()) { <hx-spinner [size]="12" /> }
              @if (r.result?.is_error) { <span class="tag">errore</span> }
            </summary>
            <div class="io">
              @switch (shape(r.ev)) {
                @case ('edit') {
                  <div class="lbl">Modifica</div>
                  <div class="mini">
                    @for (l of lines(str(r.ev.input?.['old_string'] ?? r.ev.input?.['old'])); track $index) { <div class="del">-{{ l }}</div> }
                    @for (l of lines(str(r.ev.input?.['new_string'] ?? r.ev.input?.['new'])); track $index) { <div class="add">+{{ l }}</div> }
                  </div>
                }
                @case ('write') {
                  <div class="lbl">Contenuto</div><pre class="pre">{{ str(r.ev.input?.['content']) }}</pre>
                }
                @case ('bash') {
                  <div class="lbl">Comando</div><pre class="pre cmd">$ {{ str(r.ev.input?.['command']) }}</pre>
                }
                @default {
                  <div class="lbl">Input</div><pre class="pre">{{ json(r.ev.input) }}</pre>
                }
              }
              @if (r.result) {
                <div class="lbl">{{ r.result.is_error ? 'Errore' : 'Risultato' }}</div>
                <pre class="pre out">{{ r.result.text || '(vuoto)' }}</pre>
              }
            </div>
          </details>
        }
        @case ('system') {
          <div class="sys"><hx-icon name="info" [size]="13" /> {{ r.ev.text }}
            @if (r.ev.meta?.['model']) { · {{ r.ev.meta?.['model'] }} }</div>
        }
        @case ('result') {
          <div class="end ok"><hx-icon name="check" [size]="15" />
            <div><div class="eh"><b>Fine del lavoro del motore</b><span>{{ stats(r.ev) }}</span></div><hx-markdown [text]="r.ev.text || ''" /></div></div>
        }
        @case ('error') {
          <div class="end ko"><hx-icon name="alert" [size]="15" />
            <div><div class="eh"><b>Il motore si è fermato</b><span>{{ stats(r.ev) }}</span></div><div class="pre-wrap">{{ r.ev.text }}</div></div></div>
        }
      }
    }
    @if (working() && rows().length) {
      <div class="live"><span class="dot"></span> In lavorazione… la conversazione si aggiorna da sola.</div>
    }
  `,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
    .none { color: var(--text-3); font-size: 13.5px; padding: 30px 6px; display: flex; gap: 8px; align-items: center; }
    .muted { color: var(--text-3); font-weight: 400; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
    summary { display: flex; align-items: center; gap: 7px; cursor: pointer; list-style: none; min-width: 0; }
    summary::-webkit-details-marker { display: none; }
    .card { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 12px; background: var(--bg-subtle); }
    .card[open] summary { margin-bottom: 8px; }
    .user { align-self: flex-end; max-width: 85%; background: var(--user-bubble); color: var(--user-bubble-text);
            padding: 8px 13px; border-radius: 16px 16px 4px 16px; white-space: pre-wrap; font-size: 13.5px; }
    .text { padding: 2px 2px; }
    .think { color: var(--text-3); font-size: 13px; padding: 2px 2px; }
    .think-body { white-space: pre-wrap; border-left: 2px solid var(--border-strong); padding: 4px 0 4px 12px; margin: 6px 0 2px 6px; font-style: italic; }
    .tool { border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 13px; background: var(--surface); }
    .tool summary { padding: 6px 10px; }
    .tool summary hx-icon { color: var(--text-3); }
    .tool b { font-weight: 600; font-family: var(--font-mono); font-size: 12.5px; }
    .tool .arg { font-family: var(--font-mono); font-size: 12px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
    .tool.err { border-color: color-mix(in srgb, var(--danger) 45%, var(--border)); }
    .tool.pending summary { color: var(--text-2); }
    .tag { font-size: 11px; color: var(--danger); background: var(--danger-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .io { border-top: 1px solid var(--border); padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 4px; }
    .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin-top: 4px; }
    .pre { font-family: var(--font-mono); font-size: 12px; white-space: pre-wrap; word-break: break-word; background: var(--surface-2);
           border-radius: var(--radius-sm, 6px); padding: 8px 10px; max-height: 360px; overflow: auto; margin: 0; }
    .pre.cmd { color: var(--text); }
    .mini { font-family: var(--font-mono); font-size: 12px; border-radius: 6px; overflow: auto; max-height: 360px; white-space: pre; }
    .mini .add { background: color-mix(in srgb, var(--success) 13%, transparent); padding: 0 8px; }
    .mini .del { background: color-mix(in srgb, var(--danger) 13%, transparent); padding: 0 8px; }
    .sys { font-size: 12px; color: var(--text-3); display: flex; align-items: center; gap: 6px; padding: 0 2px; }
    .end { display: flex; gap: 10px; padding: 10px 12px; border-radius: var(--radius-md); font-size: 13.5px; }
    .end > hx-icon { margin-top: 2px; }
    .end .eh { margin-bottom: 4px; } .end .eh span { color: var(--text-2); font-size: 12.5px; }
    .end.ok { background: var(--success-soft); } .end.ok > hx-icon { color: var(--success); }
    .end.ko { background: var(--danger-soft); } .end.ko > hx-icon { color: var(--danger); }
    .pre-wrap { white-space: pre-wrap; }
    .live { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-3); padding: 6px 2px; }
    .live .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: hx-pulse 1.4s infinite; }
  `],
})
export class TranscriptComponent {
  events = input<TranscriptEvent[]>([]);
  working = input(false);

  readonly rows = computed<Row[]>(() => {
    const out: Row[] = [];
    const tools = new Map<string, Row>();
    for (const ev of this.events()) {
      const key = `${ev.i}`;
      switch (ev.kind) {
        case 'user':
          out.push({ key, kind: ev.meta?.['role'] === 'task_prompt' ? 'prompt' : 'user', ev }); break;
        case 'tool_use': {
          const row: Row = { key, kind: 'tool', ev };
          if (ev.id) tools.set(ev.id, row);
          out.push(row); break;
        }
        case 'tool_result': {
          const row = ev.id ? tools.get(ev.id) : undefined;
          if (row && !row.result) row.result = ev;
          else out.push({ key, kind: 'tool', ev: { ...ev, kind: 'tool_use', input: {} }, result: ev });
          break;
        }
        default:
          if (ev.kind === 'text' && !String(ev.text ?? '').trim()) break;
          out.push({ key, kind: ev.kind, ev });
      }
    }
    return out;
  });


  icon(tool?: string) { return TOOL_ICON[tool ?? ''] ?? 'code'; }
  shape(ev: TranscriptEvent): 'edit' | 'write' | 'bash' | 'other' {
    const t = ev.tool ?? '';
    if (t === 'Edit' || t === 'edit_file') return 'edit';
    if (t === 'Write' || t === 'write_file') return 'write';
    if (t === 'Bash') return 'bash';
    return 'other';
  }
  brief(ev: TranscriptEvent): string {
    const i = ev.input ?? {};
    const v = i['file_path'] ?? i['path'] ?? i['command'] ?? i['pattern'] ?? i['glob'] ?? i['summary'] ?? i['paths'];
    if (v !== undefined) return Array.isArray(v) ? v.join(' ') : String(v);
    if (ev.tool === 'TodoWrite' && Array.isArray(i['todos'])) return `${(i['todos'] as unknown[]).length} attività`;
    return '';
  }
  str(v: unknown): string { return v === undefined || v === null ? '' : String(v); }
  lines(text: string): string[] { return text ? text.split('\n') : []; }
  json(v: unknown): string { try { return JSON.stringify(v ?? {}, null, 2); } catch { return String(v); } }
  firstLine(text?: string): string { return (text ?? '').split('\n').find(l => l.trim())?.slice(0, 140) ?? ''; }
  stats(ev: TranscriptEvent): string {
    const m = ev.meta ?? {};
    const parts: string[] = [];
    if (m['turns']) parts.push(`${m['turns']} turni`);
    if (typeof m['cost_usd'] === 'number') parts.push(`$${(m['cost_usd'] as number).toFixed(3)}`);
    if (m['duration_ms']) parts.push(`${Math.round((m['duration_ms'] as number) / 1000)} s`);
    return parts.length ? ` · ${parts.join(' · ')}` : '';
  }
}
