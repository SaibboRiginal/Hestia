# Hestia-Metis 🦉
**Role:** Continuous Improvement Organ
**Node:** Main PC (best-effort)
**Stack:** Python · FastAPI · Docker
**Port:** 19014

## Responsibility

Metis is the fifth organ in the Hestia organ model. While the other four organs operate on the system's *current state*, Metis operates on the system's *trajectory* — are we improving over time?

| Organ | Question | Scope |
|---|---|---|
| Argus | Is the system healthy? | Current state → incidents |
| Athena | What should we do? | Current state → advisory hints |
| Oracle | Execute this task | Current state → LLM reasoning |
| Hephaestus | Fix this problem | Current state → remediation |
| **Metis** | **Are we improving?** | **Trajectory → datasets, benchmarks, adapters** |

## Core Features

### Dataset Curation
- Pulls graded feedback records from Archive via Hub routing
- Deduplicates near-identical user messages
- Balances across quality tiers and domains
- Exports as ChatML, Alpaca, or ShareGPT JSONL for LoRA training

### Benchmark Evaluation
- Runs held-out eval comparing candidate model vs baseline
- Scores style adherence, accuracy, and conciseness
- Uses Oracle LLM for judgment (pluggable model)

### Training Orchestration
- Triggers external Unsloth/QLoRA training script
- Tracks job status via job ID (`GET /api/metis/lora/jobs`, persisted in `METIS_DATA_DIR/lora_jobs.json`)
- Dataset exported as JSONL before training kickoff
- **Planned in the assistant agenda**: window `metis.training` (seeded daily 01–06; edit it in the agenda —
  Chronos owns scheduling, so it is neither env nor a Themis setting). `schedule=auto` (default):
  user request → starts now; module request (e.g. Athena) → agenda task `metis.train.<job>` at the next window
  opening, fired via Hub with `schedule=now`. `schedule=window|now` forces it. Move/cancel it from the agenda.

### Usage log, «Adesso», «Scopri» (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, wave 6)
- **Taps**: clients push what the owner starts (`POST /api/metis/usage`, Telegram in the background at every action
  start; the WebUI in wave 7). Rows in Archive `metis-store` (kind `tap`: client, kind tool|page|action, ref, weekday,
  hour). Kept 180 days. Only the owner's own taps; nothing leaves Hestia.
- **Adesso** (`GET /api/metis/adesso?client=`, tool `metis_adesso`): no model at read time. In order: agenda items of
  the next 3 hours whose `params.tool` names a tool; up to 3 habits (score per tool = recency decay of 21 days ×
  same hour ±1 × same weekday / same kind of day) or recent tools; then up to 3 **ideas**. Each item has its reason
  («Di solito il lunedì a quest'ora», «In agenda alle 18:00: …», «Usata di recente», the idea's own words). Only
  tools of the Hub catalog (`GET {HUB}/discovery/catalog?type=tool`, cached 10 min, last one kept if Hub is away)
  that the client can run; delete/cancel tools never appear.
- **Ideas**: agenda jobs `metis.adesso.0700`, `.1230`, `.1800` (seeds: move them in the agenda) call
  `POST /api/metis/adesso/refresh`: Oracle use case `metis.adesso` (chain veloce) picks 3 tools different from the
  habits, better if little used; the answer is validated against the catalog, kept 8 hours per client. Model away →
  `[🔄]` habits only. The same job prunes old taps.
- **Scopri** (`GET /api/metis/scopri?client=`, tool `metis_scopri`): catalog tools used at most twice in 90 days,
  one per module first, with what they do.
- Telegram: the Oggi card shows «Adesso» (reason + one button each) instead of its fixed actions when Metis has
  something; `/adesso` and `/scopri` open the two tools.

## MCP Tools

| Tool | Description |
|---|---|
| `metis_dataset_build` | Build cleaned dataset from graded feedback records |
| `metis_dataset_export` | Export dataset as ChatML/Alpaca/ShareGPT JSONL |
| `metis_dataset_status` | Show dataset statistics |
| `metis_benchmark_run` | Evaluate candidate model vs baseline |
| `metis_loRA_train` | Orchestrate LoRA fine-tuning run |
| `metis_adesso` | «Adesso» card: what fits now, each with why and a button |
| `metis_scopri` | «Scopri» card: features never or rarely used |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health |
| `GET` | `/api/logs` | Filterable log buffer |
| `POST` | `/mcp` | MCP JSON-RPC endpoint (tools/list, tools/call) |
| `POST` | `/api/metis/dataset/build` · `/benchmark/run` · `/lora/train` | REST mirrors of the MCP tools (auto-mounted by `mount_missing_rest_routes`; were 404 via Hub/Telegram) |
| `GET` | `/api/metis/dataset/export` · `/dataset/status` | idem |
| `POST` | `/api/metis/usage` | Taps `{taps:[{client, kind, ref, label?, at?}]}` (422 if none valid) |
| `GET` | `/api/metis/usage/stats` | Taps by client, top tools |
| `GET` | `/api/metis/adesso` · `/api/metis/scopri` | Adesso and Scopri lists (`client`, `limit`) |
| `POST` | `/api/metis/adesso/refresh` | Agenda job: new ideas + prune |
| `GET` | `/api/metis/tools/adesso` · `/tools/scopri` | The two tools (display cards) |
| `GET` | `/api/metis/lora/jobs` | Training jobs: scheduled (agenda key), running (pid), finished, `no_training_script` |
| `GET` | `/api/ui/manifest` · `/ui/webui/{file}` | WebUI plugin manifest and bundle (see below) |
| `GET` | `/api/metis/insights` | Weak spots from graded feedback: `{total_feedback, bad_feedback, bad_ratio, weak_domains[{domain, bad, labels, samples}]}` (`limit`, `since`). Good labels: setting `metis.insights.good_labels` (default `excellent, good`) |

