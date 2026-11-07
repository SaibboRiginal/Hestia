import { ChangeDetectionStrategy, Component, DestroyRef, WritableSignal, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { PluginOutletComponent } from '../plugins/plugin-outlet.component';
import { PluginsService } from '../plugins/plugins.service';
import { HomeProgram, SetupChainComponent } from './setup-chain.component';
import { SetupPickComponent, PickItem, family } from './setup-pick.component';
import { ServiceCheck, ServiceRow, SetupServicesComponent } from './setup-services.component';
import { BrainCatalog, BrainChoice, CloudProvider, Download, LocalModel, Runtime, SetupApi, SetupState, TunnelState, VoiceCatalog, VoiceOption, VoiceProvider, VoiceStep, setupError } from './setup.api';

type Screen = 'benvenuto' | 'modelli' | 'memoria' | 'cervello' | 'ascolto' | 'voce' | 'telegram' | 'backup' | 'esterni' | 'fuori' | 'pronto';
/** What the server stores, derived from the choices: something at home, something in the cloud, or both. «claude»
 * (Claude Code as the whole brain) is not offered here: the Claude subscription is one of the cloud services. */
type Recipe = 'locale' | 'cloud' | 'entrambi';
type VoiceDir = 'ascolto' | 'voce';
const CLAUDE_TYPE = 'claude_cli';
/** Where to get a key, by provider type or name. */
const KEY_LINKS: Record<string, string> = {
  gemini: 'https://aistudio.google.com/apikey',
  deepseek: 'https://platform.deepseek.com/api_keys',
  anthropic: 'https://console.anthropic.com/settings/keys',
  openai: 'https://platform.openai.com/api-keys',
};
const SCREEN_KEY = 'hestia_setup_screen';
/** Other computers of the house to look on for models and speech programs. */
const HOSTS_KEY = 'hestia_setup_hosts';
/** The side summary: one line per screen. */
const TITLES: Record<Screen, string> = {
  benvenuto: 'Inizio', modelli: 'Modelli', memoria: 'Memoria', cervello: 'Modelli pronti', ascolto: 'Ascolto',
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
  imports: [...UI, FormsModule, RouterLink, SetupPickComponent, SetupChainComponent, PluginOutletComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="wrap">
      <div class="top">
        <div class="dots" aria-hidden="true">
          @for (s of screens(); track s; let i = $index) { <span [class.on]="i <= index()"></span> }
        </div>
        @if (state()) {
          <button type="button" class="sumbtn" (click)="sheet.set(true)" aria-label="Riepilogo e download">
            <hx-icon name="list" [size]="15" /> Riepilogo
            @if (activeDownloads()) { <span class="badge">{{ activeDownloads() }}</span> }
          </button>
        }
        <a class="out" routerLink="/home" (click)="leave()">Finisco dopo</a>
      </div>

      <div class="cols">
      @if (state()) {
        <aside class="side" [class.open]="sheet()" aria-label="Riepilogo e download">
          <div class="sheet-head"><button hx-btn variant="ghost" size="sm" icon="x" iconOnly aria-label="Chiudi" (click)="sheet.set(false)"></button></div>
          <nav class="hx-card panel">
            <div class="ph"><hx-icon name="list" [size]="15" tone="muted" /> Riepilogo</div>
            <ol class="sum">
              @for (s of screens(); track s; let i = $index) {
                <li>
                  <button type="button" [class.cur]="s === screen()" [disabled]="!canJump(s)" (click)="jump(s)">
                    <hx-icon [name]="stepIcon(s)" [size]="15" [tone]="stepTone(s)" />
                    <span><b>{{ title(s) }}</b>@if (stepNote(s); as n) { <small>{{ n }}</small> }</span>
                  </button>
                </li>
              }
            </ol>
          </nav>
          @if (downloads().length) {
            <section class="hx-card panel">
              <div class="ph"><hx-icon name="download" [size]="15" tone="muted" /> Download</div>
              <p class="note">I modelli li scarica Ollama sul tuo computer, le voci finiscono nella cartella di Hestia. Vanno avanti da soli mentre continui.</p>
              <ul class="list dl">
                @for (d of downloads(); track (d.module || '') + d.id) {
                  <li>
                    <hx-icon [name]="d.state === 'fatto' ? 'check-circle' : d.state === 'errore' ? 'alert' : 'download'" [size]="16"
                             [tone]="d.state === 'fatto' ? 'success' : d.state === 'errore' ? 'danger' : 'info'" />
                    <span><b>{{ d.what }}</b><small>{{ downloadText(d) }}</small>
                      @if (d.state === 'in_corso' && d.size) { <span class="bar"><span [style.width.%]="100 * d.done / d.size"></span></span> }
                    </span>
                  </li>
                }
              </ul>
              <a class="more" href="/download" target="_blank" rel="noopener">Apri la pagina Download <hx-icon name="external" [size]="13" /></a>
            </section>
          }
        </aside>
        @if (sheet()) { <div class="scrim" (click)="sheet.set(false)"></div> }
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

            @case ('modelli') {
              <hx-icon name="brain" [size]="30" tone="accent" />
              <h1>Con quali modelli pensa?</h1>
              <p class="lead">Rispondono a tutto (modalità Generale): prima quello in casa, poi i servizi cloud in ordine, se il primo non risponde o ha finito la quota. Scegli almeno uno.</p>
              <app-setup-chain [homeItems]="localItems()" [home]="localKey()" (homeChange)="pickLocalKey($event)" [programs]="programs()"
                               homeEmpty="In casa non ho trovato programmi per i modelli. Installane uno (sono gratis), aprilo e premi «Cerca di nuovo», oppure usa solo il cloud."
                               [hosts]="hosts()" [searching]="searching()" (addHost)="addHost($event)" (removeHost)="removeHost($event)" (again)="searchAgain()"
                               [services]="cloudRows()" [tester]="chatTester" [(order)]="cloudPicked" [(picks)]="cloudModel" [(ready)]="cloudReady" [(tokens)]="cloudTokens">
                <div home-extra>
                  @if (hasOllama()) {
                    <hx-field label="Oppure un altro modello di Ollama" hint="Il nome come su ollama.com/library, per esempio qwen3:32b. Se non c'è, Ollama lo scarica.">
                      <input class="hx-input mono" autocomplete="off" spellcheck="false" [ngModel]="otherModel()" (ngModelChange)="typeLocal($event)" placeholder="nome:versione" />
                    </hx-field>
                  }
                </div>
              </app-setup-chain>
              <section class="modes">
                <div class="sub">Per modalità <small>di solito tutte usano i modelli qui sopra; se vuoi, una modalità può avere il suo modello (prima quello, poi questi).</small></div>
                @for (m of modeList; track m.id) {
                  <div class="moderow">
                    <span class="ct"><b>{{ m.label }}</b><small>{{ m.help }} · {{ modeText(m.id) }}</small></span>
                    <button type="button" class="linkbtn" (click)="openMode.set(openMode() === m.id ? '' : m.id)">{{ openMode() === m.id ? 'Fatto' : 'Cambia' }}</button>
                  </div>
                  @if (openMode() === m.id) {
                    <app-setup-pick [items]="modeItems()" [selected]="modes()[m.id] || ''" [limit]="5" placeholder="Cerca un modello"
                                    empty="Scegli prima un modello qui sopra." (picked)="pickMode(m.id, $event)" />
                  }
                }
              </section>
            }

            @case ('memoria') {
              <hx-icon name="memory" [size]="30" tone="accent" />
              <h1>Con quale modello ricorda?</h1>
              <p class="lead">Serve a ritrovare ricordi e documenti. Uno solo, in casa o nel cloud: se lo cambi, Hestia rilegge la memoria e ci vuole un po'.</p>
              <app-setup-chain [single]="true" [homeItems]="embedHomeItems()" [(home)]="embedHome" [programs]="programs()"
                               homeEmpty="In casa non ho trovato programmi per i modelli: usa un modello per la memoria di un servizio cloud, oppure installa Ollama e premi «Cerca di nuovo»."
                               [hosts]="hosts()" [searching]="searching()" (addHost)="addHost($event)" (removeHost)="removeHost($event)" (again)="searchAgain()"
                               [services]="embedRows()" [tester]="embedTester" optionsLabel="Modello" cloudEmpty="Nessun servizio cloud con modelli per la memoria."
                               [(order)]="embedOrder" [(picks)]="embedPicks" [(ready)]="embedReady" [(tokens)]="embedTokens" />
            }

            @case ('cervello') {
              <hx-icon name="check-circle" [size]="30" tone="success" />
              <h1>I modelli sono pronti</h1>
              <p class="lead">{{ state()!.brain.summary || 'Fatto.' }}</p>
              @if (activeDownloads()) { <p class="hint"><hx-icon name="download" [size]="15" tone="info" /> {{ downloadHint() }}</p> }
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
              <p class="lead">Collegali qui, oppure quando ti servono dalla pagina Dispositivi: sono le stesse schede.</p>
              <div class="outlets">
                <hx-plugin-outlet module="hecate" element="hecate-google" />
                <hx-plugin-outlet module="hecate" element="hecate-garmin" />
              </div>
              <p class="hint">Il telefono come sensore (a casa, in carica) si prepara da <a href="/p/hecate/dispositivi" target="_blank" rel="noopener">Dispositivi <hx-icon name="external" [size]="12" /></a>.</p>
            }

            @case ('fuori') {
              <hx-icon name="cloud" [size]="30" tone="accent" />
              <h1>Usare Hestia fuori casa</h1>
              @if (tunnel()?.on && tunnel()!.url) {
                <p class="ok"><hx-icon name="check-circle" [size]="16" tone="success" /> Fatto. Da fuori casa, anche senza il Wi-Fi di casa, apri:</p>
                <div class="urlrow">
                  <span class="code mono small">{{ tunnel()!.url }}</span>
                  <a hx-btn variant="primary" icon="external" [href]="tunnel()!.url" target="_blank" rel="noopener">Provalo</a>
                  <button hx-btn variant="ghost" icon="copy" (click)="copyUrl()">{{ copied() ? 'Copiato' : 'Copia' }}</button>
                </div>
                <p class="hint">Ti chiede l'accesso, come qui. L'indirizzo cambia quando Hestia si riavvia: il bot su Telegram ti dà sempre quello giusto.</p>
                <div class="row"><button hx-btn variant="ghost" size="sm" icon="x" [loading]="busy()" (click)="switchTunnel(false)">Spegni</button></div>
              } @else if (busy() || tunnel()?.on || tunnel()?.phase === 'error') {
                @if (tunnel()?.phase === 'error' || tunnelLate()) {
                  <p class="warn"><hx-icon name="alert" [size]="15" tone="warning" /> {{ tunnel()?.phase === 'error' ? tunnel()!.detail : 'L\'indirizzo non arriva. Di solito è la rete che blocca Cloudflare (ufficio, scuola) o internet che non va.' }}</p>
                  <div class="row">
                    <button hx-btn variant="ghost" icon="x" (click)="switchTunnel(false)">Spegni</button>
                    <button hx-btn variant="secondary" icon="refresh" (click)="retryTunnel()">Riprova</button>
                  </div>
                } @else {
                  <ol class="steps">
                    @for (st of tunnelSteps; track st.id; let i = $index) {
                      <li>
                        @if (tunnelStep() > i) { <hx-icon name="check-circle" [size]="16" tone="success" /> }
                        @else if (tunnelStep() === i) { <hx-spinner /> }
                        @else { <hx-icon name="minus" [size]="16" tone="muted" /> }
                        {{ st.label }}
                      </li>
                    }
                  </ol>
                  <p class="hint">Puoi andare avanti: continua da solo, il download lo vedi a lato.</p>
                }
              } @else {
                <p class="lead">Dal telefono, fuori casa, apri Hestia con un indirizzo internet sicuro. Senza, Hestia si usa solo in casa e da Telegram.</p>
                <p class="hint">Se lo attivi: scarico e avvio un piccolo programma di Cloudflare (gratis, senza account) che crea un indirizzo che porta qui. Da quell'indirizzo Hestia chiede sempre l'accesso; in casa resta come ora. Lo spegni quando vuoi da questa pagina.</p>
                <div class="row start"><button hx-btn variant="primary" icon="cloud" [loading]="busy()" (click)="switchTunnel(true)">Attiva l'indirizzo</button></div>
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
            }
          }

          @if (voiceDir(); as dir) {
            <hx-icon [name]="dir.id === 'ascolto' ? 'mic' : 'volume'" [size]="30" tone="accent" />
            <h1>{{ dir.question }}</h1>
            <p class="lead">{{ dir.lead }}</p>
            @if (!voiceCat()) {
              @if (voiceError()) { <p class="warn"><hx-icon name="alert" [size]="15" tone="warning" /> {{ voiceError() }}</p> } @else { <div class="center"><hx-spinner /></div> }
            } @else {
              <app-setup-chain [homeItems]="voiceLocalItems(dir.id)" [home]="voiceLocalPick()[dir.id]" (homeChange)="setVoice(voiceLocalPick, dir.id, $event)"
                               homeEmpty="In casa non ho trovato programmi per la voce."
                               [hosts]="hosts()" [searching]="searching()" (addHost)="addHost($event)" (removeHost)="removeHost($event)" (again)="searchAgain()"
                               [services]="voiceCloudRows(dir.id)" [tester]="voiceTester(dir.id)" [optionsLabel]="dir.id === 'ascolto' ? 'Modelli' : 'Voci'"
                               [order]="voiceOrder()[dir.id]" (orderChange)="setVoice(voiceOrder, dir.id, $event)"
                               [picks]="voicePicks()[dir.id]" (picksChange)="setVoice(voicePicks, dir.id, $event)"
                               [ready]="voiceReadyMap()[dir.id]" (readyChange)="setVoice(voiceReadyMap, dir.id, $event)">
                <div home-extra>
                  @if (voiceLocal(dir.id).length) {
                    <ul class="engines">
                      @for (p of voiceLocal(dir.id); track p.name) { <li><b>{{ engineName(p) }}</b> {{ p.note }}</li> }
                    </ul>
                  }
                </div>
              </app-setup-chain>
            }
          }

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
    .top { display: flex; align-items: center; gap: 12px; min-height: 32px; }
    .sumbtn { display: none; align-items: center; gap: 6px; font-size: 13px; color: var(--text-2); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-full); padding: 4px 10px; }
    .badge { font-size: 11px; font-weight: 600; color: var(--accent); background: var(--accent-soft); border-radius: var(--radius-full); padding: 0 6px; }
    .dots { flex: 1; display: flex; gap: 6px; }
    .dots span { width: 8px; height: 8px; border-radius: var(--radius-full); background: var(--surface-3); transition: background var(--dur) var(--ease); }
    .dots span.on { background: var(--accent); }
    .out { font-size: 13px; color: var(--text-3); white-space: nowrap; }
    .cols { display: grid; grid-template-columns: 240px minmax(0, 560px); gap: 16px; align-items: start; justify-content: end; }
    .side { position: sticky; top: 0; display: flex; flex-direction: column; gap: 12px; }
    .sheet-head { display: none; }
    .panel { padding: 12px 10px; display: flex; flex-direction: column; gap: 8px; }
    .ph { display: flex; gap: 6px; align-items: center; font-size: 13px; font-weight: 600; color: var(--text-2); padding: 0 4px; }
    .note { font-size: 12px; color: var(--text-3); line-height: 1.4; padding: 0 4px; }
    .more { font-size: 12px; display: inline-flex; gap: 4px; align-items: center; padding: 0 4px; }
    .sum { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 2px; }
    .sum button { display: flex; gap: 8px; align-items: flex-start; width: 100%; text-align: left; padding: 6px; border-radius: var(--radius-sm); background: none; color: var(--text); border: 0; }
    .sum button:hover:not(:disabled) { background: var(--surface-2); }
    .sum button.cur { background: var(--accent-soft); }
    .sum button:disabled { opacity: .55; cursor: default; }
    .sum button span { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
    .sum b { font-size: 13px; font-weight: 600; }
    .sum small { font-size: 12px; color: var(--text-3); overflow-wrap: anywhere; }
    .dl { gap: 10px; padding: 0 4px; }
    .dl b { font-size: 13px; overflow-wrap: anywhere; }
    .dl small { font-size: 12px; }
    .sub { font-size: 13px; font-weight: 600; color: var(--text-2); }
    .sub small { font-weight: 400; color: var(--text-3); }
    .linkbtn { align-self: flex-start; background: none; border: 0; color: var(--accent); font-size: 13px; padding: 2px 0; }
    .scrim { display: none; }
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
    .outlets { display: flex; flex-direction: column; gap: 12px; }
    .outlets hx-plugin-outlet { flex: none; }
    .modes { display: flex; flex-direction: column; gap: 8px; padding-top: 14px; border-top: 1px solid var(--border); }
    .moderow { display: flex; gap: 10px; align-items: center; }
    .moderow .linkbtn { align-self: center; }
    .vdir { display: flex; flex-direction: column; gap: 10px; padding-top: 6px; }
    .vdir + .vdir { border-top: 1px solid var(--border); padding-top: 16px; }
    .vdir h2 { display: flex; gap: 8px; align-items: center; font-size: 17px; font-weight: 600; color: var(--text); }
    .vdir h2 small { font-size: 13px; font-weight: 400; color: var(--text-3); }
    .engines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--text-2); line-height: 1.45; }
    .engines b { color: var(--text); font-weight: 600; }
    .urlrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .urlrow .code { flex: 1 1 220px; min-width: 0; text-align: left; }
    .row.start { justify-content: flex-start; }
    .note2 { font-size: 12px; color: var(--text-3); line-height: 1.4; margin-top: -6px; }
    .hostrow { display: flex; gap: 8px; align-items: flex-end; flex-wrap: wrap; }
    .hostrow hx-field { flex: 1 1 240px; min-width: 0; }
    .chip { display: inline-flex; gap: 4px; align-items: center; font-size: 12px; background: var(--surface-2); border-radius: var(--radius-full); padding: 1px 4px 1px 9px; }
    .chip button { background: none; border: 0; padding: 2px; color: var(--text-3); display: inline-flex; }
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
      .sumbtn { display: inline-flex; }
      /* Phone: the summary and the downloads are a panel from the button at the top, not a block above the question. */
      .side { position: fixed; z-index: 41; top: 0; right: 0; bottom: 0; width: min(340px, 88vw); overflow-y: auto; padding: 14px 12px;
              background: var(--bg); box-shadow: var(--shadow-lg, 0 0 24px rgba(0,0,0,.2)); transform: translateX(100%);
              transition: transform var(--dur) var(--ease); visibility: hidden; }
      .side.open { transform: none; visibility: visible; }
      .sheet-head { display: flex; justify-content: flex-end; }
      .scrim { display: block; position: fixed; inset: 0; z-index: 40; background: rgba(0,0,0,.35); }
    }
    @media (max-width: 480px) { .card { padding: 22px 16px 16px; } h1 { font-size: 22px; } .code { font-size: 30px; } }
  `],
})
export class SetupPageComponent {
  private api = inject(SetupApi);
  private router = inject(Router);
  readonly claudeType = CLAUDE_TYPE;
  /** Phone: the summary + downloads panel, opened from the button at the top. */
  sheet = signal(false);

  state = signal<SetupState | null>(null);
  catalog = signal<BrainCatalog | null>(null);
  downloads = signal<Download[]>([]);
  loadError = signal('');
  busy = signal(false);
  formError = signal('');
  showPass = signal(false);
  code = signal('');
  searching = signal(false);

  /** The home choice of «Modelli» as «program|model» ('' = nothing at home). */
  localKey = signal('');
  localProvider = computed(() => this.localKey().split('|')[0] || 'ollama');
  localModel = computed(() => this.localKey().split('|').slice(1).join('|'));
  useLocal = computed(() => !!this.localModel());
  useCloud = computed(() => this.cloudPicked().length > 0);
  recipe = computed<Recipe>(() => this.useLocal() && this.useCloud() ? 'entrambi' : this.useLocal() ? 'locale' : 'cloud');
  /** «Memoria»: one model, at home («program|model») or one cloud service with one model. */
  embedHome = signal('');
  embedOrder = signal<string[]>([]);
  embedPicks = signal<Record<string, string[]>>({});
  embedReady = signal<Record<string, boolean>>({});
  embedTokens = signal<Record<string, string>>({});
  /** The chosen cloud services, in the order they are tried. */
  cloudPicked = signal<string[]>([]);
  /** Per service: the models chosen, in order (the next takes over when the first fails); usable or not; the Claude code. */
  cloudModel = signal<Record<string, string[]>>({});
  cloudReady = signal<Record<string, boolean>>({});
  cloudTokens = signal<Record<string, string>>({});
  botToken = '';
  passphrase = '';

  screen = signal<Screen>('benvenuto');
  /** The furthest screen reached in this run: the summary jumps back freely, forward only up to here. */
  reached = signal(0);
  /** The screens: Modelli, Memoria, Ascolto and Voce are the same step (app-setup-chain) on a different module. */
  screens = signal<Screen[]>(['benvenuto', 'modelli', 'memoria', 'cervello', 'ascolto', 'voce', 'telegram', 'backup', 'esterni', 'fuori', 'pronto']);
  index = computed(() => Math.max(0, this.screens().indexOf(this.screen())));
  optional = computed(() => (['ascolto', 'voce'].includes(this.screen()) && !this.voiceQueued())
    || (['telegram', 'backup'].includes(this.screen()) && !this.stepDone(this.screen())));
  voiceQueued = signal(false);
  tunnel = signal<TunnelState | null>(null);
  private tunnelSince = signal(0);
  private now = signal(Date.now());
  /** Patience counts only while waiting for the address (the download before it can take longer). */
  tunnelLate = computed(() => this.tunnel()?.phase === 'address' && !!this.tunnelSince() && this.now() - this.tunnelSince() > TUNNEL_PATIENCE_MS);
  readonly tunnelSteps = [
    { id: 'download', label: 'Scarico il programma di Cloudflare (solo la prima volta)' },
    { id: 'start', label: 'Lo avvio' },
    { id: 'address', label: 'Aspetto l\'indirizzo da Cloudflare' },
  ];
  tunnelStep = computed(() => {
    const ph = this.tunnel()?.phase || (this.busy() ? 'start' : '');
    return ph === 'download' ? 0 : ph === 'start' ? 1 : ph === 'address' ? 2 : ph === 'ready' ? 3 : 1;
  });

  // ── Voce (Echo's blocks, the same cards as the cloud services) ──
  readonly voiceDirs = [
    { id: 'ascolto' as const, question: 'Come ti ascolta?', lead: 'Per capire quello che dici. In casa è gratis e privato: scarico subito quello che serve, così la prima volta non aspetti. Nel cloud serve una chiave.' },
    { id: 'voce' as const, question: 'Con che voce ti risponde?', lead: 'In casa è gratis e privato: scarico subito la voce, così la prima volta non aspetti. Nel cloud serve una chiave.' },
  ];
  /** The voice screen open now (Ascolto or Voce): the same step, one direction each. */
  voiceDir = computed(() => this.voiceDirs.find(d => d.id === this.screen()) || null);
  voiceCat = signal<VoiceCatalog | null>(null);
  voiceError = signal('');
  /** Per direction: the local engine and its model/voice as «provider|id» (one), then cloud services in order. */
  voiceLocalPick = signal<Record<VoiceDir, string>>({ ascolto: '', voce: '' });
  voiceOrder = signal<Record<VoiceDir, string[]>>({ ascolto: [], voce: [] });
  voicePicks = signal<Record<VoiceDir, Record<string, string[]>>>({ ascolto: {}, voce: {} });
  voiceReadyMap = signal<Record<VoiceDir, Record<string, boolean>>>({ ascolto: {}, voce: {} });

  async loadVoice() {
    this.voiceError.set('');
    try {
      const cat = await this.api.voiceCatalog(this.hosts());
      this.voiceCat.set(cat);
      const saved = this.state()?.voice || {};
      const local: Record<VoiceDir, string> = { ascolto: '', voce: '' };
      const order: Record<VoiceDir, string[]> = { ascolto: [], voce: [] };
      const picks: Record<VoiceDir, Record<string, string[]>> = { ascolto: {}, voce: {} };
      for (const d of this.voiceDirs) {
        const own = d.id === 'ascolto' ? saved.listen : saved.speak;
        // what the user chose in the setup, else the chain in use; never Hestia's defaults for services without a key
        const steps: VoiceStep[] = (Array.isArray(own) ? own : own?.provider ? [own] : null) || cat[d.id].steps || (cat[d.id].current?.provider ? [cat[d.id].current] : []);
        const byName = (n: string) => cat[d.id].providers.find(p => p.name === n);
        for (const st of steps) {
          const p = byName(st.provider);
          if (!p) continue;
          const id = d.id === 'ascolto' ? st.model : st.voice;
          if (p.local) { if (!local[d.id]) local[d.id] = `${p.name}|${id || this.optionsOf(p, d.id)[0]?.id || ''}`; }
          else if (p.key || !p.needs_key) {   // a cloud service is preselected only when its key is saved
            if (!order[d.id].includes(p.name)) order[d.id].push(p.name);
            if (id) picks[d.id][p.name] = [...(picks[d.id][p.name] || []), id];
          }
        }
        if (!local[d.id]) local[d.id] = this.voiceLocalItems(d.id, cat)[0]?.id || '';
      }
      this.voiceLocalPick.set(local);
      this.voiceOrder.set(order);
      this.voicePicks.set(picks);
    } catch (e) {
      this.voiceError.set(setupError(e));
    }
  }
  setVoice<T>(sig: WritableSignal<Record<VoiceDir, T>>, dir: VoiceDir, value: T) { sig.set({ ...sig(), [dir]: value }); }
  private optionsOf(p: VoiceProvider, dir: VoiceDir) { return dir === 'ascolto' ? p.models : p.voices; }
  voiceLocal(dir: VoiceDir): VoiceProvider[] { return (this.voiceCat()?.[dir].providers || []).filter(p => p.local); }
  engineName(p: VoiceProvider): string { return p.label.replace(/\s*\(.*\)\s*$/, ''); }
  /** Every local engine's models (listening) or voices (speaking) in one list: one is chosen. */
  voiceLocalItems(dir: VoiceDir, cat = this.voiceCat()): PickItem[] {
    const out: PickItem[] = [];
    for (const p of (cat?.[dir].providers || []).filter(x => x.local)) {
      const many = (cat?.[dir].providers || []).filter(x => x.local).length > 1;
      this.optionsOf(p, dir).forEach((o, i) => out.push({
        id: `${p.name}|${o.id}`, title: many ? `${this.engineName(p)} · ${o.label}` : o.label, icon: dir === 'ascolto' ? 'mic' : 'volume',
        note: o.note || (p.state === 'ready' ? '' : 'Lo scarico quando confermi.'),
        tag: dir === 'voce' && p.type === 'kokoro' && i === 0 ? 'Consigliato' : '' }));
    }
    return out;
  }
  voiceCloudRows(dir: VoiceDir): ServiceRow[] {
    return (this.voiceCat()?.[dir].providers || []).filter(p => !p.local).map(p => ({
      name: p.name, label: p.label, icon: 'zap', kind: p.needs_key ? 'key' as const : 'none' as const, keySet: p.key, note: p.note || (p.key ? '' : 'Serve una chiave.') }));
  }
  private voiceTesters: Partial<Record<VoiceDir, (name: string, key: string) => Promise<ServiceCheck>>> = {};
  /** «Prova» of a voice service (a typed key is saved first, then its list is read: nothing spent). */
  voiceTester(dir: VoiceDir) {
    return this.voiceTesters[dir] ||= async (name: string, key: string): Promise<ServiceCheck> => {
      const toCheck = (r: { ok: boolean; detail?: string; models?: VoiceOption[]; voices?: VoiceOption[]; recommended?: Record<string, string[]> }): ServiceCheck => {
        const rows = (dir === 'ascolto' ? r.models : r.voices) || [];
        return { ok: r.ok, detail: r.detail, recommended: r.recommended?.[dir] || [],
                 options: rows.map(o => ({ id: o.id, title: o.label, note: o.note || '', icon: dir === 'ascolto' ? 'mic' : 'volume' })) };
      };
      try {
        const r = await this.api.voiceTest(name, key);
        if (key) this.markVoiceKey(name);
        return toCheck(r);
      } catch (e) {
        // A slow restart can drop the answer while the key was saved: if it is there, read the list again.
        const saved = key ? await this.api.voiceCatalog().then(c => [...c.ascolto.providers, ...c.voce.providers].some(p => p.name === name && p.key)).catch(() => false) : false;
        if (saved) { this.markVoiceKey(name); return toCheck(await this.api.voiceTest(name, '')); }
        throw new Error(setupError(e));
      }
    };
  }
  private markVoiceKey(name: string) {
    const c = this.voiceCat();
    if (!c) return;
    const mark = (list: VoiceProvider[]) => list.map(p => p.name === name ? { ...p, key: true } : p);
    this.voiceCat.set({ ascolto: { ...c.ascolto, providers: mark(c.ascolto.providers) }, voce: { ...c.voce, providers: mark(c.voce.providers) } });
  }
  /** The chain of one direction: the local choice, then each cloud service with its models/voices in order. */
  private voiceSteps(dir: VoiceDir): VoiceStep[] {
    const out: VoiceStep[] = [];
    const [lp, ...lid] = (this.voiceLocalPick()[dir] || '').split('|');
    const one = (provider: string, id: string): VoiceStep => ({ provider, model: dir === 'ascolto' ? id : '', voice: dir === 'voce' ? id : '' });
    if (lp) {
      const p = this.voiceLocal(dir).find(x => x.name === lp);
      out.push({ ...one(lp, lid.join('|')), ...(p?.found && p.url ? { url: p.url, type: p.type, label: p.label } : {}) });
    }
    for (const n of this.voiceOrder()[dir]) {
      const ids = this.voicePicks()[dir][n] || [];
      if (ids.length) ids.forEach(id => out.push(one(n, id)));
      else out.push(one(n, ''));
    }
    return out;
  }
  /** One direction can go on: something chosen at home or in the cloud, and every cloud service chosen usable. */
  voiceOk(dir: VoiceDir): boolean {
    if (!this.voiceCat()) return false;
    const order = this.voiceOrder()[dir];
    return (!!this.voiceLocalPick()[dir] || order.length > 0) && order.every(n => this.voiceReadyMap()[dir][n]);
  }

  constructor() {
    inject(PluginsService).start();   // the «Google» and «Garmin» cards of the esterni screen are Hecate's plugin elements
    const timer = setInterval(() => this.poll(), 3000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
    void this.load();
  }

  async load() {
    this.loadError.set('');
    try {
      const [state, catalog] = await Promise.all([this.api.state(), this.api.catalog(this.hosts()).catch(() => null)]);
      this.state.set(state);
      if (catalog) this.useCatalog(catalog, state, true);
      const saved = stored(SCREEN_KEY) as Screen;
      this.screen.set(this.screens().includes(saved) ? saved : this.firstOpen(state));
      this.reached.set(state.brain.recipe ? this.screens().length - 1 : this.index());
      if (this.screen() === 'ascolto' || this.screen() === 'voce') void this.loadVoice();
      this.api.tunnel().then(t => this.tunnel.set(t)).catch(() => undefined);
      void this.refreshDownloads();
    } catch (e) {
      this.loadError.set(setupError(e));
    }
  }

  /** Apply a catalog: the saved answers first, otherwise the best guess (first fitting model of the first program
   * found). A cloud service is preselected only when its key (or the Claude code) is already saved. */
  private useCatalog(catalog: BrainCatalog, state: SetupState, first: boolean) {
    this.catalog.set(catalog);
    const found = (catalog.runtimes || []).filter(r => r.found);
    const has = (p: string, m: string) => found.some(r => r.name === p && r.models.some(x => x.model === m));
    const savedProvider = state.brain.local_provider || 'ollama';
    const keep = this.localModel() && (has(this.localProvider(), this.localModel()) || this.otherModel());
    if (!keep && !(first && state.brain.recipe === 'cloud')) {
      const firstFit = found.map(r => ({ r, m: r.models.find(m => m.fits) || r.models[0] })).find(x => x.m);
      if (state.brain.local_model && has(savedProvider, state.brain.local_model)) this.localKey.set(`${savedProvider}|${state.brain.local_model}`);
      else if (firstFit) this.localKey.set(`${firstFit.r.name}|${firstFit.m!.model}`);
      else if (found.some(r => r.name === 'ollama')) this.localKey.set(`ollama|${state.brain.local_model || catalog.recommended.model}`);
      else this.localKey.set('');
    }
    if (first) {
      const cloud = catalog.cloud;
      const keyed = (p: CloudProvider) => p.type === CLAUDE_TYPE ? !!state.claude.token || p.available : p.key_set;
      let picked = (state.brain.cloud || []).filter(n => cloud.some(p => p.name === n));
      if (!state.brain.recipe) picked = cloud.filter(keyed).map(p => p.name);
      this.cloudPicked.set(picked);
      const models: Record<string, string[]> = {};
      for (const [k, v] of Object.entries(state.brain.cloud_models || {})) models[k] = (Array.isArray(v) ? v : [v]).filter(Boolean);
      this.cloudModel.set(models);
      const modes: Record<string, string> = {};
      for (const [k, v] of Object.entries(state.brain.modes || {})) if (v?.model) modes[k] = `${v.provider || 'ollama'}|${v.model}`;
      this.modes.set(modes);
      // «Memoria»: the model in use (at home or in the cloud), else the recommended one at home
      const now = catalog.embedding;
      const nowProvider = now?.provider || 'ollama';
      if (now?.model && cloud.some(p => p.name === nowProvider)) {
        this.embedOrder.set([nowProvider]);
        this.embedPicks.set({ [nowProvider]: [now.model] });
        this.embedHome.set('');
      }
    }
    if (!this.embedOrder().length && !this.embedItemsHas(this.embedHome())) this.embedHome.set(this.embedHomeItems()[0]?.id || '');
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
    if ((screen === 'ascolto' || screen === 'voce') && !this.voiceCat()) void this.loadVoice();
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
  jump(s: Screen) { if (this.canJump(s)) { this.go(s); this.sheet.set(false); } }
  private isDone(s: Screen): boolean {
    const st = this.state();
    if (!st) return false;
    switch (s) {
      case 'benvenuto': return this.reached() > 0;
      case 'modelli': case 'memoria': case 'cervello': return !!st.brain.recipe;
      case 'ascolto': case 'voce': return this.voiceQueued();
      case 'telegram': return st.telegram.linked;
      case 'backup': return st.backup.passphrase;
      case 'esterni': return false;   // optional cards, connected now or later
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
      case 'modelli': return [this.localModel(), ...this.cloudPicked().map(n => this.cloudLabel(n))].filter(Boolean).join(', ');
      case 'memoria': { const c = this.embeddingWanted(); return c ? c.model : ''; }
      case 'ascolto': case 'voce': return this.voiceQueued() ? 'In download' : st.later.includes('voce') ? 'Più tardi' : '';
      case 'telegram': return st.telegram.linked ? 'Collegato' : st.later.includes('telegram') ? 'Più tardi' : '';
      case 'backup': return st.backup.passphrase ? 'Pronto' : st.later.includes('backup') ? 'Più tardi' : '';
      case 'fuori': return this.tunnel()?.on ? 'Attivo' : '';
      default: return '';
    }
  }

  canNext(): boolean {
    switch (this.screen()) {
      case 'modelli': return (this.useLocal() || this.useCloud()) && this.cloudPicked().every(n => this.cloudReady()[n]);
      case 'memoria': return this.embedOrder().every(n => this.embedReady()[n]) && (!!this.embeddingWanted() || !!this.catalog()?.embedding?.model);
      case 'ascolto': case 'voce': return this.voiceQueued() || this.voiceOk(this.screen() as VoiceDir);
      case 'telegram': return this.state()!.telegram.linked || (!this.code() && !this.state()!.telegram.token && !!this.botToken.trim());
      case 'backup': return this.state()!.backup.passphrase || this.passphrase.length >= 12;
      default: return true;
    }
  }

  nextLabel(): string {
    switch (this.screen()) {
      case 'benvenuto': return 'Iniziamo';
      case 'memoria': return 'Conferma';
      case 'telegram': return this.state()!.telegram.linked || this.code() || this.state()!.telegram.token ? 'Avanti' : 'Collega';
      case 'backup': return this.state()!.backup.passphrase ? 'Avanti' : 'Salva';
      case 'voce': return this.voiceQueued() ? 'Avanti' : 'Conferma';
      case 'ascolto': return 'Avanti';
      case 'fuori': return this.tunnel()?.on ? 'Avanti' : 'Più tardi';
      case 'pronto': return 'Inizia';
      default: return 'Avanti';
    }
  }

  async next() {
    const screen = this.screen();
    const following = this.screens()[this.index() + 1];
    this.busy.set(true);
    try {
      if (following === 'cervello') { await this.applyBrain(); return; }
      if (screen === 'voce' && !this.voiceQueued()) {
        const out = await this.api.voiceApply(this.voiceSteps('ascolto'), this.voiceSteps('voce'));
        if (!out.ok) { this.formError.set(out.detail || 'Non sono riuscito a salvare la scelta.'); return; }
        this.voiceQueued.set(true);
        void this.refreshDownloads();
        this.forward();   // the downloads go on by themselves, shown at the side
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
      if (screen === 'fuori' && !this.tunnel()?.on) await this.api.later('fuori').then(s => this.state.set(s)).catch(() => undefined);
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
    const step = this.screen() === 'ascolto' ? 'voce' : this.screen();   // the voice is one step on the server
    try { this.state.set(await this.api.later(step)); } catch { /* the step stays open: nothing lost */ }
    this.forward();
  }

  // ── Modello sul computer ──
  gb(n: number): string { return String(n).replace('.', ','); }
  found = computed<Runtime[]>(() => (this.catalog()?.runtimes || []).filter(r => r.found));
  missing = computed<Runtime[]>(() => (this.catalog()?.runtimes || []).filter(r => !r.found && !r.host));
  foundNames(): string { const l = this.found().map(r => r.label); return l.length > 1 ? l.slice(0, -1).join(', ') + ' e ' + l[l.length - 1] : l[0] || ''; }
  hasOllama = computed(() => this.found().some(r => r.name === 'ollama'));
  /** The programs to install when none is found at home (the same list for Modelli and Memoria). */
  programs = computed<HomeProgram[]>(() => this.missing().map(r => ({ name: r.name, label: r.label, site: r.site, note: this.runtimeText(r) })));
  /** Every model of every program found, in one searchable list; an empty Ollama gets the suggestions to download. */
  localItems = computed<PickItem[]>(() => {
    const many = this.found().length > 1;
    const out: PickItem[] = [];
    for (const r of this.found()) {
      for (const m of r.models) {
        out.push({ id: `${r.name}|${m.model}`, title: m.model, warn: !m.fits, group: many ? r.label : family(m.model),
                   note: [many ? r.label : '', this.localText(m)].filter(Boolean).join(' · ') });
      }
      if (r.name === 'ollama' && !r.models.length) {
        (this.catalog()?.recommended?.chat || []).forEach((m, i) => out.push({
          id: `ollama|${m.model}`, title: m.model, icon: 'download', tag: i === 0 ? 'Consigliato' : '',
          note: `${m.good} ${this.gb(m.size_gb)} GB da scaricare: Ollama lo scarica mentre finisci il resto.` }));
      }
    }
    return out;
  });
  /** A tap on the list (again on the chosen one = nothing at home). */
  pickLocalKey(key: string) { this.localKey.set(key); this.otherModel.set(''); }
  otherModel = signal('');
  typeLocal(name: string) {
    this.otherModel.set(name);
    const clean = name.trim();
    this.localKey.set(clean ? `ollama|${clean}` : '');
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
  /** «Cerca di nuovo» / another computer added: the models and the speech programs are looked for again. */
  async searchAgain() {
    this.searching.set(true);
    try {
      const voice = ['ascolto', 'voce'].includes(this.screen()) || !!this.voiceCat();
      await Promise.all([
        this.api.catalog(this.hosts()).then(c => this.useCatalog(c, this.state()!, false)).catch(() => undefined),
        voice ? this.loadVoice() : Promise.resolve(),
      ]);
    } finally { this.searching.set(false); }
  }
  // ── Other computers of the house (Hestia on a Raspberry, the models on the PC): remembered in this browser ──
  hosts = signal<string[]>(stored(HOSTS_KEY).split(',').map(h => h.trim()).filter(Boolean));
  async addHost(raw: string) {
    const h = raw.trim().replace(/^https?:\/\//, '').split(/[/:]/)[0];
    if (!h) return;
    this.hosts.set([...this.hosts().filter(x => x !== h), h].slice(-4));
    store(HOSTS_KEY, this.hosts().join(','));
    await this.searchAgain();
  }
  async removeHost(h: string) {
    this.hosts.set(this.hosts().filter(x => x !== h));
    store(HOSTS_KEY, this.hosts().join(','));
    await this.searchAgain();
  }

  // ── Memoria: the same step on the embedding models ──
  /** At home: the model in use (when it still runs there), every embedding model the programs have, and Ollama's
   * recommended one when Ollama has none. */
  embedHomeItems = computed<PickItem[]>(() => {
    const now = this.catalog()?.embedding;
    const nowKey = now?.model ? `${now.provider || 'ollama'}|${now.model}` : '';
    const many = this.found().length > 1;
    const out: PickItem[] = [];
    const nowHome = nowKey && this.found().some(r => r.name === (now!.provider || 'ollama'));
    if (nowHome) out.push({ id: nowKey, title: now!.model, icon: 'memory', tag: 'Ora', note: many ? this.runtimeLabel(now!.provider || 'ollama') : '' });
    for (const r of this.found()) {
      for (const m of r.embed) if (`${r.name}|${m}` !== nowKey) out.push({ id: `${r.name}|${m}`, title: m, icon: 'memory', note: many ? r.label : '', group: many ? r.label : '' });
      const rec = this.catalog()?.recommended?.embedding;
      if (r.name === 'ollama' && rec && !r.embed.includes(rec.model) && `ollama|${rec.model}` !== nowKey) {
        out.push({ id: `ollama|${rec.model}`, title: rec.model, icon: 'download', tag: nowHome ? '' : 'Consigliato',
                   note: `${rec.good} ${this.gb(rec.size_gb)} GB: Ollama lo scarica mentre finisci il resto.` });
      }
    }
    return out;
  });
  private embedItemsHas(id: string): boolean { return !!id && this.embedHomeItems().some(i => i.id === id); }
  /** The cloud services that can have memory models (not the Claude subscription, not Anthropic: they have none). */
  embedRows = computed<ServiceRow[]>(() => this.cloudRows().filter(r => {
    const t = this.catalog()?.cloud.find(c => c.name === r.name)?.type;
    return t !== CLAUDE_TYPE && t !== 'anthropic';
  }));
  /** The memory model chosen: at home, or the one model of the cloud service. */
  embeddingWanted(): { provider: string; model: string } | null {
    if (this.embedHome()) { const [provider, ...rest] = this.embedHome().split('|'); return { provider, model: rest.join('|') }; }
    const n = this.embedOrder()[0];
    const m = n ? (this.embedPicks()[n] || [])[0] : '';
    return n && m ? { provider: n, model: m } : null;
  }
  /** What to send: nothing when it stays the one in use (the memory is not re-read). */
  private embeddingChoice(): ({ provider: string; model: string } & { url?: string; type?: string; label?: string }) | null {
    const sel = this.embeddingWanted();
    const now = this.catalog()?.embedding;
    if (!sel || (now?.model && sel.provider === (now.provider || 'ollama') && sel.model === now.model)) return null;
    return { ...sel, ...this.runtimeOf(sel.provider) };
  }
  /** A program on another computer of the house: its address goes with the choice, so it becomes a block. */
  private runtimeOf(name: string): { url?: string; type?: string; label?: string } {
    const r = this.found().find(x => x.name === name);
    return r?.host && !r.configured ? { url: r.url, type: r.type, label: r.label } : {};
  }

  // ── Per modalità: Ragionamento, Codice, Immagini follow Generale unless one gets its own model ──
  readonly modeList = [
    { id: 'potente', label: 'Ragionamento', help: 'le domande difficili' },
    { id: 'codice', label: 'Codice', help: 'quando scrive o corregge codice' },
    { id: 'visione', label: 'Immagini', help: 'foto e documenti da guardare' },
  ];
  /** Per mode: its own model as «provider|model» (missing = same as Generale). */
  modes = signal<Record<string, string>>({});
  openMode = signal('');
  /** Same as Generale, then every model the step can use: the programs at home and the cloud services that work. */
  modeItems = computed<PickItem[]>(() => {
    const out: PickItem[] = [{ id: '', title: 'Come Generale', icon: 'check', note: 'Gli stessi modelli scelti qui sopra.' }];
    for (const it of this.localItems()) out.push({ ...it, group: 'In casa' });
    for (const n of this.cloudPicked()) {
      if (!this.cloudReady()[n]) continue;
      for (const it of this.cloudLists()[n] || []) out.push({ ...it, id: `${n}|${it.id}`, note: this.cloudLabel(n), group: this.cloudLabel(n) });
    }
    return out;
  });
  modeText(id: string): string {
    const own = this.modes()[id];
    return own ? own.split('|').slice(1).join('|') + (this.cloudPicked().includes(own.split('|')[0]) ? ' nel cloud' : '') : 'come Generale';
  }
  pickMode(mode: string, id: string) {
    const next = { ...this.modes() };
    if (id) next[mode] = id; else delete next[mode];
    this.modes.set(next);
    this.openMode.set('');
  }

  // ── Servizi cloud (the same cards as the voice's cloud services) ──
  keyLink(p: CloudProvider): string { return KEY_LINKS[p.type] || KEY_LINKS[p.name] || ''; }
  cloudLabel(name: string): string { const p = this.catalog()?.cloud.find(c => c.name === name); return p?.label || name; }
  cloudRows = computed<ServiceRow[]>(() => (this.catalog()?.cloud || []).map(p => p.type === CLAUDE_TYPE ? {
      name: p.name, label: p.label || p.name, icon: 'brain', kind: 'token' as const, keySet: !!this.state()?.claude.token || p.available,
      note: 'Il tuo abbonamento Claude Pro o Max.', tokenLabel: 'Codice dell\'abbonamento Claude', tokenPlaceholder: 'sk-ant-oat…',
      tokenHint: 'Nel terminale scrivi «claude setup-token», accedi con il tuo account Claude (Pro o Max), poi incolla qui il codice che ti dà.',
    } : {
      name: p.name, label: p.label || p.name, icon: 'unlock', kind: 'key' as const, keySet: p.key_set, keyLink: this.keyLink(p),
      tag: p.type === 'gemini' ? 'Gratis' : '', note: p.type === 'gemini' ? 'Chiave gratis da Google.' : 'Serve una chiave.',
    }));
  /** Per cloud service: its chat models (for «Per modalità») and its memory models, read by «Prova». */
  cloudLists = signal<Record<string, PickItem[]>>({});
  private embedLists: Record<string, string[]> = {};
  /** «Prova» of a brain service: a typed key is saved once (the module re-reads it in a second), then its model list is
   * read (no tokens spent). The same check serves Modelli (chat models) and Memoria (embedding models). */
  private async brainCheck(name: string, key: string) {
    const markKey = () => this.catalog.set({ ...this.catalog()!, cloud: this.catalog()!.cloud.map(c => c.name === name ? { ...c, key_set: true } : c) });
    try {
      const r = await this.api.test(name, key);
      if (key) markKey();
      return r;
    } catch (e) {
      // A slow answer can be lost while the key was saved: if it is there, read the list again.
      const saved = key ? await this.api.catalog().then(c => c.cloud.find(x => x.name === name)?.key_set).catch(() => false) : false;
      if (saved) { markKey(); return this.api.test(name, ''); }
      throw new Error(setupError(e));
    }
  }
  readonly chatTester = async (name: string, key: string): Promise<ServiceCheck> => {
    const r = await this.brainCheck(name, key);
    const options = (r.models || []).map(m => ({ id: m, title: m, icon: 'zap', group: family(m) }));
    this.cloudLists.set({ ...this.cloudLists(), [name]: options });
    this.embedLists[name] = r.embed || [];
    return { ok: r.ok, detail: r.detail, recommended: r.recommended || [], options };
  };
  readonly embedTester = async (name: string, key: string): Promise<ServiceCheck> => {
    const r = await this.brainCheck(name, key);
    const embed = r.embed || [];
    this.embedLists[name] = embed;
    const ok = r.ok && embed.length > 0;
    return { ok, detail: ok ? `La chiave funziona: ${embed.length === 1 ? 'un modello' : embed.length + ' modelli'} per la memoria.`
                            : r.ok ? 'Questo servizio non ha modelli per la memoria.' : r.detail,
             recommended: embed.slice(0, 1), options: embed.map(m => ({ id: m, title: m, icon: 'memory', group: family(m) })) };
  };

  private async applyBrain() {
    const r = this.recipe();
    const local = this.localModel();
    const cloud = this.cloudPicked();
    const claude = cloud.find(n => this.catalog()?.cloud.find(p => p.name === n)?.type === CLAUDE_TYPE);
    const models: Record<string, string[]> = {};
    for (const n of cloud) if (this.cloudModel()[n]?.length) models[n] = this.cloudModel()[n];
    const modes: BrainChoice['modes'] = {};
    for (const [mode, id] of Object.entries(this.modes())) {
      const [provider, ...rest] = id.split('|');
      if (rest.length) modes[mode] = { provider, model: rest.join('|'), ...this.runtimeOf(provider) };
    }
    const out = await this.api.apply(r, local, cloud, claude ? (this.cloudTokens()[claude] || '').trim() : '', {
      local_provider: this.localProvider(), cloud_models: models, embedding: this.embeddingChoice(),
      local_runtime: local ? this.runtimeOf(this.localProvider()) : {}, modes,
    });
    this.cloudTokens.set({});
    if (!out.ok) { this.formError.set(out.detail || 'Non sono riuscito a salvare la scelta.'); return; }
    await Promise.all([this.refresh(), this.refreshDownloads(), this.api.catalog(this.hosts()).then(c => this.catalog.set(c)).catch(() => undefined)]);
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
  copied = signal(false);
  async copyUrl() {
    try { await navigator.clipboard.writeText(this.tunnel()?.url || ''); this.copied.set(true); setTimeout(() => this.copied.set(false), 2000); } catch { /* no clipboard: the address is selectable */ }
  }
  async retryTunnel() { await this.switchTunnel(false); await this.switchTunnel(true); }

  // ── polling: the code being claimed, the downloads, the tunnel address ──
  private async refresh() { try { this.state.set(await this.api.state()); } catch { /* keep the last one */ } }

  private async refreshDownloads() {
    try { this.downloads.set(await this.api.allDownloads()); return; } catch { /* only the models then */ }
    try { this.downloads.set(await this.api.pulls()); } catch { /* not ready yet */ }
  }

  activeDownloads = computed(() => this.downloads().filter(d => d.state === 'in_coda' || d.state === 'in_corso').length);
  downloadHint(): string { return this.activeDownloads() === 1 ? 'Un download in corso: lo vedi nel riepilogo.' : `${this.activeDownloads()} download in corso: li vedi nel riepilogo.`; }
  private ticks = 0;

  private poll() {
    this.now.set(Date.now());
    this.ticks++;
    const screen = this.screen();
    if (screen === 'telegram' && this.code()) {
      void this.refresh().then(() => { if (this.state()?.telegram.linked) this.code.set(''); });
    }
    const list = this.downloads();
    if (this.activeDownloads() || (!list.length && this.ticks % 5 === 0) || this.ticks % 20 === 0) void this.refreshDownloads();
    const t = this.tunnel();
    if (t?.on && !t.url) {
      if (t.phase !== 'address' || !this.tunnelSince()) this.tunnelSince.set(Date.now());
      this.api.tunnel().then(x => this.tunnel.set(x)).catch(() => undefined);
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
