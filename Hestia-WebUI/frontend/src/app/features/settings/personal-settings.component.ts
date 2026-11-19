import { PERSONAL_ROWS, PERSONAL_SECTIONS } from './personal-rows';
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
import { tr, TrPipe } from '../../core/i18n';

export { PERSONAL_ROWS, PERSONAL_SECTIONS } from './personal-rows';

/** Personal rows matching a search (for the sidebar counters). */
export function personalHits(query: string): Map<string, number> {
  const out = new Map<string, number>();
  for (const r of PERSONAL_ROWS) {
    const s = PERSONAL_SECTIONS.find(x => x.id === r.section)!;
    if (matches(query, r.label, r.help, r.keywords, s.label, 'personal')) out.set(r.section, (out.get(r.section) ?? 0) + 1);
  }
  return out;
}

/**
 * Settings → Personal: this client and your way of using the assistant, in the same rows as the
 * system settings. `section` shows one section; `query` shows every match (search).
 */
@Component({
  selector: 'app-personal-settings',
  imports: [TrPipe, FormsModule, RouterLink, SettingShellComponent, SettingRowComponent, ButtonComponent, IconComponent, SegmentedComponent, ToggleComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @for (s of shown(); track s.section.id) {
      <div class="group">
        <div class="gh"><h4><hx-icon [name]="s.section.icon" [size]="15" /> {{ s.section.label }}</h4></div>
        @for (r of s.rows; track r.id) {
          <hx-setting-shell [label]="r.label" [help]="r.help" [wide]="!!r.wide" [attr.data-row]="r.id">
            @switch (r.id) {
              @case ('theme') {
                <div class="themes">
                  <button class="th" [class.on]="theme.selected() === 'auto'" (click)="theme.set('auto')">
                    <span class="pv auto"><i></i><i></i></span><span>{{ "Automatic (system)" | tr }}</span>
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
                  @if (customised()) { <button hx-btn size="sm" variant="ghost" icon="refresh" (click)="theme.setStyle(theme.style().id)">{{ "Back to style" | tr }}</button> }
                </div>
              }
              @case ('look') {
                <div class="look">
                  <span>@if (look.now(); as n) { {{ "Now:" | tr }} <b>{{ n.profile.name }}</b>{{ n.why ? ' (' + n.why + ')' : '' }} } @else { {{ "Standard look" | tr }} }</span>
                  <a hx-btn size="sm" icon="palette" routerLink="/p/aphrodite/look">{{ "Choose" | tr }}</a>
                </div>
              }
              @case ('mascot') {
                <div class="look">
                  @if (look.hasLook()) {
                    <select class="hx-select" [attr.aria-label]="'Mascot' | tr" (focus)="look.loadPets()" (change)="look.choosePet($any($event.target).value)">
                      <option value="none" [selected]="!look.now()?.pet">{{ "None" | tr }}</option>
                      @for (p of mascots(); track p.id) { <option [value]="p.id" [selected]="look.now()?.pet?.id === p.id">{{ p.name }}</option> }
                    </select>
                    <a hx-btn size="sm" variant="ghost" icon="plus" routerLink="/p/aphrodite/look">{{ "Make your own" | tr }}</a>
                  } @else { <span>{{ "Not available" | tr }}</span> }
                </div>
              }
              @case ('push') {
                <div class="look">
                  <span>{{ pushLabel() }}</span>
                  @if (push.state() === 'on') { <button hx-btn size="sm" (click)="push.disable()">{{ "alt::Turn off" | tr }}</button> }
                  @else if (push.state() === 'off' || push.state() === 'busy') {
                    <button hx-btn size="sm" variant="primary" icon="bell" [loading]="push.state() === 'busy'" (click)="enablePush()">{{ "f::Active" | tr }}</button>
                  }
                </div>
              }
              @case ('tone') {
                <select class="hx-select"  [attr.aria-label]="'Tone' | tr" (change)="save({ tone: $any($event.target).value })">
                  @for (o of tones; track o.value) { <option [value]="o.value" [selected]="settings.settings().tone === o.value">{{ o.label }}</option> }
                </select>
              }
              @case ('thinking') {
                <hx-segmented [options]="thinking" [value]="settings.settings().thinkingDisplay" (changed)="save({ thinkingDisplay: $event })" />
              }
              @case ('instructions') {
                <textarea class="hx-textarea" rows="4" [(ngModel)]="custom"  [attr.aria-label]="'Personal instructions' | tr"></textarea>
                <button hx-btn size="sm" variant="primary" [disabled]="custom === settings.settings().customPrompt"
                        (click)="save({ customPrompt: custom })">{{ "Save instructions" | tr }}</button>
              }
              @case ('notice_mode') {
                <select class="hx-select"  [attr.aria-label]="'Where to show them' | tr" (change)="notices.update({ mode: $any($event.target).value })">
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
              @case ('new_session') { <button hx-btn size="sm" (click)="newSession()">{{ "New session" | tr }}</button> }
              @case ('reset') { <button hx-btn size="sm" icon="refresh" (click)="reset()">{{ "f::Restore" | tr }}</button> }
            }
          </hx-setting-shell>
        }
        @if (s.section.id === 'assistant') { @for (it of store.personalExtra(); track it.key) { <hx-setting [item]="it" /> } }
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
    .st[data-look=glass] .spv { border-radius: 16px; background: radial-gradient(ellipse at 15% 10%, var(--accent-soft), transparent 60%), radial-gradient(ellipse at 90% 90%, var(--info-soft), transparent 60%), var(--bg); }
    .st[data-look=glass] .spv i, .st[data-look=glass] .spv b { background: color-mix(in srgb, var(--surface) 60%, transparent); border-color: color-mix(in srgb, var(--border) 50%, transparent); border-radius: 12px; }
    .st[data-look=net] .spv { border-radius: 4px; }
    .st[data-look=net] .spv i, .st[data-look=net] .spv b { border-radius: 2px; border-color: var(--text-3); box-shadow: none; }
    .st[data-look=net] .spv u { border-radius: 1px; }
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
  /** The mascots to choose from; the current one is there even before the list is loaded. */
  readonly mascots = computed(() => {
    const list = this.look.pets();
    const cur = this.look.now()?.pet;
    return cur && !list.some(p => p.id === cur.id) ? [{ id: cur.id, name: cur.name }, ...list] : list;
  });
  private session = inject(SessionService);
  private toast = inject(ToastService);
  private dialogs = inject(DialogService);
  custom = this.settings.settings().customPrompt ?? '';

  /** Light themes first, then dark (the original order inside each). */
  readonly themesSorted = [...this.theme.themes].sort((a, b) => (a.mode === b.mode ? 0 : a.mode === 'light' ? -1 : 1));
  readonly knobRows: { key: keyof LookKnobs; label: string; options: SegmentOption[] }[] = [
    { key: 'corners', label: tr('Corners'), options: [...KNOB_OPTIONS.corners] },
    { key: 'borders', label: tr('Borders'), options: [...KNOB_OPTIONS.borders] },
    { key: 'glass', label: tr('Transparency'), options: [...KNOB_OPTIONS.glass] },
    { key: 'motion', label: tr('Animations'), options: [...KNOB_OPTIONS.motion] },
  ];
  readonly customised = computed(() => Object.keys(this.theme.look().knobs).length > 0);

  readonly shown = computed(() => {
    const q = this.query().trim();
    return PERSONAL_SECTIONS
      .filter(s => q || s.id === this.section())
      .map(s => ({ section: s, rows: PERSONAL_ROWS.filter(r => r.section === s.id
        && (!q || matches(q, r.label, r.help, r.keywords, s.label, 'personal'))) }))
      .filter(s => s.rows.length || (s.section.id === 'assistant' && this.store.personalExtra().length));
  });

  readonly tones: SegmentOption[] = [
    { value: 'neutral', label: tr('Neutral') }, { value: 'warm', label: tr('Warm') }, { value: 'direct', label: tr('Direct') }, { value: 'formal', label: tr('Formal') },
  ];
  readonly thinking: SegmentOption[] = THINKING_DISPLAY_OPTIONS;
  readonly noticeModes: SegmentOption[] = [
    { value: 'inline', label: tr('Under the answer') }, { value: 'toast', label: tr('Popup') }, { value: 'both', label: tr('Both') },
    { value: 'important', label: tr('Only important ones') }, { value: 'hidden', label: tr('pl::Hidden') },
  ] satisfies { value: NoticeMode; label: string }[];
  readonly noticeStyles: SegmentOption[] = [
    { value: 'compact', label: tr('Compact') }, { value: 'rich', label: tr('Detailed') },
  ] satisfies { value: NoticeStyle; label: string }[];
  readonly noticeGroups: { id: NoticeGroup; label: string }[] = [
    { id: 'memory', label: tr('Memory') }, { id: 'actions', label: tr('Actions') },
    { id: 'subscriptions', label: tr('Notifications') }, { id: 'other', label: tr('More (documents, agenda, development)') },
  ];
  readonly pushLabel = computed(() => ({
    unsupported: tr('This browser doesn\'t receive push notifications.'), unavailable: tr('Not active on the server yet.'),
    denied: tr('The browser blocks them: allow them from the site settings.'), off: tr('Off on this device.'),
    on: tr('Active on this device.'), busy: tr('alt::One moment…'),
  })[this.push.state()]);

  ngOnInit(): void { void this.push.refresh(); void this.look.loadPets(); }

  async enablePush() {
    if (await this.push.enable()) this.toast.success(tr('Notifications active on this device'));
    else if (this.push.state() === 'off') this.toast.error(tr('Did not work, try again'));
  }

  setGroup(id: NoticeGroup, on: boolean) {
    this.notices.update({ groups: { ...this.notices.prefs().groups, [id]: on } });
  }

  async save(p: Record<string, string>) {
    try { await this.settings.update(p); this.toast.success(tr('Saved')); } catch { this.toast.error(tr('Saving failed')); }
  }
  async newSession() {
    if (await this.dialogs.confirm(tr('New session?'))) { await this.session.clear(); this.toast.success(tr('New session')); }
  }
  async reset() {
    if (!await this.dialogs.confirm(tr('Restore the personal settings?'))) return;
    await this.settings.reset();
    this.notices.reset();
    this.custom = this.settings.settings().customPrompt ?? '';
    this.toast.success(tr('Settings restored'));
  }
}
