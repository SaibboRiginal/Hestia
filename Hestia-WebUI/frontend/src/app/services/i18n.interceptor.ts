import { HttpInterceptorFn, HttpResponse } from '@angular/common/http';
import { map } from 'rxjs';
import { localize } from '../core/i18n';

/** Every API answer reaches the page with its people texts in the owner's language: module manifests, pages,
 * widgets, cards and plugin data carry English source texts (docs/LANGUAGES.md), translated here once. */
export const i18nInterceptor: HttpInterceptorFn = (req, next) =>
  next(req).pipe(map(event => (event instanceof HttpResponse && event.body && typeof event.body === 'object'
    ? event.clone({ body: localize(event.body) }) : event)));
