import { isDevMode } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';
import { loadI18n } from './app/core/i18n';

// Fixed texts in the owner's language: index.html already loaded the catalog; the JSON is the fallback.
loadI18n().finally(() => bootstrapApplication(AppComponent, appConfig)
  .catch((err) => console.error(err)));

// PWA: installable, plugin pages work offline (public/sw.js). Not in `ng serve` (would cache dev builds).
if (!isDevMode() && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js')
    .catch(e => console.warn('event=sw_register_failed', e)));
}
