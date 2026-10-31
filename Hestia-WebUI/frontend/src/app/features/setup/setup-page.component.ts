import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { BrainCatalog, CloudProvider, Download, SetupApi, SetupState, setupError } from './setup.api';

type Screen = 'benvenuto' | 'ricetta' | 'locale' | 'cloud' | 'claude' | 'cervello' | 'telegram' | 'backup' | 'esterni' | 'pronto';
type Recipe = 'locale' | 'cloud' | 'entrambi' | 'claude';

const RECIPES: { id: Recipe; label: string; text: string; icon: string }[] = [
  { id: 'entrambi', label: 'Tutti e due', text: 'Prima il tuo computer; se è occupato o spento, il cloud.', icon: 'repeat' },
  { id: 'locale', label: 'Sul tuo computer', text: 'Privato e gratis. Serve una buona scheda video.', icon: 'host' },
  { id: 'cloud', label: 'Nel cloud', text: 'Veloce su ogni computer. Serve una chiave: quella di Gemini è gratis.', icon: 'zap' },
  { id: 'claude', label: 'Abbonamento Claude', text: 'Se hai già Claude Pro o Max.', icon: 'brain' },
];
/** Where to get a key, by provider type or name. */
const KEY_LINKS: Record<string, string> = {
  gemini: 'https://aistudio.google.com/apikey',
  deepseek: 'https://platform.deepseek.com/api_keys',
  anthropic: 'https://console.anthropic.com/settings/keys',
  openai: 'https://platform.openai.com/api-keys',
};
const SCREEN_KEY = 'hestia_setup_screen';

function stored(key: string): string {
  try { return localStorage.getItem(key) || ''; } catch { return ''; }
}
function store(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* private window: resume falls back to the first open step */ }
}

/**
 * Guided setup «Benvenuto» (docs/work/2026-10-30-setup-un-click §4.2): full screen, one question per screen, the
 * recommended answer preselected, «Più tardi» on the optional ones. Every answer is saved at once (server side), and
 * the screen is remembered, so closing the browser resumes where it was. Secrets go to Hephaestus and never come back.
 */
