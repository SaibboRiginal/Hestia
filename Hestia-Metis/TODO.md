# Hestia-Metis — Deferred Work

## LoRA Training (external)

Metis orchestrates but does NOT implement training logic. The `metis_loRA_train` tool exports the dataset as ChatML JSONL and triggers an external script.

**To implement:**
1. Write a training script (e.g. `train_lora.py` using Unsloth or QLoRA)
2. Set `METIS_TRAINING_SCRIPT=/path/to/train_lora.py` env var
3. Script receives: `--dataset <jsonl_path> --base_model <name> --adapter_name <name>`
4. Script writes progress to stdout (Metis streams it) and saves adapter to a known path

**Reference:** `feedback-and-dataset-plan.md` §6

## Benchmark Runner (live inference)

The `metis_benchmark_run` tool currently returns a placeholder. To implement live eval:

1. Add an Oracle MCP tool that accepts a prompt and returns raw LLM output
2. Metis calls Oracle for each benchmark example with both baseline and candidate models
3. Metis calls the 26B reasoning model as judge to compare outputs
4. Aggregate scores and report winner

## Persistent Dataset Store

Currently in-memory (`_datasets` dict). Datasets are lost on restart. To persist:

1. Write datasets to Archive as entities under domain `metis_dataset`
2. Or write to a local JSON file mounted as a volume
3. Load on startup, save on each `metis_dataset_build`

## MCP-to-MCP Tool Calls

When Metis needs to call Archive's `feedback_submit` or Oracle's LLM endpoint, it uses Hub REST routing. When Archive and Oracle expose MCP tools, switch to MCP `tools/call` protocol for consistency.

## Quality Trend Analytics

`metis_dataset_status` shows per-dataset stats. Add:
- `metis_quality_trend` tool — quality_label distribution over time (weekly buckets)
- `metis_domain_coverage` tool — which domains are underrepresented in the dataset
- `metis_improvement_delta` tool — before/after comparison when a new adapter is deployed
