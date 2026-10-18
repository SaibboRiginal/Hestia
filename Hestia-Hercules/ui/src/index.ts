/**
 * Hercules WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages and widgets declared in Hestia-Hercules/app/main.py (PluginClient.webui); every element is `hercules-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { HerculesPicker } from './picker';
import { HerculesToday } from './today';
import { HerculesTemplate, HerculesTemplates } from './templates';
import { HerculesExercise, HerculesExercises } from './exercises';
import { HerculesHistory, HerculesSession } from './history';
import { HerculesBody, HerculesProgress } from './progress';
import {
  HerculesExerciseWidget, HerculesLiveWidget, HerculesNextWidget, HerculesPrsWidget, HerculesQuickWidget,
  HerculesVolumeWidget, HerculesWeekWidget, HerculesWeightWidget,
} from './widgets';

definePlugin({
  'hercules-picker': HerculesPicker,
  'hercules-today': HerculesToday,
  'hercules-templates': HerculesTemplates,
  'hercules-template': HerculesTemplate,
  'hercules-exercises': HerculesExercises,
  'hercules-exercise': HerculesExercise,
  'hercules-history': HerculesHistory,
  'hercules-session': HerculesSession,
  'hercules-progress': HerculesProgress,
  'hercules-body': HerculesBody,
  'hercules-next-widget': HerculesNextWidget,
  'hercules-week-widget': HerculesWeekWidget,
  'hercules-quick-widget': HerculesQuickWidget,
  'hercules-prs-widget': HerculesPrsWidget,
  'hercules-exercise-widget': HerculesExerciseWidget,
  'hercules-volume-widget': HerculesVolumeWidget,
  'hercules-weight-widget': HerculesWeightWidget,
  'hercules-live-widget': HerculesLiveWidget,
});
