import { UrlMatchResult, UrlSegment } from '@angular/router';

/** Route matcher: /p/<module>/<any/page/path> (the rest is resolved against the module's pages at runtime). */
export function pluginPageMatcher(segments: UrlSegment[]): UrlMatchResult | null {
  if (segments.length >= 2 && segments[0].path === 'p') return { consumed: segments, posParams: { module: segments[1] } };
  return null;
}
