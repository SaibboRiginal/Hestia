import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ChatService } from '../../services/chat.service';
import { SessionService } from '../../services/session.service';
import { ButtonComponent, IconComponent, PopoverComponent, SettingLinkComponent, ToastService } from '../../ui';

interface ModelUsage {
  provider: string; model: string; calls: number; input_tokens: number; cached_tokens: number; output_tokens: number;
  cost_usd?: number; estimated?: boolean;
}
interface SessionUsage {
  calls?: number; input_tokens?: number; cached_tokens?: number; output_tokens?: number;
  cost_usd?: number; estimated?: boolean; last_prompt_tokens?: number; provider?: string; model?: string;
  by_model?: ModelUsage[];
}
interface Part { id: string; label: string; tokens: number; }
interface ContextStats {
  context_window: number;
  /** provider (the service's own) · runtime (read from the local program) · setting (forced in Hestia) ·
   *  floor (the program's own is too small) · default (not read yet). */
  window_source?: string;
  /** Central setting that forces the window ('' for a cloud model). */
  window_setting_key?: string;
  over_window?: boolean;
  breakdown?: Part[];
  breakdown_measured?: boolean;
  context_used_tokens: number;
  context_used_pct: number;
  context_measured: boolean;
  history_messages: number;
  compaction_available: boolean;
  active?: { provider: string; provider_label: string; model: string; billing: string; context_window: number };
  session_usage?: SessionUsage;
}

const WINDOW_SOURCE: Record<string, string> = {
  runtime: 'letta dal programma che fa girare il modello',
  setting: 'fissata nelle impostazioni di Hestia',
  floor: 'il programma locale ne ha impostata una troppo piccola: uso il minimo',
  default: 'non ancora letta dal programma locale: valore di partenza',
  provider: 'quella del servizio',
};

/** 12345 → "12,3k" · 1048576 → "1,05M" */
export function tokens(n: number | undefined | null): string {
  const v = Number(n || 0);
  if (v >= 1_000_000) return `${(v / 1_000_000).toLocaleString('it-IT', { maximumFractionDigits: 2 })}M`;
  if (v >= 1000) return `${(v / 1000).toLocaleString('it-IT', { maximumFractionDigits: 1 })}k`;
  return String(v);
}

/**
 * <hx-chat-context /> — chat header gauge: how full the context window of the provider in use is
 * for THIS conversation, and what the conversation consumed (Oracle /api/chat/context via WebUI).
 * Refreshed when an answer ends and when the conversation changes.
 */
