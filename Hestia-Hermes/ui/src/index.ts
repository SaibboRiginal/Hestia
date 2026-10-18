/**
 * Hestia-Hermes WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages/widgets declared in Hestia-Hermes/src/main.py (PluginClient.webui); every element is `hermes-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { HermesDeliveries } from './deliveries';
import { HermesTodayWidget } from './widget';

definePlugin({ 'hermes-deliveries': HermesDeliveries, 'hermes-today-widget': HermesTodayWidget });
