import { Injectable, inject, signal } from '@angular/core';
import { PluginsService } from '../features/plugins/plugins.service';

export type PushState = 'unsupported' | 'unavailable' | 'denied' | 'off' | 'on' | 'busy';

/**
 * Web Push on this browser (dossier 2026-10-24-tutto-brainstorm-cindy C15, W7): Hermes delivers notifications to
 * the subscribed browsers like to any client; the service worker (`public/sw.js`) shows them and opens their link.
 * Keys and subscriptions go through the Hermes plugin door (`/api/ui/push/key`, `/api/ui/push/subscribe`).
 * `unavailable` = Hermes has no VAPID keys (Web Push not set up on the server).
 */
@Injectable({ providedIn: 'root' })
export class PushService {
  private plugins = inject(PluginsService);
  readonly state = signal<PushState>('busy');

  private get supported(): boolean {
    return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  }

  async refresh(): Promise<void> {
    if (!this.supported) { this.state.set('unsupported'); return; }
    if (Notification.permission === 'denied') { this.state.set('denied'); return; }
    const key = await this.key();
    if (!key) { this.state.set('unavailable'); return; }
    const reg = await navigator.serviceWorker.getRegistration();
    const sub = await reg?.pushManager.getSubscription();
    this.state.set(sub ? 'on' : 'off');
  }

  private async key(): Promise<string> {
    if (!this.plugins.modules().has('hermes')) return '';
    const r = await this.plugins.call<{ enabled?: boolean; public_key?: string }>('hermes', 'GET', '/api/ui/push/key');
    return r.ok && r.data?.enabled ? r.data.public_key || '' : '';
  }

  async enable(): Promise<boolean> {
    if (!this.supported) return false;
    this.state.set('busy');
    try {
      const key = await this.key();
      if (!key) { this.state.set('unavailable'); return false; }
      if ((await Notification.requestPermission()) !== 'granted') { this.state.set('denied'); return false; }
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription()
        ?? await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64url(key) });
      const r = await this.plugins.call('hermes', 'POST', '/api/ui/push/subscribe', { body: { subscription: sub.toJSON(), device: device() } });
      if (!r.ok) { await sub.unsubscribe(); this.state.set('off'); return false; }
      this.state.set('on');
      return true;
    } catch (e) {
      console.warn('event=webpush_subscribe_failed', e);
      this.state.set('off');
      return false;
    }
  }

  async disable(): Promise<void> {
    this.state.set('busy');
    try {
      const reg = await navigator.serviceWorker.getRegistration();
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        await this.plugins.call('hermes', 'DELETE', '/api/ui/push/subscribe', { body: { endpoint: sub.endpoint } });
        await sub.unsubscribe();
      }
    } finally {
      this.state.set('off');
    }
  }
}

function b64url(s: string): Uint8Array {
  const pad = '='.repeat((4 - (s.length % 4)) % 4);
  const raw = atob((s + pad).replace(/-/g, '+').replace(/_/g, '/'));
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** A readable device name for the list of subscriptions (no personal data: browser + platform only). */
function device(): string {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'Browser';
  const os = /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Windows/.test(ua) ? 'Windows' : /Mac OS/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '';
  return [browser, os].filter(Boolean).join(' su ');
}
