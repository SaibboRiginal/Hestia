import { ChangeDetectionStrategy, Component, OnInit, computed, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ThemeService } from '../../core/theme/theme.service';
import { KNOB_OPTIONS, LookKnobs } from '../../core/theme/looks';
import { NoticeGroup, NoticeMode, NoticePrefsService, NoticeStyle } from '../../services/notice-prefs.service';
import { SessionService } from '../../services/session.service';
import { PushService } from '../../services/push.service';
import { AppearanceService } from '../../services/appearance.service';
import { SettingsService, THINKING_DISPLAY_OPTIONS } from '../../services/settings.service';
import { ButtonComponent, DialogService, IconComponent, SegmentedComponent, SegmentOption, ToastService, ToggleComponent } from '../../ui';
import { CentralSettingsStore, matches } from './central-settings.store';
import { SettingRowComponent } from './setting-row.component';
import { SettingShellComponent } from './setting-shell.component';

export interface PersonalSection { id: string; label: string; icon: string; }
interface PersonalRow { id: string; section: string; label: string; help: string; keywords: string; wide?: boolean; }

export const PERSONAL_SECTIONS: PersonalSection[] = [
  { id: 'aspetto', label: 'Aspetto', icon: 'palette' },
  { id: 'assistente', label: 'Assistente', icon: 'chat' },
  { id: 'messaggi', label: 'Messaggi di sistema', icon: 'bell' },
  { id: 'sessione', label: 'Sessione', icon: 'refresh' },
  { id: 'plugin', label: 'Moduli e Home', icon: 'puzzle' },
];

/** Every personal setting, so the page search finds them like the system ones. */
const ROWS: PersonalRow[] = [
  { id: 'theme', section: 'aspetto', label: 'Colori', wide: true, keywords: 'tema colori scuro chiaro dark light oceano foresta lavanda',
    help: 'Colori dell\'interfaccia su questo browser. «Automatico» segue il sistema.' },
  { id: 'style', section: 'aspetto', label: 'Stile', wide: true, keywords: 'stile vetro netto classico forma look',
    help: 'La forma dell\'interfaccia, sopra ai colori. Ogni stile è un punto di partenza: sotto puoi cambiare angoli, bordi, trasparenze e animazioni.' },
  { id: 'knobs', section: 'aspetto', label: 'Dettagli dello stile', wide: true,
    keywords: 'angoli bordi trasparenza blur sfocatura opacità animazioni movimento',
    help: 'Su questo browser. «Torna allo stile» rimette i valori dello stile scelto.' },
  { id: 'look', section: 'aspetto', label: 'Temi delle feste e animaletto', keywords: 'compleanno natale stagioni effetti neve animale pet',
    help: 'Nei giorni speciali (il tuo compleanno, le feste, le stagioni) i colori e un piccolo effetto cambiano da soli, sopra il tuo tema.' },
  { id: 'tone', section: 'assistente', label: 'Tono', keywords: 'stile risposte caldo formale diretto',
    help: 'Il tuo predefinito su ogni client. Una singola chat può cambiarlo dall\'icona delle impostazioni in alto nella chat.' },
  { id: 'thinking', section: 'assistente', label: 'Ragionamento nelle risposte', keywords: 'thinking pensiero',
    help: 'Solo visualizzazione: nascosto, compatto (chiuso), dettagliato (aperto, completo) o dal vivo (aperto mentre lavora). Si cambia anche dall\'icona delle impostazioni della chat.' },
  { id: 'instructions', section: 'assistente', label: 'Istruzioni personali', wide: true, keywords: 'prompt istruzioni',
    help: 'Aggiunte a ogni conversazione, su ogni client (vuoto = nessuna).' },
  { id: 'push', section: 'messaggi', label: 'Notifiche su questo dispositivo', keywords: 'push notifiche browser telefono pwa avvisi',
    help: 'Le notifiche arrivano anche a sito chiuso, come su Telegram. Tocca la notifica per aprire la pagina giusta.' },
  { id: 'notice_mode', section: 'messaggi', label: 'Dove mostrarli', keywords: 'avvisi notice popup toast',
    help: 'Avvisi separati dalla risposta: memoria salvata, azioni eseguite, notifiche attivate, errori. Su questo browser.' },
  { id: 'notice_style', section: 'messaggi', label: 'Stile dei messaggi', keywords: 'avvisi compatto dettagliato',
    help: 'Compatto: una riga. Dettagliato: con i particolari.' },
  { id: 'notice_groups', section: 'messaggi', label: 'Quali messaggi mostrare', wide: true,
    keywords: 'avvisi memoria azioni notifiche documenti agenda sviluppo',
    help: 'Gli errori vengono mostrati comunque, tranne con «Nascosti».' },
  { id: 'new_session', section: 'sessione', label: 'Nuova sessione', keywords: 'conversazione contesto reset',
    help: 'Hestia dimentica il contesto della conversazione (le memorie restano).' },
  { id: 'reset', section: 'sessione', label: 'Ripristina impostazioni personali', keywords: 'predefiniti reset',
    help: 'Tono, ragionamento, istruzioni e messaggi di sistema tornano ai predefiniti.' },
];

