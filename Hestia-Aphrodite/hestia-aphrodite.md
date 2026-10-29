# Hestia-Aphrodite 🌸

**Role:** How the clients look («Aspetto») — themes of holidays, seasons and special days, light effects, a pet
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · `hestia_common.module_kit`
**Port:** 19023 · Dossier: `docs/work/2026-10-24-tutto-brainstorm-cindy/` (W5, brainstorm A2)

---

## Responsibility

- **Profiles**: built-in (standard, compleanno, giornata speciale, capodanno, natale, san valentino, pasqua,
  halloween, the four seasons) plus the owner's own dated ones (`when: {from: MM-GG, to: MM-GG}`). A profile is an
  accent palette over the client's light/dark theme, an effect (`snow, leaves, petals, sun, hearts, confetti,
  pumpkins, stars`) and an optional background picture.
- **Which one is on** is decided here: today's special moment of the owner (pushed by the calendar,
  `special_moment_endpoint` = `/api/appearance/moment`; other people's dates do not decorate) > dated profiles >
  holidays (Easter computed) > season.
- **Per client** (`choice`, e.g. `webui`): `auto` off = the standard look (the owner's only switch), and the chosen
  pet. Clients only call `GET /api/appearance/now?client=`.
- **Pictures** are asked to the image module (`POST /route/apollo/api/images/jobs` with a callback to
  `/api/appearance/images/done`): a profile background, three poses per pet (idle, happy, sleep). An uploaded blob
  wins over a generated one.
- Archive `appearance-store` (`profile`, `pet`, `choice`, `moment`); export/import section `aspetto`.

## API (`/api/appearance`)

`GET /now?client=` · `GET/POST /profiles` · `PUT /profiles/{key}` · `GET/POST /pets` · `PUT/DELETE /pets/{id}` ·
`GET/PUT /choice/{client}` · `GET /upcoming?days=` · `POST /moment` (calendar push) · `POST /images/done` (image push).

## Tools (Telegram area «Immagini e aspetto»)

`aspetto_adesso`, `aspetto_scelta`, `aspetto_prossimi`, `aspetto_animale`, `aspetto_animali`, `aspetto_genera`.
The WebUI draws the effect and the pet in wave 7.

## Tests

`Hestia-Aphrodite/tests/test_aphrodite.py` (FakeArchive with a fake image module).
