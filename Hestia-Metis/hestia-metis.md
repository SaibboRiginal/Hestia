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
- Tracks job status via job ID
- Dataset exported as JSONL before training kickoff

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
| `METIS_TRAINING_SCRIPT` | `/app/train_lora.py` | Path to external training script |
| `METIS_BENCHMARK_MODEL` | (empty) | Model for benchmark evaluation |
| `METIS_BENCHMARK_PROVIDER` | (empty) | Provider for benchmark evaluation |
