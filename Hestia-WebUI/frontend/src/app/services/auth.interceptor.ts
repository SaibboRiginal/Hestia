import { HttpInterceptorFn } from '@angular/common/http';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const token = localStorage.getItem('hestia_token');
  if (token && !req.url.includes('/login')) {
    req = req.clone({ setHeaders: { 'X-Access-Token': token } });
  }
  return next(req);
};
