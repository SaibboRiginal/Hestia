/**
 * Hestia-MCP WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Pages declared in Hestia-MCP/app/main.py (PluginClient.webui); every element is `mcp-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { McpAccesses } from './accesses';
import { McpCommands } from './commands';

definePlugin({ 'mcp-accesses': McpAccesses, 'mcp-commands': McpCommands });
