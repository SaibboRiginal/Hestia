# Pausa manuale dello sviluppo (Forge)

| Version | Source | Status |
|---|---|---|
| 2.0 | user via external chat ("troppi task di sviluppo… un modo manuale per disabilitare o mettere in pausa così non inizia niente in automatico a consumare token"; poi: "chi decide… si ricorda di non creare duplicati entro x gg? si può cambiare per task il motore? mostrami i task che Argus e Athena hanno pensato") | done |

## Goal
Un interruttore manuale che ferma lo sviluppo automatico: finché è attivo nessun task Forge parte da solo
e non si consumano token.

## Scope
- Impostazione Themis `hephaestus.forge.paused` (bool, default `false`, live, `oracle: read`: l'assistente può
  leggerla, mai proporla).
- Forge in pausa:
  - task da moduli (Athena, Argus, riparazioni, ogni `source` fuori da `USER_SOURCES`) → `proposed` silenzioso
    (`held_by_pause`, nessuna notifica), indipendentemente dal modo permessi;
  - task autonomi già in coda (anche dopo un riavvio) → riportati a `proposed`;
  - lo scheduler delle finestre Claude non avvia nulla di autonomo.
- Restano attivi: le richieste dirette dell'utente (WebUI, Telegram, chat), l'**Avvia**/`approve` manuale
  (`manual_start`), il merge/deploy già approvato.
- Ripresa: non riparte niente da solo; i task trattenuti restano proposti finché l'utente li avvia o rifiuta.
- Comandi: WebUI Sviluppo → **Pausa / Riprendi** (+ banner), Impostazioni → Sistema (automatico da Themis),
  tool MCP `forge_pause` (Telegram, solo su richiesta dell'utente), `POST /api/hephaestus/forge/pause`.

## Acceptance criteria
- Pausa attiva: un task di Athena/Argus resta `proposed`, nessuna notifica, coda vuota.
- Pausa attiva: una richiesta da WebUI parte (`queued`).
- Avvia manuale di un task trattenuto lo mette in coda anche in pausa.
- `GET /forge/status` riporta `paused`.

## Design decisions
- Pausa come impostazione Themis (non env, non file di Forge): visibile in Impostazioni, storico/undo di Themis.
- Il cambio da UI/Telegram è un'azione dell'utente → `settings.put(actor="user")`, applicato subito in locale.
- Trattenere invece di rifiutare: niente va perso, ma nessuna notifica per non riempire i client.

## v2.0 — chi decide, duplicati, motore per task, chi ha proposto
- Chi crea: tu, Athena (miglioramenti), Argus (errori ricorrenti), riparazioni fallite. Chi decide se parte:
  Forge con i permessi del gruppo motore + pausa; il merge aspetta te salvo `full_auto`.
- Duplicati: `hephaestus.forge.dedup_days` (7, 0 = spento). Proposta di un modulo con stessi servizi e
  ≥ 60% parole in comune (richiesta + inizio contesto) con un task degli ultimi giorni, anche rifiutato →
  non creata, risposta = task esistente con `duplicate: true`. Prima c'era solo un filtro in memoria
  (Athena per giorno, Argus per firma) che si perdeva al riavvio.
- Motore per task: `approve {engine}` su proposto/programmato; scelta esplicita = parte subito.
  WebUI: selettore accanto ad Avvia; tool MCP `forge_approve` con `engine`.
- Chi ha proposto: WebUI lista con autore + filtro *Dai moduli*, intestazione "proposto da …";
  brief chat `· da <source>`.

### Acceptance (v2.0)
- Seconda proposta simile di Athena entro 7 giorni → nessun nuovo task.
- Stesso testo Argus ma errore diverso → due task.
- Avvia con motore Claude su un task proposto dal locale → `engine_requested=claude`, parte ora.
