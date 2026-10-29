# Hestia-Lares 💡

**Role:** The house on Home Assistant («Casa») — lights, switches, covers, climate, sensors, scenes, quick actions,
who is at home
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `websockets` · `hestia_common.module_kit`
**Port:** 19024 · Dossier: `docs/work/2026-10-24-tutto-brainstorm-cindy/` (W5, brainstorm A3)

---

## Responsibility

- The only module that talks to Home Assistant. Env (infrastructure/secret): `LARES_HA_URL`, `LARES_HA_TOKEN`
  (long-lived access token). Empty → «la casa non è collegata», nothing else breaks.
- **Push, not poll**: a websocket to `/api/websocket` (auth, `subscribe_events state_changed`) keeps an in-memory
  mirror of the entities of the domains `light, switch, cover, climate, fan, media_player, lock, scene, script,
  sensor, binary_sensor, person`; one full `GET /api/states` on every (re)connect; reconnect with backoff 5 s → 5 min
  (`[🔄] event=lares_ws_lost`).
- Commands = HA services (`turn_on/off/toggle`, `open/close_cover`, `lock/unlock`, `set_temperature`, brightness in %).
  Devices are found by entity id or by name (exact, then partial; ambiguous → the list of matches).
- **Presence**: the person entity chosen in Themis `lares.persona` (options read live from HA) → presence signal
  `home.present` (true when `home`). Hecate's state «Fuori casa» reads it next to `phone.home`.
- Quick actions (favourites: device, label, room, command) in Archive `home-store`; export/import section `preferiti`.

## API (`/api/home`)

`GET /status` · `GET /entities?domain=&q=` · `POST /entities/{entity_id}/{command}` `{value?}` · `GET/POST /favorites`
· `POST /favorites/{id}/run` · `DELETE /favorites/{id}` · `GET /persons/options` (Themis options source). For the WebUI page:
`GET /quick` (quick action chips).

## Tools (Telegram area «Casa»)

`casa_stato`, `casa_dispositivi`, `casa_comando` (undo = the opposite command), `casa_scena`, `casa_preferito`,
`casa_preferito_esegui`, `casa_preferito_elimina`.

## WebUI plugin

Page **Casa** (`lares-home`: status, quick actions to run or remove, devices by type with their controls, star = save as quick action); widget «Casa»; quick action «Casa» (chips from `GET /quick`, Home strip and Ctrl+K) runs `POST /favorites/{id}/run`. Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Lares/tests/test_lares.py` (fake Home Assistant, no network).

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-revisione-e-test-frontend`)**: The Casa widget no longer repeats «Casa» under the frame title and calls `markEmpty()` when there is nothing to show.
