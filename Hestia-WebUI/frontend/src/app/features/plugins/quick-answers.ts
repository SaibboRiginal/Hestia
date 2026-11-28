/**
 * Quick maths and dates for the «Search everything» box (docs/work/2026-11-27-webui-rethink piece 3). No words to
 * parse, so they work in every language: «12*3+4», «200 × 15%», «(3,5+1)/2»; «+10» / «-30» (days from today),
 * «3/5», «3/5/2027», «2027-05-03» (which day it is and how far).
 */
import { tr } from '../../core/i18n';

/** «expression = result», or null when the text is not a calculation. */
export function quickMath(q: string, locale: string): string | null {
  const src = q.trim();
  if (!/^[\d\s+\-*/x×÷^%().,]+$/.test(src) || !/\d/.test(src) || !/\d\s*[+\-*/x×÷^%]\s*[\d(]|\d\s*%/.test(src)) return null;
  if (quickDate(src, locale)) return null;                    // «+10», «3/5», «2027-05-03» are dates
  const text = src.replace(/×|x/g, '*').replace(/÷/g, '/').replace(/,/g, '.');
  let i = 0;
  const peek = () => { while (text[i] === ' ') i++; return text[i]; };
  const num = (): number => {
    peek();
    const m = /^\d*\.?\d+/.exec(text.slice(i));
    if (!m) throw new Error('number');
    i += m[0].length;
    let v = parseFloat(m[0]);
    if (peek() === '%') { i++; v /= 100; }
    return v;
  };
  const atom = (): number => {
    const c = peek();
    if (c === '-') { i++; return -atom(); }
    if (c === '+') { i++; return atom(); }
    if (c === '(') { i++; const v = sum(); if (peek() !== ')') throw new Error(')'); i++; return v; }
    return num();
  };
  const power = (): number => { const b = atom(); if (peek() === '^') { i++; return Math.pow(b, power()); } return b; };
  const product = (): number => {
    let v = power();
    for (let c = peek(); c === '*' || c === '/'; c = peek()) { i++; const r = power(); v = c === '*' ? v * r : v / r; }
    return v;
  };
  const sum = (): number => {
    let v = product();
    for (let c = peek(); c === '+' || c === '-'; c = peek()) {
      i++;
      // «200 + 15%» = 200 plus 15% of 200, like a calculator
      const start = i; let r = product();
      if (/%\s*$/.test(text.slice(start, i))) r = v * r;
      v = c === '+' ? v + r : v - r;
    }
    return v;
  };
  try {
    const v = sum();
    if (peek() !== undefined || !Number.isFinite(v)) return null;
    return `${src} = ${new Intl.NumberFormat(locale, { maximumFractionDigits: 8 }).format(v)}`;
  } catch {
    return null;
  }
}

/** Which day a date is and how far from today, or null when the text is not a date. */
export function quickDate(q: string, locale: string, now = new Date()): { label: string; hint: string } | null {
  const src = q.trim();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  let day: Date | null = null;
  let m: RegExpExecArray | null;
  if ((m = /^([+-])\s*(\d{1,4})\s*d?$/i.exec(src))) {
    day = new Date(today); day.setDate(day.getDate() + (m[1] === '-' ? -1 : 1) * Number(m[2]));
  } else if ((m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(src))) {
    day = valid(Number(m[1]), Number(m[2]), Number(m[3]));
  } else if ((m = /^(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2}|\d{4}))?$/.exec(src))) {
    // day first, as the owner writes it in Italian and most languages; en-US is month first
    const [a, b] = locale.toLowerCase() === 'en-us' ? [Number(m[2]), Number(m[1])] : [Number(m[1]), Number(m[2])];
    const y = m[3] ? (m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3])) : today.getFullYear();
    day = valid(y, b, a);
  }
  if (!day) return null;
  const diff = Math.round((day.getTime() - today.getTime()) / 86_400_000);
  const label = day.toLocaleDateString(locale, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  const hint = diff === 0 ? tr('today') : diff === 1 ? tr('tomorrow') : diff === -1 ? tr('yesterday')
    : diff > 0 ? tr('in {0} days', diff) : tr('{0} days ago', -diff);
  return { label: label.charAt(0).toUpperCase() + label.slice(1), hint };
}

function valid(y: number, mo: number, d: number): Date | null {
  const dt = new Date(y, mo - 1, d);
  return dt.getFullYear() === y && dt.getMonth() === mo - 1 && dt.getDate() === d ? dt : null;
}
