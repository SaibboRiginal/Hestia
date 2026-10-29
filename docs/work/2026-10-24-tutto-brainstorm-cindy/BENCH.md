# Banco di prova — giro finale W8 (2026-10-29)

Stack intero sul banco cloud (`python tools/cloud_test.py all` + `flows`), LLM finto. Rapporto di base:

## Smoke

- ✅ Hub: servizi registrati: 27: aphrodite, apollo, archive, argus, athena, calliope, chronos, demeter, dummy, echo, hecate, hephaestus, hera, hercules, hermes, hygieia, iris, kairos, lares, mcp, metis, oracle, plutus, scout, themis, wardrobe, webui
- ✅ Hub: mappa (online/offline): online 28 · offline 0
- ✅ Oracle: risposta LLM (finto): ollama: [LLM finto] Ho ricevuto: «User: Ciao Hestia, come stai? Answer:». Questo è il banco di prova: nessun modello reale.
- ✅ Themis: moduli con impostazioni: 25
- ✅ Hestia-MCP: health: {'status': 'ok', 'service': 'hestia_mcp'}

## WebUI

- chat: messaggio inviato, vedi desk-chat-roundtrip.png
- desk: 41 pagine, errori JS 0
- phone: home ok, errori JS 0

Screenshot: `.cloud-test/screens/`

---


Passi: 65 ✅ · 0 ❌


## Allenamento (Hercules)

