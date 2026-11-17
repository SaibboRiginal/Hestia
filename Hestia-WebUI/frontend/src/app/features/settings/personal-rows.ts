import { tr } from '../../core/i18n';
/** The personal settings of this client (Settings → Personal): sections and rows, as data, so the page search
 *  and the Ctrl+K palette find them without loading the page. */
export interface PersonalSection { id: string; label: string; icon: string; }
export interface PersonalRow { id: string; section: string; label: string; help: string; keywords: string; wide?: boolean; }

export const PERSONAL_SECTIONS: PersonalSection[] = [
  { id: 'look', label: tr('Look'), icon: 'palette' },
  { id: 'assistant', label: tr('Assistant'), icon: 'chat' },
  { id: 'messages', label: tr('System messages'), icon: 'bell' },
  { id: 'session', label: tr('Session'), icon: 'refresh' },
  { id: 'plugin', label: tr('Modules and Home'), icon: 'puzzle' },
];

/** Every personal setting, so the page search finds them like the system ones. */
export const PERSONAL_ROWS: PersonalRow[] = [
  { id: 'theme', section: 'look', label: tr('Colours'), wide: true, keywords: tr('theme colours dark light ocean forest lavender'),
    help: tr('Interface colours on this browser. «Automatic» follows the system.') },
  { id: 'style', section: 'look', label: tr('Style'), wide: true, keywords: tr('style glass sharp classic shape look'),
    help: tr('The shape of the interface, on top of the colours. Every style is a starting point: below you can change corners, borders, transparencies and animations.') },
  { id: 'knobs', section: 'look', label: tr('Style details'), wide: true,
    keywords: tr('corners borders transparency blur opacity animations motion'),
    help: tr('On this browser. «Back to style» restores the values of the chosen style.') },
  { id: 'look', section: 'look', label: tr('Holiday themes and little pet'), keywords: tr('birthday christmas seasons effects snow animal pet'),
    help: tr('On special days (your birthday, the holidays, the seasons) the colours and a small effect change by themselves, on top of your theme.') },
  { id: 'tone', section: 'assistant', label: tr('Tone'), keywords: tr('style answers warm formal direct'),
    help: tr('Your default on every client. A single chat can change it from the settings icon at the top of the chat.') },
  { id: 'thinking', section: 'assistant', label: tr('Reasoning in the answers'), keywords: tr('thinking reasoning'),
    help: tr('Display only: hidden, compact (closed), detailed (open, complete) or live (open while it works). Also changed from the chat settings icon.') },
  { id: 'instructions', section: 'assistant', label: tr('Personal instructions'), wide: true, keywords: tr('prompt instructions'),
    help: tr('Added to every conversation, on every client (empty = none).') },
  { id: 'push', section: 'messages', label: tr('Notifications on this device'), keywords: tr('push notifications browser phone pwa notices'),
    help: tr('Notifications arrive even with the site closed, like on Telegram. Tap the notification to open the right page.') },
  { id: 'notice_mode', section: 'messages', label: tr('Where to show them'), keywords: tr('notices popup toast'),
    help: tr('Notices separate from the answer: memory saved, actions run, notifications turned on, errors. On this browser.') },
  { id: 'notice_style', section: 'messages', label: tr('Message style'), keywords: tr('notices compact detailed'),
    help: tr('Compact: one line. Detailed: with the particulars.') },
  { id: 'notice_groups', section: 'messages', label: tr('Which messages to show'), wide: true,
    keywords: tr('notices memory actions notifications documents agenda development'),
    help: tr('Errors are shown anyway, except with «Hidden».') },
  { id: 'new_session', section: 'session', label: tr('New session'), keywords: tr('conversation context reset'),
    help: tr('{assistant} forgets the context of the conversation (the memories stay).') },
  { id: 'reset', section: 'session', label: tr('Restore personal settings'), keywords: tr('defaults reset'),
    help: tr('Tone, reasoning, instructions and system messages go back to defaults.') },
];
