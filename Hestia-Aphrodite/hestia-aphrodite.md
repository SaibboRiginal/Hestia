# Hestia-Aphrodite 🌸

**Role:** How the clients look («Look») — themes of holidays, seasons and special days, light effects, a pet
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `hestia_common.module_kit`
**Port:** 19023 · Dossier: `docs/work/2026-10-24-whole-cindy-brainstorm/` (W5, brainstorm A2)

---

## Responsibility

- **Profiles**: built-in (standard, birthday, special day, new year, christmas, valentines, easter,
  halloween, the four seasons) plus the owner's own dated ones (`when: {from: MM-GG, to: MM-GG}`). A profile is an
  accent palette over the client's light/dark theme, an effect (`snow, leaves, petals, sun, hearts, confetti,
  pumpkins, stars`) and an optional background picture.
- **Which one is on** is decided here: today's special moment of the owner (pushed by the calendar,
  `special_moment_endpoint` = `/api/appearance/moment`; other people's dates do not decorate) > dated profiles >
  holidays (Easter computed) > season.
- **Per client** (`choice`, e.g. `webui`): `auto` off = the standard look (the owner's only switch), and the chosen
  pet. Clients only call `GET /api/appearance/now?client=`.
- **Mascot** (dossier `docs/work/2026-11-18-real-test-problems` G): three built-in mascots drawn by the clients
  (`builtin:ember` «Little flame», `builtin:cat`, `builtin:owl`; `pet.drawn` = the key, no pictures, cannot be changed
  or deleted) come first in `GET /pets`. A client that never chose gets `builtin:ember`; `pet: "none"` = no mascot;
  a deleted pet falls back to the built-in one. Own pets keep their pictures (generated or uploaded).
- **Pictures** are asked to the image module (`POST /route/apollo/api/images/jobs` with a callback to
  `/api/appearance/images/done`): a profile background, three poses per pet (idle, happy, sleep). An uploaded blob
  wins over a generated one.
- Archive `appearance-store` (`profile`, `pet`, `choice`, `moment`); export/import section `look`.

## API (`/api/appearance`)

`GET /now?client=` · `GET/POST /profiles` · `PUT /profiles/{key}` · `GET/POST /pets` · `PUT/DELETE /pets/{id}` ·
`GET/PUT /choice/{client}` · `GET /upcoming?days=` · `POST /moment` (calendar push) · `POST /images/done` (image push). For the WebUI page:
`GET /image/{blob_id}` (only pictures this module uses) · `POST /pets/{id}/image/{pose} {mime, data_b64}` (owner's picture, wins over a generated one).

## Tools (Telegram area «Images and look»)

`look_now`, `look_choice`, `look_next`, `look_pet`, `look_pets`, `look_generate`.

## WebUI plugin

Page **Aspetto** (place `system`, under Settings › System; `aphrodite-look`: the look now and why, automatic themes on or off for the site, pet choice, new pet, own picture per pose, regenerate, profile editor with colours, effect, dates, picture prompt, upcoming themes). The WebUI shell draws palette, effect and pet from `GET /now`. Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Aphrodite/tests/test_aphrodite.py` and `tests/test_webui_plugin.py` (FakeArchive with a fake image module).


**2026-11-14 (backend English, dossier `docs/work/2026-11-14-english-backend`)**: tool descriptions and the module manual are English (for the model). What people read about the tools comes from `hestia_common/locales/<lang>/tools.json`.

**2026-11-15 (owner's language, dossier `docs/work/2026-11-14-english-backend`)**: the notices, errors and cards this module shows go through `hestia_common.i18n.t` and follow «Language».

**2026-11-15 (WebUI page in the owner's language, dossier `docs/work/2026-11-14-english-backend`)**: the texts of this module's WebUI page and widgets go through `tr` of `@hestia/webui-sdk` and follow «Language»; source texts in English, Italian in `Hestia-Shared/hestia_common/locales/it/messages.json`.

**2026-11-16 (no Italian in the code, dossier `docs/work/2026-11-14-english-backend` v2.0)**: every text is English in the code; Italian lives only in `Hestia-Shared/hestia_common/locales/it/messages.json`. Labels declared at registration (manifest, capabilities, agenda rules, settings) are plain English, translated at the edge.
