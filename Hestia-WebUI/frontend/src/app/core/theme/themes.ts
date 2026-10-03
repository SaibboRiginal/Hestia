/**
 * Hestia themes — the WHOLE UI reads these tokens (CSS custom properties).
 *
 * Add a theme: copy an entry, change values, give it a new `id`. Nothing else to touch:
 * ThemeService writes the tokens on <html> and every component updates.
 * Token meanings: see DESIGN-SYSTEM.md (§ Tokens).
 */
export type ThemeMode = 'light' | 'dark';

export interface ThemeDef {
  id: string;
  label: string;
  mode: ThemeMode;
  tokens: Record<string, string>;
}

/** Shared, non-color tokens (same for every theme unless a theme overrides them). */
export const BASE_TOKENS: Record<string, string> = {
  '--font-sans': "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  '--font-serif': "'Source Serif 4', 'Georgia', 'Times New Roman', serif",
  '--font-mono': "'JetBrains Mono', 'Fira Code', ui-monospace, monospace",
  '--font-chat': "var(--font-serif)",          // assistant replies (Claude-like serif)
  '--radius-xs': '4px',
  '--radius-sm': '6px',
  '--radius-md': '10px',
  '--radius-lg': '14px',
  '--radius-xl': '20px',
  '--radius-full': '9999px',
  '--nav-width': '248px',
  '--nav-width-collapsed': '60px',
  '--chat-width': '760px',
  '--ease': 'cubic-bezier(0.2, 0, 0, 1)',
  '--dur-fast': '120ms',
  '--dur': '200ms',
};

export const THEMES: ThemeDef[] = [
  {
    id: 'claude-light',
    label: 'Claude chiaro',
    mode: 'light',
    tokens: {
      '--bg': '#faf9f5',
      '--bg-subtle': '#f5f4ed',
      '--surface': '#ffffff',
      '--surface-2': '#f0eee6',
      '--surface-3': '#e8e6dc',
      '--border': '#e5e3d8',
      '--border-strong': '#d1cfc5',
      '--text': '#141413',
      '--text-2': '#3d3d3a',
      '--text-3': '#73726c',
      '--accent': '#c96442',
      '--accent-hover': '#b55a3b',
      '--accent-contrast': '#ffffff',
      '--accent-soft': 'rgba(201, 100, 66, 0.12)',
      '--danger': '#b53b3b',
      '--danger-soft': 'rgba(181, 59, 59, 0.10)',
      '--success': '#3d7a4f',
      '--success-soft': 'rgba(61, 122, 79, 0.12)',
      '--warning': '#a86b12',
      '--warning-soft': 'rgba(168, 107, 18, 0.12)',
      '--info': '#3b6ea5',
      '--info-soft': 'rgba(59, 110, 165, 0.12)',
      '--focus-ring': 'rgba(201, 100, 66, 0.45)',
      '--overlay': 'rgba(20, 20, 19, 0.35)',
      '--shadow-1': '0 1px 2px rgba(20, 20, 19, 0.06)',
      '--shadow-2': '0 4px 14px rgba(20, 20, 19, 0.08)',
      '--shadow-3': '0 12px 32px rgba(20, 20, 19, 0.14)',
      '--user-bubble': '#f0eee6',
      '--user-bubble-text': '#141413',
      '--cal-1': '#c96442', '--cal-2': '#3b6ea5', '--cal-3': '#3d7a4f', '--cal-4': '#8a5aa8',
      '--cal-5': '#a86b12', '--cal-6': '#2f8a8a', '--cal-7': '#b5466e', '--cal-8': '#6b6a64',
    },
  },
  {
    id: 'claude-dark',
    label: 'Claude scuro',
    mode: 'dark',
    tokens: {
      '--bg': '#262624',
      '--bg-subtle': '#1f1e1d',
      '--surface': '#30302e',
      '--surface-2': '#3a3936',
      '--surface-3': '#45443f',
      '--border': '#3e3d39',
      '--border-strong': '#55534d',
      '--text': '#faf9f5',
      '--text-2': '#d6d4ca',
      '--text-3': '#9a9893',
      '--accent': '#d97757',
      '--accent-hover': '#e58a6c',
      '--accent-contrast': '#1f1e1d',
      '--accent-soft': 'rgba(217, 119, 87, 0.16)',
      '--danger': '#e06c6c',
      '--danger-soft': 'rgba(224, 108, 108, 0.14)',
      '--success': '#6fbf85',
      '--success-soft': 'rgba(111, 191, 133, 0.14)',
      '--warning': '#e0a84f',
      '--warning-soft': 'rgba(224, 168, 79, 0.14)',
      '--info': '#78a6dc',
      '--info-soft': 'rgba(120, 166, 220, 0.14)',
      '--focus-ring': 'rgba(217, 119, 87, 0.5)',
      '--overlay': 'rgba(0, 0, 0, 0.5)',
      '--shadow-1': '0 1px 2px rgba(0, 0, 0, 0.3)',
      '--shadow-2': '0 4px 14px rgba(0, 0, 0, 0.35)',
      '--shadow-3': '0 12px 32px rgba(0, 0, 0, 0.5)',
      '--user-bubble': '#3a3936',
      '--user-bubble-text': '#faf9f5',
      '--cal-1': '#d97757', '--cal-2': '#78a6dc', '--cal-3': '#6fbf85', '--cal-4': '#b58ad1',
      '--cal-5': '#e0a84f', '--cal-6': '#5fb8b8', '--cal-7': '#e07aa0', '--cal-8': '#a8a69f',
    },
  },
  {
    id: 'slate-dark',
    label: 'Ardesia',
    mode: 'dark',
    tokens: {
      '--bg': '#14171c',
      '--bg-subtle': '#101317',
      '--surface': '#1b1f26',
      '--surface-2': '#232831',
      '--surface-3': '#2c323c',
      '--border': '#2a3039',
      '--border-strong': '#3a414d',
      '--text': '#e7eaf0',
      '--text-2': '#bac1cc',
      '--text-3': '#808896',
      '--accent': '#5b9cf2',
      '--accent-hover': '#76aef5',
      '--accent-contrast': '#0e1116',
      '--accent-soft': 'rgba(91, 156, 242, 0.16)',
      '--danger': '#f07171', '--danger-soft': 'rgba(240, 113, 113, 0.14)',
      '--success': '#5fcf8c', '--success-soft': 'rgba(95, 207, 140, 0.14)',
      '--warning': '#e8b04f', '--warning-soft': 'rgba(232, 176, 79, 0.14)',
      '--info': '#5b9cf2', '--info-soft': 'rgba(91, 156, 242, 0.14)',
      '--focus-ring': 'rgba(91, 156, 242, 0.5)',
      '--overlay': 'rgba(0, 0, 0, 0.55)',
      '--shadow-1': '0 1px 2px rgba(0, 0, 0, 0.35)',
      '--shadow-2': '0 4px 14px rgba(0, 0, 0, 0.4)',
      '--shadow-3': '0 12px 32px rgba(0, 0, 0, 0.55)',
      '--user-bubble': '#232831',
      '--user-bubble-text': '#e7eaf0',
      '--font-chat': "var(--font-sans)",
      '--cal-1': '#5b9cf2', '--cal-2': '#e8b04f', '--cal-3': '#5fcf8c', '--cal-4': '#b58ad1',
      '--cal-5': '#f07171', '--cal-6': '#5fb8b8', '--cal-7': '#e07aa0', '--cal-8': '#9aa3b0',
    },
  },
];

export const DEFAULT_LIGHT = 'claude-light';
export const DEFAULT_DARK = 'claude-dark';
