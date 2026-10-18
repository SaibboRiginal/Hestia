/**
 * Hygieia (self care) WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages and widgets declared in Hestia-Hygieia/app/main.py (PluginClient.webui); every element is `hygieia-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { HygieiaToday } from './today';
import { HygieiaCadence, HygieiaRoutine, HygieiaRoutines } from './routines';
import { HygieiaProduct, HygieiaProductForm, HygieiaProducts } from './products';
import { HygieiaJournal } from './journal';
import { HygieiaShopping, HygieiaStats } from './stats';
import { HygieiaAlertsWidget, HygieiaNextWidget, HygieiaTodayWidget, HygieiaWeekWidget } from './widgets';

definePlugin({
  'hygieia-cadence': HygieiaCadence,
  'hygieia-product-form': HygieiaProductForm,
  'hygieia-today': HygieiaToday,
  'hygieia-routines': HygieiaRoutines,
  'hygieia-routine': HygieiaRoutine,
  'hygieia-products': HygieiaProducts,
  'hygieia-product': HygieiaProduct,
  'hygieia-journal': HygieiaJournal,
  'hygieia-stats': HygieiaStats,
  'hygieia-shopping': HygieiaShopping,
  'hygieia-today-widget': HygieiaTodayWidget,
  'hygieia-next-widget': HygieiaNextWidget,
  'hygieia-alerts-widget': HygieiaAlertsWidget,
  'hygieia-week-widget': HygieiaWeekWidget,
});
