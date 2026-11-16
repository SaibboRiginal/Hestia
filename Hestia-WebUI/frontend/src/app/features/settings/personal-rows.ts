import { tr } from '../../core/i18n';
/** The personal settings of this client (Impostazioni → Personali): sections and rows, as data, so the page search
 *  and the Ctrl+K palette find them without loading the page. */
export interface PersonalSection { id: string; label: string; icon: string; }
export interface PersonalRow { id: string; section: string; label: string; help: string; keywords: string; wide?: boolean; }

export const PERSONAL_SECTIONS: PersonalSection[] = [
  { id: 'aspetto', label: tr('Look'), icon: 'palette' },
  { id: 'assistente', label: tr('Assistant'), icon: 'chat' },
  { id: 'messaggi', label: tr('System messages'), icon: 'bell' },
  { id: 'sessione', label: tr('Session'), icon: 'refresh' },
  { id: 'plugin', label: tr('Modules and Home'), icon: 'puzzle' },
];

/** Every personal setting, so the page search finds them like the system ones. */
export const PERSONAL_ROWS: PersonalRow[] = [
  { id: 'theme', section: 'aspetto', label: tr('Colours'), wide: true, keywords: 'tema colori scuro chiaro dark light oceano foresta lavanda',
    help: tr('Interface colours on this browser. «Automatic» follows the system.') },
  { id: 'style', section: 'aspetto', label: tr('Style'), wide: true, keywords: 'stile vetro netto classico forma look',
    help: tr('The shape of the interface, on top of the colours. Every style is a starting point: below you can change corners, borders, transparencies and animations.') },
  { id: 'knobs', section: 'aspetto', label: tr('Style details'), wide: true,
    keywords: tr('corners borders transparency blur opacity animations motion'),
    help: tr('On this browser. «Back to style» restores the values of the chosen style.') },
  { id: 'look', section: 'aspetto', label: tr('Holiday themes and little pet'), keywords: 'compleanno natale stagioni effetti neve animale pet',
    help: tr('On special days (your birthday, the holidays, the seasons) the colours and a small effect change by themselves, on top of your theme.') },
  { id: 'tone', section: 'assistente', label: tr('Tone'), keywords: 'stile risposte caldo formale diretto',
    help: tr('Your default on every client. A single chat can change it from the settings icon at the top of the chat.') },
  { id: 'thinking', section: 'assistente', label: tr('Reasoning in the answers'), keywords: 'thinking pensiero',
    help: tr('Display only: hidden, compact (closed), detailed (open, complete) or live (open while it works). Also changed from the chat settings icon.') },
  { id: 'instructions', section: 'assistente', label: tr('Personal instructions'), wide: true, keywords: 'prompt istruzioni',
    help: tr('Added to every conversation, on every client (empty = none).') },
  { id: 'push', section: 'messaggi', label: tr('Notifications on this device'), keywords: 'push notifiche browser telefono pwa avvisi',
    help: tr('Notifications arrive even with the site closed, like on Telegram. Tap the notification to open the right page.') },
  { id: 'notice_mode', section: 'messaggi', label: tr('Where to show them'), keywords: 'avvisi notice popup toast',
    help: tr('Notices separate from the answer: memory saved, actions run, notifications turned on, errors. On this browser.') },
  { id: 'notice_style', section: 'messaggi', label: tr('Message style'), keywords: 'avvisi compatto dettagliato',
    help: tr('Compact: one line. Detailed: with the particulars.') },
  { id: 'notice_groups', section: 'messaggi', label: tr('Which messages to show'), wide: true,
    keywords: 'avvisi memoria azioni notifiche documenti agenda sviluppo',
    help: tr('Errors are shown anyway, except with «Hidden».') },
  { id: 'new_session', section: 'sessione', label: tr('New session'), keywords: 'conversazione contesto reset',
    help: tr('Hestia forgets the context of the conversation (the memories stay).') },
  { id: 'reset', section: 'sessione', label: tr('Restore personal settings'), keywords: 'predefiniti reset',
    help: tr('Tone, reasoning, instructions and system messages go back to defaults.') },
];
