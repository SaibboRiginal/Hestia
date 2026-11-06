import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { BrainCatalog, CloudProvider, Download, LocalModel, Runtime, SetupApi, SetupState, TunnelState, setupError } from './setup.api';

type Screen = 'benvenuto' | 'ricetta' | 'locale' | 'cloud' | 'cervello' | 'voce' | 'telegram' | 'backup' | 'esterni' | 'fuori' | 'pronto';
/** What the server stores: derived from the two boxes (computer, cloud). «claude» (Claude Code as the whole brain)
 * is no longer offered here: the Claude subscription is one of the cloud services, in the chain like the others. */
type Recipe = 'locale' | 'cloud' | 'entrambi';
const CLAUDE_TYPE = 'claude_cli';
/** Where to get a key, by provider type or name. */
const KEY_LINKS: Record<string, string> = {
  gemini: 'https://aistudio.google.com/apikey',
  deepseek: 'https://platform.deepseek.com/api_keys',
  anthropic: 'https://console.anthropic.com/settings/keys',
  openai: 'https://platform.openai.com/api-keys',
};
const SCREEN_KEY = 'hestia_setup_screen';
/** The side summary: one line per screen. */
const TITLES: Record<Screen, string> = {
  benvenuto: 'Inizio', ricetta: 'Dove pensa', locale: 'Modello sul computer', cloud: 'Servizi cloud', cervello: 'Modelli pronti',
  voce: 'Voce', telegram: 'Telegram', backup: 'Backup', esterni: 'Calendario e dispositivi', fuori: 'Fuori casa', pronto: 'Fine',
};
/** No address after this long: say so instead of a spinner forever. */
const TUNNEL_PATIENCE_MS = 90_000;

function stored(key: string): string {
  try { return localStorage.getItem(key) || ''; } catch { return ''; }
}
function store(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* private window: resume falls back to the first open step */ }
}

