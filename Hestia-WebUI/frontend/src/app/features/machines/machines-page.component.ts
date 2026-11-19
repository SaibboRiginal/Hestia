import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { UI, DialogService, ToastService } from '../../ui';
import { TunnelState, setupError } from '../setup/setup.api';
import { tr, TrPipe } from '../../core/i18n';

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
  tutto: tr('Does everything by herself'), centrale: tr('Central home, always on'), satellite: tr('Satellite'),
};
/** What a satellite does for you, in plain words (user texts never name modules). */
const JOB: Record<string, string> = { echo: tr('voice'), metis: tr('model training') };
const SCRIPT = 'https://raw.githubusercontent.com/SaibboRiginal/Hestia/main';

/**
 * «Macchine» (docs/work/2026-10-30-one-click-setup §4.0): the central home and its satellites. Link a machine with a
 * one-time code (the satellite's installer sends it), unlink it, and let the brain's local models run on its video
 * card. Browser → WebUI → Hub → Hephaestus /api/setup/machines* (→ Hub /api/nodes, Oracle /api/llm/setup/machine).
 */
@Component({
  selector: 'app-machines-page',
  imports: [TrPipe, ...UI],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header  [title]="'Machines' | tr"  [subtitle]="'The central home and the computers that work with it: voice and models where the graphics card is' | tr">
      <button hx-btn size="sm" icon="link" [loading]="busy() === 'pair'" (click)="pair()"  [title]="'Link a machine' | tr"><span class="lbl">{{ "Link a machine" | tr }}</span></button>
    </hx-page-header>
    <div class="body">
      @if (error()) {
        <hx-empty icon="offline"  [title]="'I can\\'t read the machines' | tr">{{ error() }}</hx-empty>
      } @else if (!state()) {
        <div class="center"><hx-spinner /></div>
      } @else {
        @if (pairing(); as p) {
          <section class="pair hx-card">
            <div class="code-line">
              <span class="code">{{ p.code }}</span>
              <span class="ttl">{{ "is worth" | tr }} {{ minutesLeft() }} {{ "min, only once" | tr }}</span>
              <button hx-btn size="sm" variant="ghost" icon="x" iconOnly  [attr.aria-label]="'Close' | tr"  [title]="'Close' | tr" (click)="pairing.set(null)"></button>
            </div>
            <p>{{ "On the computer to link, on the same home network, open the terminal and paste:" | tr }}</p>
            <div class="cmd"><span class="os">Windows (PowerShell)</span><code>{{ windowsCmd() }}</code>
              <button hx-btn size="sm" variant="ghost" icon="copy" iconOnly  [attr.aria-label]="'Copy' | tr"  [title]="'Copy' | tr" (click)="copy(windowsCmd())"></button></div>
            <div class="cmd"><span class="os">Linux</span><code>{{ linuxCmd() }}</code>
              <button hx-btn size="sm" variant="ghost" icon="copy" iconOnly  [attr.aria-label]="'Copy' | tr"  [title]="'Copy' | tr" (click)="copy(linuxCmd())"></button></div>
            @if (!p.central) {
              <p class="warn"><hx-icon name="alert" [size]="14" tone="warning" /> {{ "I don't know the home address of this machine: replace" | tr }} <b>{{ central() }}</b> {{ "with its address (e.g. 192.168.1.10)." | tr }}</p>
            }
            <p class="hint">{{ "It installs what is needed and links by itself: it appears here as soon as it's ready." | tr }}</p>
          </section>
        }

        <ul class="list">
          <li class="row hx-card">
            <hx-icon name="home" [size]="20" tone="accent" />
            <div class="main">
              <div class="top"><b>{{ "This machine" | tr }}</b><span class="tag">{{ role(state()!.this.role) }}</span></div>
              <div class="sub">{{ hardware() }}</div>
            </div>
            <div class="acts">
              @if (state()!.brain_on) {
                <button hx-btn size="sm" variant="ghost" icon="brain" [loading]="busy() === 'brain:'" (click)="brain('', '')">{{ "Bring the models back here" | tr }}</button>
              } @else { <span class="using"><hx-icon name="brain" [size]="14" /> {{ "local models here" | tr }}</span> }
            </div>
          </li>
          @for (n of state()!.nodes; track n.id) {
            <li class="row hx-card">
              <hx-icon name="host" [size]="20" [tone]="n.online ? 'success' : 'muted'" />
              <div class="main">
                <div class="top"><b>{{ n.name }}</b><span class="tag">{{ n.address }}</span>
                  @if (!n.online) { <hx-badge tone="warning">{{ "off or unreachable" | tr }}</hx-badge> }</div>
                <div class="sub">{{ jobs(n) }}</div>
              </div>
              <div class="acts">
                @if (state()!.brain_on === n.address) {
                  <span class="using"><hx-icon name="brain" [size]="14" tone="accent" /> {{ "local models here" | tr }}</span>
                } @else {
                  <button hx-btn size="sm" variant="ghost" icon="brain" [loading]="busy() === 'brain:' + n.address" (click)="brain(n.address, n.name)">{{ "Use its graphics card" | tr }}</button>
                }
                <button hx-btn size="sm" variant="ghost" icon="x" [loading]="busy() === 'revoke:' + n.id" (click)="revoke(n)">{{ "Unlink" | tr }}</button>
              </div>
            </li>
          }
        </ul>
        <section class="row hx-card outside">
          <hx-icon name="cloud" [size]="20" [tone]="tunnel()?.on ? 'success' : 'muted'" />
          <div class="main">
            <div class="top"><b>{{ "From outside home" | tr }}</b>
              @if (tunnel()?.on) { <span class="tag">{{ "active" | tr }}</span> } @else { <span class="tag">{{ "only at home and from Telegram" | tr }}</span> }</div>
            <div class="sub">
              @if (tunnel()?.on && tunnel()!.url) { <a [href]="tunnel()!.url" target="_blank" rel="noopener">{{ tunnel()!.url }}</a> {{ "· always asks for access; changes at every restart" | tr }}
              } @else if (tunnel()?.on) { {{ "The address appears shortly." | tr }}
              } @else { {{ "A secure address (Cloudflare, free) to open {assistant} from your phone when you are out." | tr }} }
            </div>
          </div>
          <div class="acts">
            <button hx-btn size="sm" [variant]="tunnel()?.on ? 'ghost' : 'primary'" [icon]="tunnel()?.on ? 'x' : 'cloud'"
                    [loading]="busy() === 'tunnel'" (click)="switchTunnel(!tunnel()?.on)">{{ tunnel()?.on ? ('Turn off' | tr) : ('f::Active' | tr) }}</button>
          </div>
        </section>
        @if (!state()!.nodes.length && !pairing()) {
          <p class="note">{{ "{assistant} runs entirely here. If you have another computer with a good graphics card, link it: voice and local models run there, the rest (memory, settings, this page) stays on this always-on machine." | tr }}</p>
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
    .outside { max-width: 860px; }
    .outside a { color: var(--accent); overflow-wrap: anywhere; }
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
  tunnel = signal<TunnelState | null>(null);
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
        this.toasts.success(tr("{0} is linked.", fresh.name));
      }
      this.state.set({ ...s, nodes: s.nodes || [] });
      this.error.set('');
      this.http.get<TunnelState>('/api/webui/setup/tunnel').subscribe({ next: t => this.tunnel.set(t), error: () => undefined });
    } catch (e: any) {
      if (!this.state()) this.error.set(setupError(e));
    }
  }

  role(r: string) { return ROLE[r] || ROLE['tutto']; }

  hardware(): string {
    const h = this.state()?.this.hardware || {};
    const parts: string[] = [];
    if (h.gpu) parts.push(h.vram_gb ? `${h.gpu}, ${h.vram_gb} GB` : h.gpu);
    else parts.push(tr('no dedicated graphics card'));
    if (h.ram_gb) parts.push(tr("{0} GB of RAM", h.ram_gb));
    if (h.lan_ip) parts.push(h.lan_ip);
    return parts.join(' · ');
  }

  jobs(n: MachineNode): string {
    const names = n.modules.filter(m => m.online).map(m => JOB[m.name] || tr('other'));
    if (!names.length) return n.online ? tr('f::linked') : tr('not working now: turn it back on and it comes back by itself');
    return tr('Here: {0}', [...new Set(names)].join(', '));
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
    try { await navigator.clipboard.writeText(text); this.toasts.success(tr('Copied')); } catch { /* no clipboard: select by hand */ }
  }

  async brain(address: string, name: string) {
    this.busy.set('brain:' + address);
    try {
      const r = await firstValueFrom(this.http.post<{ detail?: string }>('/api/webui/setup/machines/brain', { address, name }));
      this.toasts.success(r.detail || tr('Done.'));
    } catch (e: any) {
      this.toasts.error(setupError(e));
    } finally {
      this.busy.set('');
    }
    await this.load();
  }

  async switchTunnel(on: boolean) {
    if (on && !await this.dialogs.confirm(tr('Open {assistant} from outside home?'),
      tr('{assistant} will have an address on the internet. From there it always asks for access; you can turn it off whenever you want.'), tr('f::Active'))) return;
    this.busy.set('tunnel');
    try {
      const t = await firstValueFrom(this.http.post<TunnelState>('/api/webui/setup/tunnel', { on }));
      this.tunnel.set(t);
      if (t.detail) this.toasts.success(t.detail);
    } catch (e: any) {
      this.toasts.error(setupError(e));
    } finally {
      this.busy.set('');
    }
  }

  async revoke(n: MachineNode) {
    const using = this.state()?.brain_on === n.address;
    const text = using
      ? tr('Local models go back to this machine. To link it again a new code is needed.')
      : tr('It stops working for {assistant}. To link it again a new code is needed.');
    if (!await this.dialogs.confirm(tr("Unlink {0}?", n.name), text, tr('Unlink'), true)) return;
    this.busy.set('revoke:' + n.id);
    try {
      if (using) await firstValueFrom(this.http.post('/api/webui/setup/machines/brain', { address: '', name: '' }));
      await firstValueFrom(this.http.post('/api/webui/setup/machines/revoke', { id: n.id }));
      this.toasts.success(tr("{0} is unlinked.", n.name));
    } catch (e: any) {
      this.toasts.error(setupError(e));
    } finally {
      this.busy.set('');
    }
    await this.load();
  }
}
