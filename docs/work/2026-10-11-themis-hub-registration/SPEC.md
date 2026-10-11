# Themis non registrato sul Hub (503 sulle impostazioni)

| Version | Source | Status |
|---|---|---|
| 1.0 | user via external chat (WebUI: 503 su `/api/webui/central-settings/items?module=oracle`) | done |

## Goal
Le impostazioni della chat (menu ⚙) e Impostazioni → Sistema devono caricarsi.

## Cause
Themis si registra con `SERVICE_TAGS=core,settings` e `layer:core,domain:settings`. Il Hub accetta solo il suo
vocabolario (`Hestia-Hub/src/modules/schemas.py`): `settings` non c'era (tag e `domain:`), `layer:core` non esiste.
Registrazione 422 ogni 60 s → Themis assente dal registry → `/route/themis/...` = 503 → WebUI 503.
Anche Metis (`improvement`) era respinto per lo stesso motivo.

## Scope / decisions
- Hub: `settings`, `improvement` in `ALLOWED_TAGS`; `settings` in `domain:` (come già fatto per `system`, `improvement`).
- Themis: `layer:foundation` (compose + default in `main.py`; il compose RPi usa il default).
- Regressione: `Hestia-Hub/tests/test_compose_registration_tags.py` valida i tag di ogni servizio dei compose.

## Acceptance
- Log Themis: `event=registered_on_hub` invece di `hub_registration_non_success status=422`.
- Entro ~60 s i moduli ri-registrano le impostazioni (retry di `settings_client`), il menu ⚙ mostra le voci Oracle.
