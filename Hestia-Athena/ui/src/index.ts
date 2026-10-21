/**
 * Hestia-Athena WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages/widgets/quick actions declared in Hestia-Athena/app/main.py (PluginClient.webui); elements are `athena-*`.
 * Inside view of Athena: docs/work/2026-10-18-moduli-core-e-mcp-esterno §A2. Recap: docs/work/2026-10-20-recap-giornaliero.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { AthenaRecaps } from './recaps';
import { AthenaThoughts } from './thoughts';
import { AthenaLastWidget } from './widgets';

definePlugin({ 'athena-thoughts': AthenaThoughts, 'athena-last-widget': AthenaLastWidget, 'athena-recaps': AthenaRecaps });
