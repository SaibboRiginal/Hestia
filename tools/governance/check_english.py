#!/usr/bin/env python3
"""No Italian in the code (standard: docs/LANGUAGES.md, Marko 2026-11-19).

What a person never sees is English: identifiers, tool names, page ids and routes, setting keys, stored values,
log lines, comments, prompts. What a person sees is an English source text in ``tr`` with its translation in the
locale catalog, never fixed in one language. Words a parser looks for in the owner's messages live in the locale
files (one file per language), not in the code.

Counts the Italian words of every source file (``.py``, ``.ts``, ``.cs``; tests, locale files and built bundles left
out; the English source text inside ``tr(…)`` is not counted). While the sweep of 2026-11-19 runs, a baseline holds
the count of each file: a file may only go down. At zero for every file the baseline is empty and any Italian word
fails.

    python tools/governance/check_english.py            # fail if a file has more Italian than its baseline
    python tools/governance/check_english.py --show F   # the Italian lines of file F (or of every file: --show all)
    python tools/governance/check_english.py --update   # lock the progress: write the current counts as baseline
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASELINE = Path(__file__).with_name("english_baseline.json")

# Italian words that are not English words (so «agenda», «estate», «note», «come», «media», «piano», «vista» are not
# here). Names of places and brands are not words of the code.
ITALIAN = frozenset("""
abbastanza abbonamenti abbonamento abiti acceso accessi accesso accessori accetta accettato acido acqua acquisto
adattamento adattato addebito addestramento adesso affitto affondi agente agenti agenzia aggiorna aggiornamenti
aggiornamento aggiornati aggiornato aggiungi agosto aiutarti alimentazione alimenti alla alle allenamenti allenamento
allo alta alto altre altri altro alzate amica amichevole amici amico analisi analizza anche ancora andamento andando
andata animale animali animazioni anniversario anno annuale annulla annullare annullata annullato annunci annuncio
anteprima aperta aperte aperto apertura appena applica applicata appoggiato approvata apre apri aprile archiviato
archivio aree armadio arriva arrivata arrivo arrotondati ascensore asciutto ascolta aspettando aspetto assente
assicurazione assistente assistite assistiti attenzione attesa attese atteso attiva attive attività attivo attuali
automatica automatico autorizzato autunno avanti avanzate aver avvia avviata avvisa avvisami avvisi avviso azelaico
azione azioni azzurra azzurro bagni bagnoschiuma balcone balsamo barba barra bassa basso basta bene benissimo
bentornato benzoile bianco bici bilanciere bisogno blocchi bolletta bollette bollo braccia breve brufoli buio buon
buonasera buongiorno caduta caffeina calendario cambia cambiare cambiata cambiato camere camicia camminata cancella
cancello capelli capelluto capi capito capodanno cappotto caratteristiche carica caricabatterie caricamento caricati
caricato carico carta cartella casa caso catalogo categoria categorie catena cavi cavo cena centrale ceramidi cerca
cercare cerco cervello che chiama chiamare chiamata chiamate chiamato chiaro chiave chiavi chiedere chiedi chiesto
chiude chiudi chiusa chiuso ciao cibo ciclo cima città ciò colazione collega collegamento collegato collutorio comandi
comando compatta compatto compleanni compleanno completa completata completato completo concentrazione condominio
conferma conferme configurato configurazione conflitto connettore conosce consapevolezza consegna consegne consenti
conservati consigli consiglio contanti contatore contatti contatto contento contesto conti continua conto contorno
contraddizione contratto controlla controllati controlli controllo conversazione conversazioni coordinate copia corda
corpo correggi correre correzione corsa corso cosa così crea creare creata creati creato credenziali crema crespo
croci cronologia cui cuoio cura dagli dai dall dalla dalle dati davvero decidere decidi declinata degli dei del dell
della delle dello denaro denti dentifricio dentista deodorante descrivi descrizione detergente dettagli dettaglio
dettatura detto deve diario dicembre dichiarano dici dieta difficile dimentica dimenticare dimenticati diretto
disattiva disegnate disponibile disponibili dispositivi disturbare diventa diversi dizionario documentazione documenti
documento domanda domande domani domenica dominio donare donato dopo dopobarba dopodomani doppione dormito dove dura
ecco effetti effetto elastico elenca elenco elimina eliminata eliminati eliminato eliminazione energia entra entrambi
entrata entrate entro erano ero errore errori esecuzione esecuzioni esegui eseguita eseguiti eseguito esercente
esercizi esercizio esfoliante esiste esporta esportare esportato essere estensioni esterna esterni esterno estrae
estratto etichetta etichette eventi evento evita fallita falliti fallito famiglia fammi farlo fatta fatti fatto
febbraio ferma fermato figlia filo filtri filtro finestra finire finisco finito fino fissa fissata fissate fissati
fissato fisso fluoro flussi foresta forfora forma fornitore forza foto fra frase frontali funzione fuori gambe genera
generale generico gennaio giacca ginocchia ginocchio giornaliera giornaliero giornata giorni giorno giovedì gira
girata giri giro giugno giusto già giù gli glicolico glutei gradi grazie grigio guardaroba guida guidato gusti hai
hanno ialuronico icona idee idratazione ieri ignora ignorati immagine immagini immobile impara imparato impegni
impegno impermeabile importa importante importanti importare importazione importo imposta impostazione impostazioni
impronta incarniti inclinata includi indietro indirizzo indossati indossato indosso inglese inizia inserisci insieme
installa installo integratore integratori interazione interessa interna interrompi invece inverno inverso invia
inviato invio irritazione iscriviti ketoconazolo labbra lascia laterale laterali lattico lavanda lavanderia lavora
lavori lavoro leggera leggere leggeri lei lento lette letto lettura libero libreria limitato limite limiti lingua
lista liste livelli locali loro luce lucentezza luglio lui lunedì lungo luoghi luogo macchina macchine maggio maglia
maglione mai manca mancano mancante manda mandami mandelico mangiando mani manubri manubrio mappa marcati marrone
martedì martello marzo maschera mascotte mattina medico medio memoria memorie meno mensile mento mentre mer mercoledì
mese mesi messa messaggi messaggio metti metto mezzanotte mie miei miglioramento minuti mio misura misure mittente
modalità modelli modello modifica modificare modificata modificate modificato modifiche modo moduli modulo molto
mostra motivi motivo motore motori movimenti movimento nascoste nascosti natale naturale necessario nei nel nell nella
nelle nello nessun nessuna nessuno netto niente nome normale normali nota notifica notifiche notizie notte notti
novembre numeri nuoto nuova nuove nuovi nuovo obbligatorio obiettivi obiettivo occasione occhi occhio occorrenza
occupato oceano oggetto oggi ogni olio oltre operazione orari orario ordine orizzontale oscurati oscurato osserva
ottima ottimo ottobre ovunque paese pagamento pagato pagina pagine palestra panca pannello panoramica pantaloni
pantenolo parallele parametri parla parlare parlo parola parzialmente pasqua passa passaporto passi passo pasti pasto
pausa peli pensando pensata pensi pensieri pensiero peptidi perché percorso periodo permesso personale personali
persone pesante peso petto pezzi piace piana pianifica piedi piegamenti pioggia pisolino più pochi poco poi polsi
pomeriggio ponte porta posizione possibile posso posta posteriori posti posto pranzo preciso predefinito preferenze
preferisco preferita preferite preferiti preferito prefisso prenota prepara presa presente presenza preso prestazioni
preventivo prezzi prezzo prima primavera prime primo problemi prodotti prodotto profilo profondo profumo programma
progressi promemoria pronta pronti pronto propone proponi proporre proposta proposte proprio prossima prossime
prossimi prossimo prova provo prurito pulito punti punto può qualche qualcosa qualsiasi quando quasi quella quelle
quello questa questi questo qui racconta raggiungibile raggiungibili raggiunto ragionamento ramo rapida rapide
rasatura reale recente recenti regali regalo regione registra registrano registrare registrata registrati registrato
registrazione registro regola regole rematore resta restano rete retinale retinolo revisione revocato riapri riassunto
riavvia riavvio ricarica ricerca ricetta ricette ricevuta ricevuto richieste ricompro riconosci ricontrolla
ricontrollo ricorda ricordami ricordati ricordi ricorrenti ridotte riepilogo rifai rifiutata rifiutato riflessione
rigenera righe rimette rimosso rimuovi rinnovo riparazioni riparte ripetizione ripetizioni ripetuta riporta riprendi
ripristina ripristinata ripristino riprova riscaldamento riscarica rispettate risponde rispondere rispondi rispondo
risposta risposte ristorante ristoranti risultati risultato ritratto riuscita riuscito rivedi rosa rossori rumeno
sabato sabbia sai saldo salgono salicilico salta saltati saltato salute salva salvare salvarlo salvata salvataggio
salvate salvati salvato sandali sbarra scade scadenza scadenze scaduta scarica scaricato scarta scegliere scelta
scelti scena scheda schede schiena scollega sconosciuto scopri scorciatoie scorsa scritto scrittura scrive scrivere
scriverlo scrivi scrivimi scrollate scuro sdraiato secchezza secondi secondo seduto segna segnale segnali segnare
segnarlo segnata segnati segnato segno segreto segui sembra semplice sempre senti sentita sento senza sera sereno
serie servizi servizio sessione sessioni settembre settimana settimanale settimane sezione sezioni sfondo siero simili
sistema sito slanci slitta smetti soglia sola soldi solito sollevamento sonno sono sopra sostituisci sostituita
sostituito sotto spalle speciali spegne spegni spento spesa spese speso spesso spinta sposta spostare spostato
spostiamo sposto spuntino squadrati sta stabile stacco stagione stai stanco stanotte stare stasera statistiche stato
stessa stessi stesso stile stili stima stipendio sto storia storico strada strategia stretta struccante strumenti
strumento sua sue suggerimenti suggerimento suggeriti suggerito sul sulla sullo suo suoi superficie supina svago
sveglio sviluppa sviluppo tanto tardi tasto telefono tema temi tenere tengo terminale terra terrazzo tese testa testo
tiene tieni tipo tirate titolo tocco togli tolgo tolte tonico torna tornano tornato totale tra tranquilla trascrizione
trasferimenti trasferta trasporti trattamento trattativa trazioni tretinoina tricipiti troppo trovato trovo tua tuo
tutta tutte tutti tutto ufficio uguali ultima ultime ultimi ultimo umore una unghie unisci uno urgenti usa usare
usarlo usata usati uscite usi uso utente utili utilizzo vai valigia valore valuta vecchia vecchio vedi veloce venduto
venerdì vengono vento vera verde veri verifica verificato verifiche vero verrà versione versioni verso vestiti vetro
vettori viaggi viaggio vicino viene visibile viso viste vita vitamina vivaci vive vocabolari vocabolario vocali voce
voci voglia voglio volte voto vuoto zavorrate zavorrati zinco zona
""".split())

SKIP = re.compile(r"(^|/)(node_modules|dist|\.git|locales|tests?|__pycache__|\.angular)(/|$)|(^|/)test_[^/]*\.py$"
                  r"|\.spec\.ts$|\.min\.|check_english\.py$")
_TR = re.compile(r"""\b(?:tr|t)\(\s*(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`)"""
                 r"""|(?:'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")\s*\|\s*tr\b""")
_WORD = re.compile(r"[A-Za-zÀ-ÿ]+")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def italian_words(line: str) -> list[str]:
    line = _TR.sub(" ", line)
    out = []
    for tok in _WORD.findall(_CAMEL.sub(" ", line)):
        w = tok.lower()
        if w in ITALIAN:
            out.append(w)
    return out


def files() -> list[Path]:
    out = []
    for path in ROOT.rglob("*"):
        if path.suffix not in (".py", ".ts", ".cs") or not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if SKIP.search(rel):
            continue
        out.append(path)
    return sorted(out)


def scan() -> dict[str, list[tuple[int, str, list[str]]]]:
    found: dict[str, list[tuple[int, str, list[str]]]] = {}
    for path in files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        hits = [(i, ln.strip(), ws) for i, ln in enumerate(lines, 1) if (ws := italian_words(ln))]
        if hits:
            found[path.relative_to(ROOT).as_posix()] = hits
    return found


def counts(found) -> dict[str, int]:
    return {f: sum(len(ws) for _, _, ws in hits) for f, hits in found.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--show")
    args = ap.parse_args()
    found = scan()
    now = counts(found)
    if args.show:
        for f, hits in sorted(found.items()):
            if args.show in ("all", f):
                for i, ln, ws in hits:
                    print(f"{f}:{i}: [{','.join(ws)}] {ln[:140]}")
        return 0
    if args.update:
        BASELINE.write_text(json.dumps(dict(sorted(now.items())), indent=1) + "\n", encoding="utf-8")
        print(f"check_english: baseline written, {sum(now.values())} Italian words in {len(now)} files")
        return 0
    base = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    worse = {f: n for f, n in now.items() if n > base.get(f, 0)}
    better = {f: n for f, n in base.items() if now.get(f, 0) < n}
    for f in sorted(worse):
        print(f"- {f}: {worse[f]} Italian words (allowed {base.get(f, 0)})")
        for i, ln, ws in found[f]:
            print(f"    {i}: [{','.join(ws)}] {ln[:120]}")
    if worse:
        print("check_english: Italian in the code. Hidden things are English; what a person reads is tr('English') "
              "with its translation in the locale catalog (docs/LANGUAGES.md).")
        return 1
    if better:
        print(f"check_english: {len(better)} files have less Italian than the baseline: lock it with "
              "`python tools/governance/check_english.py --update`")
        return 1
    print(f"check_english: no new Italian ({sum(now.values())} words left in {len(now)} files, going to zero)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
