import { ChangeDetectionStrategy, Component, computed, inject, input, output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { marked } from 'marked';
import { PluginsService } from '../plugins/plugins.service';
import { DialogService, IconComponent, ButtonComponent } from '../../ui';
import { tr, TrPipe } from '../../core/i18n';

/** One tool as the commands door gives it (GET /api/mcp/ui/tools). */
interface Cmd {
  command: string; title: string; summary?: string; description: string; area_label?: string; writes: boolean;
  response_mode: string; response_prompt: string;
  arguments_schema: { properties?: Record<string, { type?: string; description?: string; enum?: unknown[] }>; required?: string[] };
}

const MAX = 8;
const words = (s: string) => s.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

/**
 * <hx-chat-commands [query]="text after /"> — «/» in the chat box (dossier 2026-11-18-problemi-del-test B): the tools
 * the WebUI can run, filtered while typing (arrows / Tab / Enter pick one). A tool without arguments runs at once; one
 * with arguments shows its fields here. The result goes in the conversation (`done`). Same list and rules as the
 * Comandi page (Hestia-MCP), nothing duplicated.
 */
@Component({
  selector: 'hx-chat-commands',
  imports: [TrPipe, FormsModule, IconComponent, ButtonComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="box" role="listbox" [attr.aria-label]="'Commands' | tr">
      @if (picked(); as c) {
        <form class="form" (ngSubmit)="run(c)">
          <div class="head"><hx-icon name="zap" [size]="14" /><b>{{ c.title }}</b>
            <button type="button" class="link" (click)="picked.set(null)">{{ "Back" | tr }}</button></div>
          @if (c.summary) { <div class="sum">{{ c.summary }}</div> }
          @for (f of fields(c); track f.key; let first = $first) {
            <label class="fld"><span>{{ f.label }}@if (f.required) { <i>*</i> }</span>
              @if (f.options.length) {
                <select [name]="f.key" [(ngModel)]="args[f.key]">
                  <option value=""></option>
                  @for (o of f.options; track o) { <option [value]="o">{{ o }}</option> }
                </select>
              } @else {
                <input [name]="f.key" [(ngModel)]="args[f.key]" [attr.autofocus]="first ? '' : null" autocomplete="off">
              }
            </label>
          }
          <div class="act"><button hx-btn type="submit" variant="primary" size="sm" icon="play" [loading]="busy()" [disabled]="!ready(c)">{{ "Run" | tr }}</button></div>
        </form>
      } @else if (!loaded()) {
        <div class="none">{{ "Loading…" | tr }}</div>
      } @else if (!matches().length) {
        <div class="none">{{ "No command with these words" | tr }}</div>
      } @else {
        @for (c of matches(); track c.command; let i = $index) {
          <button type="button" class="opt" role="option" [class.on]="i === active()" [attr.aria-selected]="i === active()"
                  (mouseenter)="active.set(i)" (mousedown)="$event.preventDefault()" (click)="choose(c)">
            <span class="t"><b>{{ c.title }}</b><small>{{ c.summary || c.description }}</small></span>
            @if (c.area_label) { <span class="area">{{ c.area_label }}</span> }
          </button>
        }
        <div class="foot">{{ "Arrows to move, Enter to choose, Esc to close" | tr }}</div>
      }
    </div>
  `,
  styles: [`
    .box { border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); margin: 0 0 6px;
      max-height: 320px; overflow-y: auto; padding: 4px; }
    .opt { display: flex; align-items: center; gap: 10px; width: 100%; text-align: left; border: 0; background: transparent;
      color: var(--text); padding: 7px 10px; border-radius: var(--radius-sm); cursor: pointer; font: inherit; }
    .opt.on { background: var(--surface-2); }
    .t { display: flex; flex-direction: column; min-width: 0; flex: 1; }
    .t small { color: var(--text-3); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .area { font-size: 11px; color: var(--text-3); }
    .none, .foot { color: var(--text-3); font-size: 12px; padding: 6px 10px; }
    .form { display: flex; flex-direction: column; gap: 8px; padding: 6px 8px; }
    .head { display: flex; align-items: center; gap: 6px; }
    .head .link { margin-left: auto; border: 0; background: none; color: var(--accent); cursor: pointer; font: inherit; font-size: 13px; }
    .sum { color: var(--text-2); font-size: 13px; }
    .fld { display: flex; flex-direction: column; gap: 3px; font-size: 13px; color: var(--text-2); }
    .fld i { color: var(--danger); font-style: normal; }
    .fld input, .fld select { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm); padding: 6px 9px; }
    .act { display: flex; justify-content: flex-end; }
  `],
})
export class ChatCommandsComponent {
  /** What follows «/» in the box. */
  query = input('');
  /** The result, for the conversation: the command's title and the answer as HTML. */
  done = output<{ title: string; html: string }>();
  closed = output<void>();

  private plugins = inject(PluginsService);
  private dialogs = inject(DialogService);
  private all = signal<Cmd[]>([]);
  readonly loaded = signal(false);
  readonly active = signal(0);
  readonly picked = signal<Cmd | null>(null);
  readonly busy = signal(false);
  args: Record<string, string> = {};

  readonly matches = computed(() => {
    const q = words(this.query().trim()).split(/\s+/).filter(Boolean);
    const list = this.all().filter(c => {
      const hay = words(`${c.title} ${c.command} ${c.summary ?? ''} ${c.area_label ?? ''}`);
      return q.every(w => hay.includes(w));
    });
    return list.slice(0, MAX);
  });

  constructor() { void this.load(); }

  private async load() {
    const r = await this.plugins.call<{ commands?: Cmd[] }>('mcp', 'GET', '/api/mcp/ui/tools');
    this.all.set(r.ok ? (r.data?.commands ?? []) : []);
    this.loaded.set(true);
  }

  /** Keys from the box while the list is open; true = handled here (the box does not send). */
  key(e: KeyboardEvent): boolean {
    if (e.key === 'Escape') { this.closed.emit(); return true; }
    if (this.picked()) return false;
    const n = this.matches().length;
    if (e.key === 'ArrowDown' && n) { this.active.set((this.active() + 1) % n); return true; }
    if (e.key === 'ArrowUp' && n) { this.active.set((this.active() - 1 + n) % n); return true; }
    if ((e.key === 'Enter' || e.key === 'Tab') && !e.shiftKey && n) {
      this.choose(this.matches()[Math.min(this.active(), n - 1)]);
      return true;
    }
    return false;
  }

  fields(c: Cmd) {
    const req = new Set(c.arguments_schema?.required ?? []);
    return Object.entries(c.arguments_schema?.properties ?? {}).map(([key, p]) => ({
      key, label: p?.description && p.description !== key ? p.description : key, required: req.has(key),
      options: Array.isArray(p?.enum) ? p.enum.map(String) : [],
    }));
  }

  ready(c: Cmd) { return !this.busy() && (c.arguments_schema?.required ?? []).every(k => String(this.args[k] ?? '').trim()); }

  choose(c: Cmd) {
    this.args = {};
    if (this.fields(c).length) { this.picked.set(c); return; }
    void this.run(c);
  }

  async run(c: Cmd) {
    if (!this.ready(c)) return;
    if (c.writes && !(await this.dialogs.confirm(c.title, c.summary || c.description, tr('Run')))) return;
    const props = c.arguments_schema?.properties ?? {};
    const args: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(this.args)) {
      const s = String(v ?? '').trim();
      if (!s) continue;
      const t = props[k]?.type;
      args[k] = t === 'integer' || t === 'number' ? Number(s) : t === 'boolean' ? s === 'true' : s;
    }
    this.busy.set(true);
    const r = await this.plugins.call<{ ok?: boolean; result?: unknown; error?: string }>('mcp', 'POST', '/api/mcp/ui/tools/call',
      { body: { command: c.command, args } });
    let html: string;
    if (!r.ok || r.data?.ok === false) {
      html = `<p>${esc(r.data?.error || (r.error === 'offline' ? tr('You are offline: try again when you are back online') : tr('Command failed')))}</p>`;
    } else {
      html = await this.readable(c, r.data?.result);
    }
    this.busy.set(false);
    this.picked.set(null);
    this.done.emit({ title: c.title, html });
  }

  /** The result in words (Oracle, like the Comandi page) when the tool answers in natural language; else as it is. */
  private async readable(c: Cmd, result: unknown): Promise<string> {
    if (typeof result === 'string') return marked.parse(result, { gfm: true, async: false }) as string;
    if (c.response_mode === 'oracle_natural') {
      const f = await this.plugins.call<{ ok?: boolean; text?: string }>('mcp', 'POST', '/api/mcp/ui/tools/format',
        { body: { command: c.command, result, response_prompt: c.response_prompt } });
      if (f.ok && f.data?.ok && f.data.text) return marked.parse(f.data.text, { gfm: true, async: false }) as string;
    }
    if (result == null || (typeof result === 'object' && !Object.keys(result as object).length)) return `<p>${esc(tr('Done.'))}</p>`;
    return `<pre>${esc(JSON.stringify(result, null, 2))}</pre>`;
  }
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]!));
}
