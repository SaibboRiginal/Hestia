import { Injectable, computed, signal } from '@angular/core';
import { BASE_TOKENS, DEFAULT_DARK, DEFAULT_LIGHT, THEMES, ThemeDef } from './themes';
import { DEFAULT_STYLE, GLASS, LookKnobs, MOTION, RADII, STYLES, StyleDef } from './looks';

const STORAGE_KEY = 'hestia_theme';
const LOOK_KEY = 'hestia_look';

/** Saved per device: the style and the knobs changed by hand over it. */
interface SavedLook { style: string; knobs: Partial<LookKnobs>; }

/**
 * Applies a theme by writing its tokens as CSS variables on <html>.
 * 'auto' follows the OS light/dark preference. Over the colours: the interface style (looks.ts) and its knobs.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  readonly themes = THEMES;
  /** Selected id, or 'auto'. */
  readonly selected = signal<string>(this.read() || 'auto');
  private readonly systemDark = signal(window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false);

  readonly active = computed<ThemeDef>(() => {
    const sel = this.selected();
    const id = sel === 'auto' ? (this.systemDark() ? DEFAULT_DARK : DEFAULT_LIGHT) : sel;
    return THEMES.find(t => t.id === id) ?? THEMES[0];
  });

  readonly styles = STYLES;
  readonly look = signal<SavedLook>(this.readLook());
  readonly style = computed<StyleDef>(() => STYLES.find(x => x.id === this.look().style) ?? STYLES[0]);
  /** Style preset with the hand-changed knobs on top. */
  readonly knobs = computed<LookKnobs>(() => ({ ...this.style().knobs, ...this.look().knobs }));

  /** Accent colours of the active graphic profile (Aphrodite: birthday, holidays, seasons), over this theme. */
  private overlay: Record<string, string> = {};

  constructor() {
    window.matchMedia?.('(prefers-color-scheme: dark)')
      .addEventListener?.('change', e => { this.systemDark.set(e.matches); this.apply(); });
    this.apply();
  }

  set(id: string): void {
    this.selected.set(id);
    try { localStorage.setItem(STORAGE_KEY, id); } catch { /* private mode */ }
    this.apply();
  }

  /** Quick light/dark flip keeping the family when possible. */
  toggleMode(): void {
    const t = this.active();
    this.set(t.pair ?? (t.mode === 'dark' ? DEFAULT_LIGHT : DEFAULT_DARK));
  }

  /** Picks a style: its knobs start from the preset again. */
  setStyle(id: string): void { this.saveLook({ style: id, knobs: {} }); }

  /** Changes one knob over the style (same value as the preset = not overridden). */
  setKnob<K extends keyof LookKnobs>(key: K, value: LookKnobs[K]): void {
    const knobs = { ...this.look().knobs };
    if (this.style().knobs[key] === value) delete knobs[key]; else knobs[key] = value;
    this.saveLook({ style: this.look().style, knobs });
  }

  private saveLook(look: SavedLook): void {
    this.look.set(look);
    try { localStorage.setItem(LOOK_KEY, JSON.stringify(look)); } catch { /* private mode */ }
    this.apply();
  }

  /** Sets (or clears with {}) the profile accents: `accent`, `accent2` as hex colours. */
  setPalette(palette: Record<string, string>): void {
    const hex = (v?: string) => (v && /^#[0-9a-f]{6}$/i.test(v) ? v : '');
    const a = hex(palette['accent']), b = hex(palette['accent2']);
    const next: Record<string, string> = {};
    if (a) {
      const [r, g, bl] = [1, 3, 5].map(i => parseInt(a.slice(i, i + 2), 16));
      next['--accent'] = a;
      next['--accent-hover'] = `color-mix(in srgb, ${a} 86%, #000)`;
      next['--accent-soft'] = `rgba(${r},${g},${bl},.14)`;
    }
    next['--accent-2'] = b || a || '';
    if (JSON.stringify(next) === JSON.stringify(this.overlay)) return;
    this.overlay = next;
    this.apply();
  }

  private apply(): void {
    const theme = this.active();
    const root = document.documentElement;
    const k = this.knobs();
    const tokens: Record<string, string> = { ...BASE_TOKENS, ...theme.tokens, ...this.style().tokens, ...RADII[k.corners], ...MOTION[k.motion] };
    const t = theme.tokens;
    if (k.borders === 'leggeri') {
      tokens['--border'] = `color-mix(in srgb, ${t['--border']} 55%, transparent)`;
      tokens['--border-strong'] = `color-mix(in srgb, ${t['--border-strong']} 75%, transparent)`;
    } else if (k.borders === 'marcati') {
      tokens['--border'] = t['--border-strong'];
      tokens['--border-strong'] = `color-mix(in srgb, ${t['--border-strong']} 65%, ${t['--text']})`;
    }
    // Transparency: the main surfaces let the shaded backdrop through; floating panels blur what is behind them.
    const g = GLASS[k.glass];
    const see = (name: string, pct: number) => { if (pct < 100) tokens[name] = `color-mix(in srgb, ${t[name]} ${pct}%, transparent)`; };
    see('--surface', g.surface); see('--bg-subtle', g.subtle); see('--surface-2', g.surface2);
    tokens['--glass'] = g.blur;
    tokens['--backdrop'] = k.glass === 'no' ? 'var(--bg)'
      : 'radial-gradient(ellipse at 12% 8%, var(--accent-soft), transparent 55%), '
        + 'radial-gradient(ellipse at 88% 92%, var(--info-soft), transparent 60%), '
        + 'radial-gradient(ellipse at 70% 20%, var(--success-soft), transparent 45%), var(--bg)';
    for (const [name, v] of Object.entries(tokens)) root.style.setProperty(name, v);
    for (const [name, v] of Object.entries(this.overlay)) if (v) root.style.setProperty(name, v); else root.style.removeProperty(name);
    root.dataset['theme'] = theme.id;
    root.dataset['mode'] = theme.mode;
    root.dataset['style'] = this.style().id;
    root.dataset['glass'] = k.glass;
    root.dataset['motion'] = k.motion;
    root.style.colorScheme = theme.mode;
  }

  private read(): string | null {
    try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
  }

  private readLook(): SavedLook {
    try {
      const v = JSON.parse(localStorage.getItem(LOOK_KEY) || 'null');
      if (v && typeof v.style === 'string') return { style: v.style, knobs: v.knobs && typeof v.knobs === 'object' ? v.knobs : {} };
    } catch { /* private mode or broken value */ }
    return { style: DEFAULT_STYLE, knobs: {} };
  }
}
