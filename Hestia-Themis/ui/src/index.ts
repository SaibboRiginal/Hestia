/**
 * Hestia-Themis WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Page declared in Hestia-Themis/app/main.py (PluginClient.webui); every element is `themis-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { ThemisLog } from './log';

definePlugin({ 'themis-log': ThemisLog });
