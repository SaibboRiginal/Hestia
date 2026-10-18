/** Scout WebUI plugin: every element the manifest (app/ui_api.py) names. */
import { definePlugin } from '@hestia/webui-sdk';
import { ScoutListing } from './listing';
import { ScoutListings } from './listings';
import { ScoutFavoritesWidget, ScoutKpiWidget, ScoutNewWidget, ScoutPricesWidget, ScoutStats } from './stats';

definePlugin({
  'scout-listings': ScoutListings,
  'scout-listing': ScoutListing,
  'scout-stats': ScoutStats,
  'scout-kpi-widget': ScoutKpiWidget,
  'scout-new-widget': ScoutNewWidget,
  'scout-favorites-widget': ScoutFavoritesWidget,
  'scout-prices-widget': ScoutPricesWidget,
});
