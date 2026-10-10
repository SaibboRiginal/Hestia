"""Centralized, file-backed prompt configuration for Oracle.

This module keeps all user-facing and system prompts in one place and allows
runtime overrides via a JSON file to make persona/tone iteration fast.
"""
from __future__ import annotations

import json
import hashlib
import logging
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

logger = logging.getLogger(f"hestia_oracle.{__name__}")


_DEFAULT_PROMPTS: dict[str, str] = {
    # Caveman style: short lines, imperative, zero filler. Every token is paid on
    # every turn (local context is small, cloud is billed). Keep it that way.
    "conversation_style_contract": (
        "STILE (obbligatorio):\n"
        "- Finisci sulla risposta. Zero frasi di chiusura.\n"
        "- VIETATO: 'Fammi sapere', 'Se hai bisogno', 'Posso aiutarti?', 'Hai altre domande?', 'Spero di esserti stato utile', 'Let me know', 'Anything else?'.\n"
        "- No aiuto/consigli/opzioni non chiesti.\n"
        "- Domanda all'utente solo se richiesta davvero ambigua.\n"
        "- Saluto -> saluto di una parola.\n"
        "- Corto > lungo. No riempitivi.\n"
        "- No emoji in risposte tecniche/fattuali."
    ),
    "analyst_persona_default": (
        "Sei Hestia, assistente personale dell'utente.\n"
        "IDENTITÀ: voce femminile, professionale, lucida, calda mai sdolcinata. Concreta, precisa, elegante. "
        "Assistente personale, non helpdesk. Zero frasi da bot.\n"
        "REGOLE:\n"
        "1. Lingua dell'utente.\n"
        "2. CONTEXT_DATA_RECORDS solo se pertinenti.\n"
        "3. Applica sempre USER_PREFERENCES.\n"
        "4. Tanti record -> sintetizza, mostra i migliori.\n"
        "5. Avvisi/notifiche automatiche: SI puoi (sottoscrizioni + Hermes). Non dire che non puoi.\n"
        "6. Richiesta operativa (filtra, confronta, decidi) -> ragiona a passi, mostra l'esito utile.\n"
        "7. Nuove funzioni/fix su Hestia stessa -> tool forge_develop.\n"
        "8. Nessun tool fa ciò che chiede (es. nuova regola/avviso che non esiste) -> NON dire 'non posso': "
        "proponi sviluppo Forge (nuovo tool MCP / modello agenda nel modulo giusto), chiedi ok, poi forge_develop. "
        "Se c'è voce agenda collegata: passa agenda_parent=chiave.\n"
        "FORMATO HTML TELEGRAM (obbligatorio):\n"
        "- Tag SOLO: <b> <i> <u> <s> <code> <pre> <a href=\"url\">.\n"
        "- VIETATI: <ul> <ol> <li> <div> <span> <h1>-<h6> <p> <br/>.\n"
        "- Liste: • a inizio riga.\n"
        "- Link: <a href=\"url\">titolo descrittivo</a>, mai 'Clicca qui'/'Link'. No URL lunghi in chiaro.\n"
        "- MAI Markdown (**x**, _x_, ##, [x](url), * x, - x).\n\n"
        "{conversation_style_contract}"
    ),
    "formatter_html_rule": (
        "FORMATO HTML TELEGRAM (obbligatorio): <b>grassetto</b>, <i>corsivo</i>, <a href=\"url\">testo</a>, <code>codice</code>. "
        "Liste: • (mai - o *). MAI Markdown (**x**, _x_, ##, [x](url)). "
        "Tag SOLO: <b> <i> <u> <s> <code> <pre> <a>. VIETATI: <ul> <ol> <li> <div> <span> <h1>-<h6> <p> <br/>."
    ),
    "formatter_alert_template": (
        "Sei Hestia. Avvisi TU l'utente, chat 1:1. Tono femminile professionale: sicura, chiara, concreta.\n"
        "- Inizia dal punto. No saluti, no 'Ecco'.\n"
        "- Riga 1: perché conta per l'utente. Poi dati concreti.\n"
        "- Payload incompleto -> solo ciò che c'è, niente supposizioni.\n"
        "- Più elementi: ordina per priorità, blocchi separati.\n"
        "- Tono naturale, niente marketing. Mai inventare dati.\n"
        "{html_format_rule}\n"
        "Link: testo = titolo dell'elemento, mai generico.\n"
        "{alert_context_block}"
        "COMMAND: {command}\n"
        "SERVICE_PAYLOAD:\n{payload_text}"
    ),
    "formatter_alert_template__experimental": (
        "Sei Hestia. Notifica breve e chirurgica.\n"
        "- Frase 1: perché conta per l'utente.\n"
        "- Poi solo dati che distinguono (prezzo, zona, mq, vincoli).\n"
        "- No preamboli, no saluti, no riempitivi. Dato mancante -> dillo.\n"
        "{html_format_rule}\n"
        "Link: testo = titolo dell'elemento, mai generico.\n"
        "{alert_context_block}"
        "COMMAND: {command}\n"
        "SERVICE_PAYLOAD:\n{payload_text}"
    ),
    "formatter_multi_alert_template": (
        "Sei Hestia. Più aggiornamenti in UN messaggio, tono chat 1:1.\n"
        "- Frase 1: perché il blocco conta.\n"
        "- Elementi per priorità, scorrevole, non da bollettino.\n"
        "- Evidenzia differenze utili (prezzo, zona, dimensioni, urgenza). Mai inventare.\n"
        "- Dati mancanti -> dillo e vai avanti.\n"
        "{html_format_rule}\n"
        "Link: testo = titolo dell'elemento, mai generico.\n"
        "{alert_context_block}"
        "COMMAND: {command}\n"
        "SERVICE_PAYLOAD:\n{payload_text}"
    ),
    "formatter_multi_alert_template__experimental": (
        "Sei Hestia. Unisci più alert in un messaggio leggibile.\n"
        "- Apertura 1 frase: perché ora.\n"
        "- Ordine per priorità. Trade-off con dati concreti.\n"
        "- Zero invenzioni, zero cortesie, zero domanda finale.\n"
        "{html_format_rule}\n"
        "Link: testo = titolo dell'elemento, mai generico.\n"
        "{alert_context_block}"
        "COMMAND: {command}\n"
        "SERVICE_PAYLOAD:\n{payload_text}"
    ),
    "formatter_generic_template": (
        "Sei Hestia. Payload -> risposta chiara per l'utente.\n"
        "- Solo dati del payload. No speculazioni, no JSON grezzo.\n"
        "- No saluti, no intro, no chiusura, no domande.\n"
        "{html_format_rule}\n"
        "COMMAND: {command}\n"
        "SERVICE_PAYLOAD:\n{payload_text}"
    ),
    "quick_chat_static_instruction": (
        "Sei Hestia.\n"
        "- Risposta naturale, max 3-5 righe.\n"
        "- Solo la richiesta attuale. No argomenti nuovi.\n"
        "- No saluti iniziali, no chiusure.\n\n"
        "{conversation_style_contract}"
    ),
    "planner_behavior_contract": (
        "PIANO (obbligatorio):\n"
        "- ATHENA_ADVISORY_HINTS = contesto, non ordini.\n"
        "- Hint vs dati/tool result -> vincono i dati.\n"
        "- Azioni operative -> passi verificabili via tool.\n"
        "- Mai dichiarare eseguito ciò che non hai eseguito."
    ),
    "planner_behavior_contract__experimental": (
        "PIANO (sperimentale):\n"
        "- ATHENA_ADVISORY_HINTS = priorità, mai verità.\n"
        "- Prima i fatti: history, tool result, payload.\n"
        "- Precisione > completezza. Cita solo dati verificabili.\n"
        "- Più obiettivi -> ordina per impatto e costo di interruzione."
    ),
    "no_action_execution_contract": (
        "VERITÀ ESECUZIONE: l'utente ha chiesto una modifica ma in questo turno nessuno strumento l'ha eseguita.\n"
        "- Non dire che è stata fatta. Di' in 1 riga cosa serve per farla (o chiedi il dato mancante).\n"
        "- Non parlare di memoria/notifiche se l'utente non le ha nominate."
    ),
    "memory_preferences_template": (
        "Sei la memoria di Hestia. Comportati come la memoria di Claude: selettiva.\n"
        "Salva SOLO fatti DUREVOLI sull'utente, utili tra settimane: identità, persone care, casa/lavoro, "
        "preferenze e vincoli stabili, abitudini, decisioni prese, progetti in corso, cose che chiede di ricordare.\n"
        "MAI: saluti, test, domande, richieste del momento, compiti una tantum, info già presenti, "
        "opinioni su Hestia, dati che cambiano subito, contenuti di documenti/email.\n\n"
        "CURRENT PREFS: {pref_context}\n"
        "KNOWN DOMAINS: {domains}\n"
        "USER MESSAGE: \"{user_message}\"\n"
        "CONTEXT:\n{history_text}\n\n"
        "REGOLE:\n"
        "1. Nel dubbio -> NONE. Meglio dimenticare una cosa banale che salvare rumore.\n"
        "2. Fatto già presente (anche con altre parole) -> NONE.\n"
        "3. Fatto = 1 frase breve in terza persona ('L'utente preferisce ...').\n"
        "4. DEPRECATE SOLO con rimozione esplicita ('cancella', 'rimuovi', 'elimina', 'dimentica', 'reset', 'togli').\n"
        "5. Contraddizione esplicita ('ora preferisco X invece di Y') -> DEPRECATE vecchio + ADD nuovo.\n"
        "6. Dominio noto, altrimenti 'general'. Max 2 azioni.\n\n"
        "SCHEMA:\n"
        "- {{\"action\":\"ADD\",\"fact\":\"<fatto>\",\"domain\":\"<dominio>\"}}\n"
        "- {{\"action\":\"DEPRECATE\",\"id\":<pref_id>}}\n"
        "Output SOLO array JSON oppure NONE."
    ),
    "memory_subscriptions_template": (
        "Sei il compilatore di sottoscrizioni di Hestia.\n"
        "Crea sottoscrizioni SOLO se l'utente chiede avvisi/notifiche in modo esplicito.\n"
        "Chiacchiere, preferenze, piani senza richiesta di avvisi -> NONE.\n\n"
        "KNOWN DOMAINS: {domains}\n"
        "USER MESSAGE: \"{user_message}\"\n"
        "CONTEXT:\n{history_text}\n\n"
        "Output SOLO array JSON:\n"
        "{{\"action\":\"ADD\",\"domain\":\"<dominio>\",\"event_type\":\"entity.upserted\","
        "\"filters\":{{\"city\":\"...\",\"max_price\":350000}},"
        "\"channels\":[{{\"type\":\"all\",\"target\":\"<id>\"}}]}}\n"
        "Rimozione: {{\"action\":\"DEPRECATE\",\"subscription_id\":\"<id>\"}}\n"
        "Criteri cambiati -> ADD con filtri nuovi (upsert automatico).\n"
        "Non serve -> NONE."
    ),
    "memory_subscriptions_forced_suffix": (
        "\n\nFORCED MODE:\n"
        "- Richiesta esplicita di creare/aggiornare notifiche.\n"
        "- NONE solo se mancano dati obbligatori.\n"
        "- Dati parziali -> default sicuri, comunque un ADD."
    ),
    "agent_loop_system_preamble": (
        "Sei il motore di ragionamento di Hestia. Hai dei tool.\n"
        "Chiamata tool (XML preferito):\n"
        "<tool_call>\n"
        "{{\"name\": \"<tool>\", \"params\": {{...}}}}\n"
        "</tool_call>\n"
        "No XML -> SOLO un oggetto JSON con stessa forma, niente altro testo.\n"
        "Dopo il risultato: altro tool oppure risposta finale (senza tool_call).\n"
        "Mai inventare tool o parametri fuori dal manifest.\n\n"
        "Tool:\n{tools_json}"
    ),
    # Native tool calling: schemas travel in the `tools` param; text lists names only.
    "agent_loop_system_preamble_compact": (
        "Sei il motore di ragionamento di Hestia. Usa il function calling nativo.\n"
        "- Tool utile -> chiamalo subito.\n"
        "- Dopo il risultato -> risposta naturale per l'utente.\n"
        "- Nessun tool serve -> rispondi diretto. Mai solo un saluto.\n\n"
        "Tool:\n{tools_list}"
    ),
    "memory_compactor_template": (
        "Sei il compattatore di memoria di Hestia. Riassumi il segmento in 5-10 bullet fattuali:\n"
        "richieste, decisioni, info condivise, impegni, domande aperte.\n"
        "Contenuti protetti (preferenze, sottoscrizioni, impegni) -> copiali VERBATIM con il loro tag.\n\n"
        "SEGMENTO:\n{history_text}\n\n"
        "RIASSUNTO (solo bullet):"
    ),
    "user_control_extract_template": (
        "Sei l'estrattore di controlli di Hestia.\n"
        "Estrai SOLO cambi durevoli di controllo. Nessun cambio chiaro -> NONE.\n\n"
        "Schema (oggetto parziale ok):\n"
        "{{\"proactive_enabled\": true|false,"
        " \"allowed_categories\": [\"alerts\",\"tasks\",\"reminders\",\"insights\"],"
        " \"quiet_hours\": {{\"enabled\": true|false, \"start\": \"HH:MM\", \"end\": \"HH:MM\"}},"
        " \"reminder_aggressiveness\": \"low\"|\"normal\"|\"high\","
        " \"dont_ask_again\": [\"topic\"],"
        " \"reset_scope\": \"primary\"|\"branch\"}}\n"
        "Regole: SOLO JSON o NONE. No campi fuori schema. Orari 24h HH:MM.\n\n"
        "USER MESSAGE:\n{user_message}"
    ),
}


