/**
 * Hestia-Iris WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * Page «Email» (core): who receives which mails, last deliveries, the mailbox watcher in Hecate.
 * SPEC docs/work/2026-10-19-email-push-spese §3.2.
 */
import { definePlugin } from '@hestia/webui-sdk';
import { IrisEmail } from './email';

definePlugin({ 'iris-email': IrisEmail });
