# SPEC — Weather provider in Hecate (`weather_*` tools), personal places, weather in the agenda, outdoor activities

| | |
|---|---|
| **Version** | 2.0 |
| **Source** | user via external chat → project brainstorm 2026-10-19, item 7 of the final list (`/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md` §0 and §3 «Meteo?»); routed by the project coordinator |
| **Status** | Draft v2.0 after Marko's first answer (2026-10-20), waiting for his ok (§9) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

User's words (summary, Italian original in the brainstorm): «Meteo — provider in Hecate (Open-Meteo, gratis) + tool
`weather_*`; città nelle impostazioni personali Themis; lo usano assistente, Guardaroba, Hercules.» Not a new module:
Hecate owns external providers, so weather is one more provider there.

---

## 1. Today (verified in code, 2026-10-20)

- No weather source anywhere. Oracle tests mention a fake `get_weather` tool only.
- Wardrobe already takes weather as an **input**: `POST /api/wardrobe/suggest` and `/collections/packing` accept
  `temp_c` + `rain`; pieces carry `weather {min_c, max_c, rain_ok}`; the «Cosa mi metto» and «Prepara valigia» forms
  ask the user to type the temperature and tick «pioggia». The tools `wardrobe_suggest` / `wardrobe_packing` take the
  same two arguments (the assistant has to invent them).
- Hercules is gym only («cardio and sports stay on Garmin»): no outdoor workouts, no place, nothing weather depends on.
- Personal settings (`hestia_common.settings_client.PERSONAL`, owner Themis): `themis.personal.week_start`,
  `themis.personal.currency`. No place.
