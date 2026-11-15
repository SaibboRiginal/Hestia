/** Hercules UI helpers: formatting, labels, small calculations shared by pages and widgets. */
import { css, tr } from '@hestia/webui-sdk';

export const MUSCLES: Record<string, string> = {
  chest: tr('Petto'), front_delts: tr('Deltoide anteriore'), side_delts: tr('Deltoide laterale'), rear_delts: tr('Deltoide posteriore'),
  triceps: tr('Tricipiti'), biceps: tr('Bicipiti'), forearms: tr('Avambracci'), lats: tr('Dorsali'), upper_back: tr('Parte alta schiena'),
  traps: tr('Trapezi'), lower_back: tr('Lombari'), abs: tr('Addominali'), obliques: tr('Obliqui'), glutes: tr('Glutei'), quads: tr('Quadricipiti'),
  hamstrings: tr('Femorali'), adductors: tr('Adduttori'), abductors: tr('Abduttori'), calves: tr('Polpacci'), neck: tr('Collo'),
};
export const GROUPS: Record<string, string[]> = {
  petto: ['chest'], spalle: ['front_delts', 'side_delts', 'rear_delts'], braccia: ['biceps', 'triceps', 'forearms'],
  schiena: ['lats', 'upper_back', 'traps', 'lower_back'], core: ['abs', 'obliques'],
  gambe: ['quads', 'hamstrings', 'glutes', 'adductors', 'abductors', 'calves'],
};
export const GROUP_LABEL: Record<string, string> = { petto: tr('Petto'), spalle: tr('Spalle'), braccia: tr('Braccia'), schiena: tr('Schiena'), core: tr('Core'), gambe: tr('Gambe') };
export const EQUIPMENT: Record<string, string> = {
  barbell: tr('Bilanciere'), dumbbell: tr('Manubri'), machine: tr('Macchina'), cable: tr('Cavi'), kettlebell: tr('Kettlebell'), band: tr('Elastico'),
  bodyweight: tr('Corpo libero'), smith: tr('Multipower'), ez_bar: tr('Bilanciere EZ'), trap_bar: tr('Trap bar'), other: tr('Altro'),
};
export const KINDS: Record<string, string> = {
  weight_reps: tr('Peso × ripetizioni'), bodyweight_reps: tr('Corpo libero'), weighted_bodyweight: tr('Corpo libero zavorrato'),
  assisted_bodyweight: tr('Corpo libero assistito'), reps_only: tr('Solo ripetizioni'), duration: tr('Durata'), distance_duration: tr('Distanza e durata'),
};
export const SET_TYPES: Record<string, string> = { warmup: 'R', normal: '', drop: 'D', failure: 'C' };
export const SET_TYPE_LABEL: Record<string, string> = { warmup: tr('Riscaldamento'), normal: tr('Normale'), drop: tr('Drop set'), failure: tr('Cedimento') };
export const PROGRESSION: Record<string, string> = { double: tr('Doppia progressione'), linear: tr('Lineare'), rpe: 'RPE', none: tr('Nessuna') };
export const FEEDBACK_TAGS: Record<string, string> = {
  too_heavy: tr('Troppo pesante'), too_light: tr('Troppo leggero'), pain: tr('Dolore'), great: tr('Ottimo'), tired: tr('Stanco'),
  bored: tr('Mi annoia'), short_time: tr('Poco tempo'), technique: tr('Tecnica da sistemare'),
};
export const PAIN_AREAS = ['spalla', 'gomito', 'polso', 'schiena bassa', 'anca', 'ginocchio', 'caviglia', 'collo'];
export const MEASURES: Record<string, string> = {
  bodyweight: tr('Peso corporeo'), body_fat: tr('Massa grassa'), waist: tr('Vita'), chest: tr('Torace'), arm: tr('Braccio'), thigh: tr('Coscia'),
  hips: tr('Fianchi'), neck: tr('Collo'), calf: tr('Polpaccio'),
};
export const MEASURE_UNIT: Record<string, string> = { bodyweight: 'kg', body_fat: '%' };
export const WEEKDAYS = [tr('Lun'), tr('Mar'), tr('Mer'), tr('Gio'), tr('Ven'), tr('Sab'), tr('Dom')];

