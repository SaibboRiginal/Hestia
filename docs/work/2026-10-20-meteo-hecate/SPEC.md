# SPEC — Weather provider in Hecate (`weather_*` tools) used by the assistant and Wardrobe

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat → project brainstorm 2026-10-19, item 7 of the final list (`/mnt/project-files/brainstorm/2026-10-19-idee-e-cloud.md` §0 and §3 «Meteo?»); routed by the project coordinator |
| **Status** | Draft, waiting for Marko's approval (§9) |

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
2. **Place** = new personal setting `themis.personal.city` («Città», text, empty by default) in `PERSONAL`, so every
   module follows the same one and it is edited in *Impostazioni → Personali*. Hecate geocodes it (Open-Meteo
   geocoding, first match, Italian names) and caches the coordinates; an explicit `place` in a call wins (trips, «a
   Roma»). Empty city and no place → `status=needs_place` with a hint «imposta la tua città nelle impostazioni».
   The value lives in Themis/Archive only, never in tracked files.
3. **Gateway API** (Hub `route/hecate/...`):
   - `GET /api/gateway/weather/now?place=` → `{place:{name, country, lat, lon, timezone}, now:{temp_c, feels_c,
     condition, code, is_day, wind_kmh, humidity}, today:{...day}}`
   - `GET /api/gateway/weather/forecast?place=&date_from=&date_to=` (default today+2, max 16 days, Open-Meteo limit)
     → `{place, days:[{date, min_c, max_c, condition, code, rain_mm, rain_prob, wind_kmh, sunrise, sunset,
     rain_hours:[…]}]}`; with `hourly=true` also the hours.
   - `GET /api/gateway/weather/place?q=` → geocoding candidates (to check a city before saving it).
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
7. **Docs**: `hestia-hecate.md`, `hestia-wardrobe.md`, `hestia-themis.md` (personal keys), swagger, AI-GUIDE,
   ARCHITECTURE (provider list), root CHANGELOG, `.env.example` only if a host goes there (it does not: no key).

Out (and why):
- **Hercules**: nothing to use weather for today (gym only). See question §9.2.
- No weather alerts, no scheduled job, no periodic fetch: weather is read **on demand** when someone asks (push/poll
  rule: no poll at all). A morning line with the weather belongs to the *daily recap* thread (brainstorm item 6),
  which will call `weather_forecast`; coaches (item 9) likewise.
- No Home widget / no dedicated plugin page (can come later as a Hecate plugin widget if wanted).
- No other provider for now; `providers/weather.py` keeps one small interface so another one could be added.

## 4. Design decisions

- **Hecate, not a module**: CLAUDE.md, «Hecate owns external providers». Wardrobe never calls Open-Meteo.
- **Personal city in Themis**: same pattern as week start/currency (`follow_personal()`), not a Hecate setting,
  because it is about Marko, not about the gateway.
- **Rain rule** in Wardrobe, not in Hecate: Hecate returns raw numbers; what «rain» means for clothes is Wardrobe's
  domain (threshold constants in `suggest.py`, not a setting: tunables only if Marko asks).
- **Hub only**: Wardrobe → `POST {HUB}/route/hecate/api/gateway/weather/forecast`, timeout 6 s, failure = no forecast.
- **No key, no env**: Open-Meteo is free for non-commercial use and needs no key; base URLs are code constants.
- Logs: `event=weather_fetched place= kind= cached=`, `[🔄] event=weather_fetch_failed`, `event=weather_place_resolved`.

## 5. Acceptance criteria

1. With `themis.personal.city = "Milano"`, `GET route/hecate/api/gateway/weather/now` returns the place and current
   conditions in Italian; same call twice within 30 min = one upstream request.
2. `weather_forecast(place="Roma", date_from=tomorrow)` from chat answers with tomorrow's min/max and rain.
3. Empty city, no place → `needs_place` with the settings hint, no crash; unknown place → `place_not_found`.
4. Provider unreachable → `status=error` (or cached `stale=true`), logged with `[🔄]`, never a 500.
5. «Cosa mi metto» without typing anything shows the forecast used and ranks with it; typing a temperature overrides it.
6. «Prepara valigia» with place + dates within 16 days fills temperature/rain from that place's forecast.
7. *Impostazioni → Personali* shows «Città»; changing it moves the next answer to the new place.
8. Unit tests (no network, recorded Open-Meteo JSON): Hecate provider + endpoints + tools, Wardrobe fallback paths,
   personal setting declared. CI green.

## 6. Phases

- **P1** Hecate provider, cache, endpoints, tools, `themis.personal.city`, `hestia_common.weather_client`, tests.
- **P2** Wardrobe: forecast fallback in suggest/packing, tool descriptions, UI pre-fill, tests.
- **P3** Docs, swagger, root CHANGELOG, cloud bench check (with recorded data if the hosts stay blocked), PR, CI green.

## 7. Risks

- Geocoding ambiguity (two «San Giorgio»): first match by population; the place answer shows region/country so the
  user sees which; the settings field can take «Città, Paese».
- Open-Meteo fair-use limits (10 000 calls/day free): the cache keeps us far below.

## 8. Not touched

Oracle (only gains tools through the Hub), Hermes, Chronos (no job), Archive (no table).

## 9. Questions for Marko

1. **Città**: one personal setting «Città» (text, geocoded by Hecate), plus `place` in each call for trips. OK?
   *(Default if no answer: yes.)*
2. **Hercules**: it is gym only, so nothing changes there now (recommended). Alternative: a «all'aperto» flag on
   templates (e.g. calisthenics in the park) and Hercules warns/proposes another day when rain is forecast for it.
