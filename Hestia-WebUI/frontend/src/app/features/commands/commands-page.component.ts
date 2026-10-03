import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { BadgeComponent, ButtonComponent, EmptyStateComponent, FieldComponent, IconComponent, PageHeaderComponent, SpinnerComponent } from '../../ui';

interface HubCommand {
  command: string; title: string; description: string; service: string; method: string; path: string;
  response_mode?: string; response_prompt?: string; clients?: string[];
  arguments_schema?: { properties?: Record<string, { type?: string; description?: string; enum?: string[] }>; required?: string[] };
}

/** Every tool/command discovered through Hub (the same ones Oracle, Telegram and MCP use). Run with arguments. */
@Component({
  selector: 'app-commands-page',
  imports: [FormsModule, PageHeaderComponent, ButtonComponent, IconComponent, BadgeComponent, FieldComponent, EmptyStateComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Comandi & MCP" [subtitle]="all().length + ' strumenti da ' + services().length + ' servizi, scoperti via Hub'">
      <div class="search"><hx-icon name="search" [size]="15" />
        <input class="hx-input" placeholder="Cerca comando…" [ngModel]="q()" (ngModelChange)="q.set($event)" /></div>
      <button hx-btn variant="ghost" icon="refresh" iconOnly aria-label="Aggiorna" (click)="load()"></button>
    </hx-page-header>
    <div class="body">
      <div class="list">
        @if (loading()) { <div class="center"><hx-spinner /></div> }
        @for (g of groups(); track g.service) {
          <h4>{{ g.service }} <span>{{ g.items.length }}</span></h4>
          @for (c of g.items; track c.command) {
            <button class="row" [class.on]="sel()?.command === c.command" (click)="select(c)">
              <span class="t hx-truncate">{{ c.title || c.command }}</span>
              <span class="m">{{ c.method }}</span>
            </button>
          }
        }
        @if (!loading() && !groups().length) { <hx-empty icon="terminal" title="Nessun comando">Hub non ha restituito strumenti.</hx-empty> }
      </div>
      <div class="detail">
        @if (sel(); as c) {
          <h2>{{ c.title || c.command }}</h2>
          <p class="desc">{{ c.description }}</p>
          <div class="meta">
            <hx-badge>{{ c.service }}</hx-badge>
            <code>{{ c.method }} {{ c.path }}</code>
            @if (c.response_mode === 'oracle_natural') { <hx-badge tone="accent">risposta in linguaggio naturale</hx-badge> }
          </div>
          @if (argNames(c).length) {
            <div class="args">
              @for (a of argNames(c); track a) {
                <hx-field [label]="a" [hint]="argDesc(c, a)" [required]="isReq(c, a)">
                  @if (argEnum(c, a); as opts) {
                    <select class="hx-select" [(ngModel)]="args[a]"><option value=""></option>
                      @for (o of opts; track o) { <option [value]="o">{{ o }}</option> }</select>
                  } @else {
                    <input class="hx-input" [(ngModel)]="args[a]" [placeholder]="argType(c, a)" />
                  }
                </hx-field>
              }
            </div>
          }
          <button hx-btn variant="primary" icon="play" [loading]="running()" (click)="run(c)">Esegui</button>
          @if (result(); as r) {
            <div class="result" [class.err]="!r.ok">
              @if (r.text) { <div class="hx-prose" [innerHTML]="r.text"></div> }
              @else { <pre>{{ r.json }}</pre> }
            </div>
          }
        } @else {
          <hx-empty icon="terminal" title="Seleziona un comando">Vedi descrizione, parametri ed eseguilo come farebbe Hestia.</hx-empty>
        }
      </div>
    </div>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    hx-page-header { padding-left: 56px; }
    @media (min-width: 861px) { hx-page-header { padding-left: 24px; } }
    .search { position: relative; width: 240px; }
    .search hx-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search .hx-input { padding-left: 30px; height: 32px; }
    .body { flex: 1; display: grid; grid-template-columns: 320px 1fr; min-height: 0; }
    .list { border-right: 1px solid var(--border); overflow-y: auto; padding: 8px; }
    h4 { font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-3); margin: 12px 6px 4px; display: flex; justify-content: space-between; }
    .row { width: 100%; display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-radius: var(--radius-sm); font-size: 13.5px; text-align: left; }
    .row:hover { background: var(--surface-2); }
    .row.on { background: var(--accent-soft); color: var(--accent); }
    .t { flex: 1; }
    .m { font-size: 10.5px; color: var(--text-3); font-family: var(--font-mono); }
    .detail { overflow-y: auto; padding: 22px 28px; display: flex; flex-direction: column; gap: 14px; max-width: 820px; }
    h2 { font-family: var(--font-serif); font-weight: 500; font-size: 22px; }
    .desc { color: var(--text-2); white-space: pre-wrap; }
    .meta { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; }
    .args { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
    .result { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; background: var(--surface); }
    .result.err { border-color: var(--danger); }
    .result pre { margin: 0; max-height: 420px; overflow: auto; }
    .center { display: grid; place-items: center; padding: 30px; }
    button[hx-btn] { align-self: flex-start; }
    @media (max-width: 860px) { .body { grid-template-columns: 1fr; } .list { max-height: 40vh; border-right: 0; border-bottom: 1px solid var(--border); } .search { width: 150px; } }
  `],
})
export class CommandsPageComponent implements OnInit {
  private http = inject(HttpClient);
  all = signal<HubCommand[]>([]);
  q = signal('');
  sel = signal<HubCommand | null>(null);
  loading = signal(false);
  running = signal(false);
  result = signal<{ ok: boolean; text?: string; json?: string } | null>(null);
  args: Record<string, string> = {};

  services = computed(() => [...new Set(this.all().map(c => c.service))]);
  groups = computed(() => {
    const q = this.q().toLowerCase();
    const map = new Map<string, HubCommand[]>();
    for (const c of this.all()) {
      if (q && !`${c.title} ${c.command} ${c.description} ${c.service}`.toLowerCase().includes(q)) continue;
      (map.get(c.service) ?? map.set(c.service, []).get(c.service)!).push(c);
    }
    return [...map.entries()].sort().map(([service, items]) => ({ service, items }));
  });

  ngOnInit() { void this.load(); }

  async load() {
    this.loading.set(true);
    try {
      const r = await firstValueFrom(this.http.get<{ commands: HubCommand[] }>('/api/webui/commands'));
      this.all.set(r.commands ?? []);
    } catch { this.all.set([]); }
    this.loading.set(false);
  }

  select(c: HubCommand) { this.sel.set(c); this.args = {}; this.result.set(null); }
  argNames = (c: HubCommand) => Object.keys(c.arguments_schema?.properties ?? {});
  argDesc = (c: HubCommand, a: string) => c.arguments_schema?.properties?.[a]?.description ?? '';
  argType = (c: HubCommand, a: string) => c.arguments_schema?.properties?.[a]?.type ?? '';
  argEnum = (c: HubCommand, a: string) => c.arguments_schema?.properties?.[a]?.enum ?? null;
  isReq = (c: HubCommand, a: string) => (c.arguments_schema?.required ?? []).includes(a);

  async run(c: HubCommand) {
    const args: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(this.args)) {
      if (!String(v ?? '').trim()) continue;
      const t = this.argType(c, k);
      args[k] = t === 'integer' || t === 'number' ? Number(v) : t === 'boolean' ? v === 'true' : (t === 'array' || t === 'object') ? safeJson(v) : v;
    }
    this.running.set(true);
    try {
      const r = await firstValueFrom(this.http.post<{ ok: boolean; result?: unknown; text?: string; error?: string }>(
        '/api/webui/commands/execute', { command: c.command, args }));
      this.result.set(r.ok ? { ok: true, text: r.text ?? undefined, json: JSON.stringify(r.result, null, 2) }
                           : { ok: false, json: r.error ?? 'errore' });
    } catch (e: any) {
      this.result.set({ ok: false, json: e?.message ?? 'errore' });
    }
    this.running.set(false);
  }
}

function safeJson(v: string): unknown { try { return JSON.parse(v); } catch { return v.split(',').map(s => s.trim()); } }
