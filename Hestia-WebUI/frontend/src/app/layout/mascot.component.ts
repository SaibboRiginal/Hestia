import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { TrPipe } from '../core/i18n';
import { AppearanceService } from '../services/appearance.service';
import { ChatService } from '../services/chat.service';
import { LiveVoiceService } from '../services/live-voice.service';
import { MascotService } from '../services/mascot.service';
import { ToastService } from '../ui/overlays';
import { VoiceService } from '../services/voice.service';

export type MascotState = 'idle' | 'thinking' | 'speaking' | 'listening' | 'sleeping' | 'happy';

const KEY = 'hx.mascot.place';
const SIZE = 64;
const EDGE = 14;
type Place = { side: 'left' | 'right'; y: number };   // y = share of the window height (top of the mascot)

function readPlace(): Place | null {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) || 'null');
    return p && (p.side === 'left' || p.side === 'right') && typeof p.y === 'number' ? p : null;
  } catch { return null; }
}

/**
 * <hx-mascot> — the mascot in a corner of every page (dossier 2026-11-18-real-test-problems G). The built-in ones
 * (Aphrodite `pet.drawn`: ember, cat, owl) are drawn here and need no picture; a pet with pictures uses them. It shows
 * what is happening: thinking while the answer is prepared, speaking while it is written or read aloud, listening in
 * «Talk», sleeping at night. Drag it: it docks to the nearest side (the place is kept on this browser). Reduced
 * motion = still. Piece 4 of the WebUI rethink (docs/work/2026-11-27-webui-rethink): a click opens the mini chat with
 * the current or last conversation (`<hx-mascot-chat>`), holding it starts «Talk», and it reacts to what the owner
 * does on the site (`MascotService.reaction`: a pose per kind, a short bubble, an optional action). While it is on
 * screen it is the one door to the assistant (the bottom-right bubble steps aside).
 */
