/**
 * Hestia-Chronos WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages/widgets declared in Hestia-Chronos/app/main.py (PluginClient.webui); every element is `chronos-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { ChronosRuns } from './runs';
import { ChronosFailedWidget } from './widget';

definePlugin({ 'chronos-runs': ChronosRuns, 'chronos-failed-widget': ChronosFailedWidget });
