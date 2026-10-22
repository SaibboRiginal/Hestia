/**
 * Hestia-Echo WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Page declared in Hestia-Echo/app/main.py (PluginClient.webui); every element is `echo-*`.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { EchoBlocks } from './blocks';
import { EchoVoice } from './voice';

definePlugin({ 'echo-voice': EchoVoice, 'echo-blocks': EchoBlocks });