- Hecate registers `module_tool_domains: ["calendar"]` and serves its tools from `/mcp`.
- Cloud bench network: `api.open-meteo.com` and `geocoding-api.open-meteo.com` answer **403** from the Claude cloud
  proxy today (checked 2026-10-20). Tests use recorded responses; the real call needs the two hosts in the allowed
  domains of the cloud environment (or Marko's PC).

## 2. Goal

Ask «che tempo fa?» / «piove domani a Milano?» in any chat and get a real answer; «Cosa mi metto» and «Prepara
valigia» fill temperature and rain by themselves from the forecast (still editable: automatic **and** manual).
One provider, one place that talks to the weather service, every module reads it through the Hub.

## 3. Scope

In:
1. **Hecate weather provider** (`app/providers/weather.py`): Open-Meteo forecast + geocoding, free, no key, no account.
   Metric units, time zone of the place, Italian condition text from the WMO weather code (mapping in Hecate).
2. **Places** (Marko 2026-10-20: «potrei avere più luoghi: casa, lavoro, palestra, tipa…»): new personal setting
   `themis.personal.places` (type `object`, owner Themis, followed by every module with `follow_personal()`):
   `[{id, name, address, kind: home|work|other, lat?, lon?}]`, empty by default. Exactly one `home` = the default
   place for every weather question. Edited in *Impostazioni → Personali → Luoghi* (small editor: name, address, kind;
   «Verifica» calls Hecate geocoding and stores lat/lon so later calls skip geocoding). The assistant can propose a new
   place («la palestra è in via …») through the usual Themis proposal → Marko confirms via Hermes.
   A call's `place` may be a saved place name («palestra»), an address or a city; resolution order: saved name →
   saved address → Open-Meteo geocoding (cached). No home and no place → `status=needs_place` with the hint «aggiungi
   Casa nei tuoi luoghi». Values live in Themis/Archive only, never in tracked files.
3. **Gateway API** (Hub `route/hecate/...`):
   - `GET /api/gateway/weather/now?place=` → `{place:{name, country, lat, lon, timezone}, now:{temp_c, feels_c,
     condition, code, is_day, wind_kmh, humidity}, today:{...day}}`
   - `GET /api/gateway/weather/forecast?place=&date_from=&date_to=` (default today+2, max 16 days, Open-Meteo limit)
     → `{place, days:[{date, min_c, max_c, condition, code, rain_mm, rain_prob, wind_kmh, sunrise, sunset,
     rain_hours:[…]}]}`; with `hourly=true` also the hours.
   - `GET /api/gateway/weather/place?q=` → geocoding candidates (to check a place before saving it).
   - `POST /api/gateway/weather/at` `{items:[{key, place, at|date}]}` → one answer per item (weather at that place and
     hour/day), for the agenda and for activity planning (one call, deduplicated per place inside Hecate).
   - Out of range (past, beyond 16 days) → `status=out_of_range` with the reason; provider down → `status=error`,
     `[🔄] event=weather_fetch_failed`, last cached answer returned with `stale=true` when there is one.
4. **Cache** in Hecate memory per (place, kind): advanced setting `hecate.weather.cache_minutes` (default 30). No
   database, no stored history.
5. **MCP tools** (domain `weather`, Hecate adds it to `module_tool_domains`): `weather_now(place?)`,
   `weather_forecast(place?, date_from?, date_to?)`. Answer phrased by Oracle as usual.
6. **Wardrobe uses it** (via Hub, `hestia_common` helper `weather_client`, no URL): when `temp_c` / `rain` are not
   given, `suggest` takes the day's forecast (max temperature as `temp_c`, rain = rain_prob ≥ 50 % or rain_mm ≥ 1) and
   `packing` takes the trip's days at `place` (average max temp, rain if any day rains). The answer says which
   forecast was used (`weather: {source: "forecast", place, temp_c, rain, condition}`); values typed by the user always
   win. Forecast missing (no city, out of range, provider down) → today's behaviour, nothing breaks. UI: the two forms
   show «Previsione: 18° · pioggia, Milano» pre-filled and still editable, with a toned icon, no emoji.
   The tools `wardrobe_suggest` / `wardrobe_packing` make `temp_c`/`rain` optional («lascia vuoto: uso la previsione»).
7. **Weather in the agenda** (Marko: «averle nel calendario per i giorni della settimana o due»): the Chronos agenda
   page (calendar view) shows, for the next 14 days, a day chip (home: min–max, condition icon) and, on each event
   with a location, the weather at that place and hour (location matched to a saved place first, else geocoded;
   unresolved → nothing). Chronos asks Hecate once per view through `weather/at` (Hub), cached by Hecate; past days
   and days beyond 14 show nothing. Toned icons, no emoji. Google/Outlook events are **not** modified (the weather is
   shown in Hestia, not written into the provider's event).
8. **Outdoor activities in Hercules** (Marko: «ho voglia di correre questa settimana» → se confermo, teniamone
   traccia anche parziale): Hercules gains a light *activity* kind besides gym sessions (corsa, bici, camminata,
   nuoto, altro), never a replacement for Garmin:
   - `fitness_plan_activity(kind, times?, week?, place?, minutes?)`: Hercules reads the forecast for the place
     (default home) and the free time in the calendar (Hecate events) and proposes the best slots of the week (dry,
     daylight, comfortable temperature), with reasons. Nothing is saved until Marko confirms →
     `fitness_confirm_activity` stores the weekly intention (kind, times, chosen slots).
   - `fitness_log_activity(kind, date?, minutes?, km?, note?)`: «ho corso 5 km» marks one done (partial data is fine).
   - Hercules plugin: the week widget shows «Corsa 1/2» next to gym goals; quick action «Ho corso».
   - No polling of the forecast: the morning recap (item 9) carries «oggi buona finestra per correre 18–19» or «pioggia
     nello slot di oggi, meglio giovedì»; nothing else is sent.
9. **Daily recap**: Hecate implements the per-module recap contract of the *Recap giornaliero* thread
   (`GET /api/module/recap?day=&next=`, capability `recap_endpoint`, helper `hestia_common.recap`): one fact
   `{title: "Meteo", icon, next: "<next day>: 12–19°, pioggia dal pomeriggio", note}` for home (plus the place of the
   first located event of that day when it differs); no home or no forecast → no fact. Hercules adds its activity
   line (planned slot and its forecast) through the same contract. Built on that thread's helper; whichever lands first on main,
   the other adapts (coordinated through the coordinator).
10. **Docs**: `hestia-hecate.md`, `hestia-wardrobe.md`, `hestia-hercules.md`, `hestia-chronos.md`, `hestia-themis.md` (personal keys), swagger, AI-GUIDE,
   ARCHITECTURE (provider list), root CHANGELOG, `.env.example` only if a host goes there (it does not: no key).

Out (and why):
- Writing weather into Google/Outlook events (would touch Marko's provider data; Hestia shows it instead).
- Importing runs from Garmin/Strava (activities are logged by hand or by chat for now).
- No weather alerts, no scheduled job, no periodic fetch: weather is read **on demand** when someone asks (push/poll
  rule: no poll at all); the recap asks Hecate through its contract (item 7 above), coaches (item 9) call the tools.
- No other provider for now; `providers/weather.py` keeps one small interface so another one could be added.

## 4. Design decisions

- **Hecate, not a module**: CLAUDE.md, «Hecate owns external providers». Wardrobe never calls Open-Meteo.
- **Places in Themis personal settings**: same pattern as week start/currency (`follow_personal()`), not a Hecate
  setting, because they are about Marko and several modules use them (weather, agenda, Hercules, future coaches).
  Hecate only resolves them to coordinates.
- **Activities in Hercules**: Hercules is the training module; an outdoor activity is training. It stays light
  (intention + done marks), the gym logic is untouched.
- **Agenda weather in Chronos UI**: the agenda page already belongs to Chronos; it reads weather through the Hub,
  Hecate stays the only one talking to Open-Meteo.
- **Rain rule** in Wardrobe, not in Hecate: Hecate returns raw numbers; what «rain» means for clothes is Wardrobe's
  domain (threshold constants in `suggest.py`, not a setting: tunables only if Marko asks).
- **Hub only**: Wardrobe → `POST {HUB}/route/hecate/api/gateway/weather/forecast`, timeout 6 s, failure = no forecast.
- **No key, no env**: Open-Meteo is free for non-commercial use and needs no key; base URLs are code constants.
- Logs: `event=weather_fetched place= kind= cached=`, `[🔄] event=weather_fetch_failed`, `event=weather_place_resolved`.

## 5. Acceptance criteria

1. With a home place in Milano, `GET route/hecate/api/gateway/weather/now` returns the place and current
   conditions in Italian; same call twice within 30 min = one upstream request.
2. `weather_forecast(place="Roma", date_from=tomorrow)` from chat answers with tomorrow's min/max and rain.
3. No home, no place → `needs_place` with the settings hint; `place="palestra"` resolves the saved place, no crash; unknown place → `place_not_found`.
4. Provider unreachable → `status=error` (or cached `stale=true`), logged with `[🔄]`, never a 500.
5. «Cosa mi metto» without typing anything shows the forecast used and ranks with it; typing a temperature overrides it.
6. «Prepara valigia» with place + dates within 16 days fills temperature/rain from that place's forecast.
7. *Impostazioni → Personali → Luoghi*: add Casa/Lavoro/Palestra, «Verifica» shows the resolved place; changing
   Casa moves the next answer.
9. Agenda page: next 14 days show the day chip; an event at «Palestra» shows the weather at its hour.
10. «Ho voglia di correre 2 volte questa settimana» → two proposed slots with reasons; confirmed → widget «Corsa 0/2»;
    «ho corso 5 km» → 1/2; recap line about today's slot.
8. Unit tests (no network, recorded Open-Meteo JSON): Hecate provider + endpoints + tools + place resolution,
   Wardrobe fallback paths, Hercules activities, personal setting declared. CI green.

## 6. Phases

- **P1** Hecate provider, cache, place resolution, endpoints (`now`, `forecast`, `place`, `at`), tools,
  `themis.personal.places` + Luoghi editor, `hestia_common.weather_client`, tests.
- **P2** Wardrobe: forecast fallback in suggest/packing, tool descriptions, UI pre-fill, tests.
- **P3** Agenda: weather chips in the Chronos calendar view.
- **P4** Hercules activities: plan (weather + free time) / confirm / log, widget + quick action, tests.
- **P5** Recap facts (Hecate weather, Hercules activity) on the recap thread's contract.
- **P6** Docs, swagger, root CHANGELOG, cloud bench check (recorded data if the hosts stay blocked), PR, CI green.

## 7. Risks

- Geocoding ambiguity (two «San Giorgio»): first match by population; the place answer shows region/country so the
  user sees which; the settings field can take «Città, Paese».
- Open-Meteo fair-use limits (10 000 calls/day free): the cache keeps us far below.

## 8. Not touched

Oracle (only gains tools through the Hub), Hermes, Chronos backend (no job; only its agenda page reads weather), Archive (no new table: activities go in `hercules-store`).

## 9. Questions for Marko

v1.0 asked about the city (now: several places) and Hercules (now: outdoor activities, Marko's idea). Left:
1. Agenda horizon 14 days (Open-Meteo gives 16, the last days are rough). OK? *(Default: yes.)*
2. Weather only shown in Hestia's agenda, not written into Google Calendar events. OK? *(Default: yes.)*