@Component({
  selector: 'app-setup-page',
  imports: [...UI, FormsModule, RouterLink, NgTemplateOutlet],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wrap">
      <div class="top">
        <div class="dots" aria-hidden="true">
          @for (s of screens(); track s; let i = $index) { <span [class.on]="i <= index()"></span> }
        </div>
        <a class="out" routerLink="/home" (click)="leave()">Finisco dopo</a>
      </div>

      <main class="card hx-card">
        @if (!state()) {
          <div class="center">
            @if (loadError()) {
              <hx-icon name="offline" [size]="28" tone="warning" />
              <p>{{ loadError() }}</p>
              <button hx-btn variant="primary" icon="refresh" (click)="load()">Riprova</button>
            } @else { <hx-spinner /> }
          </div>
        } @else {
          @switch (screen()) {
            @case ('benvenuto') {
              <hx-icon name="sparkle" [size]="34" tone="accent" />
              <h1>Ciao, sono Hestia</h1>
              <p class="lead">Ti preparo tutto in pochi passi. Ogni risposta si salva subito: puoi chiudere e riprendere quando vuoi.</p>
              <p class="hw"><hx-icon name="host" [size]="16" tone="muted" /> {{ hardwareText() }}</p>
            }

            @case ('ricetta') {
              <hx-icon name="brain" [size]="30" tone="accent" />
              <h1>Dove pensa Hestia?</h1>
              <p class="lead">Puoi cambiarlo quando vuoi da Impostazioni.</p>
              <div class="choices">
                @for (r of recipes; track r.id) {
                  <button type="button" class="choice" [class.sel]="recipe() === r.id" (click)="recipe.set(r.id)">
                    <hx-icon [name]="r.icon" [size]="20" [tone]="recipe() === r.id ? 'accent' : 'muted'" />
                    <span class="ct"><b>{{ r.label }}</b>@if (r.id === catalog()?.recommended?.recipe) { <span class="rec">Consigliato</span> }
                      <small>{{ r.text }}</small></span>
                  </button>
                }
              </div>
              @if (needsLocal() && catalog() && !catalog()!.ollama) {
                <p class="warn"><hx-icon name="alert" [size]="15" tone="warning" /> Ollama non risponde su questo computer: i modelli locali arrivano quando lo avvii.</p>
              }
            }

            @case ('locale') {
              <hx-icon name="host" [size]="30" tone="accent" />
              <h1>Quale modello sul tuo computer?</h1>
              <p class="lead">{{ catalog()?.recommended?.label }}. Lo scarico subito, mentre finisci il resto.</p>
              <div class="choices">
                @for (m of catalog()?.recommended?.chat || []; track m.model; let first = $first) {
                  <button type="button" class="choice" [class.sel]="localModel() === m.model" (click)="localModel.set(m.model)">
                    <hx-icon name="download" [size]="20" [tone]="localModel() === m.model ? 'accent' : 'muted'" />
                    <span class="ct"><b>{{ m.model }}</b>@if (first) { <span class="rec">Consigliato</span> }
                      <small>{{ m.good }} {{ installed(m.model) ? 'Già presente.' : gb(m.size_gb) + ' GB da scaricare.' }}</small></span>
                  </button>
                }
              </div>
            }

            @case ('cloud') {
              <hx-icon name="zap" [size]="30" tone="accent" />
              <h1>Quale servizio nel cloud?</h1>
              <div class="choices">
                @for (p of catalog()?.cloud || []; track p.name) {
                  <button type="button" class="choice" [class.sel]="provider() === p.name" (click)="pickProvider(p.name)">
                    <hx-icon [name]="p.key_set ? 'check-circle' : 'unlock'" [size]="20" [tone]="p.key_set ? 'success' : 'muted'" />
                    <span class="ct"><b>{{ p.label || p.name }}</b>@if (p.type === 'gemini') { <span class="rec">Gratis</span> }
                      <small>{{ p.key_set ? 'Chiave già inserita.' : 'Serve una chiave.' }}</small></span>
                  </button>
                } @empty { <p class="lead">Nessun servizio cloud configurato.</p> }
              </div>
              @if (providerInfo(); as p) {
                <hx-field [label]="'Chiave di ' + (p.label || p.name)" [error]="testError()"
                          [hint]="testOk() ? 'Funziona.' : (p.key_set ? 'Lascia vuoto per tenere quella che c\\'è.' : '')">
                  <input class="hx-input mono" type="password" autocomplete="off" [(ngModel)]="key" placeholder="incolla qui la chiave" />
                </hx-field>
                <div class="row">
                  @if (keyLink(p)) { <a hx-btn variant="ghost" icon="external" [href]="keyLink(p)" target="_blank" rel="noopener">Prendi la chiave</a> }
                  <button hx-btn variant="secondary" icon="play" [loading]="busy()" [disabled]="!key && !p.key_set" (click)="testKey()">Prova</button>
                </div>
              }
            }

            @case ('claude') {
              <hx-icon name="brain" [size]="30" tone="accent" />
              <h1>Collega il tuo abbonamento Claude</h1>
              <p class="lead">Nel terminale scrivi <code>claude setup-token</code>, accedi, poi incolla qui il codice che ti dà.</p>
              @if (state()!.claude.token) { <p class="ok"><hx-icon name="check-circle" [size]="16" tone="success" /> Codice già inserito: lascia vuoto per tenerlo.</p> }
              <hx-field label="Codice">
                <input class="hx-input mono" type="password" autocomplete="off" [(ngModel)]="claudeToken" placeholder="sk-ant-oat…" />
              </hx-field>
            }

            @case ('cervello') {
              <hx-icon name="check-circle" [size]="30" tone="success" />
              <h1>Il cervello è pronto</h1>
              <p class="lead">{{ state()!.brain.summary || 'Fatto.' }}</p>
              <ng-container *ngTemplateOutlet="downloadsTpl" />
            }

            @case ('telegram') {
              <hx-icon name="chat" [size]="30" tone="accent" />
              <h1>Parla con Hestia dal telefono</h1>
              @if (state()!.telegram.linked) {
                <p class="ok"><hx-icon name="check-circle" [size]="16" tone="success" /> Telegram è collegato: Hestia ti riconosce.</p>
              } @else if (code()) {
                <p class="lead">Apri il tuo bot su Telegram e scrivigli questo codice:</p>
                <div class="code mono">{{ code() }}</div>
                <p class="hint"><hx-spinner /> Aspetto il tuo messaggio… (vale 10 minuti)</p>
              } @else if (state()!.telegram.token) {
                <p class="lead">Il bot c'è: manca solo farti riconoscere.</p>
                <button hx-btn variant="primary" [loading]="busy()" (click)="newCode()">Mostra il codice</button>
              } @else {
                <p class="lead">Su Telegram apri <b>&#64;BotFather</b>, scrivi <code>/newbot</code>, scegli un nome e incolla qui il token che ti dà.</p>
                <hx-field label="Token del bot" [error]="formError()">
                  <input class="hx-input mono" type="password" autocomplete="off" [(ngModel)]="botToken" placeholder="123456789:AA…" />
                </hx-field>
              }
            }

            @case ('backup') {
              <hx-icon name="unlock" [size]="30" tone="accent" />
              <h1>Una parola d'ordine per i backup</h1>
              @if (state()!.backup.passphrase) {
                <p class="ok"><hx-icon name="check-circle" [size]="16" tone="success" /> Già impostata.</p>
              } @else {
                <p class="lead">I backup sono cifrati con questa frase. Salvala nel tuo password manager: senza, non si aprono.</p>
                <hx-field label="Frase (almeno 12 caratteri)" [error]="formError()">
                  <input class="hx-input mono" [type]="showPass() ? 'text' : 'password'" autocomplete="new-password" [(ngModel)]="passphrase" />
                </hx-field>
                <div class="row">
                  <button hx-btn variant="ghost" icon="sparkle" (click)="suggest()">Generane una</button>
                  <button hx-btn variant="ghost" icon="eye" (click)="showPass.set(!showPass())">{{ showPass() ? 'Nascondi' : 'Mostra' }}</button>
                </div>
              }
            }

            @case ('esterni') {
              <hx-icon name="link" [size]="30" tone="accent" />
              <h1>Calendario, mail e dispositivi</h1>
              <p class="lead">Si collegano quando ti servono, non adesso per forza.</p>
              <ul class="list">
                <li><hx-icon name="calendar" [size]="18" tone="info" /><span><b>Google Calendar e Gmail</b><small>Scrivi al bot «collega Google Calendar».</small></span></li>
                <li><hx-icon name="pulse" [size]="18" tone="success" /><span><b>Orologio Garmin e telefono</b><small><a routerLink="/p/hecate/dispositivi" (click)="leave()">Pagina Dispositivi</a></small></span></li>
              </ul>
            }

            @case ('pronto') {
              <hx-icon name="sparkle" [size]="30" tone="accent" />
              <h1>Quasi pronto</h1>
              <ul class="list">
                <li><hx-icon [name]="state()!.brain.recipe ? 'check-circle' : 'clock'" [size]="18" [tone]="state()!.brain.recipe ? 'success' : 'warning'" />
                  <span><b>Cervello</b><small>{{ state()!.brain.summary || 'Non ancora scelto.' }}</small></span></li>
                <li><hx-icon [name]="state()!.telegram.linked ? 'check-circle' : 'clock'" [size]="18" [tone]="state()!.telegram.linked ? 'success' : 'muted'" />
                  <span><b>Telegram</b><small>{{ state()!.telegram.linked ? 'Collegato.' : 'Più tardi.' }}</small></span></li>
                <li><hx-icon [name]="state()!.backup.passphrase ? 'check-circle' : 'clock'" [size]="18" [tone]="state()!.backup.passphrase ? 'success' : 'muted'" />
                  <span><b>Backup</b><small>{{ state()!.backup.passphrase ? 'Pronto.' : 'Più tardi.' }}</small></span></li>
              </ul>
              <ng-container *ngTemplateOutlet="downloadsTpl" />
            }
          }

          <ng-template #downloadsTpl>
            @if (downloads().length) {
              <ul class="list dl">
                @for (d of downloads(); track d.id) {
                  <li>
                    <hx-icon [name]="d.state === 'fatto' ? 'check-circle' : d.state === 'errore' ? 'alert' : 'download'" [size]="18"
                             [tone]="d.state === 'fatto' ? 'success' : d.state === 'errore' ? 'danger' : 'info'" />
                    <span><b>{{ d.what }}</b><small>{{ downloadText(d) }}</small>
                      @if (d.state === 'in_corso' && d.size) { <span class="bar"><span [style.width.%]="100 * d.done / d.size"></span></span> }
                    </span>
                  </li>
                }
              </ul>
            }
          </ng-template>

          <div class="nav">
            @if (index() > 0) { <button hx-btn variant="ghost" icon="chevron-left" (click)="back()">Indietro</button> }
            <span class="sp"></span>
            @if (optional()) { <button hx-btn variant="ghost" (click)="later()">Più tardi</button> }
            <button hx-btn variant="primary" size="lg" [loading]="busy()" [disabled]="!canNext()" (click)="next()">{{ nextLabel() }}</button>
          </div>
        }
      </main>
    </div>`,
  styles: [`
    :host { display: block; min-height: 100vh; background: var(--backdrop, var(--bg)); }
    .wrap { max-width: 560px; margin: 0 auto; padding: 18px 16px 32px; display: flex; flex-direction: column; gap: 14px; }
    .top { display: flex; align-items: center; gap: 12px; min-height: 32px; }
    .dots { flex: 1; display: flex; gap: 6px; }
    .dots span { width: 8px; height: 8px; border-radius: var(--radius-full); background: var(--surface-3); transition: background var(--dur) var(--ease); }
    .dots span.on { background: var(--accent); }
    .out { font-size: 13px; color: var(--text-3); }
    .card { padding: 28px 24px 20px; display: flex; flex-direction: column; gap: 14px; }
    .center { display: grid; place-items: center; gap: 12px; padding: 40px 0; text-align: center; color: var(--text-2); }
    h1 { font-family: var(--font-serif); font-weight: 500; font-size: 26px; line-height: 1.2; color: var(--text); }
    .lead { color: var(--text-2); font-size: 15px; line-height: 1.5; }
    .hw, .ok, .warn, .hint { display: flex; gap: 8px; align-items: center; font-size: 14px; color: var(--text-2); }
    code { font-family: var(--font-mono); font-size: 13px; background: var(--surface-2); padding: 1px 5px; border-radius: var(--radius-xs); }
    .choices { display: flex; flex-direction: column; gap: 8px; }
    .choice { display: flex; gap: 12px; align-items: flex-start; text-align: left; padding: 14px; border: 1px solid var(--border);
              border-radius: var(--radius-md); background: var(--surface); color: var(--text); min-height: var(--tap, 0px);
              transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease); }
    .choice:hover { border-color: var(--border-strong); }
    .choice.sel { border-color: var(--accent); background: var(--accent-soft); }
    .ct { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
    .ct b { font-weight: 600; font-size: 15px; }
    .ct small, .list small { color: var(--text-3); font-size: 13px; line-height: 1.4; }
    .rec { align-self: flex-start; font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .row { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .code { font-size: 38px; letter-spacing: .25em; text-align: center; padding: 14px; border-radius: var(--radius-md); background: var(--surface-2); color: var(--text); }
    .list { list-style: none; display: flex; flex-direction: column; gap: 12px; padding: 0; margin: 0; }
    .list li { display: flex; gap: 10px; align-items: flex-start; }
    .list li > span { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
    .list b { font-weight: 600; font-size: 14px; }
    .bar { display: block; height: 4px; border-radius: var(--radius-full); background: var(--surface-3); overflow: hidden; margin-top: 4px; }
    .bar span { display: block; height: 100%; background: var(--accent); transition: width var(--dur) var(--ease); }
    .nav { display: flex; align-items: center; gap: 8px; margin-top: 8px; padding-top: 14px; border-top: 1px solid var(--border); }
    .sp { flex: 1; }
    @media (max-width: 480px) { .card { padding: 22px 16px 16px; } h1 { font-size: 22px; } .code { font-size: 30px; } }
  `],
})
export class SetupPageComponent {
  private api = inject(SetupApi);
  private router = inject(Router);
  readonly recipes = RECIPES;

  state = signal<SetupState | null>(null);
  catalog = signal<BrainCatalog | null>(null);
  downloads = signal<Download[]>([]);
  loadError = signal('');
  busy = signal(false);
  formError = signal('');
  testOk = signal(false);
  testError = signal('');
  showPass = signal(false);
  code = signal('');

  recipe = signal<Recipe>('entrambi');
  localModel = signal('');
  provider = signal('');
  key = '';
  claudeToken = '';
  botToken = '';
  passphrase = '';

  screen = signal<Screen>('benvenuto');
  needsLocal = computed(() => this.recipe() === 'locale' || this.recipe() === 'entrambi');
  /** The screens of this run: the brain's sub-screens follow the recipe. */
  screens = computed<Screen[]>(() => {
    const r = this.recipe();
    return ['benvenuto', 'ricetta',
      ...(this.needsLocal() ? ['locale' as Screen] : []),
      ...(r === 'cloud' || r === 'entrambi' ? ['cloud' as Screen] : []),
      ...(r === 'claude' ? ['claude' as Screen] : []),
      'cervello', 'telegram', 'backup', 'esterni', 'pronto'];
  });
  index = computed(() => Math.max(0, this.screens().indexOf(this.screen())));
  optional = computed(() => ['telegram', 'backup'].includes(this.screen()) && !this.stepDone(this.screen()));
  providerInfo = computed(() => this.catalog()?.cloud.find(p => p.name === this.provider()) ?? null);

  constructor() {
    const timer = setInterval(() => this.poll(), 3000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
    void this.load();
  }

  async load() {
    this.loadError.set('');
    try {
      const [state, catalog] = await Promise.all([this.api.state(), this.api.catalog().catch(() => null)]);
      this.state.set(state);
      if (catalog) {
        this.catalog.set(catalog);
        this.recipe.set((state.brain.recipe || catalog.recommended.recipe || 'entrambi') as Recipe);
        this.localModel.set(state.brain.local_model || catalog.recommended.model);
        const cloud = catalog.cloud;
        this.provider.set(state.brain.cloud?.[0] || cloud.find(p => p.key_set)?.name
          || cloud.find(p => p.type === 'gemini')?.name || cloud[0]?.name || '');
      }
      const saved = stored(SCREEN_KEY) as Screen;
      this.screen.set(this.screens().includes(saved) ? saved : this.firstOpen(state));
      void this.refreshDownloads();
    } catch (e) {
      this.loadError.set(setupError(e));
    }
  }

  private firstOpen(s: SetupState): Screen {
    if (!s.brain.recipe) return 'benvenuto';
    for (const step of ['telegram', 'backup'] as Screen[]) if (!this.stepDone(step) && !s.later.includes(step)) return step;
    return 'pronto';
  }

  stepDone(step: Screen): boolean {
    const s = this.state();
    if (!s) return false;
    return step === 'telegram' ? s.telegram.linked : step === 'backup' ? s.backup.passphrase : false;
  }

  private go(screen: Screen) {
    this.formError.set('');
    this.screen.set(screen);
    store(SCREEN_KEY, screen);
  }

  back() { const list = this.screens(); this.go(list[Math.max(0, this.index() - 1)]); }
  private forward() { const list = this.screens(); this.go(list[Math.min(list.length - 1, this.index() + 1)]); }

  /** «Finisco dopo»: the Home shows a card to come back; the guard does not bring the browser here again this session. */
  leave() { try { sessionStorage.setItem('hestia_setup_seen', '1'); } catch { /* ignore */ } }

  canNext(): boolean {
    switch (this.screen()) {
      case 'cloud': return !!this.providerInfo() && (this.testOk() || (!this.key && !!this.providerInfo()!.key_set));
      case 'telegram': return this.state()!.telegram.linked || (!this.code() && !this.state()!.telegram.token && !!this.botToken.trim());
      case 'backup': return this.state()!.backup.passphrase || this.passphrase.length >= 12;
      default: return true;
    }
  }

  nextLabel(): string {
    switch (this.screen()) {
      case 'benvenuto': return 'Iniziamo';
      case 'locale': case 'claude': return this.screens()[this.index() + 1] === 'cervello' ? 'Conferma' : 'Avanti';
      case 'cloud': return 'Conferma';
      case 'telegram': return this.state()!.telegram.linked || this.code() || this.state()!.telegram.token ? 'Avanti' : 'Collega';
      case 'backup': return this.state()!.backup.passphrase ? 'Avanti' : 'Salva';
      case 'pronto': return 'Inizia';
      default: return 'Avanti';
    }
  }

  async next() {
    const screen = this.screen();
    const following = this.screens()[this.index() + 1];
    this.busy.set(true);
    try {
      if (following === 'cervello' && screen !== 'ricetta') { await this.applyBrain(); return; }
      if (screen === 'telegram' && !this.state()!.telegram.linked) { await this.linkTelegram(); return; }
      if (screen === 'backup' && !this.state()!.backup.passphrase) {
        const r = await this.api.backup(this.passphrase);
        this.passphrase = '';
        if (!r.ok) { this.formError.set('Salvata, ma il servizio dei backup non è ripartito: riprova tra poco.'); }
        await this.refresh();
      }
      if (screen === 'esterni') await this.api.later('esterni').then(s => this.state.set(s)).catch(() => undefined);
      if (screen === 'pronto') {
        await this.api.complete();
        try { localStorage.removeItem(SCREEN_KEY); } catch { /* ignore */ }
        this.leave();
        void this.router.navigateByUrl('/home');
        return;
      }
      this.forward();
    } catch (e) {
      this.formError.set(setupError(e));
      if (screen === 'cloud') this.testError.set(setupError(e));
    } finally {
      this.busy.set(false);
    }
  }

  async later() {
    const step = this.screen();
    try { this.state.set(await this.api.later(step)); } catch { /* the step stays open: nothing lost */ }
    this.forward();
  }

  // ── Cervello ──
  gb(n: number): string { return String(n).replace('.', ','); }
  installed(model: string): boolean { return (this.catalog()?.installed || []).some(m => m === model || m.startsWith(model + ':')); }
  keyLink(p: CloudProvider): string { return KEY_LINKS[p.type] || KEY_LINKS[p.name] || ''; }
  pickProvider(name: string) { this.provider.set(name); this.testOk.set(false); this.testError.set(''); this.key = ''; }

  async testKey() {
    this.busy.set(true);
    this.testError.set('');
    this.testOk.set(false);
    try {
      const r = await this.api.test(this.provider(), this.key.trim());
      if (r.ok) this.testOk.set(true); else this.testError.set(r.detail || 'Non funziona.');
    } catch (e) {
      this.testError.set(setupError(e));
    } finally {
      this.busy.set(false);
    }
  }

  private async applyBrain() {
    const r = this.recipe();
    const local = this.needsLocal() || (r === 'claude' && !!this.catalog()?.ollama) ? this.localModel() : '';
    const cloud = r === 'cloud' || r === 'entrambi' ? [this.provider()].filter(Boolean) : [];
    const out = await this.api.apply(r, local, cloud, r === 'claude' ? this.claudeToken.trim() : '');
    this.claudeToken = '';
    if (!out.ok) { this.formError.set(out.detail || 'Non sono riuscito a salvare la scelta.'); return; }
    await Promise.all([this.refresh(), this.refreshDownloads()]);
    this.forward();
  }

  // ── Telegram ──
  private async linkTelegram() {
    if (!this.botToken.trim()) return;
    const r = await this.api.telegramToken(this.botToken.trim());
    this.botToken = '';
    await this.refresh();
    if (r.ok && r.code) this.code.set(r.code);
    else this.formError.set(r.detail || 'Il bot non è partito: controlla il token.');
  }

  async newCode() {
    this.busy.set(true);
    try { this.code.set((await this.api.telegramCode()).code); } catch (e) { this.formError.set(setupError(e)); } finally { this.busy.set(false); }
  }

  // ── Backup ──
  suggest() {
    const abc = 'abcdefghjkmnpqrstuvwxyz23456789';
    const bytes = crypto.getRandomValues(new Uint8Array(20));
    this.passphrase = Array.from(bytes, b => abc[b % abc.length]).join('').replace(/(.{5})(?!$)/g, '$1-');
    this.showPass.set(true);
  }

  // ── polling: the code being claimed, the downloads ──
  private async refresh() { try { this.state.set(await this.api.state()); } catch { /* keep the last one */ } }

  private async refreshDownloads() { try { this.downloads.set(await this.api.pulls()); } catch { /* not ready yet */ } }

  private poll() {
    const screen = this.screen();
    if (screen === 'telegram' && this.code()) {
      void this.refresh().then(() => { if (this.state()?.telegram.linked) this.code.set(''); });
    }
    const list = this.downloads();
    if ((screen === 'cervello' || screen === 'pronto') && (!list.length || list.some(d => d.state === 'in_coda' || d.state === 'in_corso'))) {
      void this.refreshDownloads();
    }
  }

  downloadText(d: Download): string {
    if (d.state === 'fatto') return 'Scaricato.';
    if (d.state === 'errore') return d.error || 'Non sono riuscito a scaricarlo: riprovo dalla pagina Download.';
    if (d.state === 'in_coda') return 'In coda.';
    const gb = (n: number) => (n / 1e9).toFixed(1).replace('.', ',');
    return d.size ? `${gb(d.done)} di ${gb(d.size)} GB` : 'In corso…';
  }

  hardwareText(): string {
    const hw = this.state()?.hardware || {};
    const ram = hw.ram_gb ? `${Math.round(hw.ram_gb)} GB di memoria` : '';
    const vram = hw.vram_gb || 0;
    const gpu = vram >= 12 ? `Scheda video da ${Math.round(vram)} GB: ottima per i modelli sul tuo computer.`
      : vram >= 6 ? `Scheda video da ${Math.round(vram)} GB: va bene per i modelli medi.`
      : 'Nessuna scheda video adatta: il cloud sarà più veloce.';
    return hw.ram_gb || hw.vram_gb ? [ram, gpu].filter(Boolean).join(' · ') : 'Non so ancora com\'è fatto questo computer: ti propongo la scelta più sicura.';
  }
}
