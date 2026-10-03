/** Minimal RRULE helpers for the editor: parse ↔ simple form model, human description, BYDAY shift. */
import { WEEKDAYS, WEEKDAY_LABELS } from './date-utils';

export type Freq = 'none' | 'MINUTELY' | 'HOURLY' | 'DAILY' | 'WEEKLY' | 'MONTHLY' | 'YEARLY' | 'custom';

export interface RepeatModel {
  freq: Freq;
  interval: number;
  byday: string[];      // WEEKLY
  until: string;        // yyyy-mm-dd or ''
  count: number | null;
  raw: string;          // custom RRULE
}

export function emptyRepeat(): RepeatModel {
  return { freq: 'none', interval: 1, byday: [], until: '', count: null, raw: '' };
}

export function parseRRule(rule?: string | null): RepeatModel {
  const m = emptyRepeat();
  if (!rule) return m;
  const body = rule.replace(/^RRULE:/i, '');
  const parts: Record<string, string> = {};
  for (const kv of body.split(';')) {
    const [k, v] = kv.split('=');
    if (k && v) parts[k.toUpperCase()] = v;
  }
  const known = new Set(['FREQ', 'INTERVAL', 'BYDAY', 'UNTIL', 'COUNT']);
  const freq = (parts['FREQ'] || '').toUpperCase();
  if (!['MINUTELY', 'HOURLY', 'DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY'].includes(freq)
      || Object.keys(parts).some(k => !known.has(k))) {
    return { ...m, freq: 'custom', raw: body };
  }
  m.freq = freq as Freq;
  m.interval = Math.max(1, parseInt(parts['INTERVAL'] || '1', 10) || 1);
  m.byday = parts['BYDAY'] ? parts['BYDAY'].split(',').filter(d => (WEEKDAYS as readonly string[]).includes(d)) : [];
  m.count = parts['COUNT'] ? parseInt(parts['COUNT'], 10) : null;
  if (parts['UNTIL']) {
    const u = parts['UNTIL'];
    m.until = `${u.slice(0, 4)}-${u.slice(4, 6)}-${u.slice(6, 8)}`;
  }
  m.raw = body;
  return m;
}

export function buildRRule(m: RepeatModel): string | null {
  if (m.freq === 'none') return null;
  if (m.freq === 'custom') return m.raw.trim().replace(/^RRULE:/i, '') || null;
  const parts = [`FREQ=${m.freq}`];
  if (m.interval > 1) parts.push(`INTERVAL=${m.interval}`);
  if (m.freq === 'WEEKLY' && m.byday.length) parts.push(`BYDAY=${[...m.byday].sort((a, b) => WEEKDAYS.indexOf(a as never) - WEEKDAYS.indexOf(b as never)).join(',')}`);
  if (m.count) parts.push(`COUNT=${m.count}`);
  else if (m.until) parts.push(`UNTIL=${m.until.replace(/-/g, '')}T235959`);
  return parts.join(';');
}

const UNIT: Record<string, [string, string]> = {
  MINUTELY: ['minuto', 'minuti'], HOURLY: ['ora', 'ore'], DAILY: ['giorno', 'giorni'],
  WEEKLY: ['settimana', 'settimane'], MONTHLY: ['mese', 'mesi'], YEARLY: ['anno', 'anni'],
};

export function describeRRule(rule?: string | null): string {
  if (!rule) return 'Non si ripete';
  const m = parseRRule(rule);
  if (m.freq === 'custom') return `Regola: ${m.raw}`;
  const [one, many] = UNIT[m.freq] ?? ['', ''];
  let s = m.interval === 1 ? `Ogni ${one}` : `Ogni ${m.interval} ${many}`;
  if (m.freq === 'DAILY' && m.interval === 1) s = 'Ogni giorno';
  if (m.freq === 'WEEKLY' && m.byday.length) s += `: ${m.byday.map(d => WEEKDAY_LABELS[d]).join(', ')}`;
  if (m.count) s += `, ${m.count} volte`;
  else if (m.until) s += `, fino al ${new Date(m.until).toLocaleDateString('it-IT')}`;
  return s;
}

/** Moving a whole weekly series by N days must also move its BYDAY list. */
export function shiftByDay(rule: string | null | undefined, days: number): string | null | undefined {
  if (!rule || days % 7 === 0) return rule;
  return rule.replace(/BYDAY=([A-Z,]+)/i, (_, list: string) => {
    const shifted = list.split(',').map(d => {
      const i = WEEKDAYS.indexOf(d.toUpperCase() as never);
      return i < 0 ? d : WEEKDAYS[((i + days) % 7 + 7) % 7];
    });
    return `BYDAY=${shifted.join(',')}`;
  });
}
