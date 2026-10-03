import { Injectable, computed, signal } from '@angular/core';
import { BASE_TOKENS, DEFAULT_DARK, DEFAULT_LIGHT, THEMES, ThemeDef } from './themes';

const STORAGE_KEY = 'hestia_theme';

/**
 * Applies a theme by writing its tokens as CSS variables on <html>.
 * 'auto' follows the OS light/dark preference.
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
    this.set(this.active().mode === 'dark' ? DEFAULT_LIGHT : DEFAULT_DARK);
  }

  private apply(): void {
    const theme = this.active();
    const root = document.documentElement;
    for (const [k, v] of Object.entries({ ...BASE_TOKENS, ...theme.tokens })) root.style.setProperty(k, v);
    root.dataset['theme'] = theme.id;
    root.dataset['mode'] = theme.mode;
    root.style.colorScheme = theme.mode;
  }

  private read(): string | null {
    try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
  }
}
