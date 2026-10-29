/**
 * Hestia-Argus WebUI plugin bundle (plugin contract, docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2).
 * Page, widget and quick action declared in Hestia-Argus/app/core/ui_plugin.py; every element is `argus-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { ArgusHealth } from './health';
import { ArgusPerformance } from './performance';
import { ArgusStatusWidget } from './widget';

definePlugin({ 'argus-health': ArgusHealth, 'argus-performance': ArgusPerformance, 'argus-status-widget': ArgusStatusWidget });