@Component({
  selector: 'hx-chat-context',
  imports: [ButtonComponent, IconComponent, PopoverComponent, SettingLinkComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <button class="gauge" [class.warn]="pct() >= 70" [class.full]="pct() >= 90" (click)="toggle($event)"
            [title]="stats() ? 'Contesto: ' + pct() + '% di ' + fmt(stats()!.context_window) + ' token' : 'Contesto'"
            aria-label="Contesto e consumi">
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
        <circle cx="10" cy="10" r="8" class="bg" />
        <circle cx="10" cy="10" r="8" class="fg" [attr.stroke-dasharray]="dash()" transform="rotate(-90 10 10)" />
      </svg>
      <span>{{ stats() ? pct() + '%' : '—' }}</span>
    </button>
    <hx-popover [open]="open()" [anchor]="anchor()" [width]="340" (closed)="open.set(false)">
      <div class="pop">
        @if (stats(); as s) {
          @if (s.active; as a) {
            <div class="prov">
              <b>{{ a.provider_label }}</b><span class="model">{{ a.model }}</span>
              <span class="hx-grow"></span>
              <hx-setting-link module="oracle" title="Cambia il modello che risponde" (go)="open.set(false)" />
              @if (a.billing) { <span class="bill">{{ a.billing }}</span> }
            </div>
          }
          <div class="sec">
            <div class="row"><span>Contesto</span><b>{{ fmt(s.context_used_tokens) }} / {{ fmt(s.context_window) }} · {{ pct() }}%</b></div>
            <div class="bar" role="img" [attr.aria-label]="'Contesto usato: ' + pct() + '%'">
              @for (p of parts(); track p.id) { <i [attr.data-part]="p.id" [style.width.%]="p.share" [title]="p.label + ': ' + fmt(p.tokens)"></i> }
            </div>
            <div class="note win">
              <span>Finestra: {{ windowSource() }}</span>
              @if (s.window_setting_key) { <hx-setting-link [key]="s.window_setting_key" title="Cambia la finestra di contesto" (go)="open.set(false)" /> }
            </div>
            @if (s.over_window) {
              <div class="over"><hx-icon name="alert" [size]="14" />
                <span>Il prompt è più grande della finestra: il modello ne perde una parte. Alza la finestra nel programma locale, oppure compatta.</span></div>
            }
            <div class="grid legend">
              @for (p of parts(); track p.id) {
                <span><i class="dot" [attr.data-part]="p.id"></i>{{ p.label }}@if (p.id === 'history') { · {{ s.history_messages }} msg }</span><span>{{ fmt(p.tokens) }}</span>
              }
              <span><i class="dot" data-part="free"></i>Spazio libero</span><span>{{ fmt(free()) }}</span>
            </div>
            <div class="note">{{ measureNote() }}</div>
          </div>
          <div class="sec">
            <div class="row"><span>Consumo di questa conversazione</span></div>
            @if (s.session_usage?.calls) {
              <div class="grid">
                <span>Chiamate al modello</span><span>{{ s.session_usage!.calls }}</span>
                <span>Token in ingresso</span><span>{{ fmt(s.session_usage!.input_tokens) }}</span>
                <span>· di cui dalla cache</span><span>{{ fmt(s.session_usage!.cached_tokens) }} ({{ cachePct() }}%)</span>
                <span>Token generati</span><span>{{ fmt(s.session_usage!.output_tokens) }}</span>
                @if (s.session_usage!.cost_usd) {
                  <span>{{ s.active?.provider === 'claude_cli' ? 'Equivalente API' : 'Costo' }}</span><span>$ {{ s.session_usage!.cost_usd!.toFixed(4) }}</span>
                }
              </div>
              @if (models().length > 1 || (models().length === 1 && models()[0].estimated)) {
                <div class="models">
                  @for (m of models(); track m.provider + m.model) {
                    <div class="mrow"><span class="model">{{ m.model }}</span>
                      <span>{{ m.calls === 1 ? '1 chiamata' : m.calls + ' chiamate' }} · {{ fmt(m.input_tokens) }}@if (m.estimated) { <em title="Il programma locale non dice quanto prompt ha riusato: ingresso e cache sono calcolati dalla lunghezza del testo"> stimati</em> }</span></div>
                  }
                </div>
              }
            } @else {
              <div class="note">Ancora nessuna chiamata registrata dall'ultimo riavvio.</div>
            }
          </div>
          <div class="acts">
            <button hx-btn size="sm" variant="ghost" icon="refresh" (click)="load()">Aggiorna</button>
            <button hx-btn size="sm" [disabled]="!s.compaction_available || compacting()" (click)="compact()"
                    title="Riassume i messaggi più vecchi e libera contesto">{{ compacting() ? 'Compatto…' : 'Compatta' }}</button>
          </div>
        } @else {
          <div class="note">{{ error() || 'Carico…' }}</div>
        }
      </div>
    </hx-popover>`,
  styles: [`
    :host { display: inline-flex; }
    .gauge { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 8px; border-radius: var(--radius-full); font-size: 12.5px; color: var(--text-3); }
    .gauge:hover { background: var(--surface-2); color: var(--text-2); }
    .bg { fill: none; stroke: var(--border-strong); stroke-width: 2.5; }
    .fg { fill: none; stroke: var(--accent); stroke-width: 2.5; stroke-linecap: round; transition: stroke-dasharray var(--dur); }
    .gauge.warn .fg { stroke: var(--warning); }
    .gauge.full .fg { stroke: var(--danger); }
    .pop { padding: 12px 14px; display: flex; flex-direction: column; gap: 12px; font-size: 13px; }
    .prov { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; }
    .prov b { font-weight: 600; }
    .model { color: var(--text-2); font-family: var(--font-mono); font-size: 12px; }
    .bill { width: 100%; font-size: 12px; color: var(--text-3); }
    .hx-grow { flex: 1; }
    .sec { display: flex; flex-direction: column; gap: 6px; }
    .row { display: flex; justify-content: space-between; gap: 8px; color: var(--text-2); }
    .row b { font-weight: 600; color: var(--text); }
    .bar { display: flex; height: 8px; border-radius: 4px; background: var(--surface-2); overflow: hidden; }
    .bar i { display: block; height: 100%; min-width: 2px; }
    [data-part=system] { background: var(--info); }
    [data-part=tools] { background: var(--accent); }
    [data-part=history] { background: var(--success); }
    [data-part=message] { background: var(--warning); }
    [data-part=results] { background: color-mix(in srgb, var(--accent) 45%, var(--info)); }
    [data-part=other] { background: var(--text-3); }
    [data-part=free] { background: var(--surface-3, var(--surface-2)); box-shadow: inset 0 0 0 1px var(--border-strong); }
    .dot { display: inline-block; width: 8px; height: 8px; border-radius: 2px; margin-right: 6px; }
    .legend span:nth-child(odd) { display: flex; align-items: center; }
    .win { display: flex; align-items: center; justify-content: space-between; gap: 6px; }
    .over { display: flex; gap: 6px; align-items: flex-start; padding: 7px 9px; border-radius: var(--radius-sm);
            background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--text); font-size: 12px; line-height: 1.35; }
    .over hx-icon { color: var(--danger); flex-shrink: 0; margin-top: 1px; }
    .models { display: flex; flex-direction: column; gap: 3px; padding-top: 5px; border-top: 1px solid var(--border); font-size: 12px; color: var(--text-2); }
    .mrow { display: flex; justify-content: space-between; gap: 8px; }
    .mrow em { font-style: normal; color: var(--text-3); }
    .grid { display: grid; grid-template-columns: 1fr auto; gap: 3px 12px; color: var(--text-2); font-size: 12.5px; }
    .grid span:nth-child(even) { text-align: right; color: var(--text); font-variant-numeric: tabular-nums; }
    .note { font-size: 11.5px; color: var(--text-3); }
    .acts { display: flex; justify-content: flex-end; gap: 6px; }
  `],
})
export class ChatContextComponent {
  private http = inject(HttpClient);
  private chat = inject(ChatService);
  private session = inject(SessionService);
  private toast = inject(ToastService);

  readonly stats = signal<ContextStats | null>(null);
  readonly error = signal('');
  readonly open = signal(false);
  readonly compacting = signal(false);
  readonly anchor = signal<{ x: number; y: number; width: number; height: number } | null>(null);
  readonly pct = computed(() => Math.round(Math.min(100, this.stats()?.context_used_pct ?? 0)));
  readonly dash = computed(() => { const c = 2 * Math.PI * 8; return `${(c * this.pct()) / 100} ${c}`; });
  readonly cachePct = computed(() => {
    const u = this.stats()?.session_usage;
    return u?.input_tokens ? Math.round((100 * (u.cached_tokens || 0)) / u.input_tokens) : 0;
  });
  /** Parts of the last prompt with their share of the WINDOW (the bar's free rest is the space left). */
  readonly parts = computed(() => {
    const s = this.stats();
    const win = Math.max(1, s?.context_window ?? 1);
    const rows = (s?.breakdown ?? []).filter(p => p.tokens > 0);
    const used = rows.reduce((n, p) => n + p.tokens, 0);
    const scale = used > win ? win / used : 1;             // over the window: the bar is full, never wider
    return rows.map(p => ({ ...p, share: (100 * p.tokens * scale) / win }));
  });
  readonly free = computed(() => Math.max(0, (this.stats()?.context_window ?? 0) - (this.stats()?.context_used_tokens ?? 0)));
  readonly windowSource = computed(() => WINDOW_SOURCE[this.stats()?.window_source ?? ''] ?? WINDOW_SOURCE['provider']);
  readonly measureNote = computed(() => {
    const s = this.stats();
    if (!s?.context_measured) return 'Stima: nessuna chiamata misurata ancora.';
    return s.breakdown_measured ? 'Misurato sull’ultima chiamata al modello.' : 'Totale misurato; la ripartizione è una stima.';
  });
  readonly models = computed(() => this.stats()?.session_usage?.by_model ?? []);
  readonly fmt = tokens;

  private wasStreaming = false;

  constructor() {
    effect(() => { this.session.sessionId(); untracked(() => void this.load()); });
    effect(() => {   // an answer just ended → new numbers
      const streaming = this.chat.isStreaming();
      if (this.wasStreaming && !streaming) untracked(() => void this.load());
      this.wasStreaming = streaming;
    });
  }

  async load() {
    try {
      this.stats.set(await firstValueFrom(this.http.get<ContextStats>('/api/webui/chat/context')));
      this.error.set('');
    } catch {
      this.error.set('Contesto non disponibile ora.');
    }
  }

  toggle(e: MouseEvent) {
    e.stopPropagation();
    if (this.open()) { this.open.set(false); return; }
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    this.anchor.set({ x: r.left, y: r.top, width: r.width, height: r.height });
    this.open.set(true);
    void this.load();
  }

  async compact() {
    this.compacting.set(true);
    try {
      await firstValueFrom(this.http.post('/api/webui/chat/compact', {}));
      this.toast.success('Conversazione compattata');
      await this.load();
    } catch {
      this.toast.error('Compattazione non riuscita');
    } finally {
      this.compacting.set(false);
    }
  }
}
