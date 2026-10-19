/**
 * <hephaestus-transcript> — conversation of a Forge engine run, Claude Code style: messages, collapsible thinking,
 * tool calls merged with their result. Port of the WebUI forge/transcript.component.
 */
import { LitElement, css, html, nothing, tokens } from '@hestia/webui-sdk';
import { icon } from './icons';
import type { TranscriptEvent } from './models';

interface Row { key: string; kind: 'prompt' | 'user' | 'text' | 'thinking' | 'tool' | 'system' | 'result' | 'error'; ev: TranscriptEvent; result?: TranscriptEvent; }

const TOOL_ICON: Record<string, string> = {
  Read: 'file', read_file: 'file', Edit: 'edit', edit_file: 'edit', MultiEdit: 'edit', Write: 'edit', write_file: 'edit',
  Bash: 'terminal', run_tests: 'flask', Glob: 'search', Grep: 'search', search: 'search', list_files: 'folder',
  TodoWrite: 'list', finish: 'check',
};

const str = (v: unknown) => v === undefined || v === null ? '' : String(v);
const lines = (t: string) => t ? t.split('\n') : [];
const json = (v: unknown) => { try { return JSON.stringify(v ?? {}, null, 2); } catch { return String(v); } };
const firstLine = (t?: string) => (t ?? '').split('\n').find(l => l.trim())?.slice(0, 140) ?? '';

export function transcriptRows(events: TranscriptEvent[]): Row[] {
  const out: Row[] = [];
  const tools = new Map<string, Row>();
  for (const ev of events) {
    const key = `${ev.i}`;
    switch (ev.kind) {
      case 'user': out.push({ key, kind: ev.meta?.['role'] === 'task_prompt' ? 'prompt' : 'user', ev }); break;
      case 'tool_use': { const row: Row = { key, kind: 'tool', ev }; if (ev.id) tools.set(ev.id, row); out.push(row); break; }
      case 'tool_result': {
        const row = ev.id ? tools.get(ev.id) : undefined;
        if (row && !row.result) row.result = ev;
        else out.push({ key, kind: 'tool', ev: { ...ev, kind: 'tool_use', input: {} }, result: ev });
        break;
      }
      default:
        if (ev.kind === 'text' && !String(ev.text ?? '').trim()) break;
        out.push({ key, kind: ev.kind as Row['kind'], ev });
    }
  }
  return out;
}

function brief(ev: TranscriptEvent): string {
  const i = ev.input ?? {};
  const v = i['file_path'] ?? i['path'] ?? i['command'] ?? i['pattern'] ?? i['glob'] ?? i['summary'] ?? i['paths'];
  if (v !== undefined) return Array.isArray(v) ? v.join(' ') : String(v);
  if (ev.tool === 'TodoWrite' && Array.isArray(i['todos'])) return `${(i['todos'] as unknown[]).length} attività`;
  return '';
}
function stats(ev: TranscriptEvent): string {
  const m = ev.meta ?? {};
  const parts: string[] = [];
  if (m['turns']) parts.push(`${m['turns']} turni`);
  if (typeof m['cost_usd'] === 'number') parts.push(`$${(m['cost_usd'] as number).toFixed(3)}`);
  if (m['duration_ms']) parts.push(`${Math.round((m['duration_ms'] as number) / 1000)} s`);
  return parts.length ? ` · ${parts.join(' · ')}` : '';
}

export class HephaestusTranscript extends LitElement {
  static properties = { events: { attribute: false }, working: { type: Boolean } };
  declare events: TranscriptEvent[]; declare working: boolean;
  private rowsFrom: TranscriptEvent[] | null = null;
  private rows: Row[] = [];
  constructor() { super(); this.events = []; this.working = false; }

  static styles = [tokens, css`
    :host { display: flex; flex-direction: column; gap: 8px; font-size: 14px; }
    .none { color: var(--text-3); font-size: 13.5px; padding: 30px 6px; display: flex; gap: 8px; align-items: center; }
    .muted { color: var(--text-3); font-weight: 400; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; flex: 1; }
    summary { display: flex; align-items: center; gap: 7px; cursor: pointer; list-style: none; min-width: 0; }
    summary::-webkit-details-marker { display: none; }
    .card { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 8px 12px; background: var(--bg-subtle); }
    .card[open] summary { margin-bottom: 8px; }
    .user { align-self: flex-end; max-width: 85%; background: var(--user-bubble, var(--accent-soft)); color: var(--user-bubble-text, var(--text));
            padding: 8px 13px; border-radius: 16px 16px 4px 16px; white-space: pre-wrap; font-size: 13.5px; word-break: break-word; }
    .text { padding: 2px; }
    .think { color: var(--text-3); font-size: 13px; padding: 2px; }
    .think-body { white-space: pre-wrap; border-left: 2px solid var(--border-strong); padding: 4px 0 4px 12px; margin: 6px 0 2px 6px; font-style: italic; }
    .tool { border: 1px solid var(--border); border-radius: var(--radius-md); font-size: 13px; background: var(--surface); }
    .tool summary { padding: 6px 10px; color: var(--text); }
    .tool summary .ic, .tool summary hxk-icon { color: var(--text-3); }
    .tool b { font-weight: 600; font-family: var(--font-mono); font-size: 12.5px; }
    .tool .arg { font-family: var(--font-mono); font-size: 12px; color: var(--text-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }
    .tool.err { border-color: color-mix(in srgb, var(--danger) 45%, var(--border)); }
    .tool.pending summary { color: var(--text-2); }
    .tag { font-size: 11px; color: var(--danger); background: var(--danger-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .io { border-top: 1px solid var(--border); padding: 8px 10px 10px; display: flex; flex-direction: column; gap: 4px; }
    .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin-top: 4px; }
    .pre { font-family: var(--font-mono); font-size: 12px; white-space: pre-wrap; word-break: break-word; background: var(--surface-2);
           border-radius: var(--radius-sm); padding: 8px 10px; max-height: 360px; overflow: auto; margin: 0; }
    .mini { font-family: var(--font-mono); font-size: 12px; border-radius: 6px; overflow: auto; max-height: 360px; white-space: pre; }
    .mini .add { background: color-mix(in srgb, var(--success) 13%, transparent); padding: 0 8px; }
    .mini .del { background: color-mix(in srgb, var(--danger) 13%, transparent); padding: 0 8px; }
    .sys { font-size: 12px; color: var(--text-3); display: flex; align-items: center; gap: 6px; padding: 0 2px; }
    .end { display: flex; gap: 10px; padding: 10px 12px; border-radius: var(--radius-md); font-size: 13.5px; }
    .end .eh { margin-bottom: 4px; } .end .eh span { color: var(--text-2); font-size: 12.5px; }
    .end.ok { background: var(--success-soft); } .end.ok > .ic { color: var(--success); }
    .end.ko { background: var(--danger-soft); } .end.ko > .ic { color: var(--danger); }
    .pre-wrap { white-space: pre-wrap; word-break: break-word; }
    .live { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-3); padding: 6px 2px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 1.4s infinite; }
    @keyframes pulse { 50% { opacity: .35; } }
  `];

