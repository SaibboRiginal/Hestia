/**
 * Hestia-Hephaestus WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages and widget declared in Hestia-Hephaestus/app/core/webui_plugin.py; every element is `hephaestus-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { HephaestusRepairs } from './repairs';
import { HephaestusForgeWidget } from './forge-widget';
import { HephaestusSviluppo } from './sviluppo';
import { HephaestusTaskPanel } from './forge/panel';
import { HephaestusRepo } from './forge/repo';
import { HephaestusTranscript } from './forge/transcript';
import { HephaestusDiff } from './forge/diff';
import { HephaestusMd } from './forge/md';

definePlugin({
  'hephaestus-repairs': HephaestusRepairs, 'hephaestus-forge-widget': HephaestusForgeWidget,
  'hephaestus-sviluppo': HephaestusSviluppo, 'hephaestus-task-panel': HephaestusTaskPanel, 'hephaestus-repo': HephaestusRepo,
  'hephaestus-transcript': HephaestusTranscript, 'hephaestus-diff': HephaestusDiff, 'hephaestus-md': HephaestusMd,
});