export const isBodyweight = (kind?: string) => kind === 'bodyweight_reps' || kind === 'weighted_bodyweight' || kind === 'assisted_bodyweight' || kind === 'reps_only';
export const usesWeight = (kind?: string) => !kind || kind === 'weight_reps' || kind === 'weighted_bodyweight' || kind === 'assisted_bodyweight';
export const usesTime = (kind?: string) => kind === 'duration' || kind === 'distance_duration';

export function kg(x: number | null | undefined): string {
  if (x === null || x === undefined || isNaN(x as number)) return '–';
  const v = Math.round(Number(x) * 100) / 100;
  return (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0$/, '')).replace('.', ',');
}
export function num(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined || isNaN(x as number)) return '–';
  return Number(x).toLocaleString('it-IT', { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}
export function parseNum(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(',', '.'));
  return isNaN(n) ? null : n;
}
export function dur(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const m = Math.floor(s / 60), r = s % 60;
  return m >= 60 ? `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}:${String(r).padStart(2, '0')}` : `${m}:${String(r).padStart(2, '0')}`;
}
export function minutes(m: number | null | undefined): string {
  if (!m) return '–';
  return m >= 60 ? `${Math.floor(m / 60)} h ${String(Math.round(m % 60)).padStart(2, '0')}` : `${Math.round(m)} min`;
}

