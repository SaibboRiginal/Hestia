import { ChangeDetectionStrategy, Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ChatService } from '../../services/chat.service';
import { SessionService } from '../../services/session.service';
import { ButtonComponent, PopoverComponent, ToastService } from '../../ui';

interface SessionUsage {
  calls?: number; input_tokens?: number; cached_tokens?: number; output_tokens?: number;
  cost_usd?: number; estimated?: boolean; last_prompt_tokens?: number; provider?: string; model?: string;
}
interface ContextStats {
  context_window: number;
  context_used_tokens: number;
  context_used_pct: number;
  context_measured: boolean;
  history_messages: number;
  history_tokens_est: number;
  tool_tokens_est: number;
  preference_tokens_est: number;
  system_overhead_tokens_est: number;
  compaction_available: boolean;
  active?: { provider: string; provider_label: string; model: string; billing: string; context_window: number };
  session_usage?: SessionUsage;
}

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
  imports: [ButtonComponent, PopoverComponent],
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
    <hx-popover [open]="open()" [anchor]="anchor()" [width]="330" (closed)="open.set(false)">
      <div class="pop">
        @if (stats(); as s) {
          @if (s.active; as a) {
            <div class="prov">
              <b>{{ a.provider_label }}</b><span class="model">{{ a.model }}</span>
              @if (a.billing) { <span class="bill">{{ a.billing }}</span> }
            </div>
          }
          <div class="sec">
            <div class="row"><span>Contesto</span><b>{{ fmt(s.context_used_tokens) }} / {{ fmt(s.context_window) }} · {{ pct() }}%</b></div>
            <div class="bar"><i [style.width.%]="pct()" [class.warn]="pct() >= 70" [class.full]="pct() >= 90"></i></div>
            <div class="note">{{ s.context_measured ? 'Misurato sull\\'ultima chiamata al modello' : 'Stima (nessuna chiamata misurata ancora)' }}</div>
            <div class="grid">
              <span>Cronologia · {{ s.history_messages }} msg</span><span>{{ fmt(s.history_tokens_est) }}</span>
              <span>Strumenti</span><span>{{ fmt(s.tool_tokens_est) }}</span>
              <span>Preferenze</span><span>{{ fmt(s.preference_tokens_est) }}</span>
              <span>Istruzioni di sistema</span><span>{{ fmt(s.system_overhead_tokens_est) }}</span>
            </div>
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
              @if (s.session_usage!.estimated) { <div class="note">Ollama: cache e ingresso stimati dalla lunghezza del prompt.</div> }
            } @else {
              <div class="note">Ancora nessuna chiamata registrata (dal riavvio di Oracle).</div>
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
    .sec { display: flex; flex-direction: column; gap: 6px; }
    .row { display: flex; justify-content: space-between; gap: 8px; color: var(--text-2); }
    .row b { font-weight: 600; color: var(--text); }
    .bar { height: 6px; border-radius: 3px; background: var(--surface-2); overflow: hidden; }
    .bar i { display: block; height: 100%; background: var(--accent); }
    .bar i.warn { background: var(--warning); }
    .bar i.full { background: var(--danger); }
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
      this.error.set('Contesto non disponibile (Oracle non raggiungibile).');
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
