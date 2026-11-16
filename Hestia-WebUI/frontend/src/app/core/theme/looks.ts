import { tr } from '../i18n';
/**
 * Interface styles — the second axis of the look, independent from the colour theme (themes.ts).
 *
 * A style is a preset of four knobs (corners, borders, transparency, animations) plus a few tokens of its own;
 * every knob can then be changed on its own (Impostazioni → Personali → Aspetto). ThemeService turns the
 * result into tokens on <html> and the attributes data-style / data-glass / data-motion, so plugins follow too.
 * Dossier: docs/work/2026-10-29-revisione-e-test-frontend §6.
 */
export type Corners = 'squadrati' | 'normali' | 'arrotondati';
export type Borders = 'leggeri' | 'normali' | 'marcati';
export type Glass = 'no' | 'leggera' | 'vetro';
export type Motion = 'nessuna' | 'ridotte' | 'normali' | 'vivaci';

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
    id: 'classico', label: tr('Classic'), help: tr('Warm and calm: serif titles, soft corners, full surfaces.'),
    knobs: { corners: 'normali', borders: 'normali', glass: 'no', motion: 'normali' }, tokens: {},
  },
  {
    id: 'vetro', label: tr('Glass'), help: tr('Light: transparent and blurred panels on a gradient background, rounder corners, lively animations.'),
    knobs: { corners: 'arrotondati', borders: 'leggeri', glass: 'vetro', motion: 'vivaci' }, tokens: {},
  },
  {
    id: 'netto', label: tr('Net'), help: tr('Precise: all sans serif, almost square corners, marked borders and no shadows.'),
    knobs: { corners: 'squadrati', borders: 'marcati', glass: 'no', motion: 'ridotte' },
    tokens: {
      '--font-serif': 'var(--font-sans)', '--font-chat': 'var(--font-sans)',
      '--shadow-1': 'none', '--shadow-2': '0 0 0 1px var(--border-strong)',
      '--shadow-3': '0 0 0 1px var(--border-strong), 0 10px 28px rgba(0, 0, 0, 0.14)',
    },
  },
];

export const DEFAULT_STYLE = 'classico';

export const RADII: Record<Corners, Record<string, string>> = {
  squadrati: { '--radius-xs': '2px', '--radius-sm': '3px', '--radius-md': '4px', '--radius-lg': '6px', '--radius-xl': '8px' },
  normali: { '--radius-xs': '4px', '--radius-sm': '6px', '--radius-md': '10px', '--radius-lg': '14px', '--radius-xl': '20px' },
  arrotondati: { '--radius-xs': '6px', '--radius-sm': '9px', '--radius-md': '14px', '--radius-lg': '20px', '--radius-xl': '28px' },
};

export const MOTION: Record<Motion, Record<string, string>> = {
  nessuna: { '--dur-fast': '0ms', '--dur': '0ms' },
  ridotte: { '--dur-fast': '80ms', '--dur': '120ms' },
  normali: { '--dur-fast': '120ms', '--dur': '200ms' },
  vivaci: { '--dur-fast': '160ms', '--dur': '280ms' },
};

/** Opacity of the main surfaces (%) and blur, per transparency level. */
export const GLASS: Record<Glass, { surface: number; subtle: number; surface2: number; blur: string }> = {
  no: { surface: 100, subtle: 100, surface2: 100, blur: 'none' },
  leggera: { surface: 86, subtle: 80, surface2: 90, blur: 'blur(12px) saturate(140%)' },
  vetro: { surface: 64, subtle: 56, surface2: 76, blur: 'blur(20px) saturate(170%)' },
};

/** Labels for the settings page. */
export const KNOB_OPTIONS = {
  corners: [{ value: 'squadrati', label: tr('Squared') }, { value: 'normali', label: tr('pl::Normal') }, { value: 'arrotondati', label: tr('Rounded') }],
  borders: [{ value: 'leggeri', label: tr('pl::Light') }, { value: 'normali', label: tr('pl::Normal') }, { value: 'marcati', label: tr('alt::Marked') }],
  glass: [{ value: 'no', label: tr('f::None') }, { value: 'leggera', label: tr('Light') }, { value: 'vetro', label: tr('Glass') }],
  motion: [{ value: 'nessuna', label: tr('f::None') }, { value: 'ridotte', label: tr('Reduced') }, { value: 'normali', label: tr('pl::Normal') }, { value: 'vivaci', label: tr('Vivid') }],
} as const;