- ✅ Crea una scheda (2 esercizi, 3 serie) — scheda Banco Push 162151 con 2 esercizi
- ✅ Allenamento live: inizia, 6 serie, chiudi — 6 serie salvate, sessione chiusa: {'id': 'a1dcdb62-59c2-402b-b261-6c8574de7d16', 'name': 'Banco Push 162151', 'started_at': '2026-10-29T16:21:51.653675+00 · PR 0
- ✅ «L'ultima volta» e suggerimento per la prossima — dettaglio esercizio e scheda con ultima volta/suggerimento
- ✅ Record e statistiche — record panca: {'heaviest': {'value': 62.5, 'reps': 6, 'date': '2026-10-29T15:58:22.803939+00:00', 'session_id': '61482f88-79cd-4477-af · stats chiavi ['heatmap', 'per', 'periods', 'recent_prs', 'totals']
- ✅ Offline → online: sync ripetuta senza duplicati — sync applicate ['o0', 'o3', 'o2', 'o1'] / ripetuta ['o0', 'o3', 'o2', 'o1'], 3 serie, nessun duplicato
- ✅ Home: «Segna fatto» con un tocco + Annulla — «Banco Push 162151 segnato fatto» e Annulla
- ✅ Chat «sono a pezzi, 30 minuti» → fitness_adapt_today — piano adattato: {'adaptation_id': 'e3b11477-35bd-4cdc-bc1c-79d1ed7ad035', 'name': 'Banco Push 162151', 'trace': ['Energia bassa: Panca piana con manubri -1 serie, -15% di carico.', 'Energia bassa: Rematore inverso -1
- ✅ Adattamento: applica e «ripristina» — serie pianificate: adattata 4 → ripristinata 6
- ✅ Peso, obiettivo «3 volte a settimana», riepilogo — peso + obiettivo Banco 3/settimana · riepilogo: Oggi: Banco Push 162151 · 14 min · Banco 3/settimana: 4/3 questa settimana · PR: Panca piana con man

## Self care (Hygieia)

- ✅ Aggiungi prodotti (detergente con PAO, retinolo, AHA) — 3 prodotti; il primo salvato in 0.1 s con apertura oggi e PAO 12 mesi
- ✅ Routine «Viso sera»: retinolo 3/sett, AHA 1/sett, avviso conflitto — routine con 3 passi; avviso: [{"level": "info", "steps": ["Banco Siero retinolo 162151", "Banco Tonico glicolico 162151"], "text": "Retinoidi e AHA nello stesso giorno irritano: alternali. 
- ✅ Dopo la sera col retinolo l'AHA dice «non oggi» — AHA dopo la sera col retinolo: blocked · non oggi: Banco Siero retinolo 162151
- ✅ Modificare la routine crea una versione (+ «come era» nel periodo, annulla) — versioni 2, periodo di oggi: {'date': '2026-10-29', 'routines': [{'id': '5bf372b8f92944e7895fced419e37c59', 'name': 'Banco Viso s; annullata
- ✅ Home: un tocco su prodotto e routine, Annulla, statistiche — «Banco Detergente schiumoso 162151 usato» + Annulla; stats chiavi ['days', 'heatmap', 'products_by_status', 'routines', 'spend', 'top_products']
- ✅ Chat «cosa uso stasera?» / «ho finito il detergente» → strumenti → UI — stasera: {'date': '2026-10-29', 'routines': [{'name': 'Banco Crema mani 155822', 'state': 'due', 'h · detergente finito (UI: finished), lista spesa: True
- ✅ Promemoria (interruttore acceso in Themis): un invio al giorno, notifica nella WebUI — 1 promemoria inviato, il secondo giro dice «sent_today», 1 notifica nell'inbox WebUI
- ✅ Hermes: stesso promemoria per 3 giorni → una notifica «Saltato 2 volte», la vecchia dice «già sostituita» — 1 notifica viva, repeat={"count": 3, "skipped": 2, "since": "2026-10-29T16:21:56.107494+00:00", "text": "Saltato 2 volte · dal 29 ott"}; bottone sulla vecchia → 409
- ✅ Hermes: «Fatto» chiude la catena e registra la routine — «Fatto» eseguito dal modulo ({'status': 'done', 'answer': {'action_id': 'done', 'label': 'Fatto', 'by': 'webu), routine fatta, il promemoria dopo riparte da zero

## Guardaroba (Wardrobe)

- ✅ Aggiungi capi (uno con foto) e vedi la miniatura — 9 capi in pochi secondi, la camicia con foto (miniatura servita dalla WebUI)
- ✅ Filtri e ricerca «giacca pesante scura» (chat → wardrobe_search) — filtri ok · ricerca semantica via chat eseguita; trova il cappotto: False (con il LLM finto gli embedding sono casuali)
- ✅ «Cosa mi metto domani, ufficio, 8 gradi, pioggia» (API e chat) — 3 proposte senza lavanderia né sandali; motivi: ['adatto a 8°', 'va bene con la pioggia', "giusto per l'occasione", 'colori che stanno bene insieme']
- ✅ Outfit per posizione, «Indossato» con un tocco dalla Home — outfit di 5 capi, «Banco Ufficio pioggia 162151 indossato» con un tocco, ultimo uso aggiornato
- ✅ Donare un capo segna i suoi outfit «da rivedere» — outfit segnato «da rivedere» dopo aver donato l'impermeabile
- ✅ Statistiche, valigia per 3 giorni, contesto per l'assistente — stats chiavi ['by_category', 'by_color', 'by_kind', 'by_season', 'by_status', 'by_style'] · valigia con 7 voci · contesto: Guardaroba: 12 capi, 4 scarpe, 0 accessori, 2 outfit · ultimo indossato 29/10 Banco Uffici

## Promemoria e agenda (Chronos)

- ✅ I moduli registrano i loro job nell'agenda dell'assistente — 63 regole; i moduli nuovi hanno registrato hercules.reminder, hygieia.alerts, hygieia.planner, wardrobe.reminder, wardrobe.review
- ✅ «Esegui ora» di hygieia.planner da Chronos → esecuzione ok — «Esegui ora» → {'status': 'ok', 'ok': True, 'detail': "200: {'items': [{'routine_id': 'bfb84f20; esecuzione hygieia.planner ok

## Presenza dell'assistente

- ✅ Chat → stato «Sveglio» (badge WebUI) — 🟢 Sveglio · Limitato · effetti {'work.light': 'defer', 'work.heavy': 'defer', 'llm.claude': 'save', 'notify.level': 'all', 'chat.style': 'brief', 'chat.reply': 'live', 'chat.notice': 'rispondo in modo ridotto finché i modelli principali non tornano'}
- ✅ Non disturbare dalla WebUI: notifiche solo urgenti, poi si spegne — DND → notifiche solo urgenti; spento → Sveglio · Limitato
- ✅ Soglia «idle» cambiata dal pannello vale subito; la chat risveglia — soglia 1 min dal pannello → «In attesa» dopo ~60 s; la chat riporta «Sveglio»; soglia rimessa a 5
- ✅ Strumento «stato» dalla chat (come stai?) — stato → {'base': 'awake', 'base_label': 'Sveglio', 'emoji': '🟢', 'icon': 'sun', 'tone': 'success', 'help': 'Mi stai usando: Forg

## Impostazioni centrali (Themis)

- ✅ Cambia un valore dalla WebUI, storia, Annulla; il modulo lo usa subito — 18 mesi salvato dalla WebUI → nuovo prodotto scade tra 547 g; storia 2 voci; Annulla → 12 → 365 g
- ✅ Un valore fuori dai limiti viene rifiutato — 999 rifiutato (422): {'detail': "Durata dopo l'apertura: massimo 60"}
- ✅ Tutti i moduli dichiarano le loro impostazioni — 25 moduli nel pannello

## Plugin dei moduli nella WebUI

- ✅ Catalogo: tutti i moduli online con pagine, widget e azioni rapide — 26 moduli · 78 pagine · 36 widget · 17 azioni rapide
- ✅ Home: ogni azione rapida con chip ha la sua lista — scout.preferita 0 · hercules.fatto 1 · hygieia.fatta 4 · hygieia.uso 0 · wardrobe.indossato 1 · plutus.spesa 8 · argus.ricontrolla 0 · chronos.riprova 0 · lares.azione 0
- ✅ Un plugin può chiamare solo il proprio modulo — fuori dal proprio prefisso → 403
- ✅ I bundle dei plugin sono serviti — 26 bundle JS serviti
- ✅ Ogni icona usata dai plugin esiste nella WebUI — 55 icone dei plugin tutte disegnate

## MCP esterno (Accessi AI)

- ✅ Accessi AI → nuovo token di sola lettura con la riga `claude mcp add` — token creato; riga: claude mcp add --transport http hestia <indirizzo-di-hestia>/mcp --header "Authorization: Bearer hst_…
- ✅ initialize, tools/list (solo strumenti «external»), forge_tasks — 13 strumenti esterni (system_incidents, system_log, system_performance, system_status, forge_dossier, forge_status…); forge_tasks risponde
- ✅ 401 token sbagliato/revocato, 403 scrittura in sola lettura, 429 oltre il limite — sbagliato 401 · scrittura in sola lettura rifiutata · limite [429, 429, 429, 429, 429] · revocato 401
- ✅ Connettore claude.ai: metadati OAuth 2.1 e registrazione client — metadati OAuth, risorsa protetta e registrazione dinamica ok (client hmc_sXH2…)

## WebUI nel browser (desktop, telefono, temi)

- ✅ Giro delle pagine con i dati del banco — desktop, tema chiaro — 23 pagine senza errori, screenshot desk-light-*.png
- ✅ Giro delle pagine — telefono 360 px, tema scuro — 23 pagine senza errori, screenshot phone-dark-*.png
- ✅ Home sul telefono: un tocco su un chip self care, poi Annulla — tocco sul chip: registri 3→4, Annulla → 3
- ✅ Notifiche: rispondere con un bottone dal browser — bottone «Salta» nella pagina Notifiche → il modulo registra lo skip
- ✅ Chat WebUI: scrivere riporta la presenza a «Sveglio» — da «In attesa» un messaggio nella chat WebUI riporta «Sveglio»; risposta con lo strumento nello screenshot

## Esporta e importa

- ✅ Ogni modulo dice cosa può esportare — aphrodite 0, apollo 0, calliope 3, chronos 0, demeter 6, hera 2, hercules 127, hygieia 18, kairos 1, lares 0, oracle 0, plutus 140, scout 0, themis 4, wardrobe 33
- ✅ Esporta tutto (con le foto), senza segreti — 382 record, 6 file, nessuna chiave o password
- ✅ Anteprima sullo stesso Hestia: niente da cambiare — anteprima Unisci dello stesso file: nessuna modifica
- ✅ Impostazioni: Unisci tiene il valore più recente, Sostituisci rimette quello del file — 15 esportato, 20 qui: Unisci lo lascia, Sostituisci rimette 15 (autore «import»); {'added': 0, 'updated': 1, 'unchanged': 1, 'skipped': 0, 'deleted': 0, 'problems': 0}
- ✅ Punti di ripristino: salva, elenca, rileggi, elimina — salvato, elencato (ne tiene 5), riletto ed eliminato
- ✅ Pagina Impostazioni → Esporta e importa nel browser — Esporta, Importa con anteprima, telefono: screenshot desk-transfer-*.png, phone-dark-transfer.png

## Moduli nuovi: Scadenze, Persone, Alimentazione, Documenti, Aspetto, Immagini, Casa

- ✅ Scadenze: nuova annuale → lista + calendario; «Fatto» la sposta all'anno dopo — creata, in calendario come kairos.d496556e…, «Fatto» → prossima 2027-11-03
- ✅ Persone: compleanno in arrivo, idea regalo, ultimo contatto — persona creata, compleanno nei prossimi 7 giorni, idea regalo e contatto salvati
- ✅ Alimentazione: pasto di oggi e integratore preso — pasto in «Oggi», integratore creato e preso
- ✅ Documenti: PDF, Word ed Excel veri, ricontrollati e scaricabili — pdf 2079 byte · docx 36872 byte · xlsx 5569 byte (controllati dopo la creazione)
- ✅ Aspetto: stile di oggi con palette ed effetto — oggi «Halloween» (effetto pumpkins), 12 stili; perché: Halloween
- ✅ Immagini: stato del motore (ComfyUI) — ComfyUI non configurato (atteso sul banco): le richieste restano in coda
- ✅ Casa: stato di Home Assistant (non collegato sul banco) — Home Assistant: {'configured': False, 'connected': False}
- ✅ Chat: l'assistente usa gli strumenti dei moduli nuovi — chat → scadenze_list (stesso strumento che usa Telegram) ok

## WebUI nuova: Adesso, Scopri, conversazioni ed etichette, notifiche push

- ✅ Tap della WebUI → Adesso e Scopri — tap registrati; Adesso 1 proposte, Scopri 20 idee
- ✅ Conversazioni: etichetta dalla chat, fissa, titolo, riapri — etichetta «banco» dalla chat, fissata in cima, 4 messaggi riaperti; riga «Ho fatto» con Annulla
- ✅ Notifiche push: chiave del browser — push non configurato (200)
- ✅ Pagine nuove nel browser (Scopri, Sistema, moduli nuovi) — 11 pagine aperte senza errori (screenshot nuovo_*.png)
