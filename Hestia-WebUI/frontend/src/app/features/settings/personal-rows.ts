import { tr } from '../../core/i18n';
/** The personal settings of this client (Impostazioni → Personali): sections and rows, as data, so the page search
 *  and the Ctrl+K palette find them without loading the page. */
export interface PersonalSection { id: string; label: string; icon: string; }
export interface PersonalRow { id: string; section: string; label: string; help: string; keywords: string; wide?: boolean; }

export const PERSONAL_SECTIONS: PersonalSection[] = [
  { id: 'aspetto', label: tr('Aspetto'), icon: 'palette' },
  { id: 'assistente', label: tr('Assistente'), icon: 'chat' },
  { id: 'messaggi', label: tr('Messaggi di sistema'), icon: 'bell' },
  { id: 'sessione', label: tr('Sessione'), icon: 'refresh' },
  { id: 'plugin', label: tr('Moduli e Home'), icon: 'puzzle' },
];

/** Every personal setting, so the page search finds them like the system ones. */
export const PERSONAL_ROWS: PersonalRow[] = [
  { id: 'theme', section: 'aspetto', label: tr('Colori'), wide: true, keywords: 'tema colori scuro chiaro dark light oceano foresta lavanda',
    help: tr('Colori dell\'interfaccia su questo browser. «Automatico» segue il sistema.') },
  { id: 'style', section: 'aspetto', label: tr('Stile'), wide: true, keywords: 'stile vetro netto classico forma look',
    help: tr('La forma dell\'interfaccia, sopra ai colori. Ogni stile è un punto di partenza: sotto puoi cambiare angoli, bordi, trasparenze e animazioni.') },
  { id: 'knobs', section: 'aspetto', label: tr('Dettagli dello stile'), wide: true,
    keywords: tr('angoli bordi trasparenza blur sfocatura opacità animazioni movimento'),
    help: tr('Su questo browser. «Torna allo stile» rimette i valori dello stile scelto.') },
  { id: 'look', section: 'aspetto', label: tr('Temi delle feste e animaletto'), keywords: 'compleanno natale stagioni effetti neve animale pet',
    help: tr('Nei giorni speciali (il tuo compleanno, le feste, le stagioni) i colori e un piccolo effetto cambiano da soli, sopra il tuo tema.') },
  { id: 'tone', section: 'assistente', label: tr('Tono'), keywords: 'stile risposte caldo formale diretto',
    help: tr('Il tuo predefinito su ogni client. Una singola chat può cambiarlo dall\'icona delle impostazioni in alto nella chat.') },
  { id: 'thinking', section: 'assistente', label: tr('Ragionamento nelle risposte'), keywords: 'thinking pensiero',
    help: tr('Solo visualizzazione: nascosto, compatto (chiuso), dettagliato (aperto, completo) o dal vivo (aperto mentre lavora). Si cambia anche dall\'icona delle impostazioni della chat.') },
  { id: 'instructions', section: 'assistente', label: tr('Istruzioni personali'), wide: true, keywords: 'prompt istruzioni',
    help: tr('Aggiunte a ogni conversazione, su ogni client (vuoto = nessuna).') },
  { id: 'push', section: 'messaggi', label: tr('Notifiche su questo dispositivo'), keywords: 'push notifiche browser telefono pwa avvisi',
    help: tr('Le notifiche arrivano anche a sito chiuso, come su Telegram. Tocca la notifica per aprire la pagina giusta.') },
  { id: 'notice_mode', section: 'messaggi', label: tr('Dove mostrarli'), keywords: 'avvisi notice popup toast',
    help: tr('Avvisi separati dalla risposta: memoria salvata, azioni eseguite, notifiche attivate, errori. Su questo browser.') },
  { id: 'notice_style', section: 'messaggi', label: tr('Stile dei messaggi'), keywords: 'avvisi compatto dettagliato',
    help: tr('Compatto: una riga. Dettagliato: con i particolari.') },
  { id: 'notice_groups', section: 'messaggi', label: tr('Quali messaggi mostrare'), wide: true,
    keywords: 'avvisi memoria azioni notifiche documenti agenda sviluppo',
    help: tr('Gli errori vengono mostrati comunque, tranne con «Nascosti».') },
  { id: 'new_session', section: 'sessione', label: tr('Nuova sessione'), keywords: 'conversazione contesto reset',
    help: tr('{assistant} dimentica il contesto della conversazione (le memorie restano).') },
  { id: 'reset', section: 'sessione', label: tr('Ripristina impostazioni personali'), keywords: 'predefiniti reset',
    help: tr('Tono, ragionamento, istruzioni e messaggi di sistema tornano ai predefiniti.') },
];