@Component({
  selector: 'hx-mascot',
  imports: [TrPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (pet(); as p) {
      @if (reaction(); as r) {
        @if (r.text) {
          <div class="say hx-fade-in" role="status" [class.left]="pos().side === 'left'"
               [style.top.px]="pos().top !== null ? pos().top! - 8 : null" [style.left.px]="pos().side === 'left' ? edge + size + 10 : null"
               [style.right.px]="pos().side === 'right' ? edge + size + 10 : null">
            <span>{{ r.text }}</span>
            @if (r.action; as a) { <button (click)="mascot.run(a)">{{ a.label }}</button> }
            <button class="x" (click)="mascot.dismiss()" [attr.aria-label]="'Close' | tr">×</button>
          </div>
        }
      }
      <button class="m" [attr.data-state]="state()" [attr.data-reaction]="reaction()?.kind || null" [attr.data-drawn]="p.drawn || null" [class.drag]="dragging()"
              [style.left.px]="pos().side === 'left' ? edge : null" [style.right.px]="pos().side === 'right' ? edge : null"
              [style.top.px]="pos().top" [attr.aria-label]="p.name" [title]="p.name"
              (keydown.enter)="tap()" (keydown.space)="tap(); $event.preventDefault()" (pointerdown)="down($event)" (pointermove)="move($event)" (pointerup)="up($event)" (pointercancel)="cancel()">
        @if (state() === 'listening') { <span class="ring" aria-hidden="true"></span> }
        @if (p.drawn) {
          <svg viewBox="0 0 64 64" aria-hidden="true">
            @switch (p.drawn) {
              @case ('cat') {
                <g class="body">
                  <path d="M14 22 L18 8 L28 18 Z M50 22 L46 8 L36 18 Z" class="fill" />
                  <ellipse cx="32" cy="36" rx="20" ry="18" class="fill" />
                  <ellipse cx="32" cy="42" rx="9" ry="6" class="light" />
                  <path d="M10 38 h8 M10 42 h8 M46 38 h8 M46 42 h8" class="line" />
                </g>
              }
              @case ('owl') {
                <g class="body">
                  <path d="M16 18 L20 8 L26 16 Z M48 18 L44 8 L38 16 Z" class="fill" />
                  <ellipse cx="32" cy="36" rx="19" ry="21" class="fill" />
                  <ellipse cx="32" cy="45" rx="11" ry="9" class="light" />
                  <circle cx="24" cy="31" r="8" class="light" /><circle cx="40" cy="31" r="8" class="light" />
                  <path d="M30 37 L32 41 L34 37 Z" class="beak" />
                </g>
              }
              @default {
                <g class="body flame">
                  <path d="M32 4 C40 16 52 24 52 40 C52 52 43 60 32 60 C21 60 12 52 12 40 C12 30 18 24 22 16 C24 24 27 26 30 26 C28 18 29 10 32 4 Z" class="fill" />
                  <path d="M32 30 C37 36 42 40 42 47 C42 54 37 57 32 57 C27 57 22 54 22 47 C22 41 28 37 32 30 Z" class="light" />
                </g>
              }
            }
            <g class="eyes">
              <ellipse class="eye" [attr.cx]="p.drawn === 'owl' ? 24 : 25" [attr.cy]="p.drawn === 'owl' ? 31 : 34" rx="3" ry="3.6" />
              <ellipse class="eye" [attr.cx]="p.drawn === 'owl' ? 40 : 39" [attr.cy]="p.drawn === 'owl' ? 31 : 34" rx="3" ry="3.6" />
            </g>
            <path class="shut" [attr.d]="p.drawn === 'owl' ? 'M20 31 q4 3 8 0 M36 31 q4 3 8 0' : 'M21 34 q4 3 8 0 M35 34 q4 3 8 0'" />
            <ellipse class="mouth" cx="32" [attr.cy]="p.drawn === 'owl' ? 44 : 44" rx="3.2" ry="1.6" />
          </svg>
        } @else if (picture()) {
          <img [src]="picture()" alt="" draggable="false">
        }
        @if (state() === 'thinking') { <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span> }
        @if (state() === 'sleeping') { <span class="zz" aria-hidden="true">z<small>z</small></span> }
      </button>
    }`,
  styles: [`
    .m { position: fixed; z-index: 6; width: ${SIZE}px; height: ${SIZE}px; padding: 0; border: 0; background: transparent;
         cursor: grab; border-radius: 50%; touch-action: none; user-select: none; transition: top var(--dur-fast) var(--ease); }
    .m.drag { cursor: grabbing; transition: none; }
    .m:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .m:not([style*="top"]) { bottom: 96px; }
    svg, img { width: 100%; height: 100%; display: block; filter: drop-shadow(0 2px 4px rgba(0,0,0,.25)); pointer-events: none; }
    img { object-fit: contain; }
    .fill { fill: var(--accent); }
    .light { fill: color-mix(in srgb, var(--accent) 35%, #fff); }
    [data-drawn=ember] .light { fill: color-mix(in srgb, var(--accent) 30%, #ffd27a); }
    .line { stroke: color-mix(in srgb, var(--accent) 50%, #000); stroke-width: 1.2; stroke-linecap: round; opacity: .5; }
    .beak { fill: #e8a33d; }
    .eye { fill: #2a2320; transform-box: fill-box; transform-origin: center; animation: hx-blink 5s infinite; }
    .shut { fill: none; stroke: #2a2320; stroke-width: 1.8; stroke-linecap: round; display: none; }
    .mouth { fill: #2a2320; transform-box: fill-box; transform-origin: center; }
    .body { transform-box: fill-box; transform-origin: 50% 100%; animation: hx-breathe 3.2s ease-in-out infinite; }
    .flame { animation: hx-flicker 1.8s ease-in-out infinite; }
    @keyframes hx-blink { 0%, 94%, 100% { transform: scaleY(1); } 97% { transform: scaleY(.1); } }
    @keyframes hx-breathe { 50% { transform: scale(1.03, .98); } }
    @keyframes hx-flicker { 25% { transform: scale(1.02, .97) skewX(1deg); } 75% { transform: scale(.98, 1.03) skewX(-1deg); } }
    /* thinking: eyes look up, three dots */
    [data-state=thinking] .eyes { transform: translateY(-2px); }
    .dots { position: absolute; top: -6px; right: -4px; display: flex; gap: 3px; padding: 4px 6px; border-radius: 10px;
            background: var(--surface); box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,.2)); }
    .dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--text-2); animation: hx-dot 1.2s infinite; }
    .dots i:nth-child(2) { animation-delay: .2s; } .dots i:nth-child(3) { animation-delay: .4s; }
    @keyframes hx-dot { 0%, 60%, 100% { opacity: .3; transform: translateY(0); } 30% { opacity: 1; transform: translateY(-3px); } }
    /* speaking: the mouth moves */
    [data-state=speaking] .mouth { animation: hx-talk .32s ease-in-out infinite alternate; }
    @keyframes hx-talk { from { transform: scale(1, .6); } to { transform: scale(1.1, 2.4); } }
    /* listening: a soft ring */
    .ring { position: absolute; inset: -6px; border-radius: 50%; border: 2px solid var(--accent); animation: hx-ring 1.4s ease-out infinite; }
    @keyframes hx-ring { from { opacity: .7; transform: scale(.9); } to { opacity: 0; transform: scale(1.25); } }
    [data-state=listening] .body { animation-duration: 1.6s; }
    /* sleeping: eyes shut, slow breath, z */
    [data-state=sleeping] .eye { display: none; }
    [data-state=sleeping] .shut { display: inline; }
    [data-state=sleeping] .mouth { transform: scale(.7, .5); }
    [data-state=sleeping] .body { animation-duration: 5s; }
    .zz { position: absolute; top: -10px; right: 2px; font: 600 13px var(--font-sans, sans-serif); color: var(--text-3);
          animation: hx-zz 2.6s ease-in-out infinite; }
    .zz small { font-size: 10px; margin-left: 1px; }
    @keyframes hx-zz { 0% { opacity: 0; transform: translate(0, 4px); } 40% { opacity: 1; } 100% { opacity: 0; transform: translate(6px, -8px); } }
    /* happy: a hop */
    [data-state=happy] { animation: hx-hop .5s var(--ease) 2; }
    [data-state=happy] .mouth { transform: scale(1.3, 2); }
    @keyframes hx-hop { 50% { transform: translateY(-10px); } }
    :host-context([data-motion=off]) .m *, :host-context([data-motion=off]) .m { animation: none !important; }
    @media (prefers-reduced-motion: reduce) { .m, .m * { animation: none !important; } }
    /* reactions (MascotService): proud = a bigger hop, comfort = a slow sway, nudge = a small shake */
    [data-reaction=proud] { animation: hx-hop .45s var(--ease) 3; }
    [data-reaction=comfort] .body { animation: hx-sway 2.4s ease-in-out infinite; }
    [data-reaction=nudge] { animation: hx-shake .5s ease-in-out 2; }
    @keyframes hx-sway { 50% { transform: rotate(-4deg); } }
    @keyframes hx-shake { 25% { transform: translateX(-3px); } 75% { transform: translateX(3px); } }
    .say { position: fixed; z-index: 7; bottom: ${96 + 8}px; max-width: min(280px, calc(100vw - 120px)); display: flex; flex-direction: column; gap: 6px;
           padding: 9px 30px 9px 12px; border-radius: 14px 14px 4px 14px; background: linear-gradient(var(--surface), var(--surface)), var(--bg);
           border: 1px solid var(--border); box-shadow: var(--shadow-2); font-size: 13.5px; color: var(--text); }
    .say.left { border-radius: 14px 14px 14px 4px; }
    .say button { align-self: flex-start; font-size: 13px; color: var(--accent); padding: 0; }
    .say button:hover { text-decoration: underline; }
    .say .x { position: absolute; top: 4px; right: 8px; color: var(--text-3); font-size: 16px; line-height: 1; }
    @media (max-width: 860px) { .m { width: 48px; height: 48px; } .m:not([style*="top"]) { bottom: 140px; } .say { bottom: 196px; } }   /* above the bubble and the bottom bar */
  `],
})
export class MascotComponent {
  private look = inject(AppearanceService);
  private chat = inject(ChatService);
  private live = inject(LiveVoiceService);
  private voice = inject(VoiceService);
  readonly mascot = inject(MascotService);
  private router = inject(Router);
  private toasts = inject(ToastService);

  readonly edge = EDGE;
  readonly size = SIZE;
  readonly reaction = this.mascot.reaction;
  readonly pet = this.look.pet;
  private readonly happyUntil = signal(0);
  readonly dragging = signal(false);
  private readonly place = signal<Place | null>(readPlace());
  private readonly dragTop = signal<number | null>(null);

  readonly state = computed<MascotState>(() => {
    if (this.happyUntil() > 0) return 'happy';
    const live = this.live.state();
    if (live === 'listening' || live === 'hearing') return 'listening';
    if (live === 'speaking' || this.voice.playing()) return 'speaking';
    if (live === 'thinking') return 'thinking';
    const r = this.reaction();
    if (r) return r.kind === 'cheer' || r.kind === 'proud' ? 'happy' : 'speaking';
    if (this.chat.isStreaming()) {
      const id = this.chat.currentStreamingId();
      const m = id ? this.chat.messages().find(x => x.id === id) : undefined;
      return m?.content ? 'speaking' : 'thinking';
    }
    const h = new Date().getHours();
    return h >= 23 || h < 7 ? 'sleeping' : 'idle';
  });

  /** A pet with pictures: the pose that fits the state. */
  readonly picture = computed(() => {
    const s = this.state();
    return this.look.petImage(s === 'sleeping' ? 'sleep' : s === 'happy' || s === 'speaking' ? 'happy' : 'idle');
  });

  readonly pos = computed(() => {
    const p = this.place();
    const drag = this.dragTop();
    const top = drag ?? (p ? Math.round(p.y * window.innerHeight) : null);
    return { side: p?.side ?? 'right', top };
  });

  private start: { x: number; y: number; top: number } | null = null;
  private moved = false;
  private held = false;
  private holdTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    // On screen = the one door to the assistant; the mini chat opens on its side.
    effect(() => this.mascot.present.set(!!this.pet()));
    effect(() => { document.documentElement.dataset['mascotSide'] = this.pos().side; });
  }

  down(e: PointerEvent) {
    const el = e.currentTarget as HTMLElement;
    el.setPointerCapture?.(e.pointerId);
    this.start = { x: e.clientX, y: e.clientY, top: el.getBoundingClientRect().top };
    this.moved = false;
    this.held = false;
    clearTimeout(this.holdTimer);
    // Hold (without moving) = «Talk», like a walkie-talkie button.
    this.holdTimer = setTimeout(() => { if (this.start && !this.moved) { this.held = true; this.talk(); } }, 550);
  }

  move(e: PointerEvent) {
    if (!this.start) return;
    if (!this.moved && Math.hypot(e.clientX - this.start.x, e.clientY - this.start.y) < 5) return;
    this.moved = true;
    clearTimeout(this.holdTimer);
    this.dragging.set(true);
    this.dragTop.set(this.clampTop(this.start.top + e.clientY - this.start.y));
    const side = e.clientX < window.innerWidth / 2 ? 'left' : 'right';
    if (side !== this.pos().side) this.place.set({ side, y: (this.dragTop() ?? 0) / window.innerHeight });
  }

  up(e: PointerEvent) {
    if (!this.start) return;
    clearTimeout(this.holdTimer);
    if (this.held) { this.start = null; this.held = false; return; }
    if (!this.moved) { this.tap(); this.start = null; return; }
    const side: Place['side'] = e.clientX < window.innerWidth / 2 ? 'left' : 'right';
    const place = { side, y: (this.dragTop() ?? 0) / window.innerHeight };
    this.place.set(place);
    try { localStorage.setItem(KEY, JSON.stringify(place)); } catch { /* kept for this visit only */ }
    this.cancel();
  }

  cancel() { clearTimeout(this.holdTimer); this.start = null; this.dragging.set(false); this.dragTop.set(null); }

  private clampTop(top: number) { return Math.max(8, Math.min(window.innerHeight - SIZE - 8, Math.round(top))); }

  /** A click: the mini chat with the current or last conversation (on the Chat page the chat is already there). */
  tap(): void {
    this.mascot.dismiss();
    if (this.router.url.startsWith('/chat')) { this.cheer(); return; }
    this.mascot.chatOpen.update(v => !v);
  }

  private talk(): void {
    this.cheer();
    if (this.live.on) { this.live.stop(); return; }
    void this.live.start().then(() => { if (this.live.error()) this.toasts.error(this.live.error()); });
  }

  cheer(): void {
    this.happyUntil.set(Date.now() + 2500);
    setTimeout(() => this.happyUntil.set(0), 2500);
  }
}
