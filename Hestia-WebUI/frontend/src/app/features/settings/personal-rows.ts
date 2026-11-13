/** The personal settings of this client (Impostazioni → Personali): sections and rows, as data, so the page search
 *  and the Ctrl+K palette find them without loading the page. */
export interface PersonalSection { id: string; label: string; icon: string; }
export interface PersonalRow { id: string; section: string; label: string; help: string; keywords: string; wide?: boolean; }

export const PERSONAL_SECTIONS: PersonalSection[] = [
  { id: 'aspetto', label: 'Aspetto', icon: 'palette' },
  { id: 'assistente', label: 'Assistente', icon: 'chat' },
  { id: 'messaggi', label: 'Messaggi di sistema', icon: 'bell' },
  { id: 'sessione', label: 'Sessione', icon: 'refresh' },
  { id: 'plugin', label: 'Moduli e Home', icon: 'puzzle' },
];

/** Every personal setting, so the page search finds them like the system ones. */
export const PERSONAL_ROWS: PersonalRow[] = [
  { id: 'theme', section: 'aspetto', label: 'Colori', wide: true, keywords: 'tema colori scuro chiaro dark light oceano foresta lavanda',
    help: 'Colori dell\'interfaccia su questo browser. «Automatico» segue il sistema.' },
  { id: 'style', section: 'aspetto', label: 'Stile', wide: true, keywords: 'stile vetro netto classico forma look',
    help: 'La forma dell\'interfaccia, sopra ai colori. Ogni stile è un punto di partenza: sotto puoi cambiare angoli, bordi, trasparenze e animazioni.' },
  { id: 'knobs', section: 'aspetto', label: 'Dettagli dello stile', wide: true,
    keywords: 'angoli bordi trasparenza blur sfocatura opacità animazioni movimento',
    help: 'Su questo browser. «Torna allo stile» rimette i valori dello stile scelto.' },
  { id: 'look', section: 'aspetto', label: 'Temi delle feste e animaletto', keywords: 'compleanno natale stagioni effetti neve animale pet',
    help: 'Nei giorni speciali (il tuo compleanno, le feste, le stagioni) i colori e un piccolo effetto cambiano da soli, sopra il tuo tema.' },
  { id: 'tone', section: 'assistente', label: 'Tono', keywords: 'stile risposte caldo formale diretto',
    help: 'Il tuo predefinito su ogni client. Una singola chat può cambiarlo dall\'icona delle impostazioni in alto nella chat.' },
  { id: 'thinking', section: 'assistente', label: 'Ragionamento nelle risposte', keywords: 'thinking pensiero',
    help: 'Solo visualizzazione: nascosto, compatto (chiuso), dettagliato (aperto, completo) o dal vivo (aperto mentre lavora). Si cambia anche dall\'icona delle impostazioni della chat.' },
  { id: 'instructions', section: 'assistente', label: 'Istruzioni personali', wide: true, keywords: 'prompt istruzioni',
    help: 'Aggiunte a ogni conversazione, su ogni client (vuoto = nessuna).' },
  { id: 'push', section: 'messaggi', label: 'Notifiche su questo dispositivo', keywords: 'push notifiche browser telefono pwa avvisi',
    help: 'Le notifiche arrivano anche a sito chiuso, come su Telegram. Tocca la notifica per aprire la pagina giusta.' },
  { id: 'notice_mode', section: 'messaggi', label: 'Dove mostrarli', keywords: 'avvisi notice popup toast',
    help: 'Avvisi separati dalla risposta: memoria salvata, azioni eseguite, notifiche attivate, errori. Su questo browser.' },
  { id: 'notice_style', section: 'messaggi', label: 'Stile dei messaggi', keywords: 'avvisi compatto dettagliato',
    help: 'Compatto: una riga. Dettagliato: con i particolari.' },
  { id: 'notice_groups', section: 'messaggi', label: 'Quali messaggi mostrare', wide: true,
    keywords: 'avvisi memoria azioni notifiche documenti agenda sviluppo',
    help: 'Gli errori vengono mostrati comunque, tranne con «Nascosti».' },
  { id: 'new_session', section: 'sessione', label: 'Nuova sessione', keywords: 'conversazione contesto reset',
    help: 'Hestia dimentica il contesto della conversazione (le memorie restano).' },
  { id: 'reset', section: 'sessione', label: 'Ripristina impostazioni personali', keywords: 'predefiniti reset',
    help: 'Tono, ragionamento, istruzioni e messaggi di sistema tornano ai predefiniti.' },
];
