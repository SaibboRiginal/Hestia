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
- **Planned in the assistant agenda**: window `metis.training` (default daily 01–06). `schedule=auto` (default):
  user request → starts now; module request (e.g. Athena) → agenda task `metis.train.<job>` at the next window
  opening, fired via Hub with `schedule=now`. `schedule=window|now` forces it. Move/cancel it from the agenda.

## MCP Tools

| Tool | Description |
|---|---|
| `metis_dataset_build` | Build cleaned dataset from graded feedback records |
| `metis_dataset_export` | Export dataset as ChatML/Alpaca/ShareGPT JSONL |
| `metis_dataset_status` | Show dataset statistics |
| `metis_benchmark_run` | Evaluate candidate model vs baseline |
| `metis_loRA_train` | Orchestrate LoRA fine-tuning run |

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health |
| `GET` | `/api/logs` | Filterable log buffer |
| `POST` | `/mcp` | MCP JSON-RPC endpoint (tools/list, tools/call) |
| `POST` | `/api/metis/dataset/build` · `/benchmark/run` · `/lora/train` | REST mirrors of the MCP tools (auto-mounted by `mount_missing_rest_routes`; were 404 via Hub/Telegram) |
| `GET` | `/api/metis/dataset/export` · `/dataset/status` | idem |
| `GET` | `/api/metis/lora/jobs` | Training jobs: scheduled (agenda key), running (pid), finished, `no_training_script` |
| `GET` | `/api/metis/insights` | Weak spots from graded feedback: `{total_feedback, bad_feedback, bad_ratio, weak_domains[{domain, bad, labels, samples}]}` (`limit`, `since`). Good labels: `METIS_GOOD_QUALITY_LABELS` (default `excellent,good`) |

Feedback filters (`limit`, `quality_label`, `since`) are now forwarded to Archive in the Hub envelope query
(they were appended to the URL and dropped).

`metis_benchmark_run` returns `status: not_implemented` (honest placeholder, no LLM call).
`metis_loRA_train` really launches `METIS_TRAINING_SCRIPT --dataset <jsonl> --base_model <m> --adapter_name <a>`
(dataset + log in `METIS_DATA_DIR`, default `/code/data` = `Hestia-Metis/data` volume); it used to report "triggered" without starting anything.

## Constraints

- Does NOT execute model inference → Oracle
- Does NOT store raw feedback records → Archive
- Does NOT judge individual turn quality → Athena (on-demand audit)
- Does NOT render UI → Telegram
- Does NOT implement training logic → external script
- In-memory dataset store — datasets are rebuilt on restart

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HUB_API_URL` | `http://hestia_hub:19001/api` | Hub API base URL |
| `METIS_MAX_DATASET_EXAMPLES` | `5000` | Max examples per dataset |
| `METIS_DEDUPLICATE_ENABLED` | `true` | Enable near-duplicate removal |
| `METIS_DEFAULT_QUALITY_LABELS` | `excellent,good` | Quality labels to include |
| `METIS_TRAINING_SCRIPT` | `/code/data/train_lora.py` | Path to external training script (put it in `Hestia-Metis/data/`) |
| `METIS_DATA_DIR` | `/code/data` | Exported datasets, training logs, `lora_jobs.json` |
| `METIS_TRAINING_WINDOW_START` / `_END` | `1` / `6` | Default hours of agenda window `metis.training` |
| `METIS_BENCHMARK_MODEL` | (empty) | Model for benchmark evaluation |
| `METIS_BENCHMARK_PROVIDER` | (empty) | Provider for benchmark evaluation |

## Docker

Part of the global stack (`docker-compose.global.yml`, service `metis`, port 19014). Built from the repo root
(like every service) so the shared `hestia_common` package is copied in — the old per-folder build crashed at
import. Volume `./Hestia-Metis/data:/code/data`.
