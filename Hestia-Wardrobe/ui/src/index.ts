/**
 * Wardrobe WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages and widgets declared in Hestia-Wardrobe/app/main.py (PluginClient.webui); every element is `wardrobe-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { WardrobePieceForm } from './form';
import { WardrobeAccessories, WardrobePiece, WardrobePieces } from './pieces';
import { WardrobeOutfit, WardrobeOutfitBuilder, WardrobeOutfits } from './outfits';
import { WardrobeSuggest } from './suggest';
import { WardrobeStats } from './stats';
import { WardrobeCollection, WardrobeCollections } from './collections';
import { WardrobeVocab } from './vocab';
import {
  WardrobeForgottenWidget, WardrobeKpiWidget, WardrobeLaundryWidget, WardrobeRecentWidget, WardrobeSuggestWidget, WardrobeTodayWidget,
} from './widgets';

definePlugin({
  'wardrobe-piece-form': WardrobePieceForm,
  'wardrobe-outfit-builder': WardrobeOutfitBuilder,
  'wardrobe-pieces': WardrobePieces,
  'wardrobe-accessories': WardrobeAccessories,
  'wardrobe-piece': WardrobePiece,
  'wardrobe-outfits': WardrobeOutfits,
  'wardrobe-outfit': WardrobeOutfit,
  'wardrobe-suggest': WardrobeSuggest,
  'wardrobe-stats': WardrobeStats,
  'wardrobe-collections': WardrobeCollections,
  'wardrobe-collection': WardrobeCollection,
  'wardrobe-vocab': WardrobeVocab,
  'wardrobe-today-widget': WardrobeTodayWidget,
  'wardrobe-suggest-widget': WardrobeSuggestWidget,
  'wardrobe-laundry-widget': WardrobeLaundryWidget,
  'wardrobe-forgotten-widget': WardrobeForgottenWidget,
  'wardrobe-kpi-widget': WardrobeKpiWidget,
  'wardrobe-recent-widget': WardrobeRecentWidget,
});