/**
 * Guided setup «Benvenuto» (docs/work/2026-10-30-setup-un-click §4.2): full screen, one question per screen, the
 * recommended answer preselected, «Più tardi» on the optional ones, a summary at the side to jump back. Every answer is
 * saved at once (server side), and the screen is remembered, so closing the browser resumes where it was. Secrets go
 * to Hephaestus and never come back. Local models come from the programs found on the PC (Ollama, LM Studio, Jan,
 * llama.cpp, vLLM), cloud models from the service's own list: Hestia keeps no model list of its own.
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

      <div class="cols">
      @if (state()) {
        <nav class="side hx-card" aria-label="Riepilogo">
          <details class="sum" [open]="wide">
            <summary><hx-icon name="list" [size]="15" tone="muted" /> Riepilogo</summary>
            <ol>
              @for (s of screens(); track s; let i = $index) {
                <li>
                  <button type="button" [class.cur]="s === screen()" [disabled]="!canJump(s)" (click)="jump(s)">
                    <hx-icon [name]="stepIcon(s)" [size]="15" [tone]="stepTone(s)" />
                    <span><b>{{ title(s) }}</b>@if (stepNote(s); as n) { <small>{{ n }}</small> }</span>
                  </button>
                </li>
              }
            </ol>
          </details>
        </nav>
      }

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
              <p class="lead">Scegli una o tutte e due: Hestia usa prima il tuo computer e, se è occupato o spento, il cloud.</p>
              <div class="choices">
                <button type="button" class="choice" role="checkbox" [attr.aria-checked]="useLocal()" [class.sel]="useLocal()" (click)="useLocal.set(!useLocal())">
                  <hx-icon [name]="useLocal() ? 'check-circle' : 'host'" [size]="20" [tone]="useLocal() ? 'accent' : 'muted'" />
                  <span class="ct"><b>Il tuo computer</b>@if (recommendLocal()) { <span class="rec">Consigliato</span> }
                    <small>Privato e gratis. Funziona con Ollama, LM Studio, Jan, llama.cpp o vLLM. Serve una buona scheda video.</small></span>
                </button>
                <button type="button" class="choice" role="checkbox" [attr.aria-checked]="useCloud()" [class.sel]="useCloud()" (click)="useCloud.set(!useCloud())">
                  <hx-icon [name]="useCloud() ? 'check-circle' : 'zap'" [size]="20" [tone]="useCloud() ? 'accent' : 'muted'" />
                  <span class="ct"><b>Cloud</b><span class="rec">Consigliato</span>
                    <small>Veloce su ogni computer. Gemini (chiave gratis), il tuo abbonamento Claude o un'altra chiave: li scegli dopo.</small></span>
                </button>
              </div>
              <p class="hint">Puoi cambiarlo quando vuoi da Impostazioni.</p>
            }

            @case ('locale') {
              <hx-icon name="host" [size]="30" tone="accent" />
              <h1>Quale modello sul tuo computer?</h1>
              @if (found().length) {
                <p class="lead">I modelli che hai già, programma per programma.</p>
                @for (r of found(); track r.name) {
                  <div class="group">
                    <div class="gh"><hx-icon name="check-circle" [size]="15" tone="success" /><b>{{ r.label }}</b><small>trovato</small></div>
                    @if (r.models.length) {
                      <div class="choices">
                        @for (m of r.models; track m.model) {
                          <button type="button" class="choice" [class.sel]="isLocal(r.name, m.model)" (click)="pickLocal(r.name, m.model)">
                            <hx-icon [name]="m.fits ? 'host' : 'alert'" [size]="20" [tone]="isLocal(r.name, m.model) ? 'accent' : (m.fits ? 'muted' : 'warning')" />
                            <span class="ct"><b>{{ m.model }}</b>@if (localText(m); as t) { <small>{{ t }}</small> }</span>
                          </button>
                        }
                      </div>
                    } @else if (r.name === 'ollama') {
                      <p class="hint">Ollama non ha ancora modelli. Per la tua scheda video ti propongo questi: Ollama lo scarica sul tuo computer mentre finisci il resto.</p>
                      <div class="choices">
                        @for (m of catalog()?.recommended?.chat || []; track m.model; let first = $first) {
                          <button type="button" class="choice" [class.sel]="isLocal('ollama', m.model)" (click)="pickLocal('ollama', m.model)">
                            <hx-icon name="download" [size]="20" [tone]="isLocal('ollama', m.model) ? 'accent' : 'muted'" />
                            <span class="ct"><b>{{ m.model }}</b>@if (first) { <span class="rec">Consigliato</span> }
                              <small>{{ m.good }} {{ gb(m.size_gb) }} GB da scaricare.</small></span>
                          </button>
                        }
                      </div>
                    } @else {
                      <p class="hint">Nessun modello caricato: aprilo, scaricane uno da lì e premi «Cerca di nuovo».</p>
                    }
                    @if (r.name === 'ollama') {
                      <hx-field label="Oppure un altro modello di Ollama" hint="Il nome come su ollama.com/library, per esempio qwen3:32b. Se non c'è, Ollama lo scarica.">
                        <input class="hx-input mono" autocomplete="off" spellcheck="false" [ngModel]="otherModel()" (ngModelChange)="typeLocal($event)" placeholder="nome:versione" />
                      </hx-field>
                    }
                  </div>
                }
              } @else {
                <p class="lead">Sul tuo computer non ho trovato programmi per i modelli. Installane uno (sono gratis), aprilo e premi «Cerca di nuovo».</p>
                <div class="choices">
                  @for (r of missing(); track r.name; let first = $first) {
                    <a class="choice" [href]="r.site" target="_blank" rel="noopener">
                      <hx-icon name="external" [size]="20" tone="muted" />
                      <span class="ct"><b>{{ r.label }}</b>@if (first) { <span class="rec">Consigliato</span> }
                        <small>{{ runtimeText(r) }}</small></span>
                    </a>
                  }
                </div>
                <p class="hint">Oppure torna indietro e usa solo il cloud.</p>
              }
              @if (found().length && missing().length) {
                <p class="hint">Non trovati: {{ missingNames() }}. Se ne usi uno, aprilo e premi «Cerca di nuovo».</p>
              }
              <div class="row"><button hx-btn variant="ghost" icon="refresh" [loading]="searching()" (click)="searchAgain()">Cerca di nuovo</button></div>
              @if (found().length) {
                <details class="adv">
                  <summary>Avanzate</summary>
                  <hx-field label="Modello per la memoria" hint="Serve a ritrovare ricordi e documenti. Se lo cambi, Hestia rilegge la memoria: ci vuole un po'.">
                    <select class="hx-input" [ngModel]="embeddingKey()" (ngModelChange)="embeddingKey.set($event)">
                      @for (e of embedChoices(); track e.key) { <option [value]="e.key">{{ e.label }}</option> }
                    </select>
                  </hx-field>
                </details>
              }
            }

            @case ('cloud') {
              <hx-icon name="zap" [size]="30" tone="accent" />
              <h1>Quali servizi nel cloud?</h1>
              <p class="lead">Scegline uno o più: li usa in quest'ordine, il secondo se il primo non risponde o ha finito la quota.</p>
              <div class="choices">
                @for (p of catalog()?.cloud || []; track p.name) {
                  <div class="opt" [class.sel]="picked(p.name)">
                    <button type="button" class="choice" role="checkbox" [attr.aria-checked]="picked(p.name)" (click)="toggleProvider(p.name)">
                      <hx-icon [name]="picked(p.name) ? 'check-circle' : (p.type === claudeType ? 'brain' : 'unlock')" [size]="20" [tone]="picked(p.name) ? 'accent' : 'muted'" />
                      <span class="ct"><b>@if (cloudOrder(p.name) > 0) { {{ cloudOrder(p.name) }}. }{{ p.label || p.name }}</b>
                        @if (p.type === 'gemini') { <span class="rec">Gratis</span> }
                        <small>{{ providerText(p) }}</small></span>
                      @if (picked(p.name)) { <hx-icon [name]="ready(p.name) ? 'check-circle' : 'clock'" [size]="16" [tone]="ready(p.name) ? 'success' : 'warning'" /> }
                    </button>
                    @if (picked(p.name)) {
                      <div class="cfg">
                        @if (p.type === claudeType) {
                          <p class="hint">Nel terminale scrivi <code>claude setup-token</code>, accedi con il tuo account Claude (Pro o Max), poi incolla qui il codice che ti dà.</p>
                          <hx-field label="Codice dell'abbonamento Claude" [hint]="state()!.claude.token ? 'Codice già inserito: lascia vuoto per tenerlo.' : ''">
                            <input class="hx-input mono" type="password" autocomplete="off" [(ngModel)]="claudeToken" placeholder="sk-ant-oat…" />
                          </hx-field>
                        } @else {
                          <hx-field [label]="'Chiave di ' + (p.label || p.name)" [error]="testError()[p.name] || ''"
                                    [hint]="testNote()[p.name] || (p.key_set ? 'Lascia vuoto per tenere quella che c\\'è.' : '')">
                            <input class="hx-input mono" type="password" autocomplete="off" [ngModel]="keys[p.name] || ''" (ngModelChange)="typeKey(p.name, $event)" placeholder="incolla qui la chiave" />
                          </hx-field>
                          @if (modelsOf()[p.name]?.length) {
                            <hx-field label="Modello" hint="La lista viene dal servizio stesso.">
                              <select class="hx-input" [ngModel]="cloudModel()[p.name] || ''" (ngModelChange)="pickCloudModel(p.name, $event)">
                                <option value="" disabled>Scegli un modello</option>
                                @for (m of modelsOf()[p.name]; track m) { <option [value]="m">{{ m }}</option> }
                              </select>
                            </hx-field>
                          }
                          <div class="row">
                            @if (keyLink(p)) { <a hx-btn variant="ghost" icon="external" [href]="keyLink(p)" target="_blank" rel="noopener">Prendi la chiave</a> }
                            <button hx-btn variant="secondary" icon="play" [loading]="testing() === p.name" [disabled]="!keys[p.name] && !p.key_set" (click)="testKey(p.name)">Prova</button>
                          </div>
                        }
                        @if (cloudOrder(p.name) > 1) {
                          <div class="row"><button hx-btn variant="ghost" size="sm" icon="chevron-up" (click)="moveUp(p.name)">Prima di {{ before(p.name) }}</button></div>
                        }
                      </div>
                    }
                  </div>
                } @empty { <p class="lead">Nessun servizio cloud configurato.</p> }
              </div>
            }

            @case ('cervello') {
              <hx-icon name="check-circle" [size]="30" tone="success" />
              <h1>I modelli sono pronti</h1>
              <p class="lead">{{ state()!.brain.summary || 'Fatto.' }}</p>
              <ng-container *ngTemplateOutlet="downloadsTpl" />
            }

            @case ('voce') {
              <hx-icon name="volume" [size]="30" tone="accent" />
              <h1>Vuoi parlare con Hestia a voce?</h1>
              <p class="lead">Scarico adesso le voci e l'ascolto, così la prima volta che parli non devi aspettare. Funzionano sul tuo computer, senza servizi a pagamento.</p>
              @if (voiceQueued()) { <p class="ok"><hx-icon name="check-circle" [size]="16" tone="success" /> Le sto scaricando: puoi andare avanti, continuano da sole.</p> }
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
                <li><hx-icon name="pulse" [size]="18" tone="success" /><span><b>Orologio Garmin e telefono</b>
                  <small><a href="/p/hecate/dispositivi" target="_blank" rel="noopener">Pagina Dispositivi</a>: si apre in un'altra scheda, questa resta qui.</small></span></li>
              </ul>
            }

            @case ('fuori') {
              <hx-icon name="cloud" [size]="30" tone="accent" />
              <h1>Usare Hestia fuori casa</h1>
              @if (tunnel()?.on && tunnel()!.url) {
                <p class="ok"><hx-icon name="check-circle" [size]="16" tone="success" /> Fatto. Da fuori casa, anche senza il Wi-Fi di casa, apri:</p>
                <div class="code mono small">{{ tunnel()!.url }}</div>
                <p class="hint">Ti chiede l'accesso, come qui. L'indirizzo cambia quando Hestia si riavvia: il bot su Telegram ti dà sempre quello giusto.</p>
                <div class="row">
                  <a hx-btn variant="secondary" icon="external" [href]="tunnel()!.url" target="_blank" rel="noopener">Provalo</a>
                  <button hx-btn variant="ghost" icon="x" [loading]="busy()" (click)="switchTunnel(false)">Spegni</button>
                </div>
              } @else if (busy() || tunnel()?.on) {
                @if (tunnelLate()) {
                  <p class="warn"><hx-icon name="alert" [size]="15" tone="warning" /> L'indirizzo non arriva. Di solito è la rete che blocca Cloudflare (ufficio, scuola) o internet che non va.</p>
                  <div class="row">
                    <button hx-btn variant="ghost" icon="x" (click)="switchTunnel(false)">Spegni</button>
                    <button hx-btn variant="secondary" icon="refresh" (click)="retryTunnel()">Riprova</button>
                  </div>
                } @else {
                  <ol class="steps">
                    <li [class.done]="!!tunnel()?.on"><hx-icon [name]="tunnel()?.on ? 'check-circle' : 'download'" [size]="16" [tone]="tunnel()?.on ? 'success' : 'info'" /> Scarico e avvio il programma di Cloudflare</li>
                    <li><hx-spinner /> Aspetto l'indirizzo da Cloudflare (fino a un minuto)</li>
                  </ol>
                }
              } @else {
                <p class="lead">Dal telefono, fuori casa, apri Hestia con un indirizzo internet sicuro. Senza, Hestia si usa solo in casa e da Telegram.</p>
                <p class="hint">Se lo attivi: scarico e avvio un piccolo programma di Cloudflare (gratis, senza account) che crea un indirizzo che porta qui. Da quell'indirizzo Hestia chiede sempre l'accesso; in casa resta come ora. Lo spegni quando vuoi da questa pagina.</p>
              }
              @if (formError()) { <p class="warn"><hx-icon name="alert" [size]="15" tone="danger" /> {{ formError() }}</p> }
            }

            @case ('pronto') {
              <hx-icon name="sparkle" [size]="30" tone="accent" />
              <h1>Quasi pronto</h1>
              <p class="lead">Ecco cosa hai scelto. Tocca una riga del riepilogo per cambiarla.</p>
              <ul class="list">
                <li><hx-icon [name]="state()!.brain.recipe ? 'check-circle' : 'clock'" [size]="18" [tone]="state()!.brain.recipe ? 'success' : 'warning'" />
                  <span><b>Modelli</b><small>{{ state()!.brain.summary || 'Non ancora scelti.' }}</small></span></li>
                <li><hx-icon [name]="state()!.telegram.linked ? 'check-circle' : 'clock'" [size]="18" [tone]="state()!.telegram.linked ? 'success' : 'muted'" />
                  <span><b>Telegram</b><small>{{ state()!.telegram.linked ? 'Collegato.' : 'Più tardi.' }}</small></span></li>
                <li><hx-icon [name]="state()!.backup.passphrase ? 'check-circle' : 'clock'" [size]="18" [tone]="state()!.backup.passphrase ? 'success' : 'muted'" />
                  <span><b>Backup</b><small>{{ state()!.backup.passphrase ? 'Pronto.' : 'Più tardi.' }}</small></span></li>
                <li><hx-icon [name]="tunnel()?.on ? 'check-circle' : 'clock'" [size]="18" [tone]="tunnel()?.on ? 'success' : 'muted'" />
                  <span><b>Fuori casa</b><small>{{ tunnel()?.on ? (tunnel()!.url || 'Attivo.') : 'Solo in casa e da Telegram.' }}</small></span></li>
              </ul>
              <ng-container *ngTemplateOutlet="downloadsTpl" />
            }
          }

          <ng-template #downloadsTpl>
            @if (downloads().length) {
              <div class="dlbox">
                <p class="hint">I modelli li scarica Ollama sul tuo computer, le voci finiscono nella cartella di Hestia. Puoi andare avanti: continuano da sole.
                  <a href="/download" target="_blank" rel="noopener">Pagina Download</a></p>
                <ul class="list dl">
                  @for (d of downloads(); track (d.module || '') + d.id) {
                    <li>
                      <hx-icon [name]="d.state === 'fatto' ? 'check-circle' : d.state === 'errore' ? 'alert' : 'download'" [size]="18"
                               [tone]="d.state === 'fatto' ? 'success' : d.state === 'errore' ? 'danger' : 'info'" />
                      <span><b>{{ d.what }}</b><small>{{ downloadText(d) }}</small>
                        @if (d.state === 'in_corso' && d.size) { <span class="bar"><span [style.width.%]="100 * d.done / d.size"></span></span> }
                      </span>
                    </li>
                  }
                </ul>
              </div>
            }
          </ng-template>

          <div class="nav">
            @if (index() > 0) { <button hx-btn variant="ghost" icon="chevron-left" (click)="back()">Indietro</button> }
            <span class="sp"></span>
            @if (optional()) { <button hx-btn variant="ghost" (click)="later()">Più tardi</button> }
            <button hx-btn variant="primary" size="lg" [loading]="busy()" [disabled]="!canNext()" (click)="next()">{{ nextLabel() }}</button>
          </div>
          @if (screen() !== 'fuori' && screen() !== 'telegram' && screen() !== 'backup' && formError()) {
            <p class="warn"><hx-icon name="alert" [size]="15" tone="danger" /> {{ formError() }}</p>
          }
        }
      </main>
      </div>
    </div>`,
  styles: [`
    :host { display: block; height: 100vh; height: 100dvh; overflow-y: auto; overscroll-behavior: contain; background: var(--backdrop, var(--bg)); }
    .wrap { max-width: 860px; margin: 0 auto; padding: 18px 16px 32px; display: flex; flex-direction: column; gap: 14px; }
    .top { display: flex; align-items: center; gap: 12px; min-height: 32px; max-width: 560px; width: 100%; margin-left: auto; }
    .dots { flex: 1; display: flex; gap: 6px; }
    .dots span { width: 8px; height: 8px; border-radius: var(--radius-full); background: var(--surface-3); transition: background var(--dur) var(--ease); }
    .dots span.on { background: var(--accent); }
    .out { font-size: 13px; color: var(--text-3); }
    .cols { display: grid; grid-template-columns: 240px minmax(0, 560px); gap: 16px; align-items: start; justify-content: end; }
    .side { position: sticky; top: 0; padding: 12px 10px; }
    .sum summary { display: flex; gap: 6px; align-items: center; font-size: 13px; font-weight: 600; color: var(--text-2); cursor: pointer; list-style: none; padding: 2px 4px 8px; }
    .sum summary::-webkit-details-marker { display: none; }
    .sum ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
    .sum button { display: flex; gap: 8px; align-items: flex-start; width: 100%; text-align: left; padding: 6px; border-radius: var(--radius-sm); background: none; color: var(--text); border: 0; }
    .sum button:hover:not(:disabled) { background: var(--surface-2); }
    .sum button.cur { background: var(--accent-soft); }
    .sum button:disabled { opacity: .55; cursor: default; }
    .sum button span { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .sum b { font-size: 13px; font-weight: 600; }
    .sum small { font-size: 12px; color: var(--text-3); overflow-wrap: anywhere; }
    .card { padding: 28px 24px 20px; display: flex; flex-direction: column; gap: 14px; }
    .center { display: grid; place-items: center; gap: 12px; padding: 40px 0; text-align: center; color: var(--text-2); }
    h1 { font-family: var(--font-serif); font-weight: 500; font-size: 26px; line-height: 1.2; color: var(--text); }
    .lead { color: var(--text-2); font-size: 15px; line-height: 1.5; }
    .hw, .ok, .warn, .hint { display: flex; gap: 8px; align-items: center; font-size: 14px; color: var(--text-2); flex-wrap: wrap; }
    code { font-family: var(--font-mono); font-size: 13px; background: var(--surface-2); padding: 1px 5px; border-radius: var(--radius-xs); }
    .choices { display: flex; flex-direction: column; gap: 8px; }
    .choice { display: flex; gap: 12px; align-items: flex-start; text-align: left; padding: 14px; border: 1px solid var(--border);
              border-radius: var(--radius-md); background: var(--surface); color: var(--text); min-height: var(--tap, 0px); width: 100%;
              transition: border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease); text-decoration: none; }
    .choice:hover { border-color: var(--border-strong); }
    .choice.sel { border-color: var(--accent); background: var(--accent-soft); }
    .opt { border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); overflow: hidden;
           transition: border-color var(--dur-fast) var(--ease); }
    .opt .choice { border: 0; border-radius: 0; background: none; }
    .opt.sel { border-color: var(--accent); }
    .opt.sel > .choice { background: var(--accent-soft); }
    .cfg { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px 14px; border-top: 1px solid var(--border); }
    .group { display: flex; flex-direction: column; gap: 8px; }
    .gh { display: flex; gap: 6px; align-items: center; font-size: 14px; }
    .gh small { color: var(--text-3); font-size: 12px; }
    .adv summary { font-size: 13px; color: var(--text-2); cursor: pointer; margin-bottom: 8px; }
    select.hx-input { width: 100%; }
    .ct { display: flex; flex-direction: column; gap: 3px; flex: 1; min-width: 0; }
    .ct b { font-weight: 600; font-size: 15px; overflow-wrap: anywhere; }
    .ct small, .list small { color: var(--text-3); font-size: 13px; line-height: 1.4; }
    .rec { align-self: flex-start; font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); padding: 1px 7px; border-radius: var(--radius-full); }
    .row { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .code { font-size: 38px; letter-spacing: .25em; text-align: center; padding: 14px; border-radius: var(--radius-md); background: var(--surface-2); color: var(--text); }
    .code.small { font-size: 14px; letter-spacing: 0; overflow-wrap: anywhere; user-select: all; }
    .list { list-style: none; display: flex; flex-direction: column; gap: 12px; padding: 0; margin: 0; }
    .list li { display: flex; gap: 10px; align-items: flex-start; }
    .list li > span { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
    .list b { font-weight: 600; font-size: 14px; }
    .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; font-size: 14px; color: var(--text-2); }
    .steps li { display: flex; gap: 8px; align-items: center; }
    .dlbox { display: flex; flex-direction: column; gap: 10px; }
    .bar { display: block; height: 4px; border-radius: var(--radius-full); background: var(--surface-3); overflow: hidden; margin-top: 4px; }
    .bar span { display: block; height: 100%; background: var(--accent); transition: width var(--dur) var(--ease); }
    .nav { display: flex; align-items: center; gap: 8px; margin-top: 8px; padding-top: 14px; border-top: 1px solid var(--border); }
    .sp { flex: 1; }
    @media (max-width: 860px) {
      .wrap { max-width: 560px; }
      .cols { grid-template-columns: minmax(0, 1fr); }
      .side { position: static; order: -1; }
    }
    @media (max-width: 480px) { .card { padding: 22px 16px 16px; } h1 { font-size: 22px; } .code { font-size: 30px; } }
  `],
})
export class SetupPageComponent {
  private api = inject(SetupApi);
  private router = inject(Router);
  readonly claudeType = CLAUDE_TYPE;
  /** The summary starts open beside the card, folded above it on a phone. */
  readonly wide = typeof window === 'undefined' || window.matchMedia?.('(min-width: 861px)').matches !== false;

  state = signal<SetupState | null>(null);
  catalog = signal<BrainCatalog | null>(null);
  downloads = signal<Download[]>([]);
  loadError = signal('');
  busy = signal(false);
  formError = signal('');
  showPass = signal(false);
  code = signal('');
  searching = signal(false);

  useLocal = signal(true);
  useCloud = signal(true);
  recipe = computed<Recipe>(() => this.useLocal() && this.useCloud() ? 'entrambi' : this.useLocal() ? 'locale' : 'cloud');
  /** The local program (provider block name) and its model. */
  localProvider = signal('ollama');
  localModel = signal('');
  /** The memory's model as «provider|model»; empty = keep the current one. */
  embeddingKey = signal('');
  /** The chosen cloud services, in the order they are tried. */
  cloudPicked = signal<string[]>([]);
  /** Per service: the model picked, the chat models it really has (after «Prova»), the result of «Prova». */
  cloudModel = signal<Record<string, string>>({});
  modelsOf = signal<Record<string, string[]>>({});
  testNote = signal<Record<string, string>>({});
  testError = signal<Record<string, string>>({});
  /** Services whose key passed «Prova» in this run (with a model that answers). */
  tested = signal<string[]>([]);
  testing = signal('');
  keys: Record<string, string> = {};
  claudeToken = '';
  botToken = '';
  passphrase = '';

  screen = signal<Screen>('benvenuto');
  /** The furthest screen reached in this run: the summary jumps back freely, forward only up to here. */
  reached = signal(0);
  needsLocal = computed(() => this.useLocal());
  recommendLocal = computed(() => this.catalog()?.recommended?.recipe !== 'cloud');
  /** The screens of this run: the brain's sub-screens follow the recipe. */
  screens = computed<Screen[]>(() => {
    const r = this.recipe();
    return ['benvenuto', 'ricetta',
      ...(this.needsLocal() ? ['locale' as Screen] : []),
      ...(r === 'cloud' || r === 'entrambi' ? ['cloud' as Screen] : []),
      'cervello', 'voce', 'telegram', 'backup', 'esterni', 'fuori', 'pronto'];
  });
  index = computed(() => Math.max(0, this.screens().indexOf(this.screen())));
  optional = computed(() => (this.screen() === 'voce' && !this.voiceQueued())
    || (this.screen() === 'fuori' && !this.tunnel()?.on)
    || (['telegram', 'backup'].includes(this.screen()) && !this.stepDone(this.screen())));
  voiceQueued = signal(false);
  tunnel = signal<TunnelState | null>(null);
  private tunnelSince = signal(0);
  private now = signal(Date.now());
  tunnelLate = computed(() => !!this.tunnelSince() && !this.tunnel()?.url && this.now() - this.tunnelSince() > TUNNEL_PATIENCE_MS);

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
      if (catalog) this.useCatalog(catalog, state, true);
      const saved = stored(SCREEN_KEY) as Screen;
      this.screen.set(this.screens().includes(saved) ? saved : this.firstOpen(state));
      this.reached.set(state.brain.recipe ? this.screens().length - 1 : this.index());
      this.api.tunnel().then(t => this.tunnel.set(t)).catch(() => undefined);
      void this.refreshDownloads();
    } catch (e) {
      this.loadError.set(setupError(e));
    }
  }

  /** Apply a catalog: the saved answers first, otherwise the best guess (first fitting model of the first program found). */
  private useCatalog(catalog: BrainCatalog, state: SetupState, first: boolean) {
    this.catalog.set(catalog);
    const saved = state.brain.recipe || catalog.recommended.recipe || 'entrambi';
    if (first) {
      // «claude» was the old fourth choice (Claude as the whole brain, chains as fallback): computer + cloud with Claude.
      this.useLocal.set(saved !== 'cloud');
      this.useCloud.set(saved !== 'locale');
    }
    const found = (catalog.runtimes || []).filter(r => r.found);
    const has = (p: string, m: string) => found.some(r => r.name === p && r.models.some(x => x.model === m));
    const savedProvider = state.brain.local_provider || 'ollama';
    if (!(this.localModel() && has(this.localProvider(), this.localModel()))) {
      const firstFit = found.map(r => ({ r, m: r.models.find(m => m.fits) || r.models[0] })).find(x => x.m);
      if (state.brain.local_model && has(savedProvider, state.brain.local_model)) {
        this.localProvider.set(savedProvider);
        this.localModel.set(state.brain.local_model);
      } else if (firstFit) {
        this.localProvider.set(firstFit.r.name);
        this.localModel.set(firstFit.m!.model);
      } else if (found.some(r => r.name === 'ollama')) {
        this.localProvider.set('ollama');
        this.localModel.set(state.brain.local_model || catalog.recommended.model);
      } else {
        this.localModel.set('');
      }
    }
    if (first) {
      const cloud = catalog.cloud;
      let picked = (state.brain.cloud || []).filter(n => cloud.some(p => p.name === n));
      if (saved === 'claude') {
        const claude = cloud.find(p => p.type === CLAUDE_TYPE)?.name;
        if (claude && !picked.includes(claude)) picked = [claude, ...picked];
      }
      if (!picked.length) {
        const one = cloud.find(p => p.key_set)?.name || cloud.find(p => p.type === 'gemini')?.name || cloud[0]?.name;
        picked = one ? [one] : [];
      }
      this.cloudPicked.set(picked);
      this.cloudModel.set({ ...(state.brain.cloud_models || {}) });
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
    if (screen === 'fuori') this.api.tunnel().then(t => this.tunnel.set(t)).catch(() => undefined);
    this.screen.set(screen);
    this.reached.set(Math.max(this.reached(), this.screens().indexOf(screen)));
    store(SCREEN_KEY, screen);
  }

  back() { const list = this.screens(); this.go(list[Math.max(0, this.index() - 1)]); }
  private forward() { const list = this.screens(); this.go(list[Math.min(list.length - 1, this.index() + 1)]); }

  /** «Finisco dopo»: the Home shows a card to come back; the guard does not bring the browser here again this session. */
  leave() { try { sessionStorage.setItem('hestia_setup_seen', '1'); } catch { /* ignore */ } }

  // ── Riepilogo (side) ──
  title(s: Screen): string { return TITLES[s]; }
  canJump(s: Screen): boolean {
    const i = this.screens().indexOf(s);
    if (s === 'cervello') return !!this.state()?.brain.recipe;
    return i <= this.reached();
  }
  jump(s: Screen) { if (this.canJump(s)) this.go(s); }
  private isDone(s: Screen): boolean {
    const st = this.state();
    if (!st) return false;
    switch (s) {
      case 'benvenuto': return this.reached() > 0;
      case 'ricetta': case 'locale': case 'cloud': case 'cervello': return !!st.brain.recipe;
      case 'voce': return this.voiceQueued();
      case 'telegram': return st.telegram.linked;
      case 'backup': return st.backup.passphrase;
      case 'esterni': return this.reached() > this.screens().indexOf('esterni');
      case 'fuori': return !!this.tunnel()?.on;
      default: return false;
    }
  }
  stepIcon(s: Screen): string {
    if (s === this.screen()) return 'chevron-right';
    if (this.isDone(s)) return 'check-circle';
    return this.state()?.later.includes(s) ? 'clock' : 'minus';
  }
  stepTone(s: Screen): string {
    if (s === this.screen()) return 'accent';
    return this.isDone(s) ? 'success' : 'muted';
  }
  stepNote(s: Screen): string {
    const st = this.state();
    if (!st) return '';
    switch (s) {
      case 'ricetta': return this.recipe() === 'entrambi' ? 'Computer e cloud' : this.recipe() === 'locale' ? 'Solo il computer' : 'Solo il cloud';
      case 'locale': return this.localModel() ? `${this.localModel()} (${this.runtimeLabel(this.localProvider())})` : '';
      case 'cloud': return this.cloudPicked().map(n => this.cloudLabel(n)).join(', ');
      case 'voce': return this.voiceQueued() ? 'In download' : st.later.includes('voce') ? 'Più tardi' : '';
      case 'telegram': return st.telegram.linked ? 'Collegato' : st.later.includes('telegram') ? 'Più tardi' : '';
      case 'backup': return st.backup.passphrase ? 'Pronto' : st.later.includes('backup') ? 'Più tardi' : '';
      case 'fuori': return this.tunnel()?.on ? 'Attivo' : '';
      default: return '';
    }
  }

  canNext(): boolean {
    switch (this.screen()) {
      case 'ricetta': return this.useLocal() || this.useCloud();
      case 'locale': return !!this.localModel();
      case 'cloud': return this.cloudPicked().length > 0 && this.cloudPicked().every(n => this.ready(n));
      case 'telegram': return this.state()!.telegram.linked || (!this.code() && !this.state()!.telegram.token && !!this.botToken.trim());
      case 'backup': return this.state()!.backup.passphrase || this.passphrase.length >= 12;
      default: return true;
    }
  }

  nextLabel(): string {
    switch (this.screen()) {
      case 'benvenuto': return 'Iniziamo';
      case 'locale': return this.screens()[this.index() + 1] === 'cervello' ? 'Conferma' : 'Avanti';
      case 'cloud': return 'Conferma';
      case 'telegram': return this.state()!.telegram.linked || this.code() || this.state()!.telegram.token ? 'Avanti' : 'Collega';
      case 'backup': return this.state()!.backup.passphrase ? 'Avanti' : 'Salva';
      case 'voce': return this.voiceQueued() ? 'Avanti' : 'Sì, scarica';
      case 'fuori': return this.tunnel()?.on ? 'Avanti' : 'Attiva';
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
      if (screen === 'voce' && !this.voiceQueued()) {
        await this.api.prefetchVoice();
        this.voiceQueued.set(true);
        void this.refreshDownloads();
        return;
      }
      if (screen === 'telegram' && !this.state()!.telegram.linked) { await this.linkTelegram(); return; }
      if (screen === 'backup' && !this.state()!.backup.passphrase) {
        const r = await this.api.backup(this.passphrase);
        this.passphrase = '';
        if (!r.ok) { this.formError.set('Salvata, ma il servizio dei backup non è ripartito: riprova tra poco.'); }
        await this.refresh();
      }
      if (screen === 'esterni') await this.api.later('esterni').then(s => this.state.set(s)).catch(() => undefined);
      if (screen === 'fuori' && !this.tunnel()?.on) { this.busy.set(false); await this.switchTunnel(true); return; }
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
    } finally {
      this.busy.set(false);
    }
  }

  async later() {
    const step = this.screen();
    try { this.state.set(await this.api.later(step)); } catch { /* the step stays open: nothing lost */ }
    this.forward();
  }

  // ── Modello sul computer ──
  gb(n: number): string { return String(n).replace('.', ','); }
  found = computed<Runtime[]>(() => (this.catalog()?.runtimes || []).filter(r => r.found));
  missing = computed<Runtime[]>(() => (this.catalog()?.runtimes || []).filter(r => !r.found));
  missingNames(): string { return this.missing().map(r => r.label).join(', '); }
  otherModel = signal('');
  isLocal(provider: string, model: string): boolean { return this.localProvider() === provider && this.localModel() === model && !this.otherModel(); }
  pickLocal(provider: string, model: string) { this.localProvider.set(provider); this.localModel.set(model); this.otherModel.set(''); }
  typeLocal(name: string) {
    this.otherModel.set(name);
    const clean = name.trim();
    if (clean) { this.localProvider.set('ollama'); this.localModel.set(clean); }
    else this.localModel.set('');
  }
  localText(m: LocalModel): string {
    const what = [m.params, m.quant].filter(Boolean).join(' · ');
    const size = m.size_gb ? `${this.gb(m.size_gb)} GB` : '';
    const vram = Math.round(this.state()?.hardware?.vram_gb || 0);
    const warn = m.fits ? '' : `Più grande della scheda video (${vram} GB): funziona, ma più lento.`;
    return [[what, size].filter(Boolean).join(', '), warn].filter(Boolean).join(' ');
  }
  runtimeText(r: Runtime): string {
    return r.name === 'ollama' ? 'Il più semplice: Hestia scarica da solo i modelli adatti alla tua scheda video.'
      : r.name === 'lmstudio' ? 'Con una finestra per cercare e scaricare i modelli. Poi attiva il server locale.'
      : 'Si scaricano i modelli da lì.';
  }
  runtimeLabel(name: string): string { return (this.catalog()?.runtimes || []).find(r => r.name === name)?.label || name; }
  async searchAgain() {
    this.searching.set(true);
    try { this.useCatalog(await this.api.catalog(), this.state()!, false); } catch { /* keep the last list */ } finally { this.searching.set(false); }
  }
  /** The memory's model: the current one, then every embedding model the programs found have. */
  embedChoices = computed(() => {
    const now = this.catalog()?.embedding;
    const out: { key: string; label: string }[] = [];
    if (now?.model) out.push({ key: '', label: `${now.model} (${this.runtimeLabel(now.provider)}, quello di ora)` });
    for (const r of this.found()) {
      for (const m of r.embed) {
        if (now && r.name === now.provider && m === now.model) continue;
        out.push({ key: `${r.name}|${m}`, label: `${m} (${r.label})` });
      }
    }
    if (!out.length) out.push({ key: '', label: 'Quello consigliato' });
    return out;
  });

  // ── Servizi cloud ──
  keyLink(p: CloudProvider): string { return KEY_LINKS[p.type] || KEY_LINKS[p.name] || ''; }
  cloudLabel(name: string): string { const p = this.catalog()?.cloud.find(c => c.name === name); return p?.label || name; }
  picked(name: string): boolean { return this.cloudPicked().includes(name); }
  cloudOrder(name: string): number { return this.cloudPicked().length > 1 ? this.cloudPicked().indexOf(name) + 1 : 0; }
  before(name: string): string { const l = this.cloudPicked(); return this.cloudLabel(l[l.indexOf(name) - 1]); }
  toggleProvider(name: string) {
    const list = this.cloudPicked();
    this.cloudPicked.set(list.includes(name) ? list.filter(n => n !== name) : [...list, name]);
  }
  moveUp(name: string) {
    const l = [...this.cloudPicked()];
    const i = l.indexOf(name);
    if (i > 0) { [l[i - 1], l[i]] = [l[i], l[i - 1]]; this.cloudPicked.set(l); }
  }
  typeKey(name: string, value: string) {
    this.keys[name] = value;
    this.tested.set(this.tested().filter(n => n !== name));
    this.testNote.set({ ...this.testNote(), [name]: '' });
    this.testError.set({ ...this.testError(), [name]: '' });
  }
  pickCloudModel(name: string, model: string) {
    this.cloudModel.set({ ...this.cloudModel(), [name]: model });
    // A model picked from the service's own list after a working key: nothing more to try.
    if (model && this.modelsOf()[name]?.includes(model) && !this.tested().includes(name)) this.tested.set([...this.tested(), name]);
  }
  /** A chosen service can be used: key already there or just tried, and a model it has; Claude: the code. */
  ready(name: string): boolean {
    const p = this.catalog()?.cloud.find(c => c.name === name);
    if (!p) return false;
    if (p.type === CLAUDE_TYPE) return !!this.state()?.claude.token || !!this.claudeToken.trim() || p.available;
    const listed = this.modelsOf()[name];
    if (listed?.length && !this.cloudModel()[name]) return false;
    return this.tested().includes(name) || (p.key_set && !this.keys[name]);
  }
  providerText(p: CloudProvider): string {
    if (p.type === CLAUDE_TYPE) return this.ready(p.name) ? 'Abbonamento collegato.' : 'Il tuo abbonamento Claude Pro o Max.';
    const model = this.cloudModel()[p.name];
    return (p.key_set ? 'Chiave già inserita.' : 'Serve una chiave.') + (model ? ` Modello: ${model}.` : '');
  }

  async testKey(name: string) {
    this.testing.set(name);
    this.testError.set({ ...this.testError(), [name]: '' });
    this.testNote.set({ ...this.testNote(), [name]: '' });
    try {
      const r = await this.api.test(name, (this.keys[name] || '').trim(), this.cloudModel()[name] || '');
      if (r.models?.length) this.modelsOf.set({ ...this.modelsOf(), [name]: r.models });
      if (r.ok && r.model) this.cloudModel.set({ ...this.cloudModel(), [name]: r.model });
      if (r.ok && r.model === '') this.cloudModel.set({ ...this.cloudModel(), [name]: '' });
      if (r.ok) {
        this.keys[name] = '';
        this.tested.set([...this.tested().filter(n => n !== name), name]);
        this.testNote.set({ ...this.testNote(), [name]: r.detail || 'Funziona.' });
        void this.api.catalog().then(c => this.catalog.set({ ...c, runtimes: this.catalog()?.runtimes ?? c.runtimes })).catch(() => undefined);
      } else {
        this.testError.set({ ...this.testError(), [name]: r.detail || 'Non funziona.' });
      }
    } catch (e) {
      this.testError.set({ ...this.testError(), [name]: setupError(e) });
    } finally {
      this.testing.set('');
    }
  }

  private async applyBrain() {
    const r = this.recipe();
    const local = this.needsLocal() ? this.localModel() : '';
    const cloud = this.useCloud() ? this.cloudPicked() : [];
    const claudeChosen = cloud.some(n => this.catalog()?.cloud.find(p => p.name === n)?.type === CLAUDE_TYPE);
    const models: Record<string, string> = {};
    for (const n of cloud) if (this.cloudModel()[n]) models[n] = this.cloudModel()[n];
    const [ep, em] = this.embeddingKey() ? this.embeddingKey().split('|') : ['', ''];
    const out = await this.api.apply(r, local, cloud, claudeChosen ? this.claudeToken.trim() : '', {
      local_provider: this.localProvider(), cloud_models: models, embedding: em ? { provider: ep, model: em } : null,
    });
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

  // ── Fuori casa ──
  async switchTunnel(on: boolean) {
    this.busy.set(true);
    this.formError.set('');
    this.tunnelSince.set(on ? Date.now() : 0);
    try {
      this.tunnel.set(await this.api.setTunnel(on));
    } catch (e) {
      this.formError.set(setupError(e));
      this.tunnelSince.set(0);
    } finally {
      this.busy.set(false);
    }
  }
  async retryTunnel() { await this.switchTunnel(false); await this.switchTunnel(true); }

  // ── polling: the code being claimed, the downloads, the tunnel address ──
  private async refresh() { try { this.state.set(await this.api.state()); } catch { /* keep the last one */ } }

  private async refreshDownloads() {
    try { this.downloads.set(await this.api.allDownloads()); return; } catch { /* only the models then */ }
    try { this.downloads.set(await this.api.pulls()); } catch { /* not ready yet */ }
  }

  private poll() {
    this.now.set(Date.now());
    const screen = this.screen();
    if (screen === 'telegram' && this.code()) {
      void this.refresh().then(() => { if (this.state()?.telegram.linked) this.code.set(''); });
    }
    const list = this.downloads();
    if ((screen === 'cervello' || screen === 'voce' || screen === 'pronto')
        && (!list.length || list.some(d => d.state === 'in_coda' || d.state === 'in_corso'))) {
      void this.refreshDownloads();
    }
    if (screen === 'fuori' && this.tunnel()?.on && !this.tunnel()!.url) {
      if (!this.tunnelSince()) this.tunnelSince.set(Date.now());
      this.api.tunnel().then(t => this.tunnel.set(t)).catch(() => undefined);
    }
  }

  downloadText(d: Download): string {
    if (d.state === 'fatto') return 'Scaricato.';
    if (d.state === 'errore') return d.error || 'Non sono riuscito a scaricarlo: riprovo dalla pagina Download.';
    if (d.state === 'in_coda') return 'In coda.';
    if (d.state === 'in_pausa') return 'In pausa.';
    const gb = (n: number) => (n / 1e9).toFixed(1).replace('.', ',');
    const left = d.eta_s ? ` · ancora ${d.eta_s >= 60 ? Math.round(d.eta_s / 60) + ' min' : Math.round(d.eta_s) + ' s'}` : '';
    return d.size ? `${gb(d.done)} di ${gb(d.size)} GB${left}` : 'In corso…';
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
