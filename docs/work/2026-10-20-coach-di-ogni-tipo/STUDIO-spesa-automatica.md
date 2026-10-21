# Spesa e cibo senza diario: quali dati arrivano da soli

Studio C4 del dossier «Coach di ogni tipo» (SPEC v1.1 §8), 2026-10-21. Solo valutazione, nessun codice.
Domanda di Marko: «finché non riesco ad automatizzare la mia vita stile grande fratello non credo di seguirlo
manualmente». Quindi conta solo ciò che arriva **senza fatica quotidiana**.

## Fonti a confronto

| Fonte | Fatica per Marko | Cosa sappiamo | Qualità | Chi la gestisce |
|---|---|---|---|---|
| Email di ordini online (spesa a domicilio, delivery) | nessuna, arrivano già in Gmail | prodotti, quantità, prezzo, data | alta, testo strutturato | Hecate → Iris push (come PayPal per Spese), un modulo cibo si iscrive ai mittenti |
| Pagamenti con carta già in Spese | nessuna | dove, quanto, quando; **non cosa** | alta per soldi, nulla per cibo | Spese (già fatto): basta una categoria «spesa» |
| Scontrino digitale nelle app fedeltà dei supermercati | bassa (attivarlo una volta) | prodotti e prezzi | alta | dipende dalla catena: se lo scontrino arriva **per email** rientra nel caso 1; se resta solo nell'app non c'è un accesso pulito (niente API pubbliche note, da verificare catena per catena) |
| Foto dello scontrino in chat | una foto per ogni spesa | prodotti (abbreviati), prezzi | media: sigle tipo «MOZZ.FDL 125G» da interpretare | Oracle legge la foto (come gli estratti conto), il modulo salva |

## Cosa ne esce

- **Senza fatica oggi c'è solo «quanto spendo in spesa»**, e lo fa già Spese. È un dato economico, non alimentare.
- Il **cosa** si mangia arriva da solo solo se la spesa passa da ordini online o scontrini via email. Con la spesa
  in negozio serve almeno la foto dello scontrino: un gesto a settimana, non al giorno.
- Anche con gli scontrini sappiamo cosa entra in casa, non cosa e quanto mangi. Per obiettivi di nutrizione
  (calorie, proteine) resta un'approssimazione grossolana.

## Raccomandazione

**Non vale ancora la pena di un modulo alimentazione.** Da riconsiderare quando almeno una di queste è vera:
1. la spesa la fai soprattutto online o il tuo supermercato manda lo scontrino per email (allora un modulo
   «Dispensa» si iscrive a quei mittenti con Iris, zero fatica, e può dire cosa sta finendo);
2. ti va bene una foto dello scontrino a settimana in chat.

Nel frattempo: gli integratori restano in Self care come informazione (decisione D2), e la spesa come soldi resta
in Spese. Se un giorno nasce «Dispensa», diventa un coach come gli altri (un `CoachRouter`, nessun cambio al
piano della settimana).
