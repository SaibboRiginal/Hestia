/**
 * Hestia-Oracle WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages/widgets declared in Hestia-Oracle/app/main.py (PluginClient.webui); every element is `oracle-*`.
 * Inside view of Oracle: docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { OracleBrain } from './brain';
import { OracleDocuments } from './documents';
import { OracleMemory } from './memory';
import { OracleModels } from './models';
import { OracleUsage } from './usage';
import { OracleUsageWidget } from './widgets';

definePlugin({ 'oracle-brain': OracleBrain, 'oracle-documents': OracleDocuments, 'oracle-usage-widget': OracleUsageWidget,
               'oracle-usage': OracleUsage, 'oracle-models': OracleModels, 'oracle-memory': OracleMemory });
