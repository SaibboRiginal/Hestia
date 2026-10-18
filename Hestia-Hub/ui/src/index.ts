/**
 * Hestia-Hub WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Page and widget declared in Hestia-Hub/src/modules/inside.py (PluginClient.webui); every element is `hub-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { HubMap, HubOnlineWidget } from './map';

definePlugin({ 'hub-map': HubMap, 'hub-online-widget': HubOnlineWidget });
