import { tr } from '../i18n';
/**
 * Interface styles — the second axis of the look, independent from the colour theme (themes.ts).
 *
 * A style is a preset of four knobs (corners, borders, transparency, animations) plus a few tokens of its own;
 * every knob can then be changed on its own (Settings → Personal → Look). ThemeService turns the
 * result into tokens on <html> and the attributes data-style / data-glass / data-motion, so plugins follow too.
 * Dossier: docs/work/2026-10-29-frontend-review-and-tests §6.
 */
export type Corners = 'squared' | 'normal' | 'rounded';
export type Borders = 'light' | 'normal' | 'marked';
export type Glass = 'no' | 'light' | 'glass';
export type Motion = 'none' | 'reduced' | 'normal' | 'lively';

export interface LookKnobs { corners: Corners; borders: Borders; glass: Glass; motion: Motion; }

export interface StyleDef {
  id: string;
  label: string;
  help: string;
  knobs: LookKnobs;
  /** Extra tokens over the theme (fonts, shadows). */
  tokens: Record<string, string>;
}

export const STYLES: StyleDef[] = [
  {
    id: 'classic', label: tr('Classic'), help: tr('Warm and calm: serif titles, soft corners, full surfaces.'),
    knobs: { corners: 'normal', borders: 'normal', glass: 'no', motion: 'normal' }, tokens: {},
  },
  {
    id: 'glass', label: tr('Glass'), help: tr('Light: transparent and blurred panels on a gradient background, rounder corners, lively animations.'),
    knobs: { corners: 'rounded', borders: 'light', glass: 'glass', motion: 'lively' }, tokens: {},
  },
  {
    id: 'net', label: tr('Net'), help: tr('Precise: all sans serif, almost square corners, marked borders and no shadows.'),
    knobs: { corners: 'squared', borders: 'marked', glass: 'no', motion: 'reduced' },
    tokens: {
      '--font-serif': 'var(--font-sans)', '--font-chat': 'var(--font-sans)',
      '--shadow-1': 'none', '--shadow-2': '0 0 0 1px var(--border-strong)',
      '--shadow-3': '0 0 0 1px var(--border-strong), 0 10px 28px rgba(0, 0, 0, 0.14)',
    },
  },
];

export const DEFAULT_STYLE = 'glass';

export const RADII: Record<Corners, Record<string, string>> = {
  squared: { '--radius-xs': '2px', '--radius-sm': '3px', '--radius-md': '4px', '--radius-lg': '6px', '--radius-xl': '8px' },
  normal: { '--radius-xs': '4px', '--radius-sm': '6px', '--radius-md': '10px', '--radius-lg': '14px', '--radius-xl': '20px' },
  rounded: { '--radius-xs': '6px', '--radius-sm': '9px', '--radius-md': '14px', '--radius-lg': '20px', '--radius-xl': '28px' },
};

export const MOTION: Record<Motion, Record<string, string>> = {
  none: { '--dur-fast': '0ms', '--dur': '0ms' },
  reduced: { '--dur-fast': '80ms', '--dur': '120ms' },
  normal: { '--dur-fast': '120ms', '--dur': '200ms' },
  lively: { '--dur-fast': '160ms', '--dur': '280ms' },
};

/** Opacity of the main surfaces (%) and blur, per transparency level. */
export const GLASS: Record<Glass, { surface: number; subtle: number; surface2: number; blur: string }> = {
  no: { surface: 100, subtle: 100, surface2: 100, blur: 'none' },
  light: { surface: 86, subtle: 80, surface2: 90, blur: 'blur(12px) saturate(140%)' },
  glass: { surface: 64, subtle: 56, surface2: 76, blur: 'blur(20px) saturate(170%)' },
};

/** Labels for the settings page. */
export const KNOB_OPTIONS = {
  corners: [{ value: 'squared', label: tr('Squared') }, { value: 'normal', label: tr('pl::Normal') }, { value: 'rounded', label: tr('Rounded') }],
  borders: [{ value: 'light', label: tr('pl::Light') }, { value: 'normal', label: tr('pl::Normal') }, { value: 'marked', label: tr('alt::Marked') }],
  glass: [{ value: 'no', label: tr('f::None') }, { value: 'light', label: tr('Light') }, { value: 'glass', label: tr('Glass') }],
  motion: [{ value: 'none', label: tr('f::None') }, { value: 'reduced', label: tr('Reduced') }, { value: 'normal', label: tr('pl::Normal') }, { value: 'lively', label: tr('Vivid') }],
} as const;
