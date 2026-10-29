/**
 * Hestia-Hecate WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Page declared in Hestia-Hecate/app/main.py (PluginClient.webui); every element is `hecate-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { HecateDevices } from './devices';

definePlugin({ 'hecate-devices': HecateDevices });
