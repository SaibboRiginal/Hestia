/**
 * <hephaestus-md> — small GitHub-flavoured markdown renderer (headings, lists, task lists, code, tables, quotes,
 * links) for dossiers and engine messages. The SDK has no markdown lib: text is HTML-escaped first, then only the
 * tags below are produced, so the innerHTML holds nothing the text did not ask for. Links: http(s) only.
 */
import { LitElement, css, html, tokens } from '@hestia/webui-sdk';

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function inline(s: string): string {
  const codes: string[] = [];
  let t = esc(s).replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  t = t.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/__([^_]+)__/g, '<b>$1</b>')
    .replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>').replace(/(^|\W)_([^_\s][^_]*)_(?=\W|$)/g, '$1<i>$2</i>')
    .replace(/~~([^~]+)~~/g, '<s>$1</s>');
  return t.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${codes[+i]}</code>`);
}

const cells = (row: string) => row.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());

export function renderMarkdown(text: string): string {
  const lines = (text || '').replace(/\r\n?/g, '\n').split('\n');
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const fence = /^\s*(```|~~~)/.exec(line);
    if (fence) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++]);
      i++;
      out.push(`<pre><code>${esc(body.join('\n'))}</code></pre>`);
      continue;
    }
    if (!line.trim()) { i++; continue; }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { const n = Math.min(h[1].length, 4); out.push(`<h${n}>${inline(h[2])}</h${n}>`); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push('<hr>'); i++; continue; }
    if (line.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1]) && lines[i + 1].includes('-')) {
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(cells(lines[i++]));
      out.push(`<table><thead><tr>${head.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${
        rows.map(r => `<tr>${r.map(c => `<td>${inline(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`);
      continue;
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ''));
      out.push(`<blockquote>${renderMarkdown(body.join('\n'))}</blockquote>`);
      continue;
    }
    const li = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
    if (li) {
      const ordered = /\d/.test(li[2]);
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(lines[i]);
        if (!m) {
          if (lines[i].trim() && /^\s{2,}/.test(lines[i]) && items.length) { items[items.length - 1] += ' ' + inline(lines[i].trim()); i++; continue; }
          break;
        }
        const indent = m[1].length > 1 ? ' class="sub"' : '';
        const task = /^\[([ xX])\]\s+(.*)$/.exec(m[3]);
        items.push(task
          ? `<li class="task${indent ? ' sub' : ''}"><input type="checkbox" disabled ${task[1] !== ' ' ? 'checked' : ''}>${inline(task[2])}`
          : `<li${indent}>${inline(m[3])}`);
        i++;
      }
      const tag = ordered ? 'ol' : 'ul';
      out.push(`<${tag}>${items.map(x => x + '</li>').join('')}</${tag}>`);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*```|\s*~~~|\s*>|\s*([-*+]|\d+[.)])\s)/.test(lines[i])) para.push(lines[i++]);
    if (!para.length) para.push(lines[i++]);
    out.push(`<p>${para.map(inline).join('<br>')}</p>`);
  }
  return out.join('');
}

export class HephaestusMd extends LitElement {
  static properties = { text: {} };
  declare text: string;
  constructor() { super(); this.text = ''; }
  static styles = [tokens, css`
    :host { display: block; }
    .md { font-size: 14px; line-height: 1.6; color: var(--text); word-wrap: break-word; }
    .md :is(h1, h2, h3, h4) { font-family: var(--font-serif); font-weight: 500; line-height: 1.25; margin: 1.1em 0 .45em; }
    .md h1 { font-size: 21px; } .md h2 { font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
    .md h3 { font-size: 15.5px; } .md h4 { font-size: 14px; }
    .md > :first-child { margin-top: 0; }
    .md p { margin: 0 0 .7em; }
    .md :is(ul, ol) { margin: .2em 0 .8em 1.4em; padding: 0; }
    .md li { margin: .12em 0; } .md li.sub { margin-left: 1.2em; }
    .md li.task { list-style: none; margin-left: -1.3em; }
    .md input[type=checkbox] { margin-right: 6px; accent-color: var(--accent); }
    .md code { font-family: var(--font-mono); font-size: 12.5px; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
    .md pre { background: var(--surface-2); border-radius: var(--radius-md); padding: 10px 12px; overflow-x: auto; margin: .4em 0 .9em; }
    .md pre code { background: none; padding: 0; }
    .md table { border-collapse: collapse; margin: .4em 0 .9em; font-size: 13px; display: block; overflow-x: auto; }
    .md :is(th, td) { border: 1px solid var(--border); padding: 5px 9px; text-align: left; vertical-align: top; }
    .md th { background: var(--bg-subtle); font-weight: 600; }
    .md blockquote { border-left: 3px solid var(--border-strong); padding-left: 12px; color: var(--text-2); margin: .5em 0; }
    .md hr { border: 0; border-top: 1px solid var(--border); margin: 1.2em 0; }
    .md a { color: var(--accent); }
  `];
  render() { return html`<div class="md"></div>`; }
  updated() {
    const el = this.renderRoot.querySelector('.md');
    if (el) el.innerHTML = renderMarkdown(this.text || '');
  }
}
