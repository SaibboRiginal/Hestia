import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { SystemSettingsComponent } from './system-settings.component';
import { ThemeService } from '../../core/theme/theme.service';
import { SettingsService } from '../../services/settings.service';
import { SessionService } from '../../services/session.service';
import { ButtonComponent, DialogService, FieldComponent, IconComponent, PageHeaderComponent, SegmentedComponent, SegmentOption, ToastService, ToggleComponent } from '../../ui';
import { NoticeGroup, NoticeMode, NoticePrefsService, NoticeStyle } from '../../services/notice-prefs.service';

/** Personali (appearance, assistant behaviour for this client) + Sistema (central settings, Themis). */
@Component({
  selector: 'app-settings-page',
  imports: [FormsModule, SystemSettingsComponent, PageHeaderComponent, ButtonComponent, IconComponent, FieldComponent, SegmentedComponent, ToggleComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Impostazioni" [subtitle]="tab() === 'system' ? 'Tutti i moduli di Hestia: valori, stato, preset' : 'Questo client e il tuo modo di usare Hestia'">
      <hx-segmented [options]="tabs" [value]="tab()" (changed)="setTab($event)" />
    </hx-page-header>
    @if (tab() === 'system') {
      <app-system-settings [module]="module" />
    } @else {
    <div class="body">
      <section>
        <h3><hx-icon name="palette" [size]="17" /> Aspetto</h3>
        <div class="themes">
          <button class="th" [class.on]="theme.selected() === 'auto'" (click)="theme.set('auto')">
            <span class="pv auto"><i></i><i></i></span><span>Automatico (sistema)</span>
          </button>
          @for (t of theme.themes; track t.id) {
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
        <p class="hint">Nuovo tema: aggiungi una voce in <code>src/app/core/theme/themes.ts</code> (vedi DESIGN-SYSTEM.md).</p>
      </section>

      <section>
        <h3><hx-icon name="chat" [size]="17" /> Assistente</h3>
        <hx-field label="Tono">
          <hx-segmented [options]="tones" [value]="settings.settings().tone" (changed)="save({ tone: $event })" />
        </hx-field>
        <hx-field label="Ragionamento nelle risposte" hint="Solo visualizzazione: nascosto, compatto (chiuso) o dettagliato (aperto).">
          <hx-segmented [options]="thinking" [value]="settings.settings().thinkingDisplay" (changed)="save({ thinkingDisplay: $event })" />
        </hx-field>
        <hx-field label="Istruzioni personali" hint="Aggiunte a ogni messaggio verso Oracle da questo client.">
          <textarea class="hx-textarea" rows="4" [(ngModel)]="custom"></textarea>
        </hx-field>
        <button hx-btn variant="primary" (click)="save({ customPrompt: custom })">Salva istruzioni</button>
      </section>

      <section>
        <h3><hx-icon name="bell" [size]="17" /> Messaggi di sistema</h3>
        <p class="hint">Avvisi separati dalla risposta: memoria salvata, azioni eseguite, notifiche attivate, errori. Valgono per questo browser.</p>
        <hx-field label="Dove mostrarli">
          <hx-segmented [options]="noticeModes" [value]="notices.prefs().mode" (changed)="notices.update({ mode: $any($event) })" />
        </hx-field>
        <hx-field label="Stile">
          <hx-segmented [options]="noticeStyles" [value]="notices.prefs().style" (changed)="notices.update({ style: $any($event) })" />
        </hx-field>
        <div class="toggles">
          @for (g of noticeGroups; track g.id) {
            <hx-toggle [checked]="notices.prefs().groups[g.id]" [label]="g.label" (changed)="setGroup(g.id, $event)" />
          }
        </div>
        <p class="hint">Gli errori vengono mostrati comunque, tranne con «Nascosti».</p>
      </section>

      <section>
        <h3><hx-icon name="refresh" [size]="17" /> Sessione</h3>
        <p class="hint">Nuova sessione: Hestia dimentica il contesto della conversazione (le memorie restano).</p>
        <div class="hx-row">
          <button hx-btn (click)="newSession()">Nuova sessione</button>
          <button hx-btn variant="ghost" (click)="reset()">Ripristina impostazioni</button>
        </div>
      </section>
    </div>
    }`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    hx-page-header { padding-left: 56px; }
    @media (min-width: 861px) { hx-page-header { padding-left: 24px; } }
    .body { flex: 1; overflow-y: auto; padding: 18px 24px 40px; }
    section { max-width: 760px; display: flex; flex-direction: column; gap: 14px; padding: 6px 0 26px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
    section:last-child { border-bottom: 0; }
    .toggles { display: flex; flex-wrap: wrap; gap: 12px 22px; }
    h3 { font-size: 15px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
    .themes { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 10px; }
    .th { display: flex; flex-direction: column; gap: 6px; padding: 8px; border-radius: var(--radius-lg); border: 2px solid transparent; font-size: 13px; text-align: left; color: var(--text-2); }
    .th:hover { background: var(--surface-2); }
    .th.on { border-color: var(--accent); color: var(--text); }
    .pv { height: 70px; border-radius: var(--radius-md); border: 1px solid var(--border); position: relative; overflow: hidden; display: block; }
    .pv i { position: absolute; inset: 0 auto 0 0; width: 30%; }
    .pv b { position: absolute; right: 10px; bottom: 10px; width: 26px; height: 12px; border-radius: 6px; }
    .pv u { position: absolute; left: 38%; right: 10px; top: 12px; height: 10px; border-radius: 5px; }
    .pv.auto { background: linear-gradient(135deg, #faf9f5 50%, #262624 50%); }
    .hint { font-size: 12.5px; color: var(--text-3); }
    button[hx-btn] { align-self: flex-start; }
  `],
})
export class SettingsPageComponent {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  readonly tabs: SegmentOption[] = [{ value: 'personal', label: 'Personali' }, { value: 'system', label: 'Sistema' }];
  /** Deep links: /settings?tab=system&module=oracle */
  readonly tab = signal(this.route.snapshot.queryParamMap.get('tab') === 'system' ? 'system' : 'personal');
  readonly module = this.route.snapshot.queryParamMap.get('module');
  setTab(t: string) {
    this.tab.set(t);
    void this.router.navigate([], { queryParams: { tab: t === 'system' ? 'system' : null }, queryParamsHandling: 'merge', replaceUrl: true });
  }

  theme = inject(ThemeService);
  settings = inject(SettingsService);
  private session = inject(SessionService);
  private toast = inject(ToastService);
  private dialogs = inject(DialogService);
  custom = this.settings.settings().customPrompt ?? '';

  readonly tones: SegmentOption[] = [
    { value: 'neutral', label: 'Neutro' }, { value: 'warm', label: 'Caldo' }, { value: 'direct', label: 'Diretto' }, { value: 'formal', label: 'Formale' },
  ];
  readonly thinking: SegmentOption[] = [
    { value: 'hidden', label: 'Nascosto' }, { value: 'compact', label: 'Compatto' }, { value: 'detailed', label: 'Dettagliato' },
  ];

  notices = inject(NoticePrefsService);
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
    await this.settings.reset();
    this.notices.reset();
    this.custom = this.settings.settings().customPrompt ?? '';
    this.toast.success('Impostazioni ripristinate');
  }
}