Feedback filters (`limit`, `quality_label`, `since`) are now forwarded to Archive in the Hub envelope query
(they were appended to the URL and dropped).

`metis_benchmark_run` returns `status: not_implemented` (honest placeholder, no LLM call).
Default `baseline_model` (benchmark) and `base_model` (LoRA) = the model Oracle uses now for the `oracle.generale` use case
(first usable step of its chain), read via Hub from Oracle `GET /api/llm/usecases/oracle.generale`; Oracle unreachable →
`[🔄]` fallback to the first step of Oracle's default «veloce» chain, `gemma4:e4b`. Metis never picks models itself (Oracle owns them).
`metis_loRA_train` really launches `METIS_TRAINING_SCRIPT --dataset <jsonl> --base_model <m> --adapter_name <a>`
(dataset + log in `METIS_DATA_DIR`, default `/code/data` = `Hestia-Metis/data` volume); it used to report "triggered" without starting anything.

## WebUI plugin (Sistema)

Metis ships its inside view on the client plugin contract (`hestia_common.plugin_client`, SPEC
`docs/work/2026-10-18-moduli-core-e-mcp-esterno` §A2/A3), declared in `app/main.py`: kind `core` (WebUI sidebar
section *Sistema*), `api_prefix` `/api/metis/`, no new endpoint.
- page **Miglioramento** (`miglioramento`, `metis-improvement`, order 180): *Dove sbaglia* from
  `/api/metis/insights` (grades, negatives, negative share, weak domains with labels and examples), *Dataset* from
  `/api/metis/dataset/status` (in-memory, shown only when there are some), *Training LoRA* from `/api/metis/lora/jobs`
  (state, dataset, base model, requester, planned start). Read only: building datasets and training stay chat/agenda
  actions; a planned training is moved/cancelled from the agenda window `metis.training`.
- No widgets, no quick actions. Metis unreachable → "non raggiungibile"; Archive feedback unavailable → only that
  card shows an error.
Bundle: `Hestia-Metis/ui/src` (Lit, `@hestia/webui-sdk`), built by the Node stage of the Dockerfile into
`/ui/dist/webui/metis.js` (outside `/code`: the dev mount of `app/` would hide it); infra env `METIS_UI_DIST`.

## Constraints

- Does NOT execute model inference → Oracle
- Does NOT store raw feedback records → Archive
- Does NOT judge individual turn quality → Athena (on-demand audit)
- Does NOT render UI → Telegram
- Does NOT implement training logic → external script
- In-memory dataset store — datasets are rebuilt on restart

## Central settings (Themis)

Declared in `app/core/metis_settings.py` (`SettingsClient("metis")`), all **live** (read at use time).
Endpoints `GET /api/settings/effective`, `POST /api/settings/reload` (used by Themis).

| Key | Type · default | Effect |
|---|---|---|
| `metis.dataset.max_examples` | int · 5000 | cap of examples per dataset (a larger `max_examples` request is clipped) |
| `metis.dataset.deduplicate` | bool · on | near-duplicate removal when the caller does not say |
| `metis.dataset.quality_labels` | list · `[excellent, good]` | labels collected when the caller gives none |
| `metis.insights.good_labels` | list · `[excellent, good]` | labels not counted as weak spots in `/insights` |
| `metis.log.level` | enum · `LOG_LEVEL` boot value | log verbosity |

## Environment Variables (infrastructure only)

| Variable | Default | Description |
|---|---|---|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub API base URL |
| `SERVICE_*` | — | Hub registration identity |
| `METIS_TRAINING_SCRIPT` | `/code/data/train_lora.py` | Path to external training script (put it in `Hestia-Metis/data/`) |
| `METIS_DATA_DIR` | `/code/data` | Exported datasets, training logs, `lora_jobs.json` |
| `LOG_LEVEL` | `INFO` | Boot log level only (then `metis.log.level`) |
| `METIS_UI_DIST` | `/ui/dist` | Built WebUI plugin bundle (set by the Dockerfile) |

## Docker

Part of the global stack (`docker-compose.global.yml`, service `metis`, port 19014). Built from the repo root
(like every service) so the shared `hestia_common` package is copied in — the old per-folder build crashed at
import. Volume `./Hestia-Metis/data:/code/data`.

## Assistant presence

Window-mode trainings also wait for presence `work.heavy` allow/local: held → re-planned +30 min (agenda key `metis.train.<job>.<ts>`). A running training is activity `metis.training.<job>` (heavy, gpu).

## Telegram menus
Tool titles are plain Italian without emoji; each tool says where it goes on Telegram with `telegram_group` (area) and `telegram={section, primary, summary, label}` (docs/work/2026-10-23-telegram-da-zero §5.7, checked by `tools/governance/check_telegram.py`). Here: sviluppo › Dataset e training: 5 (area › section: tools).

## Module guide for the assistant (dossier `docs/work/2026-10-24-tutto-brainstorm-cindy`, Cindy 30)
The Hub registration declares `capabilities.when_to_use` (one line in the assistant's «MODULI» index) and
`capabilities.manual` (short manual the assistant loads with `module_manual` only when it needs it).

**2026-10-29 (texts for people, dossier `docs/work/2026-10-29-revisione-e-test-frontend`)**: Plugin title «Miglioramento»; «Scopri» items carry a description for people and `area`, `area_label`, `area_icon`, `area_order` (one per area first); agenda titles «Finestra per allenare i modelli», «Allena il modello: …».
