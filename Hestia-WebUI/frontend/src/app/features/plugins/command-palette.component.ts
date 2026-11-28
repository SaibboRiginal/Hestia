import { ChangeDetectionStrategy, Component, ElementRef, HostListener, computed, effect, inject, signal, viewChild } from '@angular/core';
import { Router } from '@angular/router';
import { marked } from 'marked';
import { IconComponent } from '../../ui';
import { APP_MODULES } from '../../app.modules';
import { PluginsService } from './plugins.service';
import { QuickActionsService } from './quick-actions.service';
import { MetisService } from '../../services/metis.service';
import { CentralSettingsStore, matches, moduleLabel } from '../settings/central-settings.store';
import { PERSONAL_ROWS, PERSONAL_SECTIONS } from '../settings/personal-rows';
import { assistantName, locale, tr, TrPipe } from '../../core/i18n';
import { uid } from '../../core/uid';
import { ChatsService } from '../../services/chats.service';
import { PluginSearch, SearchHit } from './plugins.types';
import { quickDate, quickMath } from './quick-answers';

const PROVIDER_TIMEOUT_MS = 2500;
const QUICK_KEY = 'hx.quick.session';

interface Entry { id: string; label: string; hint: string; icon: string; group: string; run: () => void;
  /** Extra text the search reads (help, key…). */ more?: string; }

/**
 * «Search everything» (Ctrl/⌘+K or `/`, docs/work/2026-11-27-webui-rethink piece 3): «Now» (from Metis), every quick
 * action, pages, dashboards, connections and settings, then what the modules find in their own data (search
 * providers, asked in parallel: each group appears when it arrives, a slow module never holds the others), plus quick
 * maths and dates. Tab (or a leading «?») asks the assistant instead: a short answer under the box, kept in the
 * «Quick questions» conversation that «Continue in chat» opens. Also opened by the rail «Search».
 */
