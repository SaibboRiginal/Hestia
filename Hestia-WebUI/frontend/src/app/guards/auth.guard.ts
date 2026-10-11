import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

/** Home network → straight in; otherwise a valid token is needed (login page). */
export const authGuard: CanActivateFn = async () => {
  const auth = inject(AuthService);
  const router = inject(Router);
  await auth.checkAccess();
  return auth.isAuthenticated() ? true : router.createUrlTree(['/login']);
};