  private tool(r: Row) {
    const ev = r.ev, t = ev.tool ?? '', i = ev.input ?? {};
    const shape = t === 'Edit' || t === 'edit_file' ? 'edit' : t === 'Write' || t === 'write_file' ? 'write' : t === 'Bash' ? 'bash' : 'other';
    return html`<details class="tool ${r.result?.is_error ? 'err' : ''} ${r.result ? '' : 'pending'}">
      <summary>${icon(TOOL_ICON[t] ?? 'code', 14)}<b>${t}</b><span class="arg">${brief(ev)}</span>
        ${!r.result && this.working ? html`<span class="dot"></span>` : nothing}
        ${r.result?.is_error ? html`<span class="tag">errore</span>` : nothing}</summary>
      <div class="io">
        ${shape === 'edit' ? html`<div class="lbl">Modifica</div><div class="mini">
            ${lines(str(i['old_string'] ?? i['old'])).map(l => html`<div class="del">-${l}</div>`)}
            ${lines(str(i['new_string'] ?? i['new'])).map(l => html`<div class="add">+${l}</div>`)}</div>`
          : shape === 'write' ? html`<div class="lbl">Contenuto</div><pre class="pre">${str(i['content'])}</pre>`
          : shape === 'bash' ? html`<div class="lbl">Comando</div><pre class="pre">$ ${str(i['command'])}</pre>`
          : html`<div class="lbl">Input</div><pre class="pre">${json(ev.input)}</pre>`}
        ${r.result ? html`<div class="lbl">${r.result.is_error ? 'Errore' : 'Risultato'}</div><pre class="pre">${r.result.text || '(vuoto)'}</pre>` : nothing}
      </div></details>`;
  }

  private row(r: Row) {
    const ev = r.ev;
    switch (r.kind) {
      case 'prompt': return html`<details class="card"><summary>${icon('user', 14)} <b>Istruzioni date al motore</b>
        <span class="muted">${firstLine(ev.text)}</span></summary><pre class="pre">${ev.text}</pre></details>`;
      case 'user': return html`<div class="user">${ev.text}</div>`;
      case 'text': return html`<div class="text"><hephaestus-md .text=${ev.text || ''}></hephaestus-md></div>`;
      case 'thinking': return html`<details class="think"><summary>${icon('brain', 14)} Ragionamento <span class="muted">${firstLine(ev.text)}</span></summary>
        <div class="think-body">${ev.text}</div></details>`;
      case 'tool': return this.tool(r);
      case 'system': return html`<div class="sys">${icon('info', 13)} ${ev.text}${ev.meta?.['model'] ? ` · ${ev.meta['model']}` : ''}</div>`;
      case 'result': return html`<div class="end ok">${icon('check', 15)}<div><div class="eh"><b>Fine del lavoro del motore</b><span>${stats(ev)}</span></div>
        <hephaestus-md .text=${ev.text || ''}></hephaestus-md></div></div>`;
      case 'error': return html`<div class="end ko">${icon('alert', 15)}<div><div class="eh"><b>Il motore si è fermato</b><span>${stats(ev)}</span></div>
        <div class="pre-wrap">${ev.text}</div></div></div>`;
    }
    return nothing;
  }

  render() {
    if (this.rowsFrom !== this.events) { this.rows = transcriptRows(this.events || []); this.rowsFrom = this.events; }
    if (!this.rows.length) return html`<div class="none">${this.working ? html`<span class="dot"></span> Il motore sta partendo…`
      : 'Nessuna conversazione registrata per questo task (task precedente alla registrazione, o mai avviato).'}</div>`;
    return html`${this.rows.map(r => this.row(r))}
      ${this.working ? html`<div class="live"><span class="dot"></span> In lavorazione… la conversazione si aggiorna da sola.</div>` : nothing}`;
  }
}