@Component({
  selector: 'hx-command-palette',
  imports: [TrPipe, IconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (open()) {
      <div class="backdrop" (mousedown)="close()">
        <div class="pal hx-glass hx-fade-in" role="dialog"  [attr.aria-label]="'Search everything' | tr" (mousedown)="$event.stopPropagation()">
          <div class="in"><hx-icon [name]="asking() ? 'sparkle' : 'search'" [size]="17" [class.ask]="asking()" />
            <input #q [placeholder]="(asking() ? 'Ask the assistant, then Enter' : 'Search everything, Tab to ask') | tr" [value]="query()"
                   (input)="onInput($any($event.target).value)" (keydown)="onKeys($event)"  [attr.aria-label]="'Search' | tr">
            @if (asking()) { <button class="mode" (click)="setAsk(false)">{{ "Search" | tr }}</button> }
            @else if (query().trim()) { <button class="mode" (click)="setAsk(true)"><kbd>Tab</kbd> {{ "Ask" | tr }}</button> }
          </div>
          @if (asking()) {
            <div class="answer">
              @if (answer().q) { <div class="q">{{ answer().q }}</div> }
              @if (answer().html) { <div class="a" [innerHTML]="answer().html"></div> }
              @else if (answer().busy) { <div class="a muted"><span class="dots"><i></i><i></i><i></i></span></div> }
              @else if (!answer().q) { <div class="a muted">{{ "A short answer here, without leaving the page. It stays in the «Quick questions» conversation." | tr }}</div> }
              @if (answer().q && !answer().busy) {
                <div class="acts">
                  <button class="link" (click)="continueInChat()"><hx-icon name="chat" [size]="14" />{{ "Continue in chat" | tr }}</button>
                  <button class="link" (click)="newQuestion()"><hx-icon name="plus" [size]="14" />{{ "New question" | tr }}</button>
                </div>
              }
            </div>
          } @else {
            <div class="list">
              @for (e of results(); track e.id; let i = $index) {
                @if (i === 0 || results()[i - 1].group !== e.group) { <div class="g">{{ e.group }}</div> }
                <button class="it" [class.on]="i === sel()" (mouseenter)="sel.set(i)" (click)="exec(e)">
                  <hx-icon [name]="e.icon" [size]="16" /><span class="l">{{ e.label }}</span><span class="h">{{ e.hint }}</span>
                </button>
              } @empty {
                @if (!pending()) { <div class="none">{{ "Nothing found" | tr }}@if (query().trim()) { <button class="link" (click)="setAsk(true)">{{ "Ask the assistant" | tr }}</button> }</div> }
              }
              @if (pending()) { <div class="wait"><span class="dots"><i></i><i></i><i></i></span>{{ "Still looking…" | tr }}</div> }
            </div>
          }
        </div>
      </div>
    }`,
  styles: [`
    .backdrop { position: fixed; inset: 0; z-index: 1050; background: var(--overlay); display: flex; justify-content: center; padding: 12vh 16px 16px; }
    /* opaque under the glass tint: a box of results over the page must read like paper, whatever the style */
    .pal { width: min(620px, 100%); max-height: 70vh; align-self: flex-start; display: flex; flex-direction: column; background: linear-gradient(var(--surface), var(--surface)), var(--bg); border: 1px solid var(--border);
           border-radius: var(--radius-xl); box-shadow: var(--shadow-3); overflow: hidden; }
    .in { display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid var(--border); color: var(--text-3); }
    .in input { flex: 1; border: 0; background: transparent; outline: none; font: inherit; font-size: 15px; color: var(--text); }
    .list { overflow: auto; padding: 6px; }
    .g { font-size: 11.5px; color: var(--text-3); font-weight: 600; padding: 8px 10px 4px; text-transform: uppercase; letter-spacing: .03em; }
    .it { width: 100%; display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--radius-md); text-align: left; color: var(--text-2); }
    .it.on { background: var(--accent-soft); color: var(--text); } .it.on hx-icon { color: var(--accent); }
    .l { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .h { font-size: 12px; color: var(--text-3); white-space: nowrap; }
    .none { padding: 18px; text-align: center; color: var(--text-3); display: flex; flex-direction: column; align-items: center; gap: 6px; }
    .in hx-icon.ask { color: var(--accent); }
    .mode { font-size: 12px; color: var(--text-3); border: 1px solid var(--border); border-radius: 99px; padding: 3px 9px; white-space: nowrap; }
    .mode:hover { color: var(--text); border-color: var(--border-strong); }
    kbd { font: 10.5px var(--font-mono, monospace); }
    .link { display: inline-flex; align-items: center; gap: 5px; color: var(--accent); font-size: 13px; padding: 4px 2px; }
    .link:hover { text-decoration: underline; }
    .answer { padding: 14px 18px 16px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
    .answer .q { font-size: 13px; color: var(--text-3); }
    .answer .a { font-size: 14.5px; line-height: 1.5; color: var(--text); overflow-wrap: anywhere; }
    .answer .a.muted { color: var(--text-3); font-size: 13.5px; }
    .answer .a :is(p, ul, ol) { margin: 0 0 6px; }
    .acts { display: flex; gap: 14px; flex-wrap: wrap; }
    .wait { display: flex; align-items: center; gap: 8px; padding: 8px 10px; font-size: 12.5px; color: var(--text-3); }
    .dots { display: inline-flex; gap: 3px; } .dots i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; opacity: .4; animation: hx-dot 1s infinite; }
    .dots i:nth-child(2) { animation-delay: .15s; } .dots i:nth-child(3) { animation-delay: .3s; }
    @keyframes hx-dot { 50% { opacity: 1; } }
    @media (prefers-reduced-motion: reduce) { .dots i { animation: none; } }
  `],
})
export class CommandPaletteComponent {
  private plugins = inject(PluginsService);
  private qa = inject(QuickActionsService);
  private router = inject(Router);
  private metis = inject(MetisService);
  private settings = inject(CentralSettingsStore);
  private chats = inject(ChatsService);
  readonly open = signal(false);
  readonly query = signal('');
  readonly sel = signal(0);
  /** Tab / leading «?»: the box asks the assistant instead of searching. */
  readonly asking = signal(false);
  readonly answer = signal<{ q: string; html: string; busy: boolean }>({ q: '', html: '', busy: false });
  /** What each search provider found for the current query (provider id → hits), filled as answers arrive. */
  private readonly found = signal<Record<string, SearchHit[]>>({});
  readonly pending = signal(0);
  private input = viewChild<ElementRef<HTMLInputElement>>('q');
  private seq = 0;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private askAbort: AbortController | null = null;

  private readonly entries = computed<Entry[]>(() => {
    const mod = (m: string) => this.plugins.modules().get(m)?.title ?? m;
    return [
      ...this.metis.now().map(a => ({ id: 'now:' + a.tool + a.title, label: a.title, hint: a.reason || mod(a.module), icon: 'zap',
        group: tr('Now'), run: () => this.metis.open(a.tool, a.args ?? {}, a.title) })),
      ...this.qa.sorted().map(c => ({ id: 'qa:' + c.key, label: c.label, hint: [c.hint, mod(c.action.module)].filter(Boolean).join(' · '),
        icon: c.state === 'done' ? 'check' : c.icon || 'zap', group: tr('Quick actions'), run: () => void this.qa.run(c) })),
      ...this.plugins.navPages().map(p => ({ id: 'pg:' + p.id, label: p.label, hint: mod(p.module), icon: p.icon || 'puzzle', group: tr('Modules'),
        run: () => void this.router.navigateByUrl(this.plugins.link(p.module, p.local_id)) })),
      ...this.plugins.dashboards().map(d => ({ id: 'db:' + d.id, label: d.title, hint: tr('Dashboard'), icon: d.icon || 'grid', group: tr('Dashboard'),
        run: () => void this.router.navigateByUrl(d.id === 'home' ? '/home' : '/d/' + d.id) })),
      ...APP_MODULES.filter(m => m.path !== 'home').map(m => ({ id: 'app:' + m.path, label: m.label, hint: assistantName(), icon: m.icon, group: tr('Pages'),
        run: () => void this.router.navigateByUrl('/' + m.path) })),
      { id: 'app:connections', label: tr('Connections'), hint: assistantName(), icon: 'link', group: tr('Pages'),
        more: tr('accounts devices services link'), run: () => void this.router.navigateByUrl('/connections') },
      // Every external service a module links (ComfyUI, Home Assistant, Google, Garmin…): found by name, what it
      // gives, its search words and the module's name, opened on its card.
      ...this.plugins.connections().map(c => ({ id: 'cn:' + c.id, label: c.label, hint: tr('Connections · ') + mod(c.module),
        icon: c.icon || 'link', group: tr('Connections'), more: `${c.what} ${(c.keywords ?? []).join(' ')} ${c.module}`,
        run: () => void this.router.navigate(['/connections'], { queryParams: { open: c.id } }) })),
    ];
  });
  /** Every setting (central and personal): found by name, help or key, opened already on it. Shown only while
   *  searching, after the things to do. */
  private readonly settingEntries = computed<Entry[]>(() => {
    const section = (id: string) => PERSONAL_SECTIONS.find(s => s.id === id)?.label ?? id;
    const go = (queryParams: Record<string, string>) => () => void this.router.navigate(['/settings'], { queryParams });
    return [
      ...PERSONAL_ROWS.map(r => ({ id: 'set:row:' + r.id, label: r.label, hint: tr('Settings · ') + section(r.section), icon: 'settings',
        group: tr('Settings'), more: `${r.help} ${r.keywords}`, run: go({ section: r.section, row: r.id }) })),
      ...this.settings.items().map(i => ({ id: 'set:' + i.key, label: i.label,
        hint: tr('Settings · ') + (i.scope === 'user' ? tr('Assistant') : moduleLabel(i.module)) + (i.group ? ' · ' + i.group : ''),
        icon: 'settings', group: tr('Settings'), more: `${i.help ?? ''} ${i.key}`, run: go({ key: i.key }) })),
    ];
  });
  /** Quick maths and dates: the answer is the first line (Enter copies it). */
  private readonly quick = computed<Entry[]>(() => {
    const q = this.query().trim();
    const out: Entry[] = [];
    const m = quickMath(q, locale());
    if (m) out.push({ id: 'calc', label: m, hint: tr('Copy'), icon: 'calculator', group: tr('Calculation'), run: () => void copy(m) });
    const d = quickDate(q, locale());
    if (d) out.push({ id: 'date', label: d.label, hint: d.hint, icon: 'calendar', group: tr('Date'), run: () => void copy(d.label) });
    return out;
  });
  private readonly providerEntries = computed<Entry[]>(() => {
    const found = this.found();
    return this.plugins.searches().flatMap(p => (found[p.id] ?? []).map((h, i) => ({
      id: `sr:${p.id}:${i}:${h.link}`, label: h.title, hint: h.hint, icon: h.icon || p.icon || 'search', group: p.label,
      run: () => this.openHit(p, h) })));
  });
  readonly results = computed(() => {
    const q = this.query().trim();
    if (!q) return this.entries().slice(0, 60);
    const hit = (e: Entry) => matches(q, e.label, e.hint, e.more);
    const byName = (e: Entry) => matches(q, e.label) ? 0 : 1;      // a name that matches comes before a help text that does
    return [...this.quick(), ...this.entries().filter(hit).slice(0, 12), ...this.providerEntries(),
            ...this.settingEntries().filter(hit).sort((a, b) => byName(a) - byName(b)).slice(0, 8)].slice(0, 80);
  });

  constructor() {
    effect(() => { if (this.open()) queueMicrotask(() => this.input()?.nativeElement.focus()); });
  }

  /** The sidebar «Search» button. */
  @HostListener('window:hestia:palette')
  fromSidebar() { if (!this.open()) this.show(); }

  @HostListener('document:keydown', ['$event'])
  onGlobal(e: KeyboardEvent) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      if (this.open()) { this.close(); return; }
      this.show();
    } else if (e.key === '/' && !this.open() && !e.ctrlKey && !e.metaKey && !e.altKey && !typing(e)) {
      e.preventDefault();
      this.show();
    } else if (e.key === 'Escape' && this.open()) this.close();
  }

  onInput(v: string) {
    if (!this.asking() && v.startsWith('?')) { this.asking.set(true); v = v.slice(1).trimStart(); }
    this.query.set(v); this.sel.set(0);
    if (!this.asking()) this.searchSoon();
  }

  onKeys(e: KeyboardEvent) {
    if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); this.setAsk(!this.asking()); return; }
    if (this.asking()) {
      if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); void this.ask(); }
      else if (e.key === 'Backspace' && !this.query()) { e.preventDefault(); this.setAsk(false); }
      return;
    }
    const n = this.results().length;
    if (e.key === 'ArrowDown') { e.preventDefault(); this.sel.set(n ? (this.sel() + 1) % n : 0); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.sel.set(n ? (this.sel() - 1 + n) % n : 0); }
    else if (e.key === 'Enter') { const it = this.results()[this.sel()]; if (it) this.exec(it); }
  }

  setAsk(on: boolean) {
    this.asking.set(on);
    if (!on) this.searchSoon();
    queueMicrotask(() => this.input()?.nativeElement.focus());
  }

  show() {
    this.query.set(''); this.sel.set(0); this.found.set({}); this.pending.set(0);
    this.asking.set(false); this.answer.set({ q: '', html: '', busy: false });
    this.open.set(true);
    void this.qa.reload();
    void this.metis.loadNow();
    if (!this.settings.items().length) void this.settings.loadItems();   // one read; the Settings page keeps it fresh
  }

  exec(e: Entry) { this.close(); e.run(); }
  close() { this.open.set(false); this.askAbort?.abort(); clearTimeout(this.timer); }

  // ── search providers ────────────────────────────────────────────────
  /** Asks every provider after a short pause in typing; each answer lands on its own (a slow one never blocks). */
  private searchSoon() {
    clearTimeout(this.timer);
    const q = this.query().trim();
    const run = ++this.seq;
    if (q.length < 2) { this.found.set({}); this.pending.set(0); return; }
    this.timer = setTimeout(() => {
      const providers = this.plugins.searches();
      this.found.set({}); this.pending.set(providers.length);
      for (const p of providers) {
        const timeout = new Promise<null>(res => setTimeout(() => res(null), PROVIDER_TIMEOUT_MS));
        void Promise.race([this.plugins.call<{ items?: SearchHit[] }>(p.module, 'GET', p.path, { query: { q, limit: 5 } }), timeout])
          .then(r => {
            if (run !== this.seq) return;
            const items = r && r.ok && Array.isArray(r.data?.items) ? r.data.items.filter(h => h && h.title) : [];
            if (items.length) this.found.update(f => ({ ...f, [p.id]: items }));
            this.pending.update(n => Math.max(0, n - 1));
          });
      }
    }, 180);
  }

  private openHit(p: PluginSearch, h: SearchHit) {
    if (h.link.startsWith('chat:')) { void this.chats.open(h.link.slice(5)); return; }
    void this.router.navigateByUrl(this.plugins.link(p.module, h.link || ''));
  }

  // ── ask on the fly ──────────────────────────────────────────────────
  /** One short answer in the «Quick questions» conversation of this browser (Quick mode, the chat's tools). */
  async ask() {
    const q = this.query().trim();
    if (!q || this.answer().busy) return;
    const sid = quickSession();
    this.answer.set({ q, html: '', busy: true });
    this.query.set('');
    this.askAbort = new AbortController();
    let text = '';
    const show = (t: string) => this.answer.set({ q, html: marked.parse(t, { gfm: true, async: false }) as string, busy: true });
    try {
      const resp = await fetch('/api/webui/chat/quick', {
        method: 'POST', signal: this.askAbort.signal,
        headers: { 'Content-Type': 'application/json', 'X-Access-Token': localStorage.getItem('hestia_token') || '' },
        body: JSON.stringify({ message: q, sessionId: sid }),
      });
      if (!resp.ok || !resp.body) throw new Error(String(resp.status));
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          let ev: any;
          try { ev = JSON.parse(line); } catch { continue; }
          if (ev.type === 'token' && ev.text) { text += ev.text; show(text); }
          else if (ev.type === 'final' && ev.reply) { text = ev.reply; show(text); }
          else if (ev.type === 'error') { text = ev.content || tr('Not available'); show(text); }
        }
      }
      if (!text) show(tr('No answer: try again or continue in chat.'));
      void this.nameQuickConversation(sid);
    } catch (err: any) {
      if (err?.name !== 'AbortError') show(tr("I can't answer right now: try again later."));
    } finally {
      this.answer.update(a => ({ ...a, busy: false }));
      this.askAbort = null;
    }
  }

  newQuestion() {
    this.answer.set({ q: '', html: '', busy: false });
    queueMicrotask(() => this.input()?.nativeElement.focus());
  }

  async continueInChat() {
    this.close();
    await this.chats.open(quickSession());
  }

  /** The conversation is called «Quick questions» in the chat list (once per browser). */
  private async nameQuickConversation(sid: string) {
    if (store('get', QUICK_KEY + '.named') === sid) return;
    if ((await this.chats.setMeta(sid, { title: tr('Quick questions') })).ok) store('set', QUICK_KEY + '.named', sid);
  }
}

/** The key went to a field (also inside a plugin's shadow root): `/` is then just a character. */
function typing(e: KeyboardEvent): boolean {
  const el = (e.composedPath?.()[0] ?? e.target) as HTMLElement | null;
  const tag = (el?.tagName || '').toLowerCase();
  return tag === 'input' || tag === 'textarea' || tag === 'select' || !!el?.isContentEditable;
}

function store(op: 'get' | 'set', key: string, value = ''): string {
  try {
    if (op === 'set') { localStorage.setItem(key, value); return value; }
    return localStorage.getItem(key) || '';
  } catch { return ''; }
}

/** The browser's «Quick questions» conversation (one id, kept per browser). */
function quickSession(): string {
  return store('get', QUICK_KEY) || store('set', QUICK_KEY, 'quick-' + uid());
}

async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); } catch { /* clipboard refused: the text is on screen */ }
}
