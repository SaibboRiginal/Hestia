import { isDevMode } from '@angular/core';
import { bootstrapApplication } from '@angular/platform-browser';
import { appConfig } from './app/app.config';
import { AppComponent } from './app/app.component';

bootstrapApplication(AppComponent, appConfig)
  .catch((err) => console.error(err));

// PWA: installable, plugin pages work offline (public/sw.js). Not in `ng serve` (would cache dev builds).
if (!isDevMode() && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js')
    .catch(e => console.warn('event=sw_register_failed', e)));
}
