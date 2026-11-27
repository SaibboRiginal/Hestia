# SPEC — Scout ready for a real house hunt (review)

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (project thread «Rendere Scout pronto per cercare casa», 2026-11-27) |
| **Status** | Done (bug fixes); design proposals waiting for Marko |

## 1. Today (verified in code, main b5c01e2)
Whole module read: mail push (Iris) → pre-parse → dedup → status scan / LLM extraction (Oracle) → enrichment
(Atlas + site handlers, Nominatim) → Archive → `entity.upserted` → Hermes; search tool, stats, plugin API,
export, settings. Bugs found, each one breaking the house hunt:

| # | Bug | Effect |
|---|---|---|
| 1 | Only Idealista links survived the email cleaning | Immobiliare alerts: zero houses |
| 2 | Every email marked read even when the model did not answer | Listings of those emails lost for good |
| 3 | Reconcile cleanup required coordinates | Houses the map service could not place deleted at every cycle (favourites too) |
| 4 | Page «sold» check on raw HTML with bare «venduto/venduta» | Live houses marked sold and hidden |
| 5 | Email status scan on the whole alert, bare «trattativa», «trattativa riservata», «affittato», «investimento immobiliare» | One description changed the status of every known house of the email |
| 6 | Status updater read `GET /api/entities/{id}` (no such route) | One useless call per known house |
| 7 | Page recheck stamped only when the page changed | Every listing page reopened at every cycle |
| 8 | `HousePayload` dropped `pending_steps` | A page not read the first time never retried |
| 9 | «€ 250.000» parsed as 250 | Wrong prices, filters, statistics |
| 10 | Search tool: `filters/filters_gt/filters_lt` ignored by the request model | Chat search never filtered (city, price, rooms) |
| 11 | Archive bounds strict | «at least 3 rooms» dropped the 3-room flats |
| 12 | City only ranked, discarded houses returned | Other cities and discarded houses in the answer |
| 13 | Event payload without `city`/`rooms`/`surface_m2` at top level | Alerts «houses in <city>» never matched |
| 14 | `scout_stats` counted ≤ 100 listings, raw/untranslated state names; plugin status labels not translated; «1 locale» hard-coded; tool summaries English in Italian and naming modules | Wrong numbers, mixed languages |
| 15 | Broken extraction answer written to `debug_broken_batch_<n>.txt` in the working folder (= the repo on the PC) | Stray files in the repo |

## 2. Goal
Marko can really look for a house: every alert email becomes houses, none is lost or wrongly hidden, the chat
search filters, the alerts match.

## 3. Scope and design
Bug fixes only, no new feature, no new setting. Details in `Hestia-Scout/hestia-scout.md` § «House-hunt review».
Design proposals (not done, waiting for Marko's go) are listed in the thread, not here.

## 4. New feature checklist
Not a new feature (fixes). Texts: English in code, Italian in `locales/it/*.json`; no module names in tool
summaries; words lists in `words.json`.

## 5. Acceptance criteria
- An Immobiliare alert gives its houses; an Idealista one as before.
- Oracle down → the emails stay unread and are processed at the next cycle.
- No house deleted for missing coordinates; no live house marked sold by a menu word.
- `scout.search` with city/price/rooms filters; bounds inclusive; discarded houses out.
- A subscription `{city, max_price}` matches a new house of that city.
- Regression tests in `Hestia-Scout/tests/test_house_hunt_review.py` (run by CI).
