import { Injectable } from '@angular/core';

/**
 * One tooltip for the whole site (dossier docs/work/2026-11-18-problemi-del-test D).
 *
 * Nothing to declare: every `title` — in the WebUI and inside the module plugins (their shadow roots are open, the
 * event path reaches them) — and the `aria-label` of a button or link with no visible text get the same tooltip:
 * same look, same delay, on hover and on keyboard focus, long press on touch. The native browser tooltip is
 * suppressed by moving `title` into `data-hx-tip` the first time the element is pointed at; an element left without
 * a name keeps the text as its `aria-label`, so screen readers lose nothing.
 */
@Injectable({ providedIn: 'root' })
export class TooltipService {
  private tip: HTMLDivElement | null = null;
  private current: Element | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private lastHidden = 0;

  /** Called once by the app shell. */
  init(): void {
    if (this.tip || typeof document === 'undefined') return;
    const tip = document.createElement('div');
    tip.className = 'hx-tip';
    tip.id = 'hx-tip';
    tip.setAttribute('role', 'tooltip');
    document.body.appendChild(tip);
    this.tip = tip;
    const opts = { capture: true, passive: true } as const;
    document.addEventListener('pointerover', e => { if (e.pointerType !== 'touch') this.enter(e); }, opts);
    document.addEventListener('pointerout', e => this.leave(e), opts);
    document.addEventListener('focusin', e => this.enter(e), opts);
    document.addEventListener('focusout', () => this.hide(), opts);
    document.addEventListener('pointerdown', e => this.press(e), opts);
    document.addEventListener('pointerup', e => { if (e.pointerType === 'touch') this.cancelTimer(); }, opts);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') this.hide(); }, opts);
    document.addEventListener('scroll', () => this.hide(), opts);
    window.addEventListener('blur', () => this.hide());
  }

  /** The element of the event path that has a tooltip, and its text. */
  private find(e: Event): { el: Element; text: string } | null {
    for (const node of e.composedPath()) {
      if (!(node instanceof Element) || node === document.body || node === document.documentElement) continue;
      const title = node.getAttribute('title');
      if (title !== null) {
        node.removeAttribute('title');
        if (title.trim()) {
          node.setAttribute('data-hx-tip', title);
          if (!node.getAttribute('aria-label') && !(node.textContent || '').trim()) node.setAttribute('aria-label', title);
        }
      }
      const text = node.getAttribute('data-hx-tip');
      if (text) return { el: node, text };
      const label = node.getAttribute('aria-label');
      if (label && isControl(node) && !(node.textContent || '').trim()) return { el: node, text: label };
      if (isControl(node)) return null;   // a control with its own visible text: no tooltip from its container
    }
    return null;
  }

  private enter(e: Event): void {
    const hit = this.find(e);
    if (!hit) { if (e.type === 'focusin') this.hide(); return; }
    if (hit.el === this.current) return;
    this.cancelTimer();
    this.current = hit.el;
    // Moving along a toolbar: the next tooltip shows at once.
    const delay = Date.now() - this.lastHidden < 400 ? 0 : 450;
    this.timer = setTimeout(() => this.show(hit.el, hit.text), delay);
  }

  private leave(e: PointerEvent): void {
    if (!this.current) return;
    const to = e.relatedTarget as Node | null;
    if (to && (this.current === to || this.current.contains(to))) return;
    this.hide();
  }

  /** Touch: a long press shows the tooltip for a moment. */
  private press(e: PointerEvent): void {
    this.hide();
    if (e.pointerType !== 'touch') return;
    const hit = this.find(e);
    if (!hit) return;
    this.current = hit.el;
    this.timer = setTimeout(() => {
      this.show(hit.el, hit.text);
      this.timer = setTimeout(() => this.hide(), 1800);
    }, 550);
  }

  private show(el: Element, text: string): void {
    const tip = this.tip;
    if (!tip || !el.isConnected) return;
    tip.textContent = text;          // measured while still hidden (visibility keeps the layout)
    const r = el.getBoundingClientRect();
    const t = tip.getBoundingClientRect();
    const gap = 8;
    let top = r.top - t.height - gap;
    if (top < 6) top = r.bottom + gap;
    let left = r.left + r.width / 2 - t.width / 2;
    left = Math.max(6, Math.min(left, window.innerWidth - t.width - 6));
    tip.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
    tip.classList.add('on');
  }

  private hide(): void {
    this.cancelTimer();
    if (this.tip?.classList.contains('on')) { this.tip.classList.remove('on'); this.lastHidden = Date.now(); }
    this.current = null;
  }

  private cancelTimer(): void {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
  }
}

function isControl(el: Element): boolean {
  const tag = el.tagName;
  return tag === 'BUTTON' || tag === 'A' || tag === 'HXK-BUTTON' || el.getAttribute('role') === 'button';
}
