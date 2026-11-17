# Hestia-Lares 💡

**Role:** The house on Home Assistant («Home») — lights, switches, covers, climate, sensors, scenes, quick actions,
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
- **Presence**: the person entity chosen in Themis `lares.person` (options read live from HA) → presence signal
  `home.present` (true when `home`). Hecate's state «Outside home» reads it next to `phone.home`.
- Quick actions (favourites: device, label, room, command) in Archive `home-store`; export/import section `favorites`.

## API (`/api/home`)

`GET /status` · `GET /entities?domain=&q=` · `POST /entities/{entity_id}/{command}` `{value?}` · `GET/POST /favorites`
· `POST /favorites/{id}/run` · `DELETE /favorites/{id}` · `GET /persons/options` (Themis options source). For the WebUI page:
`GET /quick` (quick action chips).

## Tools (Telegram area «Home»)

`home_status`, `home_devices`, `home_command` (undo = the opposite command), `home_scene`, `home_favorite`,
`home_favorite_run`, `home_favorite_delete`.

## WebUI plugin

Page **Casa** (`lares-home`: status, quick actions to run or remove, devices by type with their controls, star = save as quick action); widget «Home»; quick action «Home» (chips from `GET /quick`, Home strip and Ctrl+K) runs `POST /favorites/{id}/run`. Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Lares/tests/test_lares.py` (fake Home Assistant, no network).

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-revisione-e-test-frontend`)**: The Casa widget no longer repeats «Home» under the frame title and calls `markEmpty()` when there is nothing to show.


**2026-11-14 (backend English, dossier `docs/work/2026-11-14-backend-inglese`)**: tool descriptions and the module manual are English (for the model). What people read about the tools comes from `hestia_common/locales/<lang>/tools.json`.

**2026-11-15 (owner's language, dossier `docs/work/2026-11-14-backend-inglese`)**: the notices, errors and cards this module shows go through `hestia_common.i18n.t` and follow «Language».

**2026-11-15 (WebUI page in the owner's language, dossier `docs/work/2026-11-14-backend-inglese`)**: the texts of this module's WebUI page and widgets go through `tr` of `@hestia/webui-sdk` and follow «Language»; source texts in English, Italian in `Hestia-Shared/hestia_common/locales/it/messages.json`.

**2026-11-16 (no Italian in the code, dossier `docs/work/2026-11-14-backend-inglese` v2.0)**: every text is English in the code; Italian lives only in `Hestia-Shared/hestia_common/locales/it/messages.json`. Labels declared at registration (manifest, capabilities, agenda rules, settings) are plain English, translated at the edge.