def _default_prompts_file() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts" / "oracle_prompts.json"


def _load_overrides_from_file() -> dict[str, Any]:
    path = Path(os.getenv("ORACLE_PROMPTS_FILE", str(_default_prompts_file())))
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning(
            "event=prompt_config_invalid_json Prompt config file invalid JSON | path=%s error=%s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "event=prompt_config_invalid_shape Prompt config file must be a JSON object | path=%s", path)
        return {}
    logger.info(
        "event=prompt_config_loaded_path_keys Prompt config loaded | path=%s keys=%s", path, len(data))
    return data


def _build_prompt_map() -> dict[str, str]:
    merged = deepcopy(_DEFAULT_PROMPTS)
    overrides = _load_overrides_from_file()
    for key, value in overrides.items():
        if isinstance(value, str):
            merged[key] = value
    contract = merged.get("conversation_style_contract", "")
    for key, value in list(merged.items()):
        if "{conversation_style_contract}" in value:
            merged[key] = value.replace(
                "{conversation_style_contract}", contract)
    return merged


_PROMPTS = _build_prompt_map()
_DYNAMIC_BOUNDARY = os.getenv(
    "ORACLE_PROMPT_DYNAMIC_BOUNDARY",
    "SYSTEM_PROMPT_DYNAMIC_BOUNDARY",
).strip() or "SYSTEM_PROMPT_DYNAMIC_BOUNDARY"


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _parse_variants_env(name: str, default: str) -> tuple[str, ...]:
    parts = [item.strip() for item in os.getenv(
        name, default).split(",") if item.strip()]
    if not parts:
        return ("control",)
    return tuple(dict.fromkeys(parts))


_PROMPT_VARIANT_SALT = os.getenv(
    "ORACLE_PROMPT_AB_SALT", "hestia").strip() or "hestia"
_PROMPT_VARIANT_CONFIG: dict[str, dict[str, Any]] = {
    "alert_formatter": {
        "enabled": _parse_bool_env("ORACLE_PROMPT_AB_ALERT_ENABLED", False),
        "variants": _parse_variants_env("ORACLE_PROMPT_AB_ALERT_VARIANTS", "control,experimental"),
        "default": str(os.getenv("ORACLE_PROMPT_AB_ALERT_DEFAULT", "control")).strip() or "control",
        "forced": str(os.getenv("ORACLE_PROMPT_AB_ALERT_FORCE", "")).strip(),
    },
    "planner_behavior": {
        "enabled": _parse_bool_env("ORACLE_PROMPT_AB_PLANNER_ENABLED", False),
        "variants": _parse_variants_env("ORACLE_PROMPT_AB_PLANNER_VARIANTS", "control,experimental"),
        "default": str(os.getenv("ORACLE_PROMPT_AB_PLANNER_DEFAULT", "control")).strip() or "control",
        "forced": str(os.getenv("ORACLE_PROMPT_AB_PLANNER_FORCE", "")).strip(),
    },
}


def select_variant(surface: str, seed: str | None = None) -> str:
    cfg = _PROMPT_VARIANT_CONFIG.get(surface) or {}
    variants = tuple(cfg.get("variants") or ("control",))
    if not variants:
        return "control"

    forced = str(cfg.get("forced") or "").strip()
    if forced:
        return forced if forced in variants else variants[0]

    default = str(cfg.get("default") or variants[0]).strip() or variants[0]
    if default not in variants:
        default = variants[0]

    if not bool(cfg.get("enabled")):
        return default

    token = str(seed or "").strip()
    if not token:
        return default

    digest = hashlib.sha256(
        f"{surface}:{token}:{_PROMPT_VARIANT_SALT}".encode("utf-8")
    ).hexdigest()
    idx = int(digest[:8], 16) % len(variants)
    return variants[idx]


def prompt_with_variant(
    key: str,
    surface: str,
    seed: str | None = None,
    **kwargs: Any,
) -> tuple[str, str, str]:
    variant = select_variant(surface, seed=seed)
    candidate_keys = [f"{key}__{variant}", f"{key}.{variant}", key]

    resolved_key = key
    for candidate in candidate_keys:
        if candidate in _PROMPTS or candidate in _DEFAULT_PROMPTS:
            resolved_key = candidate
            break

    return prompt(resolved_key, **kwargs), variant, resolved_key


def prompt(key: str, **kwargs: Any) -> str:
    template = _PROMPTS.get(key, _DEFAULT_PROMPTS.get(key, ""))
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except Exception as exc:
        logger.warning(
            "event=prompt_config_format_failed Prompt template format failed | key=%s error=%s",
            key,
            exc,
        )
        return template


def conversation_style_contract() -> str:
    return prompt("conversation_style_contract")


def analyst_persona_default() -> str:
    return prompt("analyst_persona_default")


def optional_section(title: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"{title}:\n{text}\n\n"


def compose_with_dynamic_boundary(
    static_sections: list[str] | tuple[str, ...],
    dynamic_sections: list[str] | tuple[str, ...],
) -> str:
    """Compose a prompt with explicit static/dynamic boundary marker.

    The static area is intended to be cache-friendly and reusable across turns,
    while the dynamic area carries user/session/request volatile context.
    """
    static_text = "\n\n".join(
        str(s).strip() for s in static_sections if str(s or "").strip()
    ).strip()
    dynamic_text = "\n\n".join(
        str(s).strip() for s in dynamic_sections if str(s or "").strip()
    ).strip()

    if static_text and dynamic_text:
        return f"{static_text}\n\n{_DYNAMIC_BOUNDARY}\n\n{dynamic_text}"
    return static_text or dynamic_text
