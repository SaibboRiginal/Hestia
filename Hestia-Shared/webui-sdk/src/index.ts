/**
 * @hestia/webui-sdk — what every WebUI plugin imports (SPEC docs/work/2026-10-17-client-plugins §4.3–4.5).
 *
 * At runtime the WebUI serves ONE copy of this SDK (and of Lit) at /plugins/_sdk/sdk.js and maps the bare
 * imports `@hestia/webui-sdk`, `lit` and `lit/*` to it with an import map, so plugin bundles stay small and
 * all plugins share the same kit (`hxk-*` elements) and styles.
 */
export * from 'lit';
export { customElement, property, state, query } from 'lit/decorators.js';
export { repeat } from 'lit/directives/repeat.js';
export { classMap } from 'lit/directives/class-map.js';
export { styleMap } from 'lit/directives/style-map.js';

export * from './types';
export { tokens, kitStyles, toneColor } from './styles';
export { HestiaElement, definePlugin, fillPath } from './base';
export { HxkIcon, HxkButton, HxkBadge, HxkCard, HxkStat, HxkState, HxkList } from './kit/basics';
export { HxkChart } from './kit/chart';
export type { ChartSeries } from './kit/chart';
export { HxkField, HxkImagePicker } from './kit/forms';
export { HxkQuicklog } from './kit/quicklog';
export type { QuickAction } from './kit/quicklog';

import { definePlugin } from './base';
import { HxkBadge, HxkButton, HxkCard, HxkIcon, HxkList, HxkStat, HxkState } from './kit/basics';
import { HxkChart } from './kit/chart';
import { HxkField, HxkImagePicker } from './kit/forms';
import { HxkQuicklog } from './kit/quicklog';

/** Kit elements, registered once for every plugin (prefix `hxk-` so they never clash with the WebUI's own `hx-*`). */
definePlugin({
  'hxk-icon': HxkIcon, 'hxk-button': HxkButton, 'hxk-badge': HxkBadge, 'hxk-card': HxkCard, 'hxk-stat': HxkStat,
  'hxk-state': HxkState, 'hxk-list': HxkList, 'hxk-chart': HxkChart, 'hxk-field': HxkField,
  'hxk-image-picker': HxkImagePicker, 'hxk-quicklog': HxkQuicklog,
});

export const SDK_VERSION = '1';