export function localDay(iso: string | Date): string {
  const d = typeof iso === 'string' ? new Date(iso) : iso;
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export const today = () => localDay(new Date());
export function dayLabel(iso: string, withWeekday = true): string {
  if (!iso) return '';
  const d = iso.length === 10 ? new Date(iso + 'T12:00:00') : new Date(iso);
  const t = today(), ld = localDay(d);
  const y = localDay(new Date(Date.now() - 86400000));
  if (ld === t) return tr('Oggi');
  if (ld === y) return tr('Ieri');
  return d.toLocaleDateString('it-IT', withWeekday ? { weekday: 'short', day: 'numeric', month: 'short' } : { day: 'numeric', month: 'short', year: '2-digit' });
}
export function timeLabel(iso: string): string {
  return iso ? new Date(iso).toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : '';
}
export function relDays(iso: string | null | undefined): string {
  if (!iso) return 'mai';
  const days = Math.floor((Date.parse(today() + 'T12:00:00') - Date.parse(localDay(iso) + 'T12:00:00')) / 86400000);
  return days <= 0 ? 'oggi' : days === 1 ? 'ieri' : days < 14 ? tr("{0} giorni fa", days) : days < 60 ? `${Math.round(days / 7)} settimane fa` : `${Math.round(days / 30)} mesi fa`;
}

export function e1rm(weight: number | null | undefined, reps: number | null | undefined, formula = 'epley'): number | null {
  if (!weight || !reps || reps <= 0) return null;
  if (reps === 1) return weight;
  if (formula === 'brzycki') return reps < 37 ? weight * 36 / (37 - reps) : null;
  return weight * (1 + reps / 30);
}

export function round(weight: number, inc: number): number {
  if (!inc) return weight;
  return Math.round(weight / inc) * inc;
}

/** Plates per side for a barbell weight. */
export function plates(total: number, bar: number, available: number[]): { perSide: number[]; rest: number } {
  let side = (total - bar) / 2;
  const out: number[] = [];
  if (side <= 0) return { perSide: [], rest: 0 };
  for (const p of [...available].sort((a, b) => b - a)) {
    while (side + 1e-6 >= p) { out.push(p); side -= p; }
  }
  return { perSide: out, rest: Math.round(side * 2 * 100) / 100 };
}

export function warmups(work: number | null | undefined, scheme: Array<{ pct: number; reps: number }>, inc: number, bar = 20): Array<{ weight_kg: number; reps: number }> {
  if (!work || work <= bar) return [];
  const out: Array<{ weight_kg: number; reps: number }> = [];
  for (const s of scheme) {
    const w = Math.max(bar, round(work * s.pct / 100, inc || 2.5));
    if (w < work && !out.some(o => o.weight_kg === w)) out.push({ weight_kg: w, reps: s.reps });
  }
  return out;
}

export function setLabel(s: any, kind?: string): string {
  if (usesTime(kind)) return `${s.duration_s ? dur(s.duration_s) : '–'}${s.distance_m ? ` · ${num(s.distance_m)} m` : ''}`;
  if (!usesWeight(kind)) return `${s.reps ?? '–'} rip`;
  const w = s.weight_kg === null || s.weight_kg === undefined ? '' : `${kg(s.weight_kg)} kg × `;
  return `${w}${s.reps ?? '–'}`;
}

export function plannedLabel(p: any, kind?: string): string {
  if (usesTime(kind)) return p.duration_s ? dur(p.duration_s) : '–';
  const reps = p.reps ?? p.reps_target ?? (p.reps_min && p.reps_max && p.reps_min !== p.reps_max ? `${p.reps_min}–${p.reps_max}` : p.reps_max ?? p.reps_min ?? '–');
  if (!usesWeight(kind)) return `${reps} rip`;
  return `${p.weight_kg ? kg(p.weight_kg) + ' kg × ' : ''}${reps}`;
}

export function muscleText(e: any): string {
  return (e?.primary_muscles || []).map((m: string) => MUSCLES[m] || m).join(', ');
}

export function search(items: any[], q: string): any[] {
  const n = (s: string) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
  const words = n(q).split(/\s+/).filter(Boolean);
  if (!words.length) return items;
  const scored: Array<[number, any]> = [];
  for (const it of items) {
    const name = n(it.name), hay = `${name} ${(it.aliases || []).map(n).join(' ')} ${(it.primary_muscles || []).map((m: string) => n(MUSCLES[m] || m)).join(' ')}`;
    if (!words.every(w => hay.includes(w))) continue;
    scored.push([(name.startsWith(words[0]) ? 0 : name.includes(words[0]) ? 1 : 2) * 1000 - (it.times || 0), it]);
  }
  return scored.sort((a, b) => a[0] - b[0]).map(x => x[1]);
}

/** Shared styles of Hercules pages (on top of the kit). */
export const herculesStyles = css`
  h1 { font-size: 22px; font-weight: 650; margin: 0; letter-spacing: -.01em; }
  h2 { font-size: 15px; font-weight: 600; margin: 0; }
  h3 { font-size: 13px; font-weight: 600; margin: 0; color: var(--text-2); text-transform: uppercase; letter-spacing: .04em; }
  .head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .head .sub { color: var(--text-3); font-size: 13px; }
  .tabs { display: flex; gap: 4px; flex-wrap: wrap; }
  .tab { border: 1px solid var(--border); background: var(--surface); color: var(--text-2); border-radius: var(--radius-full);
    padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; }
  .tab[aria-pressed=true] { background: var(--accent-soft); color: var(--accent); border-color: transparent; font-weight: 600; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { border: 1px solid var(--border-strong); background: var(--surface); color: var(--text); border-radius: var(--radius-full);
    padding: 6px 12px; font: inherit; font-size: 13px; cursor: pointer; min-height: 34px; }
  .chip[aria-pressed=true] { background: var(--accent); border-color: var(--accent); color: var(--accent-contrast); }
  .chip.warn[aria-pressed=true] { background: var(--warning); border-color: var(--warning); }
  input.in, select.in, textarea.in { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
    border-radius: var(--radius-sm); padding: 7px 10px; outline: none; min-width: 0; }
  input.in:focus, select.in:focus, textarea.in:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
  input.num { width: 72px; text-align: center; font-variant-numeric: tabular-nums; }
  .tnum { font-variant-numeric: tabular-nums; }
  .pill { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; color: var(--text-2); background: var(--surface-2);
    border-radius: var(--radius-full); padding: 2px 8px; }
  .sep { height: 1px; background: var(--border); margin: 4px 0; }
  .between { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .link { color: var(--accent); cursor: pointer; background: none; border: none; font: inherit; padding: 0; }
  .empty { color: var(--text-3); font-size: 13px; padding: 8px 0; }
  .list { display: flex; flex-direction: column; }
  .li { display: flex; align-items: center; gap: 10px; padding: 10px 4px; border-bottom: 1px solid var(--border); cursor: pointer; }
  .li:last-child { border-bottom: none; }
  .li:hover { background: var(--surface-2); }
  .offline { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--warning); }
  @media (max-width: 860px) { .page { padding: 12px 12px 90px; } }
`;
