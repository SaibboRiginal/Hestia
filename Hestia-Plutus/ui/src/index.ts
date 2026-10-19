/**
 * Plutus (expenses) WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages and widgets declared in Hestia-Plutus/app/main.py (PluginClient.webui); every element is `plutus-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { PlutusOverview } from './overview';
import { PlutusTransaction, PlutusTransactions, PlutusTxForm } from './transactions';
import { PlutusBudgets, PlutusRecurring } from './budgets';
import { PlutusImport } from './import';
import { PlutusCategories, PlutusStats } from './stats';
import { PlutusLatestWidget, PlutusMonthWidget } from './widgets';

definePlugin({
  'plutus-tx-form': PlutusTxForm,
  'plutus-overview': PlutusOverview,
  'plutus-transactions': PlutusTransactions,
  'plutus-transaction': PlutusTransaction,
  'plutus-budgets': PlutusBudgets,
  'plutus-recurring': PlutusRecurring,
  'plutus-import': PlutusImport,
  'plutus-stats': PlutusStats,
  'plutus-categories': PlutusCategories,
  'plutus-month-widget': PlutusMonthWidget,
  'plutus-latest-widget': PlutusLatestWidget,
});
