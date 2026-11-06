/**
 * Emoji reactions in chat bubbles (docs/work/2026-11-06-hestia-viva F4). Marko 2026-11-06: reactions are chat
 * content, real emoji like any chat app, not UI icons. This file is the only WebUI place allowed to hold emoji
 * (tools/governance/check_icons.py exempts it); everything else keeps <hx-icon>.
 */
export const REACTION_EMOJI: readonly string[] = ['👍', '❤️', '😂', '😮', '😢', '🙏'];
