import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { UI, DialogService, ToastService } from '../../ui';
import { setupError } from '../setup/setup.api';

export interface MachineNode {
  id: string; name: string; role: string; address: string; joined_at: number; last_seen: number | null;
  online: boolean; modules: { name: string; online: boolean }[];
}
interface MachinesState {
  this: { role: string; hardware: { os?: string; gpu?: string; vram_gb?: number; ram_gb?: number; lan_ip?: string } };
  nodes: MachineNode[];
  brain_on: string;
}
interface Pairing { code: string; expires_in: number; central: string; }

const ROLE: Record<string, string> = {
  tutto: 'Fa tutto da sola', centrale: 'Casa centrale, sempre accesa', satellite: 'Satellite',
};
/** What a satellite does for you, in plain words (user texts never name modules). */
const JOB: Record<string, string> = { echo: 'voce', metis: 'allenamento dei modelli' };
const SCRIPT = 'https://raw.githubusercontent.com/SaibboRiginal/Hestia/main';

/**
 * «Macchine» (docs/work/2026-10-30-setup-un-click §4.0): the central home and its satellites. Link a machine with a
 * one-time code (the satellite's installer sends it), unlink it, and let the brain's local models run on its video
 * card. Browser → WebUI → Hub → Hephaestus /api/setup/machines* (→ Hub /api/nodes, Oracle /api/llm/setup/machine).
 */
