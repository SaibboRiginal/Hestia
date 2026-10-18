/**
 * Hestia-Hephaestus WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Page and widget declared in Hestia-Hephaestus/app/core/webui_plugin.py; every element is `hephaestus-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { HephaestusRepairs } from './repairs';
import { HephaestusForgeWidget } from './forge-widget';

definePlugin({ 'hephaestus-repairs': HephaestusRepairs, 'hephaestus-forge-widget': HephaestusForgeWidget });
