import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';
import { AuthService } from './auth.service';

/** Adds X-Access-Token; on 401 (token expired/revoked) logs out and goes to /login. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const token = auth.getToken();
  if (token && !req.url.includes('/auth/login')) {
    req = req.clone({ setHeaders: { 'X-Access-Token': token } });
  }
  return next(req).pipe(catchError((err: HttpErrorResponse) => {
    if (err.status === 401 && !req.url.includes('/auth/login')) {
      auth.logout();
      router.navigate(['/login']);
    }
    return throwError(() => err);
  }));
};