@Component({
  selector: 'app-machines-page',
  imports: [...UI],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Macchine" subtitle="La casa centrale e i computer che lavorano con lei: voce e modelli dove c'è la scheda video">
      <button hx-btn size="sm" icon="link" [loading]="busy() === 'pair'" (click)="pair()" title="Collega una macchina"><span class="lbl">Collega una macchina</span></button>
    </hx-page-header>
    <div class="body">
      @if (error()) {
        <hx-empty icon="offline" title="Non riesco a leggere le macchine">{{ error() }}</hx-empty>
      } @else if (!state()) {
        <div class="center"><hx-spinner /></div>
      } @else {
        @if (pairing(); as p) {
          <section class="pair hx-card">
            <div class="code-line">
              <span class="code">{{ p.code }}</span>
              <span class="ttl">vale {{ minutesLeft() }} min, una volta sola</span>
              <button hx-btn size="sm" variant="ghost" icon="x" iconOnly aria-label="Chiudi" title="Chiudi" (click)="pairing.set(null)"></button>
            </div>
            <p>Sul computer da collegare, nella stessa rete di casa, apri il terminale e incolla:</p>
            <div class="cmd"><span class="os">Windows (PowerShell)</span><code>{{ windowsCmd() }}</code>
              <button hx-btn size="sm" variant="ghost" icon="copy" iconOnly aria-label="Copia" title="Copia" (click)="copy(windowsCmd())"></button></div>
            <div class="cmd"><span class="os">Linux</span><code>{{ linuxCmd() }}</code>
              <button hx-btn size="sm" variant="ghost" icon="copy" iconOnly aria-label="Copia" title="Copia" (click)="copy(linuxCmd())"></button></div>
            @if (!p.central) {
              <p class="warn"><hx-icon name="alert" [size]="14" tone="warning" /> Non conosco l'indirizzo di questa macchina in casa: sostituisci <b>{{ central() }}</b> con il suo indirizzo (es. 192.168.1.10).</p>
            }
            <p class="hint">Installa quello che serve e si collega da solo: qui compare appena è pronto.</p>
          </section>
        }

        <ul class="list">
          <li class="row hx-card">
            <hx-icon name="home" [size]="20" tone="accent" />
            <div class="main">
              <div class="top"><b>Questa macchina</b><span class="tag">{{ role(state()!.this.role) }}</span></div>
              <div class="sub">{{ hardware() }}</div>
            </div>
            <div class="acts">
              @if (state()!.brain_on) {
                <button hx-btn size="sm" variant="ghost" icon="brain" [loading]="busy() === 'brain:'" (click)="brain('', '')">Riporta qui i modelli</button>
              } @else { <span class="using"><hx-icon name="brain" [size]="14" /> modelli locali qui</span> }
            </div>
          </li>
          @for (n of state()!.nodes; track n.id) {
            <li class="row hx-card">
              <hx-icon name="host" [size]="20" [tone]="n.online ? 'success' : 'muted'" />
              <div class="main">
                <div class="top"><b>{{ n.name }}</b><span class="tag">{{ n.address }}</span>
                  @if (!n.online) { <hx-badge tone="warning">spenta o non raggiungibile</hx-badge> }</div>
                <div class="sub">{{ jobs(n) }}</div>
              </div>
              <div class="acts">
                @if (state()!.brain_on === n.address) {
                  <span class="using"><hx-icon name="brain" [size]="14" tone="accent" /> modelli locali qui</span>
                } @else {
                  <button hx-btn size="sm" variant="ghost" icon="brain" [loading]="busy() === 'brain:' + n.address" (click)="brain(n.address, n.name)">Usa la sua scheda video</button>
                }
                <button hx-btn size="sm" variant="ghost" icon="x" [loading]="busy() === 'revoke:' + n.id" (click)="revoke(n)">Scollega</button>
              </div>
            </li>
          }
        </ul>
        @if (!state()!.nodes.length && !pairing()) {
          <p class="note">Hestia gira tutta qui. Se hai un altro computer con una buona scheda video, collegalo: voce e modelli
            locali girano lì, il resto (memoria, impostazioni, questa pagina) resta su questa macchina sempre accesa.</p>
        }
      }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    .body { flex: 1; overflow: auto; padding: 18px 24px 32px; display: flex; flex-direction: column; gap: 12px; }
    .center { display: grid; place-items: center; padding: 40px; }
    .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; max-width: 860px; }
    .row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; }
    .main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
    .top { display: flex; align-items: baseline; gap: 8px; min-width: 0; flex-wrap: wrap; }
    .top b { font-weight: 600; font-size: 14px; }
    .tag, .sub { font-size: 12.5px; color: var(--text-3); }
    .acts { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
    .using { display: inline-flex; gap: 5px; align-items: center; font-size: 12.5px; color: var(--text-2); padding: 0 8px; }
    .pair { max-width: 860px; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
    .pair p { margin: 0; font-size: 13px; color: var(--text-2); }
    .code-line { display: flex; align-items: center; gap: 12px; }
    .code { font: 600 26px/1 var(--font-mono, monospace); letter-spacing: 4px; }
    .ttl { flex: 1; font-size: 12.5px; color: var(--text-3); }
    .cmd { display: flex; align-items: center; gap: 8px; background: var(--surface-2); border-radius: var(--radius); padding: 6px 8px; }
    .cmd .os { font-size: 11.5px; color: var(--text-3); width: 130px; flex-shrink: 0; }
    .cmd code { flex: 1; min-width: 0; font-size: 12px; overflow-x: auto; white-space: nowrap; }
    .warn, .note { display: flex; gap: 6px; align-items: flex-start; font-size: 12.5px; color: var(--text-3); max-width: 860px; }
    .hint { font-size: 12.5px !important; color: var(--text-3) !important; }
    @media (max-width: 720px) { .body { padding: 14px 12px 28px; } .row { flex-wrap: wrap; } .acts { width: 100%; justify-content: flex-end; }
      .cmd { flex-wrap: wrap; } .cmd .os { width: 100%; } }
    @media (max-width: 860px) { hx-page-header { padding-left: 56px; } }
    @media (max-width: 520px) { .lbl { display: none; } }
  `],
})
export class MachinesPageComponent {
  private http = inject(HttpClient);
  private dialogs = inject(DialogService);
  private toasts = inject(ToastService);
  state = signal<MachinesState | null>(null);
  error = signal('');
  busy = signal('');
  pairing = signal<Pairing | null>(null);
  private pairedAt = 0;
  private now = signal(Date.now());

  central = computed(() => {
    const p = this.pairing();
    const host = location.hostname;
    return p?.central || (host && host !== 'localhost' && host !== '127.0.0.1' ? host : 'INDIRIZZO');
  });
  windowsCmd = computed(() =>
    `& ([scriptblock]::Create((irm ${SCRIPT}/install.ps1))) -Join ${this.pairing()?.code} -Central ${this.central()}`);
  linuxCmd = computed(() => `curl -fsSL ${SCRIPT}/install.sh | bash -s -- --join ${this.pairing()?.code} --central ${this.central()}`);
  minutesLeft = computed(() => {
    const p = this.pairing();
    if (!p) return 0;
    return Math.max(0, Math.ceil((p.expires_in * 1000 - (this.now() - this.pairedAt)) / 60000));
  });

  constructor() {
    void this.load();
    // Faster while a code waits for its machine, calm otherwise.
    let tick = 0;
    const timer = setInterval(() => {
      tick++;
      this.now.set(Date.now());
      if (this.pairing() && !this.minutesLeft()) this.pairing.set(null);
      if (this.pairing() || tick % 6 === 0) void this.load();
    }, 5000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  async load() {
    try {
      const before = new Set((this.state()?.nodes || []).map(n => n.id));
      const s = await firstValueFrom(this.http.get<MachinesState>('/api/webui/setup/machines'));
      const fresh = (s.nodes || []).find(n => !before.has(n.id));
      if (fresh && this.pairing() && this.state()) {
        this.pairing.set(null);
        this.toasts.success(`${fresh.name} è collegata.`);
      }
      this.state.set({ ...s, nodes: s.nodes || [] });
      this.error.set('');
    } catch (e: any) {
      if (!this.state()) this.error.set(setupError(e));
    }
  }

  role(r: string) { return ROLE[r] || ROLE['tutto']; }

  hardware(): string {
    const h = this.state()?.this.hardware || {};
    const parts: string[] = [];
    if (h.gpu) parts.push(h.vram_gb ? `${h.gpu}, ${h.vram_gb} GB` : h.gpu);
    else parts.push('nessuna scheda video dedicata');
    if (h.ram_gb) parts.push(`${h.ram_gb} GB di RAM`);
    if (h.lan_ip) parts.push(h.lan_ip);
    return parts.join(' · ');
  }

  jobs(n: MachineNode): string {
    const names = n.modules.filter(m => m.online).map(m => JOB[m.name] || 'altro');
    if (!names.length) return n.online ? 'collegata' : 'non lavora ora: riaccendila e torna da sola';
    return 'Qui: ' + [...new Set(names)].join(', ');
  }

  async pair() {
    this.busy.set('pair');
    try {
      const p = await firstValueFrom(this.http.post<Pairing>('/api/webui/setup/machines/pair', {}));
      this.pairedAt = Date.now();
      this.now.set(this.pairedAt);
      this.pairing.set(p);
    } catch (e: any) {
      this.toasts.error(setupError(e));
    } finally {
      this.busy.set('');
    }
  }

  async copy(text: string) {
    try { await navigator.clipboard.writeText(text); this.toasts.success('Copiato'); } catch { /* no clipboard: select by hand */ }
  }

  async brain(address: string, name: string) {
    this.busy.set('brain:' + address);
    try {
      const r = await firstValueFrom(this.http.post<{ detail?: string }>('/api/webui/setup/machines/brain', { address, name }));
      this.toasts.success(r.detail || 'Fatto.');
    } catch (e: any) {
      this.toasts.error(setupError(e));
    } finally {
      this.busy.set('');
    }
    await this.load();
  }

  async revoke(n: MachineNode) {
    const using = this.state()?.brain_on === n.address;
    const text = using
      ? 'I modelli locali tornano su questa macchina. Per ricollegarla serve un codice nuovo.'
      : 'Smette di lavorare per Hestia. Per ricollegarla serve un codice nuovo.';
    if (!await this.dialogs.confirm(`Scollegare ${n.name}?`, text, 'Scollega', true)) return;
    this.busy.set('revoke:' + n.id);
    try {
      if (using) await firstValueFrom(this.http.post('/api/webui/setup/machines/brain', { address: '', name: '' }));
      await firstValueFrom(this.http.post('/api/webui/setup/machines/revoke', { id: n.id }));
      this.toasts.success(`${n.name} è scollegata.`);
    } catch (e: any) {
      this.toasts.error(setupError(e));
    } finally {
      this.busy.set('');
    }
    await this.load();
  }
}
