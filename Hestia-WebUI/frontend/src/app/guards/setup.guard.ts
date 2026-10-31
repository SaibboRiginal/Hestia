import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { SetupApi } from '../features/setup/setup.api';

/** First visit after the install: the guided setup «Benvenuto» opens once per browser session until it is completed.
 *  Hestia not answering → straight in (the setup must never lock the app). */
export const setupGuard: CanActivateFn = async () => {
  const router = inject(Router);
  const api = inject(SetupApi);
  try {
    if (sessionStorage.getItem('hestia_setup_seen')) return true;
    sessionStorage.setItem('hestia_setup_seen', '1');
  } catch {
    return true;
  }
  try {
    return (await api.state()).completed ? true : router.createUrlTree(['/benvenuto']);
  } catch {
    return true;
  }
};
