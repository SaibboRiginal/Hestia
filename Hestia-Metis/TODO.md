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
