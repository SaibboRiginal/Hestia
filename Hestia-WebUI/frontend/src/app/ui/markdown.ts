/** Markdown renderer: <hx-markdown [text]="md" /> — GitHub-flavoured (tables, task lists), sanitized by Angular. */
import { ChangeDetectionStrategy, Component, ViewEncapsulation, computed, input } from '@angular/core';
import { marked } from 'marked';

@Component({
  selector: 'hx-markdown',
  changeDetection: ChangeDetectionStrategy.OnPush,
  // innerHTML gets no _ngcontent attributes: styles are global, scoped by the `hx-markdown .md` prefix.
  encapsulation: ViewEncapsulation.None,
  template: `<div class="md" [innerHTML]="html()"></div>`,
  styles: [`
    hx-markdown { display: block; }
    hx-markdown .md { font-size: 14px; line-height: 1.6; color: var(--text); word-wrap: break-word; }
    hx-markdown .md :is(h1, h2, h3, h4) { font-family: var(--font-serif); font-weight: 500; line-height: 1.25; margin: 1.1em 0 .45em; }
    hx-markdown .md h1 { font-size: 21px; } hx-markdown .md h2 { font-size: 18px; border-bottom: 1px solid var(--border); padding-bottom: 4px; }
    hx-markdown .md h3 { font-size: 15.5px; } hx-markdown .md h4 { font-size: 14px; }
    hx-markdown .md :first-child { margin-top: 0; }
    hx-markdown .md p { margin: 0 0 .7em; }
    hx-markdown .md :is(ul, ol) { margin: .2em 0 .8em 1.4em; }
    hx-markdown .md li { margin: .12em 0; }
    hx-markdown .md li:has(> input[type=checkbox]) { list-style: none; margin-left: -1.3em; }
    hx-markdown .md input[type=checkbox] { margin-right: 6px; accent-color: var(--accent); }
    hx-markdown .md code { font-family: var(--font-mono); font-size: 12.5px; background: var(--surface-2); padding: 1px 5px; border-radius: 4px; }
    hx-markdown .md pre { background: var(--surface-2); border-radius: var(--radius-md); padding: 10px 12px; overflow-x: auto; margin: .4em 0 .9em; }
    hx-markdown .md pre code { background: none; padding: 0; }
    hx-markdown .md table { border-collapse: collapse; margin: .4em 0 .9em; font-size: 13px; display: block; overflow-x: auto; }
    hx-markdown .md :is(th, td) { border: 1px solid var(--border); padding: 5px 9px; text-align: left; vertical-align: top; }
    hx-markdown .md th { background: var(--bg-subtle); font-weight: 600; }
    hx-markdown .md blockquote { border-left: 3px solid var(--border-strong); padding-left: 12px; color: var(--text-2); margin: .5em 0; }
    hx-markdown .md hr { border: 0; border-top: 1px solid var(--border); margin: 1.2em 0; }
    hx-markdown .md a { color: var(--accent); }
  `],
})
export class MarkdownComponent {
  text = input('');
  html = computed(() => marked.parse(this.text() || '', { gfm: true, breaks: false, async: false }) as string);
}
