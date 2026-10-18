/**
 * Hestia-Metis WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Page declared in Hestia-Metis/app/main.py (PluginClient.webui); every element is `metis-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { MetisImprovement } from './improvement';

definePlugin({ 'metis-improvement': MetisImprovement });
