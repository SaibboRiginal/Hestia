import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ButtonComponent, IconComponent, SpinnerComponent, ToastService } from '../../ui';
import { ChatSummary, ChatTag, ChatsService, TAG_COLORS, TAG_CSS } from '../../services/chats.service';
import { SessionService } from '../../services/session.service';

const PAGE = 30;

/**
 * Second sidebar «Cronologia» (brainstorm C13 + Cindy 26, W7): every conversation, newest first (pinned on top),
 * search in titles and messages, from/to dates, a tag filter; open one, pin it, rename it, colour its tags.
 */
@Component({
  selector: 'hx-chat-history',
  imports: [DatePipe, ButtonComponent, IconComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <aside class="hist hx-fade-in" aria-label="Cronologia delle conversazioni">
      <div class="h"><b>Cronologia</b><span class="hx-grow"></span>
        <button hx-btn variant="ghost" size="sm" icon="x" iconOnly aria-label="Chiudi" (click)="chats.historyOpen.set(false)"></button></div>
      <div class="search"><hx-icon name="search" [size]="14" />
        <input class="hx-input" placeholder="Cerca nelle conversazioni" [value]="q()" (input)="type($any($event.target).value)" (keydown.enter)="reload()" aria-label="Cerca"></div>
      <div class="dates">
        <label>Dal <input class="hx-input" type="date" [value]="since()" (change)="since.set($any($event.target).value); reload()"></label>
        <label>Al <input class="hx-input" type="date" [value]="until()" (change)="until.set($any($event.target).value); reload()"></label>
      </div>
      @if (chats.tags().length) {
        <div class="tags">
          @for (t of chats.tags(); track t.name) {
            <button class="tag" [class.on]="tag() === t.name" [style.--c]="css(t.color)" (click)="pickTag(t.name)"><i></i>{{ t.name }}</button>
          }
        </div>
      }
      <div class="list">
        @for (c of items(); track c.session_id) {
          <div class="it" [class.cur]="c.session_id === session.sessionId()">
            <button class="open" (click)="open(c)">
              <span class="t">@if (c.pinned) { <hx-icon name="pin" [size]="12" /> }{{ c.title }}</span>
              <span class="m">{{ c.last_at | date:'d MMM, HH:mm' }} · {{ c.messages }} messaggi</span>
              @if (c.tags.length) { <span class="ct">@for (t of c.tags; track t.name) { <span class="chip" [style.--c]="css(t.color)"><i></i>{{ t.name }}</span> }</span> }
            </button>
            <button class="mini" [class.on]="c.pinned" (click)="pin(c)" [attr.aria-label]="c.pinned ? 'Sblocca' : 'Fissa'" [attr.title]="c.pinned ? 'Togli da fissate' : 'Fissa in cima'"><hx-icon name="pin" [size]="13" /></button>
            <button class="mini" (click)="edit.set(edit() === c.session_id ? '' : c.session_id)" aria-label="Etichette e titolo" title="Etichette e titolo"><hx-icon name="tag" [size]="13" /></button>
          </div>
          @if (edit() === c.session_id) {
            <div class="ed">
              <input class="hx-input" placeholder="Titolo" [value]="c.title" (change)="rename(c, $any($event.target).value)" aria-label="Titolo">
              <div class="row">
                <input #nt class="hx-input" placeholder="Nuova etichetta" (keydown.enter)="addTag(c, nt.value, color()); nt.value = ''" aria-label="Nuova etichetta">
                <button hx-btn size="sm" icon="plus" (click)="addTag(c, nt.value, color()); nt.value = ''">Aggiungi</button>
              </div>
              <div class="colors">@for (k of colors; track k) {
                <button class="sw" [class.on]="color() === k" [style.background]="css(k)" (click)="color.set(k)" [attr.aria-label]="k"></button> }</div>
              @if (c.tags.length) { <div class="ct">@for (t of c.tags; track t.name) {
                <button class="chip rm" [style.--c]="css(t.color)" (click)="dropTag(c, t)" [attr.title]="'Togli ' + t.name"><i></i>{{ t.name }}<hx-icon name="x" [size]="11" /></button> }</div> }
            </div>
          }
        } @empty {
          @if (!loading()) { <div class="none">{{ error() ? 'Non disponibile, riprova tra poco.' : 'Nessuna conversazione.' }}</div> }
        }
        @if (loading()) { <div class="none"><hx-spinner [size]="16" /></div> }
        @else if (items().length < total()) { <button hx-btn variant="ghost" size="sm" (click)="more()">Carica altre</button> }
      </div>
    </aside>`,
  styles: [`
    :host { display: contents; }
    .hist { width: 300px; flex-shrink: 0; border-right: 1px solid var(--border); background: var(--bg); display: flex; flex-direction: column; gap: 8px; padding: 12px 10px; min-height: 0; }
    .h { display: flex; align-items: center; gap: 8px; padding: 0 4px; }
    .search { position: relative; } .search hx-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); color: var(--text-3); }
    .search input { width: 100%; padding-left: 30px; }
    .dates { display: flex; gap: 6px; } .dates label { flex: 1; display: flex; flex-direction: column; gap: 2px; font-size: 11.5px; color: var(--text-3); }
    .dates input { width: 100%; font-size: 12.5px; padding: 4px 6px; }
    .tags, .ct { display: flex; flex-wrap: wrap; gap: 4px; }
    .tag, .chip { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; padding: 2px 8px; border-radius: var(--radius-full);
                  border: 1px solid var(--border); background: var(--surface); color: var(--text-2); }
    .tag i, .chip i { width: 7px; height: 7px; border-radius: 50%; background: var(--c); }
    .tag { cursor: pointer; } .tag.on { border-color: var(--c); color: var(--text); background: var(--surface-2); }
    .chip.rm { cursor: pointer; } .chip.rm:hover { border-color: var(--danger); }
    .list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; margin: 0 -4px; padding: 0 4px; }
    .it { display: flex; align-items: flex-start; gap: 2px; border-radius: var(--radius-md); }
    .it:hover { background: var(--surface-2); } .it.cur { background: var(--surface-3); }
    .open { flex: 1; min-width: 0; text-align: left; display: flex; flex-direction: column; gap: 2px; padding: 7px 8px; color: var(--text); }
    .t { font-size: 13.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; gap: 4px; align-items: center; }
    .t hx-icon { color: var(--accent); flex: none; }
    .m { font-size: 11.5px; color: var(--text-3); }
    .mini { width: 26px; height: 26px; margin-top: 6px; border-radius: var(--radius-md); display: grid; place-items: center; color: var(--text-3); opacity: 0; }
    .it:hover .mini, .mini:focus-visible, .mini.on { opacity: 1; } .mini.on { color: var(--accent); }
    .mini:hover { background: var(--surface-3); color: var(--text); }
    @media (hover: none) { .mini { opacity: .7; } }
    .ed { display: flex; flex-direction: column; gap: 6px; padding: 6px 8px 10px; border-bottom: 1px solid var(--border); }
    .ed .row { display: flex; gap: 6px; } .ed .row input { flex: 1; min-width: 0; }
    .colors { display: flex; gap: 5px; } .sw { width: 18px; height: 18px; border-radius: 50%; border: 2px solid transparent; }
    .sw.on { border-color: var(--text); }
    .none { text-align: center; color: var(--text-3); font-size: 13px; padding: 18px 0; display: grid; place-items: center; }
    @media (max-width: 860px) { .hist { position: fixed; inset: 0 auto 0 0; z-index: 810; width: min(320px, 92vw); box-shadow: var(--shadow-3); } }
  `],
})
export class ChatHistoryComponent implements OnInit {
  chats = inject(ChatsService);
  session = inject(SessionService);
  private toast = inject(ToastService);
  readonly colors = TAG_COLORS;
  readonly items = signal<ChatSummary[]>([]);
  readonly total = signal(0);
  readonly loading = signal(false);
  readonly error = signal(false);
  readonly q = signal('');
  readonly since = signal('');
  readonly until = signal('');
  readonly tag = signal('');
  readonly edit = signal('');
  readonly color = signal('blue');
  private timer: ReturnType<typeof setTimeout> | null = null;
  private readonly query = computed(() => ({
    q: this.q().trim(), tag: this.tag(), since: this.since() ? `${this.since()}T00:00:00` : '',
    until: this.until() ? `${this.until()}T23:59:59` : '',
  }));

  /** Typing searches after a short pause. */
  type(v: string): void {
    this.q.set(v);
    if (this.timer) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.reload(), 350);
  }

  ngOnInit(): void { void this.reload(); void this.chats.loadTags(); }

  css(c: string): string { return TAG_CSS[c] || TAG_CSS['gray']; }

  async reload(): Promise<void> {
    this.loading.set(true);
    const r = await this.chats.list({ ...this.query(), limit: PAGE });
    this.loading.set(false);
    this.error.set(!r.ok);
    this.items.set(r.items);
    this.total.set(r.total);
  }

  async more(): Promise<void> {
    this.loading.set(true);
    const r = await this.chats.list({ ...this.query(), limit: PAGE, offset: this.items().length });
    this.loading.set(false);
    if (r.ok) this.items.update(x => [...x, ...r.items]);
  }

  pickTag(name: string): void { this.tag.set(this.tag() === name ? '' : name); void this.reload(); }

  async open(c: ChatSummary): Promise<void> {
    if (!(await this.chats.open(c.session_id))) { this.toast.error('Conversazione non disponibile'); return; }
    if (window.innerWidth < 861) this.chats.historyOpen.set(false);
  }

  private async save(c: ChatSummary, body: Parameters<ChatsService['setMeta']>[1]): Promise<void> {
    const r = await this.chats.setMeta(c.session_id, body);
    if (!r.ok) { this.toast.error('Non salvato'); return; }
    this.items.update(x => x.map(i => i.session_id === c.session_id ? { ...i, title: r.data.title || i.title, tags: r.data.tags, pinned: r.data.pinned } : i));
  }

  pin(c: ChatSummary) { void this.save(c, { pinned: !c.pinned }); }
  rename(c: ChatSummary, title: string) { if (title.trim() && title.trim() !== c.title) void this.save(c, { title: title.trim() }); }
  addTag(c: ChatSummary, name: string, color: string) { if (name.trim()) void this.save(c, { add_tags: [{ name: name.trim(), color }] }); }
  dropTag(c: ChatSummary, t: ChatTag) { void this.save(c, { remove_tags: [t.name] }); }
}
