/**
 * Hestia-Archive WebUI plugin bundle (plugin contract, docs/work/2026-10-17-client-plugins/SPEC.md §4).
 * One settings panel declared in Hestia-Archive/app/backup/wiring.py: the Backup panel (docs/work/2026-10-20-backup-drive).
 */
import { definePlugin } from '@hestia/webui-sdk';
import { ArchiveBackupPanel } from './backup';

definePlugin({ 'archive-backup-panel': ArchiveBackupPanel });
