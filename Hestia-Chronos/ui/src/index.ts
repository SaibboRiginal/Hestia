/**
 * Hestia-Chronos WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages/widgets declared in Hestia-Chronos/app/main.py (PluginClient.webui); every element is `chronos-*`.
 * The calendar's building blocks (dialog, popover, menu, mini month, views, details, editor, wizard) are registered
 * first so the «Agenda di Hestia» page finds them.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { ChronosDialog, ChronosMenu, ChronosPop } from './cal/ui';
import { ChronosCalMini } from './cal/mini';
import { ChronosCalGrid } from './cal/views/timegrid';
import { ChronosCalMonth } from './cal/views/month';
import { ChronosCalList } from './cal/views/list';
import { ChronosCalDetails } from './cal/details';
import { ChronosCalEditor } from './cal/editor';
import { ChronosCalWizard } from './cal/wizard';
import { ChronosAgenda } from './agenda';
import { ChronosRuns } from './runs';
import { ChronosRoutines } from './routines';
import { ChronosSpecial } from './special';
import { ChronosStandard } from './standard';
import { ChronosWeek } from './week';
import { ChronosFailedWidget, ChronosTodayWidget } from './widget';

definePlugin({
  'chronos-dialog': ChronosDialog, 'chronos-pop': ChronosPop, 'chronos-menu': ChronosMenu, 'chronos-cal-mini': ChronosCalMini,
  'chronos-cal-grid': ChronosCalGrid, 'chronos-cal-month': ChronosCalMonth, 'chronos-cal-list': ChronosCalList,
  'chronos-cal-details': ChronosCalDetails, 'chronos-cal-editor': ChronosCalEditor, 'chronos-cal-wizard': ChronosCalWizard,
  'chronos-agenda': ChronosAgenda, 'chronos-runs': ChronosRuns, 'chronos-standard': ChronosStandard, 'chronos-failed-widget': ChronosFailedWidget,
  'chronos-week': ChronosWeek, 'chronos-today-widget': ChronosTodayWidget,
  'chronos-routines': ChronosRoutines, 'chronos-special': ChronosSpecial,
});
