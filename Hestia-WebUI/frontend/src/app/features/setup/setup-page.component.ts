import { ChangeDetectionStrategy, Component, DestroyRef, WritableSignal, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { marked } from 'marked';
import { Router, RouterLink } from '@angular/router';
import { UI } from '../../ui';
import { PluginOutletComponent } from '../plugins/plugin-outlet.component';
import { PluginsService } from '../plugins/plugins.service';
import { HomeProgram, ServiceCheck, ServiceRow, SetupChainComponent, chosenKeys, keyStep, ranked } from './setup-chain.component';
import { SetupPickComponent, PickItem, family } from './setup-pick.component';
import { AssistantTextComponent } from '../chat/assistant-text.component';
import { MicRecorder, VoiceService, b64ToBlob, blobToB64 } from '../../services/voice.service';
import { DEFAULT_ASSISTANT, IdentityService, LANGUAGES } from '../../services/identity.service';
import { BrainCatalog, BrainChoice, CloudProvider, Download, LocalModel, Runtime, SetupApi, SetupState, TunnelState, VoiceCatalog, VoiceOption, VoiceProvider, VoiceStep, setupError } from './setup.api';
import { tr, TrPipe } from '../../core/i18n';

type Screen = 'benvenuto' | 'chi' | 'modelli' | 'memoria' | 'cervello' | 'ascolto' | 'voce' | 'telegram' | 'backup' | 'esterni' | 'fuori' | 'pronto';
/** What the server stores, derived from the choices: something at home, something in the cloud, or both. «claude»
 * (Claude Code as the whole brain) is not offered here: the Claude subscription is one of the cloud services. */
type Recipe = 'locale' | 'cloud' | 'entrambi';
type VoiceDir = 'ascolto' | 'voce';
/** A mode with its own list: the same four choices as the step of Generale. */
interface ModeChoice { home: string; order: string[]; picks: Record<string, string[]>; rank: string[]; }
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
/** The steps list (from the bar on top): one line per screen. */
const TITLES: Record<Screen, string> = {
  benvenuto: tr('Start'), chi: tr('You and me'), modelli: tr('Models'), memoria: tr('Memory'), cervello: tr('Models ready'), ascolto: tr('Listening'),
  voce: tr('Voice'), telegram: 'Telegram', backup: tr('Backup'), esterni: tr('Calendar and Garmin'), fuori: tr('Outside home'), pronto: tr('End'),
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
 * Guided setup «Benvenuto» (docs/work/2026-10-30-setup-un-click §4.2, layout of round 7): full screen, one column, one
 * question per screen with the buttons always at the bottom; on top the step («3/11 Memoria») opens the list of the
 * steps and the downloads. The recommended answer is preselected, «Più tardi» on the optional ones. Every answer is
 * saved at once (server side), and the screen is remembered, so closing the browser resumes where it was. Secrets go
 * to Hephaestus and never come back. Local models come from the programs found on the PC (Ollama, LM Studio, Jan,
 * llama.cpp, vLLM), cloud models from the service's own list: Hestia keeps no model list of its own.
 */
@Component({
  selector: 'app-setup-page',
  imports: [TrPipe, ...UI, FormsModule, RouterLink, SetupPickComponent, SetupChainComponent, PluginOutletComponent, AssistantTextComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="bar">
      <span class="brand"><hx-icon name="sparkle" [size]="18" tone="accent" /> {{ identity.assistant() }}</span>
      @if (state()) {
        <button type="button" class="pill" [class.on]="panel()" (click)="panel.set(!panel())" [attr.aria-expanded]="panel()"  [attr.aria-label]="'Steps and downloads' | tr">
          <span class="pn">{{ index() + 1 }}/{{ screens().length }}</span> {{ title(screen()) }}
          @if (activeDownloads()) { <span class="dlc"><hx-icon name="download" [size]="13" /> {{ activeDownloads() }}</span> }
          <hx-icon [name]="panel() ? 'chevron-up' : 'chevron-down'" [size]="14" tone="muted" />
        </button>
      }
      <span class="sp"></span>
      <a class="out" routerLink="/home" (click)="leave()">{{ "I finish after" | tr }}</a>
    </header>
    <div class="progress" aria-hidden="true"><span [style.width.%]="100 * (index() + 1) / screens().length"></span></div>

    @if (panel() && state()) {
      <div class="scrim" (click)="panel.set(false)"></div>
      <aside class="drop"  [attr.aria-label]="'Steps and downloads' | tr">
        <ol class="steps-nav">
          @for (s of screens(); track s; let i = $index) {
            <li>
              <button type="button" [class.cur]="s === screen()" [disabled]="!canJump(s)" (click)="jump(s)">
                <hx-icon [name]="stepIcon(s)" [size]="16" [tone]="stepTone(s)" />
                <span><b>{{ title(s) }}</b>@if (stepNote(s); as n) { <small>{{ n }}</small> }</span>
              </button>
            </li>
          }
        </ol>
        @if (downloads().length) {
          <div class="dlh"><hx-icon name="download" [size]="15" tone="muted" /> {{ "alt::Download" | tr }} <small>{{ "run on their own" | tr }}</small></div>
          <ul class="dl">
            @for (d of downloads(); track (d.module || '') + d.id) {
              <li>
                <hx-icon [name]="d.state === 'fatto' ? 'check-circle' : d.state === 'errore' ? 'alert' : 'download'" [size]="16"
                         [tone]="d.state === 'fatto' ? 'success' : d.state === 'errore' ? 'danger' : 'info'" />
                <span><b>{{ d.what }}</b><small>{{ downloadText(d) }}</small>
                  @if (d.state === 'in_corso' && d.size) { <span class="meter"><span [style.width.%]="100 * d.done / d.size"></span></span> }
                </span>
              </li>
            }
          </ul>
          <a class="more" href="/download" target="_blank" rel="noopener">{{ "Downloads page" | tr }} <hx-icon name="external" [size]="13" /></a>
        }
      </aside>
    }

    <main class="scroll">
      <div class="col">
        @if (!state()) {
          <div class="center">
            @if (loadError()) {
              <hx-icon name="offline" [size]="28" tone="warning" />
              <p>{{ loadError() }}</p>
              <button hx-btn variant="primary" icon="refresh" (click)="load()">{{ "Try again" | tr }}</button>
            } @else { <hx-spinner /> }
          </div>
        } @else {
          @switch (screen()) {
            @case ('benvenuto') {
              <div class="hero">
                <span class="mark"><hx-icon name="sparkle" [size]="26" tone="accent" /></span>
                <h1>{{ "Hi, I'm" | tr }} {{ identity.assistant() }}</h1>
                <p class="lead">{{ "I'll set everything up in a few steps. Every answer is saved right away: you can close and resume whenever you want." | tr }}</p>
                <p class="fact top"><hx-icon name="host" [size]="16" tone="muted" /><span>{{ hardwareText() }}</span></p>
              </div>
            }

            @case ('chi') {
              <h1>{{ "What's your name?" | tr }}</h1>
              <p class="lead">{{ "So I know who you are and what to call you. You can also give me another name." | tr }}</p>
              <hx-field  [label]="'Your name' | tr">
                <input class="hx-input" autocomplete="given-name" maxlength="40" [(ngModel)]="ownerName" />
              </hx-field>
              <hx-field  [label]="'What you want me to call you' | tr"  [hint]="'A nickname or short name. Empty = your name.' | tr">
                <input class="hx-input" autocomplete="nickname" maxlength="40" [(ngModel)]="ownerCall" />
              </hx-field>
              <hx-field  [label]="'My name' | tr">
                <input class="hx-input" autocomplete="off" maxlength="40" [(ngModel)]="assistantName" />
              </hx-field>
              <hx-field  [label]="'I am' | tr">
                <hx-segmented [options]="genderOptions" [value]="assistantGender()" (changed)="assistantGender.set($event)" />
              </hx-field>
              <hx-field  [label]="'Your language' | tr"  [hint]="'For the notifications and the messages I write to you. In chat I answer in the language you write in.' | tr">
                <select class="hx-select" [value]="language()" (change)="language.set($any($event.target).value)">
                  @for (l of languages; track l.value) {
                    <option [value]="l.value" [selected]="l.value === language()">{{ l.label }}</option>
                  }
                </select>
              </hx-field>
            }

            @case ('modelli') {
              <h1>{{ "With which models does it think?" | tr }}</h1>
              <p class="lead">{{ "Choose at least one, local or cloud. Each mode can have its own." | tr }}</p>
              <div class="modetabs" role="tablist"  [attr.aria-label]="'alt::Mode' | tr">
                @for (m of modeList; track m.id) {
                  <button type="button" role="tab" [attr.aria-selected]="modeTab() === m.id" [class.on]="modeTab() === m.id" (click)="modeTab.set(m.id)">
                    {{ m.label }}<small>{{ m.id === 'generale' ? ('for everything' | tr) : modeOwn()[m.id] ? 'propri' : ('like General' | tr) }}</small>
                  </button>
                }
              </div>
              @if (modeTab() === 'generale') {
                <app-setup-chain [homeItems]="localItems()" [home]="localKey()" (homeChange)="pickLocalKey($event)" [programs]="programs()"
                                 [homeEmpty]="'No program for the models found. Install one (they are free), open it and press «Search again».' | tr"
                                 [hosts]="hosts()" [searching]="searching()" (addHost)="addHost($event)" (removeHost)="removeHost($event)" (again)="searchAgain()"
                                 [services]="cloudRows()" [tester]="chatTester" [(order)]="cloudPicked" [(picks)]="cloudModel" [(ready)]="cloudReady" [(tokens)]="cloudTokens" [(rank)]="cloudRank">
                  <div home-extra>
                    @if (hasOllama()) {
                      @if (otherOpen() || otherModel()) {
                        <hx-field  [label]="'Another Ollama model' | tr"  [hint]="'The name as on ollama.com/library, for example qwen3:32b: Ollama downloads it.' | tr">
                          <input class="hx-input mono" autocomplete="off" spellcheck="false" [ngModel]="otherModel()" (ngModelChange)="typeLocal($event)" [placeholder]="'name:version' | tr" />
                        </hx-field>
                      } @else { <button type="button" class="link" (click)="otherOpen.set(true)">{{ "Another Ollama model" | tr }}</button> }
                    }
                  </div>
                </app-setup-chain>
              } @else {
                @for (m of modeList; track m.id) {
                  @if (modeTab() === m.id) {
                    <label class="same">
                      <input type="checkbox" [checked]="!modeOwn()[m.id]" (change)="toggleMode(m.id)" />
                      <span><b>{{ "The same as General" | tr }}</b><small>{{ m.help }}</small></span>
                    </label>
                    @if (modeOwn()[m.id]; as own) {
                      <app-setup-chain [homeItems]="localItems()" [home]="own.home" (homeChange)="setMode(m.id, 'home', $event)" [programs]="programs()"
                                       [homeEmpty]="'No program for the models found.' | tr"
                                       [hosts]="hosts()" [searching]="searching()" (addHost)="addHost($event)" (removeHost)="removeHost($event)" (again)="searchAgain()"
                                       [services]="cloudRows()" [tester]="chatTester" [(ready)]="cloudReady" [(tokens)]="cloudTokens"
                                       [order]="own.order" (orderChange)="setMode(m.id, 'order', $event)"
                                       [picks]="own.picks" (picksChange)="setMode(m.id, 'picks', $event)"
                                       [rank]="own.rank" (rankChange)="setMode(m.id, 'rank', $event)" />
                    }
                  }
                }
              }
            }

            @case ('memoria') {
              <h1>{{ "With which model does it remember?" | tr }}</h1>
              <p class="lead">{{ "It's used to find memories and documents again. You can choose more than one: the next ones answer when the first is not available." | tr }}</p>
              <app-setup-chain [homeItems]="embedHomeItems()" [(home)]="embedHome" [programs]="programs()"
                               [homeEmpty]="'No program for the models found. Install one (they are free) and press «Search again», or choose a cloud service.' | tr"
                               [hosts]="hosts()" [searching]="searching()" (addHost)="addHost($event)" (removeHost)="removeHost($event)" (again)="searchAgain()"
                               [services]="embedRows()" [tester]="embedTester" [cloudEmpty]="'No cloud service with models for the memory.' | tr"
                               [(order)]="embedOrder" [(picks)]="embedPicks" [(ready)]="embedReady" [(tokens)]="embedTokens" />
            }

            @case ('cervello') {
              <h1>{{ "The models are ready" | tr }}</h1>
              <div class="msg">
                @if (hello(); as h) {
                  @if (h.ok) { <hx-assistant-text [html]="h.html || ''" /><small>{{ "Written with" | tr }} {{ h.model }}</small> }
                  @else {
                    <p class="warn"><hx-icon name="alert" [size]="15" tone="warning" /> {{ activeDownloads() ? ('The model is still downloading: I\\'ll write to you as soon as it\\'s ready.' | tr) : h.detail }}</p>
                    @if (!activeDownloads()) { <div class="row start"><button hx-btn variant="secondary" size="sm" icon="refresh" [loading]="helloBusy()" (click)="sayHello()">{{ "Try again" | tr }}</button></div> }
                  }
                } @else { <hx-assistant-text [streaming]="true" /> }
              </div>
              @if (activeDownloads()) { <p class="note">{{ downloadHint() }}</p> }
            }

            @case ('telegram') {
              <h1>Telegram</h1>
              <p class="lead">{{ "To write and talk with {assistant} from the phone." | tr }}</p>
              @if (state()!.telegram.linked) {
                <p class="fact"><hx-icon name="check-circle" [size]="16" tone="success" /> {{ "Linked: {assistant} recognises you." | tr }}</p>
              } @else if (code()) {
                <p class="fact">{{ "Open your bot on Telegram and send it this code:" | tr }}</p>
                <div class="code mono">{{ code() }}</div>
                <p class="fact"><hx-spinner /> {{ "I'm waiting for your message (valid for 10 minutes)." | tr }}</p>
              } @else if (state()!.telegram.token) {
                <p class="fact">{{ "The bot is there: it only needs to recognise you." | tr }}</p>
                <div class="row start"><button hx-btn variant="primary" [loading]="busy()" (click)="newCode()">{{ "Show the code" | tr }}</button></div>
              } @else {
                <ol class="howto">
                  <li>{{ "On Telegram open" | tr }} <b>&#64;BotFather</b> {{ "and write" | tr }} <code>/newbot</code>.</li>
                  <li>{{ "Choose a name: it gives you a token." | tr }}</li>
                  <li>{{ "Paste it here." | tr }}</li>
                </ol>
                <hx-field  [label]="'Bot token' | tr" [error]="formError()">
                  <input class="hx-input mono" type="password" autocomplete="off" [(ngModel)]="botToken" placeholder="123456789:AA…" />
                </hx-field>
              }
            }

            @case ('backup') {
              <h1>{{ "Backup password" | tr }}</h1>
              @if (state()!.backup.passphrase) {
                <p class="fact"><hx-icon name="check-circle" [size]="16" tone="success" /> {{ "Already set." | tr }}</p>
              } @else {
                <p class="lead">{{ "Backups are encrypted with this phrase: save it in your password manager, without it they can't be opened." | tr }}</p>
                <hx-field  [label]="'Phrase (at least 12 characters)' | tr" [error]="formError()">
                  <input class="hx-input mono" [type]="showPass() ? 'text' : 'password'" autocomplete="new-password" [(ngModel)]="passphrase" />
                </hx-field>
                <div class="row start">
                  <button hx-btn variant="secondary" icon="sparkle" (click)="suggest()">{{ "Generate one" | tr }}</button>
                  <button hx-btn variant="ghost" [icon]="showPass() ? 'eye-off' : 'eye'" (click)="showPass.set(!showPass())">{{ showPass() ? ('Hide' | tr) : ('Show' | tr) }}</button>
                </div>
              }
            }

            @case ('esterni') {
              <h1>{{ "Your services" | tr }}</h1>
              <p class="lead">{{ "If you want, link them now. You can also do it later from the Devices page." | tr }}</p>
              <div class="outlets">
                <hx-plugin-outlet module="hecate" element="hecate-connections" [ctx]="{ params: { place: 'setup' } }" />
              </div>
            }

            @case ('fuori') {
              <h1>{{ "Outside home" | tr }}</h1>
              @if (tunnel()?.on && tunnel()!.url) {
                <p class="fact"><hx-icon name="check-circle" [size]="16" tone="success" /> {{ "Done. Even without the home Wi-Fi open:" | tr }}</p>
                <div class="urlrow">
                  <span class="code mono small">{{ tunnel()!.url }}</span>
                  <a hx-btn variant="primary" icon="external" [href]="tunnel()!.url" target="_blank" rel="noopener">{{ "Open" | tr }}</a>
                  <button hx-btn variant="ghost" icon="copy" (click)="copyUrl()">{{ copied() ? ('Copied' | tr) : ('Copy' | tr) }}</button>
                </div>
                <p class="note">{{ "It asks for access, like here. It changes when {assistant} restarts: the bot on Telegram always gives you the right one." | tr }}</p>
                <div class="row start"><button hx-btn variant="ghost" size="sm" icon="x" [loading]="busy()" (click)="switchTunnel(false)">{{ "Turn off" | tr }}</button></div>
              } @else if (busy() || tunnel()?.on || tunnel()?.phase === 'error') {
                @if (tunnel()?.phase === 'error' || tunnelLate()) {
                  <p class="fact warn"><hx-icon name="alert" [size]="15" tone="warning" /> {{ tunnel()?.phase === 'error' ? tunnel()!.detail : ('The address doesn\\'t arrive. Usually it\\'s the network blocking Cloudflare (office, school) or the internet not working.' | tr) }}</p>
                  <div class="row start">
                    <button hx-btn variant="secondary" icon="refresh" (click)="retryTunnel()">{{ "Try again" | tr }}</button>
                    <button hx-btn variant="ghost" icon="x" (click)="switchTunnel(false)">{{ "Turn off" | tr }}</button>
                  </div>
                } @else {
                  <ol class="progress-list">
                    @for (st of tunnelSteps; track st.id; let i = $index) {
                      <li>
                        @if (tunnelStep() > i) { <hx-icon name="check-circle" [size]="16" tone="success" /> }
                        @else if (tunnelStep() === i) { <hx-spinner /> }
                        @else { <hx-icon name="minus" [size]="16" tone="muted" /> }
                        {{ st.label }}
                      </li>
                    }
                  </ol>
                  <p class="note">{{ "You can go on: it finishes by itself." | tr }}</p>
                }
              } @else {
                <p class="lead">{{ "To open {assistant} from the phone even outside the home Wi-Fi. Without it, you use it at home and from Telegram." | tr }}</p>
                <p class="note">{{ "Create a secure address with Cloudflare, free and without an account. From there {assistant} always asks for access. Turn it off when you want." | tr }}</p>
                <div class="row start"><button hx-btn variant="primary" icon="cloud" [loading]="busy()" (click)="switchTunnel(true)">{{ "f::Active" | tr }}</button></div>
              }
            }

            @case ('pronto') {
              <h1>{{ "All set" | tr }}</h1>
              <p class="lead">{{ "Tap a row to change it." | tr }}</p>
              <div class="recap">
                @for (s of recapSteps(); track s) {
                  <button type="button" class="rrow" (click)="jump(s)">
                    <hx-icon [name]="isDone(s) ? 'check-circle' : 'clock'" [size]="18" [tone]="isDone(s) ? 'success' : 'muted'" />
                    <span><b>{{ title(s) }}</b><small>{{ recapText(s) }}</small></span>
                    <hx-icon name="chevron-right" [size]="15" tone="muted" />
                  </button>
                }
              </div>
            }
          }

          @if (voiceDir(); as dir) {
            <h1>{{ dir.question }}</h1>
            <p class="lead">{{ dir.lead }}</p>
            @if (!voiceCat()) {
              @if (voiceError()) { <p class="fact warn"><hx-icon name="alert" [size]="15" tone="warning" /> {{ voiceError() }}</p> } @else { <div class="center"><hx-spinner /></div> }
            } @else {
              <app-setup-chain [homeItems]="voiceLocalItems(dir.id)" [home]="voiceLocalPick()[dir.id]" (homeChange)="setVoice(voiceLocalPick, dir.id, $event)"
                               [programs]="voiceCat()?.[dir.id]?.programs || []"
                               [homeEmpty]="'No program for the voice found.' | tr"
                               [hosts]="hosts()" [searching]="searching()" (addHost)="addHost($event)" (removeHost)="removeHost($event)" (again)="searchAgain()"
                               [services]="voiceCloudRows(dir.id)" [tester]="voiceTester(dir.id)"
                               [order]="voiceOrder()[dir.id]" (orderChange)="setVoice(voiceOrder, dir.id, $event)"
                               [picks]="voicePicks()[dir.id]" (picksChange)="setVoice(voicePicks, dir.id, $event)"
                               [ready]="voiceReadyMap()[dir.id]" (readyChange)="setVoice(voiceReadyMap, dir.id, $event)"
                               [rank]="voiceRank()[dir.id]" (rankChange)="setVoice(voiceRank, dir.id, $event)"
                               [trial]="dir.id" [trialState]="trialState()" (tryRow)="tryVoice(dir.id, $event)">
                <div home-extra>
                  @if (voiceLocal(dir.id).length > 1) {
                    <ul class="engines">
                      @for (p of voiceLocal(dir.id); track p.name) { @if (p.note) { <li><b>{{ engineName(p) }}</b> {{ p.note }}</li> } }
                    </ul>
                  }
                </div>
              </app-setup-chain>
            }
          }
        }
      </div>
    </main>

    @if (state()) {
      <footer class="foot">
        <div class="col">
          @if (formError() && !['fuori', 'telegram', 'backup'].includes(screen())) {
            <p class="fact warn"><hx-icon name="alert" [size]="15" tone="danger" /> {{ formError() }}</p>
          } @else if (screen() === 'fuori' && formError()) {
            <p class="fact warn"><hx-icon name="alert" [size]="15" tone="danger" /> {{ formError() }}</p>
          }
          <div class="navrow">
            @if (index() > 0) { <button hx-btn variant="ghost" icon="chevron-left" (click)="back()">{{ "Back" | tr }}</button> }
            <span class="sp"></span>
            @if (optional()) { <button hx-btn variant="ghost" (click)="later()">{{ "Later" | tr }}</button> }
            <button hx-btn variant="primary" [loading]="busy()" [disabled]="!canNext()" (click)="next()">{{ nextLabel() }}</button>
          </div>
        </div>
      </footer>
    }`,
  styles: [`
    :host { display: grid; grid-template-rows: auto auto 1fr auto; height: 100vh; height: 100dvh; background: var(--bg); color: var(--text); position: relative; }
    .bar { display: flex; align-items: center; gap: 12px; padding: 10px 20px; background: var(--surface); }
    .brand { display: inline-flex; gap: 6px; align-items: center; font-weight: 600; font-size: 15px; }
    .pill { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--text); background: var(--surface-2); border: 1px solid transparent;
            border-radius: var(--radius-full); padding: 5px 10px 5px 12px; min-width: 0; }
    .pill.on, .pill:hover { border-color: var(--border-strong); }
    .pn { color: var(--text-3); font-variant-numeric: tabular-nums; }
    .dlc { display: inline-flex; gap: 3px; align-items: center; font-size: 12px; font-weight: 600; color: var(--info, var(--accent)); }
    .out { font-size: 13px; color: var(--text-3); white-space: nowrap; }
    .sp { flex: 1; }
    .progress { height: 3px; background: var(--surface-3); }
    .progress span { display: block; height: 100%; background: var(--accent); transition: width var(--dur) var(--ease); }
    .scrim { position: fixed; inset: 0; z-index: 40; background: rgba(0,0,0,.25); }
    .drop { position: absolute; z-index: 41; top: 52px; left: 50%; transform: translateX(-50%); width: min(380px, calc(100vw - 24px)); max-height: calc(100dvh - 80px);
            overflow-y: auto; padding: 8px; display: flex; flex-direction: column; gap: 8px; background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius-lg, 14px); box-shadow: var(--shadow-lg, 0 12px 32px rgba(0,0,0,.18)); }
    .steps-nav { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 1px; }
    .steps-nav button { display: flex; gap: 10px; align-items: flex-start; width: 100%; text-align: left; padding: 7px 8px; border-radius: var(--radius-sm); background: none; color: var(--text); border: 0; }
    .steps-nav button:hover:not(:disabled) { background: var(--surface-2); }
    .steps-nav button.cur { background: var(--accent-soft); }
    .steps-nav button:disabled { opacity: .5; cursor: default; }
    .steps-nav span, .dl li > span, .rrow > span { display: flex; flex-direction: column; gap: 1px; min-width: 0; flex: 1; }
    .steps-nav b, .dl b { font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
    .steps-nav small, .dl small { font-size: 12px; color: var(--text-3); overflow-wrap: anywhere; }
    .dlh { display: flex; gap: 6px; align-items: center; font-size: 13px; font-weight: 600; color: var(--text-2); padding: 8px 8px 0; border-top: 1px solid var(--border); }
    .dlh small { font-weight: 400; color: var(--text-3); }
    .dl { list-style: none; margin: 0; padding: 0 8px; display: flex; flex-direction: column; gap: 10px; }
    .dl li { display: flex; gap: 10px; align-items: flex-start; }
    .meter { display: block; height: 4px; border-radius: var(--radius-full); background: var(--surface-3); overflow: hidden; margin-top: 4px; }
    .meter span { display: block; height: 100%; background: var(--accent); transition: width var(--dur) var(--ease); }
    .more { font-size: 12px; display: inline-flex; gap: 4px; align-items: center; padding: 0 8px 6px; }
    .scroll { overflow-y: auto; overscroll-behavior: contain; min-height: 0; }
    .col { width: 100%; max-width: 640px; margin: 0 auto; padding: 0 20px; box-sizing: border-box; }
    main .col { padding-top: 36px; padding-bottom: 40px; display: flex; flex-direction: column; gap: 16px; }
    .center { display: grid; place-items: center; gap: 12px; padding: 48px 0; text-align: center; color: var(--text-2); }
    .hero { display: flex; flex-direction: column; gap: 14px; align-items: flex-start; padding-top: 24px; }
    .mark { display: grid; place-items: center; width: 52px; height: 52px; border-radius: var(--radius-lg, 14px); background: var(--accent-soft); }
    .mark.ok { background: var(--success-soft, var(--surface-2)); }
    h1 { font-family: var(--font-serif); font-weight: 500; font-size: 28px; line-height: 1.2; color: var(--text); margin: 0; }
    .lead { color: var(--text-2); font-size: 15px; line-height: 1.5; margin: -6px 0 4px; }
    .hero .lead { margin: 0; }
    .fact { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 14px; color: var(--text-2); line-height: 1.45; margin: 0; }
    .fact.warn { color: var(--text); }
    .fact.top { flex-wrap: nowrap; align-items: flex-start; }
    .fact.top hx-icon { margin-top: 2px; flex: none; }
    .note { font-size: 13px; color: var(--text-3); line-height: 1.5; margin: 0; }
    code { font-family: var(--font-mono); font-size: 13px; background: var(--surface-2); padding: 1px 5px; border-radius: var(--radius-xs); }
    .link { align-self: flex-start; background: none; border: 0; padding: 2px 0; color: var(--accent); font-size: 13px; }
    .howto { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 4px; font-size: 14px; color: var(--text-2); line-height: 1.5; }
    .same b, .rrow b { font-size: 14px; font-weight: 600; }
    .same small, .rrow small { font-size: 12px; color: var(--text-3); line-height: 1.4; overflow-wrap: anywhere; }
    .modetabs { display: flex; gap: 4px; border-bottom: 1px solid var(--border); overflow-x: auto; scrollbar-width: none; }
    .modetabs button { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; padding: 8px 12px 9px; border: 0; border-bottom: 2px solid transparent;
                       margin-bottom: -1px; background: none; color: var(--text-2); font-size: 14px; font-weight: 600; white-space: nowrap; }
    .modetabs button small { font-size: 11px; font-weight: 400; color: var(--text-3); }
    .modetabs button.on { color: var(--text); border-bottom-color: var(--accent); }
    .same { display: flex; gap: 10px; align-items: flex-start; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); cursor: pointer; }
    .same input { margin-top: 3px; accent-color: var(--accent); width: 16px; height: 16px; flex: none; }
    .same span { display: flex; flex-direction: column; gap: 1px; }
    .outlets { display: flex; flex-direction: column; gap: 12px; }
    .outlets hx-plugin-outlet { flex: none; }
    .engines { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; font-size: 13px; color: var(--text-3); line-height: 1.45; }
    .engines b { color: var(--text-2); font-weight: 600; }
    .urlrow { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .urlrow .code { flex: 1 1 220px; min-width: 0; text-align: left; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .row.start { justify-content: flex-start; }
    .code { font-size: 38px; letter-spacing: .25em; text-align: center; padding: 14px; border-radius: var(--radius-md); background: var(--surface-2); color: var(--text); }
    .code.small { font-size: 14px; letter-spacing: 0; overflow-wrap: anywhere; user-select: all; padding: 10px 12px; }
    .progress-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; font-size: 14px; color: var(--text-2); }
    .progress-list li { display: flex; gap: 8px; align-items: center; }
    .recap { display: flex; flex-direction: column; gap: 6px; }
    .rrow { display: flex; gap: 12px; align-items: center; width: 100%; text-align: left; padding: 12px; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--text); }
    .rrow:hover { border-color: var(--border-strong); }
    .msg { display: flex; flex-direction: column; gap: 6px; }
    .msg small { font-size: 12px; color: var(--text-3); }
    .msg .warn { display: flex; gap: 6px; align-items: center; margin: 0; font-size: 14px; color: var(--text-2); }
    .foot { background: var(--surface); border-top: 1px solid var(--border); }
    .foot .col { padding-top: 12px; padding-bottom: 12px; padding-bottom: max(12px, env(safe-area-inset-bottom)); display: flex; flex-direction: column; gap: 8px; }
    .navrow { display: flex; align-items: center; gap: 8px; }
    @media (max-width: 560px) {
      .bar { padding: 8px 12px; gap: 8px; }
      .brand { font-size: 0; gap: 0; }
      .col { padding: 0 16px; }
      main .col { padding-top: 24px; }
      h1 { font-size: 23px; }
      .code { font-size: 30px; }
      .drop { top: 48px; }
    }
  `],
})
export class SetupPageComponent {
  private api = inject(SetupApi);
  /** The site's one player: a voice tried stops the one playing (in the setup or in the chat), never two at once. */
  private player = inject(VoiceService);
  private trialTicket = 0;
  private router = inject(Router);
  readonly claudeType = CLAUDE_TYPE;
  /** The list of the steps + the downloads, opened from the step on the bar at the top. */
  panel = signal(false);
  /** «Modelli»: the field for another Ollama model. */
  otherOpen = signal(false);

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
  /** «Scelti» of Modelli in the user's order (local and cloud mixed), sent as ``order``. */
  cloudRank = signal<string[]>([]);
  botToken = '';
  passphrase = '';
  /** «Tu e io»: who the owner is and who the assistant is (personal settings, live for every module). */
  readonly identity = inject(IdentityService);
  ownerName = '';
  ownerCall = '';
  assistantName = DEFAULT_ASSISTANT;
  assistantGender = signal<'lei' | 'lui'>('lei');
  language = signal('it');
  readonly languages = LANGUAGES;
  readonly genderOptions: { value: 'lei' | 'lui'; label: string }[] = [{ value: 'lei', label: tr('A woman') }, { value: 'lui', label: tr('A man') }];

  screen = signal<Screen>('benvenuto');
  /** The furthest screen reached in this run: the summary jumps back freely, forward only up to here. */
  reached = signal(0);
  /** The screens: Modelli, Memoria, Ascolto and Voce are the same step (app-setup-chain) on a different module. */
  screens = signal<Screen[]>(['benvenuto', 'chi', 'modelli', 'memoria', 'cervello', 'ascolto', 'voce', 'telegram', 'backup', 'esterni', 'fuori', 'pronto']);
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
    { id: 'download', label: tr('Downloading the Cloudflare program (only the first time)') },
    { id: 'start', label: tr('I\'ll start it') },
    { id: 'address', label: tr('Waiting for the address from Cloudflare') },
  ];
  tunnelStep = computed(() => {
    const ph = this.tunnel()?.phase || (this.busy() ? 'start' : '');
    return ph === 'download' ? 0 : ph === 'start' ? 1 : ph === 'address' ? 2 : ph === 'ready' ? 3 : 1;
  });

  // ── Voce (Echo's blocks, the same cards as the cloud services) ──
  readonly voiceDirs = [
    { id: 'ascolto' as const, question: tr('How does it listen to you?'), lead: tr('To understand what you say by voice.') },
    { id: 'voce' as const, question: tr('With which voice does it answer you?'), lead: tr('It speaks in the language you write in: if you write in English, it answers with an English voice.') },
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
  voiceRank = signal<Record<VoiceDir, string[]>>({ ascolto: [], voce: [] });

  async loadVoice() {
    this.voiceError.set('');
    try {
      const cat = await this.api.voiceCatalog(this.hosts());
      this.voiceCat.set(cat);
      const saved = this.state()?.voice || {};
      const local: Record<VoiceDir, string> = { ascolto: '', voce: '' };
      const order: Record<VoiceDir, string[]> = { ascolto: [], voce: [] };
      const picks: Record<VoiceDir, Record<string, string[]>> = { ascolto: {}, voce: {} };
      const rank: Record<VoiceDir, string[]> = { ascolto: [], voce: [] };
      for (const d of this.voiceDirs) {
        const own = d.id === 'ascolto' ? saved.listen : saved.speak;
        // what the user chose in the setup, else the chain in use; never Hestia's defaults for services without a key
        const steps: VoiceStep[] = (Array.isArray(own) ? own : own?.provider ? [own] : null) || cat[d.id].steps || (cat[d.id].current?.provider ? [cat[d.id].current] : []);
        const byName = (n: string) => cat[d.id].providers.find(p => p.name === n);
        for (const st of steps) {
          const p = byName(st.provider);
          if (!p) continue;
          const id = d.id === 'ascolto' ? st.model : st.voice;
          if (p.local) { if (!local[d.id]) { local[d.id] = `${p.name}|${id || this.optionsOf(p, d.id)[0]?.id || ''}`; rank[d.id].push('h'); } }
          else if (p.key || !p.needs_key) {   // a cloud service is preselected only when its key is saved
            if (!order[d.id].includes(p.name)) order[d.id].push(p.name);
            if (id) picks[d.id][p.name] = [...(picks[d.id][p.name] || []), id];
            rank[d.id].push(id ? `m:${p.name}:${id}` : `s:${p.name}`);   // the saved order, local and cloud mixed
          }
        }
        if (!local[d.id]) local[d.id] = this.voiceLocalItems(d.id, cat)[0]?.id || '';
        if (local[d.id] && !rank[d.id].includes('h')) rank[d.id].unshift('h');
      }
      this.voiceLocalPick.set(local);
      this.voiceOrder.set(order);
      this.voicePicks.set(picks);
      this.voiceRank.set(rank);
    } catch (e) {
      this.voiceError.set(setupError(e));
    }
  }
  // «Prova» on a voice (hear it) or listening engine (speak, see what it understood), chosen or still in the lists:
  // nothing saved.
  trialState = signal<{ key: string; busy?: boolean; recording?: boolean; playing?: boolean; text?: string } | null>(null);
  private mic: MicRecorder | null = null;
  async tryVoice(dir: VoiceDir, row: { key: string; provider: string; model: string }) {
    const cur = this.trialState();
    if (dir === 'voce') {
      const ticket = ++this.trialTicket;              // a later tap wins: an older answer never plays over it
      this.player.stop();
      if (cur?.key === row.key && (cur.playing || cur.busy)) { this.trialState.set(null); return; }   // tap again = stop
      this.trialState.set({ key: row.key, busy: true });
      try {
        const r = await this.api.voicePreview(row.provider, row.model);
        if (ticket !== this.trialTicket) return;
        if (r.ok && r.audio_b64) {
          this.trialState.set({ key: row.key, playing: true });
          this.player.play('setup:' + row.key, b64ToBlob(r.audio_b64, r.mime_type || 'audio/mpeg'),
            err => { if (ticket === this.trialTicket)      // never a silent «played»: say why it did not play
              this.trialState.set({ key: row.key, text: tr("The browser didn't play it ({0}): try again.", (err as Error)?.name || tr('error')) }); },
            () => { if (ticket === this.trialTicket) this.trialState.set(null); });
        } else this.trialState.set({ key: row.key, text: r.detail || tr('It didn\'t answer.') });
      } catch (e) { if (ticket === this.trialTicket) this.trialState.set({ key: row.key, text: setupError(e) }); }
      return;
    }
    if (cur?.recording && cur.key === row.key && this.mic) {   // second tap: stop and hear it
      const got = await this.mic.stop();
      const mime = this.mic.mime;
      this.mic = null;
      if (!got) { this.trialState.set({ key: row.key, text: tr('Too short: tap, speak for a few seconds, tap again.') }); return; }
      this.trialState.set({ key: row.key, busy: true });
      try {
        const r = await this.api.voiceHear(row.provider, row.model, await blobToB64(got.blob), mime);
        this.trialState.set({ key: row.key, text: r.ok ? tr("I understood: «{0}»", r.text) : (r.detail || tr('It didn\'t answer.')) });
      } catch (e) { this.trialState.set({ key: row.key, text: setupError(e) }); }
      return;
    }
    if (this.mic) { await this.mic.stop(true); this.mic = null; }
    try {
      this.mic = new MicRecorder();
      await this.mic.start();
      this.trialState.set({ key: row.key, recording: true, text: tr('I\'m listening: speak, then tap again.') });
    } catch {
      this.mic = null;
      this.trialState.set({ key: row.key, text: tr('The browser doesn\'t give me the microphone (permission or an https address is needed).') });
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
        id: `${p.name}|${o.id}`, title: many ? `${this.engineName(p)} · ${o.label}` : o.label, group: many ? this.engineName(p) : '',
        lang: o.lang, langLabel: o.lang_label,
        note: o.note || (p.state === 'ready' ? '' : tr('I download it when you confirm.')),
        tag: dir === 'voce' && p.type === 'kokoro' && i === 0 ? tr('Recommended') : '' }));
    }
    return out;
  }
  voiceCloudRows(dir: VoiceDir): ServiceRow[] {
    return (this.voiceCat()?.[dir].providers || []).filter(p => !p.local).map(p => ({
      name: p.name, label: p.label, kind: p.needs_key ? 'key' as const : 'none' as const, keySet: p.key, note: p.note || '' }));
  }
  private voiceTesters: Partial<Record<VoiceDir, (name: string, key: string) => Promise<ServiceCheck>>> = {};
  /** «Prova» of a voice service (a typed key is saved first, then its list is read: nothing spent). */
  voiceTester(dir: VoiceDir) {
    return this.voiceTesters[dir] ||= async (name: string, key: string): Promise<ServiceCheck> => {
      const toCheck = (r: { ok: boolean; detail?: string; models?: VoiceOption[]; voices?: VoiceOption[]; recommended?: Record<string, string[]> }): ServiceCheck => {
        const rows = (dir === 'ascolto' ? r.models : r.voices) || [];
        return { ok: r.ok, detail: r.detail, recommended: r.recommended?.[dir] || [],
                 options: rows.map(o => ({ id: o.id, title: o.label, note: o.note || '', icon: 'zap', group: family(o.id) })) };
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
    const home = this.voiceLocalPick()[dir] || '';
    const keys = ranked(chosenKeys(home, this.voiceOrder()[dir], this.voicePicks()[dir]), this.voiceRank()[dir]);
    return keys.map(k => {
      const { provider, model: id } = keyStep(k, home);
      const step: VoiceStep = { provider, model: dir === 'ascolto' ? id : '', voice: dir === 'voce' ? id : '' };
      const p = k === 'h' ? this.voiceLocal(dir).find(x => x.name === provider) : undefined;
      return p?.found && p.url ? { ...step, url: p.url, type: p.type, label: p.label } : step;
    });
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
      if (this.screen() === 'cervello') void this.sayHello();
      this.api.tunnel().then(t => this.tunnel.set(t)).catch(() => undefined);
      void this.refreshDownloads();
      void this.identity.load(true).then(() => {
        this.ownerName = this.identity.ownerName();
        this.ownerCall = this.identity.ownerCall();
        this.assistantName = this.identity.assistant();
        this.assistantGender.set(this.identity.gender());
        this.language.set(this.identity.language());
      });
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
      const own: Record<string, ModeChoice> = {};
      for (const [k, v] of Object.entries(state.brain.modes || {})) {
        const steps = (v?.steps?.length ? v.steps : v?.model ? [v] : []) as { provider?: string; model?: string }[];
        if (steps.length) own[k] = this.modeFromSteps(steps.map(x => ({ provider: x.provider || 'ollama', model: x.model || '' })));
      }
      this.modeOwn.set(own);
      // «Scelti» in the saved order (local and cloud mixed)
      const lk = this.localKey();
      const rank = (state.brain.order || []).map(o => lk && o.provider === this.localProvider() && o.model === this.localModel() ? 'h'
        : o.model ? `m:${o.provider}:${o.model}` : `s:${o.provider}`);
      this.cloudRank.set(rank.length && lk && !rank.includes('h') ? ['h', ...rank] : rank);
      // «Memoria»: the model in use (at home or in the cloud), else the recommended one at home
      const steps = catalog.embedding_steps?.length ? catalog.embedding_steps : catalog.embedding?.model ? [catalog.embedding] : [];
      const order: string[] = []; const picks: Record<string, string[]> = {}; let home = '';
      for (const s of steps) {
        const provider = s.provider || 'ollama';
        if (cloud.some(p => p.name === provider)) {
          if (!order.includes(provider)) order.push(provider);
          picks[provider] = [...(picks[provider] || []), s.model];
        } else if (!home) home = `${provider}|${s.model}`;
      }
      this.embedOrder.set(order); this.embedPicks.set(picks); this.embedHome.set(home);
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
    if (screen === 'cervello' && !this.hello()?.ok) { this.hello.set(null); void this.sayHello(); }
    if (this.mic) { void this.mic.stop(true); this.mic = null; }
    this.trialState.set(null);
    this.screen.set(screen);
    this.reached.set(Math.max(this.reached(), this.screens().indexOf(screen)));
    store(SCREEN_KEY, screen);
  }

  back() { const list = this.screens(); this.go(list[Math.max(0, this.index() - 1)]); }
  private forward() { const list = this.screens(); this.go(list[Math.min(list.length - 1, this.index() + 1)]); }

  /** «Finisco dopo»: the Home shows a card to come back; the guard does not bring the browser here again this session. */
  leave() { try { sessionStorage.setItem('hestia_setup_seen', '1'); } catch { /* ignore */ } }

  // ── The steps list (from the bar) ──
  title(s: Screen): string { return TITLES[s]; }
  canJump(s: Screen): boolean {
    const i = this.screens().indexOf(s);
    if (s === 'cervello') return !!this.state()?.brain.recipe;
    return i <= this.reached();
  }
  jump(s: Screen) { if (this.canJump(s)) { this.go(s); this.panel.set(false); } }
  isDone(s: Screen): boolean {
    const st = this.state();
    if (!st) return false;
    switch (s) {
      case 'benvenuto': return this.reached() > 0;
      case 'chi': return !!this.identity.ownerName();
      case 'modelli': case 'memoria': case 'cervello': return !!st.brain.recipe;
      case 'ascolto': case 'voce': return this.voiceQueued();
      case 'telegram': return st.telegram.linked;
      case 'backup': return st.backup.passphrase;
      case 'esterni': return !!st.later?.includes('esterni');   // optional cards, connected now or later
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
      case 'memoria': return this.embeddingList().map(c => c.model).join(', ');
      case 'ascolto': case 'voce': return this.voiceQueued() ? tr('Choice') : st.later.includes('voce') ? tr('Later') : '';
      case 'telegram': return st.telegram.linked ? tr('Linked') : st.later.includes('telegram') ? tr('Later') : '';
      case 'backup': return st.backup.passphrase ? tr('Ready') : st.later.includes('backup') ? tr('Later') : '';
      case 'fuori': return this.tunnel()?.on ? tr('Active') : '';
      default: return '';
    }
  }

  // ── «I modelli sono pronti»: the assistant's first message, written with the models just chosen ──
  hello = signal<{ ok: boolean; text?: string; html?: string; model?: string; detail?: string } | null>(null);
  helloBusy = signal(false);
  async sayHello() {
    if (this.helloBusy()) return;
    this.helloBusy.set(true);
    try {
      const h = await this.api.hello();
      // Same rendering as the chat: markdown → HTML, then the chat's own assistant text component.
      this.hello.set(h.ok ? { ...h, html: marked.parse(h.text || '', { gfm: true, async: false }) as string } : h);
    }
    catch (e) { this.hello.set({ ok: false, detail: setupError(e) }); }
    finally { this.helloBusy.set(false); }
    this.helloWait = this.hello()?.ok === false && this.activeDownloads() > 0;
  }
  /** It failed while a model was downloading: write again once the downloads are over (once). */
  private helloWait = false;

  /** «Tutto pronto»: one row per choice, a tap goes back to it. */
  recapSteps(): Screen[] { return ['chi', 'modelli', 'memoria', 'voce', 'telegram', 'backup', 'fuori']; }
  recapText(s: Screen): string {
    const st = this.state()!;
    switch (s) {
      case 'chi': return this.identity.ownerName() ? tr("{0} and {1}.", this.identity.ownerCall() || this.identity.ownerName(), this.identity.assistant()) : tr('You haven\'t told me your name yet.');
      case 'modelli': return st.brain.summary || tr('pl::Not chosen yet.');
      case 'memoria': { const list = this.embeddingList(); return list.length ? list.map(c => c.model).join(', ') : this.catalog()?.embedding?.model || tr('Not chosen yet.'); }
      case 'voce': return this.voiceQueued() ? tr('Chosen.') : tr('Later.');
      case 'telegram': return st.telegram.linked ? tr('Linked.') : tr('Later.');
      case 'backup': return st.backup.passphrase ? tr('Ready.') : tr('Later.');
      case 'fuori': return this.tunnel()?.on ? (this.tunnel()!.url || tr('Active.')) : tr('Only at home and from Telegram.');
      default: return '';
    }
  }

  canNext(): boolean {
    switch (this.screen()) {
      case 'chi': return !!this.ownerName.trim();
      case 'modelli': return (this.useLocal() || this.useCloud()) && this.cloudPicked().every(n => this.cloudReady()[n])
        && Object.values(this.modeOwn()).every(c => (!!c.home || c.order.length > 0) && c.order.every(n => this.cloudReady()[n]));
      case 'memoria': return this.embedOrder().every(n => this.embedReady()[n]) && (!!this.embeddingWanted() || !!this.catalog()?.embedding?.model);
      case 'ascolto': case 'voce': return this.voiceQueued() || this.voiceOk(this.screen() as VoiceDir);
      case 'telegram': return this.state()!.telegram.linked || (!this.code() && !this.state()!.telegram.token && !!this.botToken.trim());
      case 'backup': return this.state()!.backup.passphrase || this.passphrase.length >= 12;
      default: return true;
    }
  }

  nextLabel(): string {
    switch (this.screen()) {
      case 'benvenuto': return tr('Let\'s start');
      case 'memoria': return tr('Confirm');
      case 'telegram': return this.state()!.telegram.linked || this.code() || this.state()!.telegram.token ? tr('alt::Next') : tr('alt::Link');
      case 'backup': return this.state()!.backup.passphrase ? tr('alt::Next') : tr('Save');
      case 'voce': return this.voiceQueued() ? tr('alt::Next') : tr('Confirm');
      case 'ascolto': return tr('alt::Next');
      case 'fuori': return this.tunnel()?.on ? tr('alt::Next') : tr('Later');
      case 'pronto': return tr('f::Start');
      default: return tr('alt::Next');
    }
  }

  async next() {
    const screen = this.screen();
    const following = this.screens()[this.index() + 1];
    this.busy.set(true);
    try {
      if (screen === 'chi') {
        await this.identity.save({ assistant: this.assistantName, gender: this.assistantGender(), ownerName: this.ownerName, ownerCall: this.ownerCall, language: this.language() });
        this.assistantName = this.identity.assistant();
      }
      if (following === 'cervello') { await this.applyBrain(); return; }
      if (screen === 'voce' && !this.voiceQueued()) {
        const out = await this.api.voiceApply(this.voiceSteps('ascolto'), this.voiceSteps('voce'));
        if (!out.ok) { this.formError.set(out.detail || tr('I couldn\'t save the choice.')); return; }
        this.voiceQueued.set(true);
        void this.refreshDownloads();
        this.forward();   // the downloads go on by themselves, shown at the side
        return;
      }
      if (screen === 'telegram' && !this.state()!.telegram.linked) { await this.linkTelegram(); return; }
      if (screen === 'backup' && !this.state()!.backup.passphrase) {
        const r = await this.api.backup(this.passphrase);
        this.passphrase = '';
        if (!r.ok) { this.formError.set(tr('Saved, but the backup service didn\'t restart: try again shortly.')); }
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
          id: `ollama|${m.model}`, title: m.model, icon: 'download', tag: i === 0 ? tr('Recommended') : '',
          note: tr("{0} {1} GB to download: Ollama downloads it while you finish the rest.", m.good, this.gb(m.size_gb)) }));
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
    const warn = m.fits ? '' : tr("Bigger than the graphics card ({0} GB): it works, but slower.", vram);
    return [[what, size].filter(Boolean).join(', '), warn].filter(Boolean).join(' ');
  }
  runtimeText(r: Runtime): string {
    return r.name === 'ollama' ? tr('The simplest: {assistant} downloads by {g:herself|himself} the models suited to your graphics card.')
      : r.name === 'lmstudio' ? tr('With a window to search and download the models. Then turn on the local server.')
      : tr('The models are downloaded from there.');
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
    if (nowHome) out.push({ id: nowKey, title: now!.model, tag: tr('alt::Now'), note: many ? this.runtimeLabel(now!.provider || 'ollama') : '' });
    for (const r of this.found()) {
      for (const m of r.embed) if (`${r.name}|${m}` !== nowKey) out.push({ id: `${r.name}|${m}`, title: m, note: many ? r.label : '', group: many ? r.label : family(m) });
      const rec = this.catalog()?.recommended?.embedding;
      if (r.name === 'ollama' && rec && !r.embed.includes(rec.model) && `ollama|${rec.model}` !== nowKey) {
        out.push({ id: `ollama|${rec.model}`, title: rec.model, icon: 'download', tag: nowHome ? '' : tr('Recommended'),
                   note: tr("{0} {1} GB: Ollama downloads it while you finish the rest.", rec.good, this.gb(rec.size_gb)) });
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
  /** The memory models chosen, in order: the one at home first, then the cloud services in their order. */
  embeddingList(): { provider: string; model: string }[] {
    const out: { provider: string; model: string }[] = [];
    if (this.embedHome()) { const [provider, ...rest] = this.embedHome().split('|'); out.push({ provider, model: rest.join('|') }); }
    for (const n of this.embedOrder()) for (const m of this.embedPicks()[n] || []) out.push({ provider: n, model: m });
    return out;
  }
  embeddingWanted(): { provider: string; model: string } | null { return this.embeddingList()[0] || null; }
  /** What to send: nothing when the list stays the one in use. */
  private embeddingChoice(): { steps: ({ provider: string; model: string } & { url?: string; type?: string; label?: string })[] } | null {
    const list = this.embeddingList();
    const now = (this.catalog()?.embedding_steps || []).map(s => `${s.provider || 'ollama'}|${s.model}`).join(',');
    if (!list.length || list.map(s => `${s.provider}|${s.model}`).join(',') === now) return null;
    return { steps: list.map(s => ({ ...s, ...this.runtimeOf(s.provider) })) };
  }
  /** A program on another computer of the house: its address goes with the choice, so it becomes a block. */
  private runtimeOf(name: string): { url?: string; type?: string; label?: string } {
    const r = this.found().find(x => x.name === name);
    return r?.host && !r.configured ? { url: r.url, type: r.type, label: r.label } : {};
  }

  // ── Modalità: Ragionamento, Codice, Immagini use Generale's list unless one gets its own (the same step) ──
  readonly modeList = [
    { id: 'generale', label: tr('General'), help: '' },
    { id: 'potente', label: tr('Reasoning'), help: tr('For the hard questions.') },
    { id: 'codice', label: tr('Code'), help: tr('When it writes or fixes code.') },
    { id: 'visione', label: tr('Images'), help: tr('Photos and documents to look at.') },
  ];
  modeTab = signal('generale');
  /** Per mode with its own list: the same choices as Generale (local, services in order, models, «Scelti» order). */
  modeOwn = signal<Record<string, ModeChoice>>({});
  /** «Gli stessi di Generale» off → a copy of Generale to change; on → back to Generale. */
  toggleMode(mode: string) {
    const next = { ...this.modeOwn() };
    if (next[mode]) delete next[mode];
    else next[mode] = { home: this.localKey(), order: [...this.cloudPicked()], picks: { ...this.cloudModel() }, rank: [...this.cloudRank()] };
    this.modeOwn.set(next);
  }
  setMode<K extends keyof ModeChoice>(mode: string, field: K, value: ModeChoice[K]) {
    const cur = this.modeOwn()[mode];
    if (cur) this.modeOwn.set({ ...this.modeOwn(), [mode]: { ...cur, [field]: value } });
  }
  /** A saved list → the step's choices: a step on a program found here (or not a cloud service) is the local one. */
  private modeFromSteps(steps: { provider: string; model: string }[]): ModeChoice {
    const cloud = new Set((this.catalog()?.cloud || []).map(c => c.name));
    const out: ModeChoice = { home: '', order: [], picks: {}, rank: [] };
    for (const st of steps) {
      if (!cloud.has(st.provider)) { if (!out.home) { out.home = `${st.provider}|${st.model}`; out.rank.push('h'); } continue; }
      if (!out.order.includes(st.provider)) out.order.push(st.provider);
      if (st.model) out.picks[st.provider] = [...(out.picks[st.provider] || []), st.model];
      out.rank.push(st.model ? `m:${st.provider}:${st.model}` : `s:${st.provider}`);
    }
    return out;
  }
  /** What to send for each mode with its own list: its steps in the «Scelti» order (a program elsewhere with its address). */
  private modeSteps(): BrainChoice['modes'] {
    const out: BrainChoice['modes'] = {};
    for (const [mode, c] of Object.entries(this.modeOwn())) {
      const steps = ranked(chosenKeys(c.home, c.order, c.picks), c.rank).map(k => {
        const st = keyStep(k, c.home);
        return k === 'h' ? { ...st, ...this.runtimeOf(st.provider) } : st;
      });
      if (steps.length) out[mode] = { steps };
    }
    return out;
  }

  // ── Servizi cloud (the same cards as the voice's cloud services) ──
  keyLink(p: CloudProvider): string { return KEY_LINKS[p.type] || KEY_LINKS[p.name] || ''; }
  cloudLabel(name: string): string { const p = this.catalog()?.cloud.find(c => c.name === name); return p?.label || name; }
  cloudRows = computed<ServiceRow[]>(() => (this.catalog()?.cloud || []).map(p => p.type === CLAUDE_TYPE ? {
      name: p.name, label: p.label || p.name, kind: 'token' as const, keySet: !!this.state()?.claude.token || p.available,
      note: tr('Your Claude Pro or Max subscription.'), tokenLabel: tr('Claude subscription code'), tokenPlaceholder: 'sk-ant-oat…',
      tokenHint: tr('In the terminal type «claude setup-token», sign in with your Claude account (Pro or Max), then paste here the code it gives you.'),
    } : {
      name: p.name, label: p.label || p.name, kind: 'key' as const, keySet: p.key_set, keyLink: this.keyLink(p),
      tag: p.type === 'gemini' ? tr('alt::Free') : '', note: p.type === 'gemini' ? tr('Free key from Google.') : '',
    }));
  /** Per cloud service: its chat models (for «Per modalità») and its memory models, read by «Prova». */
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
    this.embedLists[name] = r.embed || [];
    return { ok: r.ok, detail: r.detail, recommended: r.recommended || [], options };
  };
  readonly embedTester = async (name: string, key: string): Promise<ServiceCheck> => {
    const r = await this.brainCheck(name, key);
    const embed = r.embed || [];
    this.embedLists[name] = embed;
    const ok = r.ok && embed.length > 0;
    return { ok, detail: ok ? tr("The key works: {0} for the memory.", embed.length === 1 ? tr('one model') : tr('{0} models', embed.length))
                            : r.ok ? tr('This service has no models for the memory.') : r.detail,
             recommended: embed.slice(0, 1), options: embed.map(m => ({ id: m, title: m, icon: 'zap', group: family(m) })) };
  };

  private async applyBrain() {
    const r = this.recipe();
    const local = this.localModel();
    const cloud = this.cloudPicked();
    const used = [...cloud, ...Object.values(this.modeOwn()).flatMap(c => c.order)];
    const claude = used.find(n => this.catalog()?.cloud.find(p => p.name === n)?.type === CLAUDE_TYPE);
    const models: Record<string, string[]> = {};
    for (const n of cloud) if (this.cloudModel()[n]?.length) models[n] = this.cloudModel()[n];
    const modes = this.modeSteps();
    const out = await this.api.apply(r, local, cloud, claude ? (this.cloudTokens()[claude] || '').trim() : '', {
      local_provider: this.localProvider(), cloud_models: models, embedding: this.embeddingChoice(),
      local_runtime: local ? this.runtimeOf(this.localProvider()) : {}, modes,
      order: ranked(chosenKeys(local ? this.localKey() : '', cloud, models), this.cloudRank()).map(k => keyStep(k, this.localKey())),
    });
    this.cloudTokens.set({});
    if (!out.ok) { this.formError.set(out.detail || tr('I couldn\'t save the choice.')); return; }
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
    else this.formError.set(r.detail || tr('The bot did not start: check the token.'));
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
  downloadHint(): string { return this.activeDownloads() === 1 ? tr('A download in progress: you can see it at the top.') : tr("{0} downloads in progress: you can see them at the top.", this.activeDownloads()); }
  private ticks = 0;

  private poll() {
    this.now.set(Date.now());
    this.ticks++;
    const screen = this.screen();
    if (screen === 'telegram' && this.code()) {
      void this.refresh().then(() => { if (this.state()?.telegram.linked) this.code.set(''); });
    }
    // the local model was still downloading: write again as soon as the downloads are over
    if (screen === 'cervello' && this.helloWait && !this.activeDownloads() && !this.helloBusy()) { this.helloWait = false; void this.sayHello(); }
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
    if (d.state === 'errore') return d.error || tr('I couldn\'t download it: I\'ll retry from the Downloads page.');
    if (d.state === 'in_coda') return tr('Queued.');
    if (d.state === 'in_pausa') return tr('Paused.');
    const gb = (n: number) => (n / 1e9).toFixed(1).replace('.', ',');
    const left = d.eta_s ? tr(" · {0} more", d.eta_s >= 60 ? Math.round(d.eta_s / 60) + ' min' : Math.round(d.eta_s) + ' s') : '';
    return d.size ? tr("{0} of {1} GB{2}", gb(d.done), gb(d.size), left) : tr('In progress…');
  }

  hardwareText(): string {
    const hw = this.state()?.hardware || {};
    const ram = hw.ram_gb ? tr("{0} GB of memory", Math.round(hw.ram_gb)) : '';
    const vram = hw.vram_gb || 0;
    const gpu = vram >= 12 ? tr("{0} GB graphics card: great for the models on your computer.", Math.round(vram))
      : vram >= 6 ? tr("{0} GB graphics card: fine for medium models.", Math.round(vram))
      : tr('No suitable graphics card: the cloud will be faster.');
    return hw.ram_gb || hw.vram_gb ? [ram, gpu].filter(Boolean).join(' · ') : tr('I don\'t know what this computer is like yet: I suggest the safest choice.');
  }
}