/** Personal rows matching a search (for the sidebar counters). */
export function personalHits(query: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const r of ROWS) {
    const s = PERSONAL_SECTIONS.find(x => x.id === r.section)!;
    if (matches(query, r.label, r.help, r.keywords, s.label, 'personali')) out.set(r.section, (out.get(r.section) ?? 0) + 1);
  }
  return out;
}

/**
 * Impostazioni → Personali: this client and your way of using Hestia, in the same rows as the
 * system settings. `section` shows one section; `query` shows every match (search).
 */
@Component({
  selector: 'app-personal-settings',
  imports: [FormsModule, RouterLink, SettingShellComponent, SettingRowComponent, ButtonComponent, IconComponent, SegmentedComponent, ToggleComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @for (s of shown(); track s.section.id) {
      <div class="group">
        <div class="gh"><h4><hx-icon [name]="s.section.icon" [size]="15" /> {{ s.section.label }}</h4></div>
        @for (r of s.rows; track r.id) {
          <hx-setting-shell [label]="r.label" [help]="r.help" [wide]="!!r.wide">
            @switch (r.id) {
              @case ('theme') {
                <div class="themes">
                  <button class="th" [class.on]="theme.selected() === 'auto'" (click)="theme.set('auto')">
                    <span class="pv auto"><i></i><i></i></span><span>Automatico (sistema)</span>
                  </button>
                  @for (t of themesSorted; track t.id) {
                    <button class="th" [class.on]="theme.selected() === t.id" (click)="theme.set(t.id)">
                      <span class="pv" [style.background]="t.tokens['--bg']" [style.border-color]="t.tokens['--border']">
                        <i [style.background]="t.tokens['--bg-subtle']"></i>
                        <b [style.background]="t.tokens['--accent']"></b>
                        <u [style.background]="t.tokens['--surface-2']"></u>
                      </span>
                      <span>{{ t.label }}</span>
                    </button>
                  }
                </div>
              }
              @case ('style') {
                <div class="styles">
                  @for (st of theme.styles; track st.id) {
                    <button class="st" [class.on]="theme.style().id === st.id" [attr.data-look]="st.id" (click)="theme.setStyle(st.id)">
                      <span class="spv"><i></i><b></b><u></u></span>
                      <span class="sl">{{ st.label }}</span><span class="sh">{{ st.help }}</span>
                    </button>
                  }
                </div>
              }
              @case ('knobs') {
                <div class="knobs">
                  @for (k of knobRows; track k.key) {
                    <div class="knob"><span class="kl">{{ k.label }}</span>
                      <hx-segmented [options]="k.options" [value]="theme.knobs()[k.key]" (changed)="theme.setKnob(k.key, $any($event))" />
                    </div>
                  }
                  @if (customised()) { <button hx-btn size="sm" variant="ghost" icon="refresh" (click)="theme.setStyle(theme.style().id)">Torna allo stile</button> }
                </div>
              }
              @case ('look') {
                <div class="look">
                  <span>@if (look.now(); as n) { Ora: <b>{{ n.profile.name }}</b>{{ n.why ? ' (' + n.why + ')' : '' }}{{ n.pet ? ' · ' + n.pet.name : '' }} } @else { Aspetto standard }</span>
                  <a hx-btn size="sm" icon="palette" routerLink="/p/aphrodite/aspetto">Scegli</a>
                </div>
              }
              @case ('push') {
                <div class="look">
                  <span>{{ pushLabel() }}</span>
                  @if (push.state() === 'on') { <button hx-btn size="sm" (click)="push.disable()">Disattiva</button> }
                  @else if (push.state() === 'off' || push.state() === 'busy') {
                    <button hx-btn size="sm" variant="primary" icon="bell" [loading]="push.state() === 'busy'" (click)="enablePush()">Attiva</button>
                  }
                </div>
              }
              @case ('tone') {
                <select class="hx-select" aria-label="Tono" (change)="save({ tone: $any($event.target).value })">
                  @for (o of tones; track o.value) { <option [value]="o.value" [selected]="settings.settings().tone === o.value">{{ o.label }}</option> }
                </select>
              }
              @case ('thinking') {
                <hx-segmented [options]="thinking" [value]="settings.settings().thinkingDisplay" (changed)="save({ thinkingDisplay: $event })" />
              }
              @case ('instructions') {
                <textarea class="hx-textarea" rows="4" [(ngModel)]="custom" aria-label="Istruzioni personali"></textarea>
                <button hx-btn size="sm" variant="primary" [disabled]="custom === settings.settings().customPrompt"
                        (click)="save({ customPrompt: custom })">Salva istruzioni</button>
              }
              @case ('notice_mode') {
                <select class="hx-select" aria-label="Dove mostrarli" (change)="notices.update({ mode: $any($event.target).value })">
                  @for (o of noticeModes; track o.value) { <option [value]="o.value" [selected]="notices.prefs().mode === o.value">{{ o.label }}</option> }
                </select>
              }
              @case ('notice_style') {
                <hx-segmented [options]="noticeStyles" [value]="notices.prefs().style" (changed)="notices.update({ style: $any($event) })" />
              }
              @case ('notice_groups') {
                <div class="toggles">
                  @for (g of noticeGroups; track g.id) {
                    <hx-toggle [checked]="notices.prefs().groups[g.id]" [label]="g.label" (changed)="setGroup(g.id, $event)" />
                  }
                </div>
              }
              @case ('new_session') { <button hx-btn size="sm" (click)="newSession()">Nuova sessione</button> }
              @case ('reset') { <button hx-btn size="sm" icon="refresh" (click)="reset()">Ripristina</button> }
            }
          </hx-setting-shell>
        }
        @if (s.section.id === 'assistente') { @for (it of store.personalExtra(); track it.key) { <hx-setting [item]="it" /> } }
      </div>
    }`,
  styles: [`
    :host { display: flex; flex-direction: column; gap: 14px; }
    .group { border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 6px 14px 4px; background: var(--surface); }
    .gh { padding: 8px 0 6px; }
    .gh h4 { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 7px; }
    .hx-select { width: 100%; }
    textarea { width: 100%; }
    .look { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; font-size: 13.5px; color: var(--text-2); }
    .look span { flex: 1; min-width: 180px; }
    .toggles { display: flex; flex-wrap: wrap; gap: 12px 22px; }
    .themes { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; width: 100%; }
    .th { display: flex; flex-direction: column; gap: 6px; padding: 8px; border-radius: var(--radius-lg); border: 2px solid transparent; font-size: 13px; text-align: left; color: var(--text-2); }
    .th:hover { background: var(--surface-2); }
    .th.on { border-color: var(--accent); color: var(--text); }
    .pv { height: 70px; border-radius: var(--radius-md); border: 1px solid var(--border); position: relative; overflow: hidden; display: block; }
    .pv i { position: absolute; inset: 0 auto 0 0; width: 30%; }
    .pv b { position: absolute; right: 10px; bottom: 10px; width: 26px; height: 12px; border-radius: 6px; }
    .pv u { position: absolute; left: 38%; right: 10px; top: 12px; height: 10px; border-radius: 5px; }
    .pv.auto { background: linear-gradient(135deg, #faf9f5 50%, #262624 50%); }
    .styles { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; width: 100%; }
    .st { display: flex; flex-direction: column; gap: 4px; padding: 8px; border-radius: var(--radius-lg); border: 2px solid transparent; text-align: left; color: var(--text-2); }
    .st:hover { background: var(--surface-2); }
    .st.on { border-color: var(--accent); color: var(--text); }
    .sl { font-size: 13.5px; font-weight: 600; } .sh { font-size: 12px; color: var(--text-3); line-height: 1.35; }
    /* Little drawing of each style, with the current colours */
    .spv { height: 64px; position: relative; display: block; border-radius: 12px; overflow: hidden; margin-bottom: 4px; background: var(--bg); border: 1px solid var(--border); }
    .spv i { position: absolute; left: 8px; top: 8px; bottom: 8px; width: 28%; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; }
    .spv b { position: absolute; left: 40%; right: 8px; top: 8px; height: 22px; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; box-shadow: var(--shadow-1); }
    .spv u { position: absolute; right: 8px; bottom: 8px; width: 30px; height: 12px; background: var(--accent); border-radius: 6px; }
    .st[data-look=vetro] .spv { border-radius: 16px; background: radial-gradient(ellipse at 15% 10%, var(--accent-soft), transparent 60%), radial-gradient(ellipse at 90% 90%, var(--info-soft), transparent 60%), var(--bg); }
    .st[data-look=vetro] .spv i, .st[data-look=vetro] .spv b { background: color-mix(in srgb, var(--surface) 60%, transparent); border-color: color-mix(in srgb, var(--border) 50%, transparent); border-radius: 12px; }
    .st[data-look=netto] .spv { border-radius: 4px; }
    .st[data-look=netto] .spv i, .st[data-look=netto] .spv b { border-radius: 2px; border-color: var(--text-3); box-shadow: none; }
    .st[data-look=netto] .spv u { border-radius: 1px; }
    .knobs { display: flex; flex-direction: column; gap: 10px; width: 100%; }
    .knob { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
    .kl { width: 110px; font-size: 13px; color: var(--text-2); }
  `],
})
export class PersonalSettingsComponent implements OnInit {
  readonly store = inject(CentralSettingsStore);
  section = input<string | null>(null);
  query = input('');

  theme = inject(ThemeService);
  settings = inject(SettingsService);
  notices = inject(NoticePrefsService);
  push = inject(PushService);
  look = inject(AppearanceService);
  private session = inject(SessionService);
  private toast = inject(ToastService);
  private dialogs = inject(DialogService);
  custom = this.settings.settings().customPrompt ?? '';

  /** Light themes first, then dark (the original order inside each). */
  readonly themesSorted = [...this.theme.themes].sort((a, b) => (a.mode === b.mode ? 0 : a.mode === 'light' ? -1 : 1));
  readonly knobRows: { key: keyof LookKnobs; label: string; options: SegmentOption[] }[] = [
    { key: 'corners', label: 'Angoli', options: [...KNOB_OPTIONS.corners] },
    { key: 'borders', label: 'Bordi', options: [...KNOB_OPTIONS.borders] },
    { key: 'glass', label: 'Trasparenze', options: [...KNOB_OPTIONS.glass] },
    { key: 'motion', label: 'Animazioni', options: [...KNOB_OPTIONS.motion] },
  ];
  readonly customised = computed(() => Object.keys(this.theme.look().knobs).length > 0);

  readonly shown = computed(() => {
    const q = this.query().trim();
    return PERSONAL_SECTIONS
      .filter(s => q || s.id === this.section())
      .map(s => ({ section: s, rows: ROWS.filter(r => r.section === s.id
        && (!q || matches(q, r.label, r.help, r.keywords, s.label, 'personali'))) }))
      .filter(s => s.rows.length || (s.section.id === 'assistente' && this.store.personalExtra().length));
  });

  readonly tones: SegmentOption[] = [
    { value: 'neutral', label: 'Neutro' }, { value: 'warm', label: 'Caldo' }, { value: 'direct', label: 'Diretto' }, { value: 'formal', label: 'Formale' },
  ];
  readonly thinking: SegmentOption[] = THINKING_DISPLAY_OPTIONS;
  readonly noticeModes: SegmentOption[] = [
    { value: 'inline', label: 'Sotto la risposta' }, { value: 'toast', label: 'Popup' }, { value: 'both', label: 'Entrambi' },
    { value: 'important', label: 'Solo importanti' }, { value: 'hidden', label: 'Nascosti' },
  ] satisfies { value: NoticeMode; label: string }[];
  readonly noticeStyles: SegmentOption[] = [
    { value: 'compact', label: 'Compatto' }, { value: 'rich', label: 'Dettagliato' },
  ] satisfies { value: NoticeStyle; label: string }[];
  readonly noticeGroups: { id: NoticeGroup; label: string }[] = [
    { id: 'memory', label: 'Memoria' }, { id: 'actions', label: 'Azioni' },
    { id: 'subscriptions', label: 'Notifiche' }, { id: 'other', label: 'Altro (documenti, agenda, sviluppo)' },
  ];
  readonly pushLabel = computed(() => ({
    unsupported: 'Questo browser non riceve notifiche push.', unavailable: 'Non ancora attive sul server.',
    denied: 'Il browser le blocca: consentile dalle impostazioni del sito.', off: 'Spente su questo dispositivo.',
    on: 'Attive su questo dispositivo.', busy: 'Un momento…',
  })[this.push.state()]);

  ngOnInit(): void { void this.push.refresh(); }

  async enablePush() {
    if (await this.push.enable()) this.toast.success('Notifiche attive su questo dispositivo');
    else if (this.push.state() === 'off') this.toast.error('Non riuscito, riprova');
  }

  setGroup(id: NoticeGroup, on: boolean) {
    this.notices.update({ groups: { ...this.notices.prefs().groups, [id]: on } });
  }

  async save(p: Record<string, string>) {
    try { await this.settings.update(p); this.toast.success('Salvato'); } catch { this.toast.error('Salvataggio non riuscito'); }
  }
  async newSession() {
    if (await this.dialogs.confirm('Nuova sessione?')) { await this.session.clear(); this.toast.success('Nuova sessione'); }
  }
  async reset() {
    if (!await this.dialogs.confirm('Ripristinare le impostazioni personali?')) return;
    await this.settings.reset();
    this.notices.reset();
    this.custom = this.settings.settings().customPrompt ?? '';
    this.toast.success('Impostazioni ripristinate');
  }
}
