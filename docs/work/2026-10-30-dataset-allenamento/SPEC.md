# Dataset di Hestia: every conversation becomes training material, a smarter model fixes it, a LoRA makes the local model better

| | |
|---|---|
| **Version** | 2.3 |
| **Source** | user via external chat (Project thread) (Marko 2026-10-30: «salvare come converso con hestia … per contribuire a un dataset mio locale … passarlo ad un modello più inteligente per riformattare o aggiustare le risposte usando il sistema di feedback e altri dati/metadati … per poi permettermi di fare il training? … o aggiungo lora cosi diventa parte della sua conoscenza») |
| **Status** | Approved 2026-10-30 (v2.0: dataset only; teacher = cloud model with masking) — D1 on main (PR #60), D2 on main (PR #64), D3 done |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 0. Scope v2.0 (Marko 2026-10-30)

«non preoccuparti del train magari lo faccio online... mi serve solo il dataset». In scope: §3.1–§3.4 and §3.7
(capture, signals, teacher correction, review, export) + a **download** of the export (zip from the WebUI page and
Telegram). **Out of scope**: §3.5 training container/script and §3.6 benchmark/adapter loading — kept below only as
reference for a later phase. The export uses the generic OpenAI `messages` + `tools` format that Unsloth, TRL,
axolotl and online trainers accept, so no base model choice is needed now.

## 0.1 In short (for Marko)

Most of the pipe already exists but is empty: Metis can build a dataset, export it and start a LoRA training, but
it only reads 👍/👎 votes, and the votes from Telegram arrive **without the conversation** (no question, no answer),
so today the dataset is always empty. The plan:

1. **Registra** — Oracle saves every finished turn as a *trace*: exactly what the model saw (system prompt, tools
   offered, history window) and did (tool calls, results, final answer), with model, timings, outcome. Local, in Archive.
2. **Segnali** — each trace collects signals: your 👍/👎 and words, plus automatic ones (you rephrased the same
   question, you said «no, intendevo…», you undid an action, a tool failed, a guard blocked a duplicate…).
3. **Correggi** — at night a stronger model (the *teacher*) re-reads the traces with the signals and Hestia's rules
   and writes the version the answer *should* have been. Doubtful cases wait for you in a «Da rivedere» list.
4. **Esporta** — two files: examples to imitate (SFT) and *good vs bad* pairs (DPO), in the exact chat format of
   your local model, with a frozen test set.
5. **Allena** — in the `metis.training` night window, a QLoRA on your GPU makes an adapter.
6. **Prova e attiva** — the new adapter is tested against the current model on the test set (+ the bench
   scenarios); only if it wins does Hestia *propose* switching to it; you confirm; going back is one tap.

**Important about «diventa parte della sua conoscenza»**: a LoRA teaches *how* Hestia behaves (tone, Italian,
picking the right tool, not duplicating, not claiming actions it did not do, short answers). It is a bad place for
*facts about you* (your mother's name, your gym days): they change, a LoRA cannot forget one fact on request, and
small models trained on facts invent similar wrong ones. Facts stay in memory/People (which Hestia reads every
turn); the LoRA makes it better at *using* them. So the dataset never trains on personal facts as targets (§3.4).

## 1. Today (verified in code, main `6dd88dd`)

- **Feedback** — Archive `feedback_records` (`quality_label`, `quality_score`, `feedback_text`, `tags`,
  `payload` JSONB, `session_id`, `interaction_id`). Writers:
  - Telegram 👍/👎 (`chat_service.handle_feedback_callback`) posts straight to Archive with **empty payload**;
    `interaction_id` comes from the callback data. Shown only on some turns (`should_show_feedback_prompt`, snooze).
  - WebUI (`FeedbackService` → `FeedbackController`) sends `prompt` + `response` with the vote.
  - Oracle `submit_feedback` fills `instruction/output` from the last two history rows (wrong turn if the vote
    comes late) — but Telegram does not go through it.
- **Chat history** — Archive `chat_history` = `session_id, role, content, timestamp` only: no tool calls, no tool
  results, no model, no system prompt, no turn id. Not enough to train a tool-using agent.
- **Turn trace** — Oracle `activity_log.record_turn` already has, per finished turn, `trace_id`, route
  (quick / quick_chat / agent), model + provider, domains, tool_log (tool, ok, writes), ms, usage — but in a
  200-row RAM ring, lost on restart (page *Cervello*).
- **LLM usage** — Archive `llm_usage` per call (chain, step, model, tokens, outcome): tells when a fallback answered.
- **Metis** — `dataset_builder.build_dataset` reads feedback with `quality_label in (excellent, good)` and needs
  `payload.instruction/output` → with Telegram votes, `total_kept = 0`. Datasets in RAM. Export ChatML/Alpaca/
  ShareGPT (single user/assistant pair, no tools, no system). `metis_loRA_train` really launches
  `METIS_TRAINING_SCRIPT` in the agenda window `metis.training` (01–06, held by presence unless `work.heavy`
  allowed); **the script does not exist**. `metis_benchmark_run` = `not_implemented`. Base model = Oracle's
  `oracle.generale` first step.
- **Local serving** — Oracle providers `ollama` and `llamacpp` (compose profile `llamacpp`, GPU, `-c 16384`).
  Both can load a GGUF LoRA (Ollama: `ADAPTER` in a Modelfile; llama-server: `--lora`, scale per request).

## 2. Goal

As Marko uses Hestia, it collects **its own local dataset** of real conversations, made better by a stronger model
and by Marko's signals, and periodically produces a **LoRA for the local model** that is measurably better at
being Hestia. Nothing leaves the house unless Marko chose it (§3.3). Every step is visible and reversible.

## 3. Scope and design

### 3.1 Owners (module boundaries)
- **Oracle** (brain) only *emits* the trace of the turn it just ran (it is the only one that knows the exact
  prompt and tool calls) and runs the teacher/judge use cases when Metis asks. It does not store or judge.
- **Metis** (improvement organ) owns traces, signals, reviews, datasets, trainings, adapters. Stores them in
  Archive's generic `metis-store` (kinds `trace`, `prompt`, `toolset`, `review`, `example`, `adapter`).
- **Archive** stores. **Chronos** plans (windows/jobs). **Themis** holds tunables. **Hermes** asks Marko to confirm
  a switch. Clients (Telegram, WebUI) only send votes/corrections and show pages.

### 3.2 Registra: the trace (push, Oracle → Hub → Metis)
At the end of every turn (`_record_turn`, all three routes) Oracle posts in the background
`POST /route/metis/api/metis/traces` (never blocks or fails the chat):

```
trace_id, session_id, client, at, route, mode, use_case, chain, step, provider, model, thinking,
prompt_ref (hash of the system prompt text, stored once as kind=prompt),
toolset_ref (hash of the tool schemas offered, stored once as kind=toolset),
system (the agent loop system prompt, or the one prompt of a quick route), history (the history text
the model got), user, steps: [{turn, tool, params, ok, writes, result (what the model read, ≤ 4000 chars)}],
answer,   (D3 turns these into OpenAI `messages` with `tool_calls` / `tool` roles)
tools: [{tool, ok, writes, ms}], domains, total_ms, tokens_in/out, fallback_used, guard_events[]
```
- Thinking text is **not** kept (it is model-specific and noisy).
- The final event of the chat stream gains `trace_id` (today it has only `reply`, `domain`, `origin`); Telegram puts
  it in the 👍/👎 callback and WebUI in its vote, so a vote attaches to the **right turn** (fixes the «last two history rows» guess).
- Excluded: Forge/coding turns, module use cases without a user (recap, ideas…) — they are a later, separate set.
- Deleting a chat deletes its traces; retention `metis.traces.keep_days` (default 365). Rough size: ~15 KB/turn
  → a few hundred MB per year in Postgres. Stored in Archive `dataset-store` (not the mirrored `metis-store`).

### 3.3 Segnali e correzione (the part where a smarter model fixes answers)

**Signals** attached to a trace (kind `signal`, each with source and weight):
| Signal | Source | Meaning |
|---|---|---|
| 👍 / 👎 + text | Telegram, WebUI | explicit grade (strongest) |
| «Correggi» text | WebUI/Telegram button «Avrei voluto…» on the answer (new, optional) | Marko's own target answer → gold |
| rephrase | Metis: same session, next user message < 2 min and very similar | previous answer missed |
| correction words | Metis: next message starts with «no», «intendevo», «non è quello»… | previous answer wrong |
| undo | a write tool of this turn undone/deleted within 10 min | action wrong |
| tool failed / invented tool / guard fired (duplicate memory, false «ho registrato») | Oracle trace | behaviour bug |
| fallback answered / «Non disponibile» | `llm_usage` | not a quality signal, only excluded from SFT of the first model |

**Teacher review** — agenda job `metis.dataset.review` (nightly, inside a window, batch size setting). For each
trace not yet reviewed, Metis asks Oracle use case `metis.dataset.review` (its own chain in Themis, so Marko picks
the model) with: the trace, its signals, the **Hestia rules sheet** (from `docs/REGOLE-DI-MARKO.md` + prompt
rules: memory discipline, no duplicates between People and memory, never claim an action not done, short Italian,
tool naming…). The teacher answers strict JSON:
```
verdict: keep | fix | drop,  confidence 0..1,
fixed_messages: (only if fix) corrected assistant tool calls and/or final answer,
reasons: [rule ids broken],  needs_owner: bool
```
Safety rules for corrections:
- The teacher may **remove** a wrong/duplicate tool call, **rewrite** the final text, or **change arguments** of a
  read-only tool; it may not invent the *result* of a tool that was never run. If the right fix needs a different
  write tool or new results, the trace goes to `needs_owner` (or is used only as the *rejected* side of a pair).
- `confidence ≥ metis.review.auto_accept` (default 0.85) and no 👎 text from Marko contradicting it → accepted.
  Otherwise → **«Da rivedere»** list (WebUI Miglioramento page + Telegram tool `metis_rivedi`): original vs fixed
  side by side, buttons Accetta / Modifica / Scarta. Marko's choice always wins and is itself a signal.
- Traces with a 👍 and no negative signal are reviewed only lightly (verdict keep unless a rule is broken).

**Where the teacher runs — decided by Marko 2026-10-30: A, cloud with redaction.** Built as: use case `metis.dataset.review` with a new default chain `cloud` (Gemini; Marko can point it to Claude in Sistema); turns younger than 30 min wait (the next turns may still signal them); Persone (Hera) unreachable → no turn is sent that night. The traces contain his life. Two ways:
- **A. Cloud teacher with redaction (recommended)**: Claude (subscription via `claude -p`, already wired) or Gemini.
  Before sending, Metis replaces personal data with stable placeholders (`<PERSONA_1>`, `<EMAIL_1>`, phones,
  IBAN, addresses, names from People/contacts), keeps the map locally, and puts the real values back in the
  corrected text. Much better corrections; something does leave the house (redacted).
- **B. Local only**: a bigger local model (e.g. a 26–32B at night) as teacher. Nothing leaves; weaker corrections,
  slower, and a 9B student learns less from it.
- Either way: chats Marko marks as private (a «non usare per l'allenamento» flag on the conversation, next to
  title/tags/pin) never enter the dataset.

### 3.4 Esporta
**As built (v2.3)**: `POST /api/metis/export` / tool `metis_dataset_esporta` → zip in Archive blobs (owner `metis`),
row kind `export` in dataset-store, download from WebUI Miglioramento and Telegram. Files `sft.jsonl`, `dpo.jsonl`,
`eval.jsonl`, `card.json` as below; turns used = review accepted keep/fix or edited by Marko (`include_unreviewed`
adds the not yet reviewed ones). **Masked or clear is chosen at each export** (Marko: «a me non dispiacerebbe
averli in chiaro ma anche non, opzione durante la esportazione?»): «oscurato» (default, same masker as the review,
refused when Persone is unreachable) or «in chiaro». Domain balancing and the long-result cut are left to the
trainer for now (the card lists routes and models). The original plan follows.

`metis_dataset_build` gains `source=traces` (default) next to the old feedback path. Output in
`METIS_DATA_DIR/datasets/<name>/` (Docker volume, gitignored, included in the Drive backup like other data):
- `sft.jsonl` — OpenAI-style `messages` with `tool_calls` / `tool` roles + `tools` schemas, from traces with
  verdict keep (good signals) or fix (the corrected version). Rendered with the **current** system prompt
  structure but the turn's toolset, so it matches what the model sees in production.
- `dpo.jsonl` — `{prompt, chosen, rejected}`: chosen = fixed/Marko's version, rejected = the original bad answer.
  This is where 👎 votes become useful.
- `eval.jsonl` — a frozen held-out set (split **by session**, ~10%, never trained on) + the real-AI bench scenarios.
- `card.json` — counts, domains, signals, base model, prompt/toolset hashes, rules version.
- **Personal facts are not targets**: examples where the answer's value is a stored fact are kept only if the
  fact was in the model's context (memory/People block) — the model learns to *read and use* context, not to
  memorise Marko. Long tool results are cut. Dedup as today.
- Balance per domain and per route so one heavy habit (e.g. gym) does not dominate.

### 3.5 Allena (on Marko's GPU, see §6)
- `Hestia-Metis/training/train_lora.py` (tracked, no data): Unsloth QLoRA 4-bit, chat template of the base model,
  SFT then optional DPO; LoRA r=16, α=32, 2–3 epochs, max length 8–16k (tunables in Themis
  `metis.training.*`). Writes progress lines Metis already reads, saves the adapter, then converts it to a **GGUF
  LoRA** with llama.cpp `convert_lora_to_gguf.py`.
- Runs in a new compose service `metis-trainer` (profile `training`, nvidia reservation like `llamacpp`) that Metis
  starts through the existing job mechanism (`METIS_TRAINING_SCRIPT` becomes a call to that container). Same rules
  as now: agenda window `metis.training`, held by presence unless heavy local work is allowed, and the LLM server is
  paused during training if the GPU is the same (VRAM).
- Minimum to start: `metis.training.min_examples` (default 300 SFT); below it Metis says how many are missing.

### 3.6 Prova e attiva
- `metis_benchmark_run` becomes real: candidate (base + adapter) vs current on `eval.jsonl`; a judge (use case
  `metis.dataset.judge`, same teacher choice as §3.3) scores rule adherence, tool choice, correctness, length;
  plus hard checks (valid tool JSON, no duplicate writes, no false claims).
- Wins on score and loses nothing on hard checks → Metis registers the adapter (kind `adapter`, version n) and
  makes it loadable:
  - **llama-server**: adapter file in the models folder, `--lora` with scale 0 at start; Oracle sets the scale per
    request → instant switch and A/B without restart.
  - **Ollama**: Metis writes a Modelfile `FROM <base>` + `ADAPTER <file>` and `ollama create hestia-<base>-v<n>`;
    the new model name appears in Oracle's model list.
  Then it **proposes** in Themis «use hestia-…-v<n> for oracle.generale» → Hermes asks Marko → he confirms. Going
  back = the previous value in Themis (one tap). Argus watches error rate for 48 h and proposes rollback if worse.
- The base model must be the exact same weights the adapter was trained on; changing base model = new training.

### 3.7 Where Marko sees it
WebUI *Sistema → Miglioramento* (Metis plugin) gains: **Raccolta** (traces per day, signals, % with vote),
**Da rivedere** (the queue), **Dataset** (last builds, card), **Allenamenti** (jobs, as today), **Versioni**
(adapters, benchmark score vs current, active one). Telegram: tools `metis_rivedi`, `metis_dataset_status`,
`metis_allena`, `metis_versioni` (Telegram parity rule). Icons, no emoji, user texts never name modules.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job: Hestia gets better at being *his* assistant the more he uses it; his 👎 finally do something.
2. Owner module: Metis (Oracle only emits traces and runs the teacher/judge use cases).
3. Configuration: Themis `metis.traces.keep_days`, `metis.traces.tool_result_chars`, `metis.review.auto_accept`,
   `metis.review.batch`, `metis.training.min_examples`, `metis.training.{rank,epochs,max_len}`; teacher/judge model
   = Oracle use case chains. Env only for infra (`METIS_DATA_DIR`, trainer image/models dir).
4. Push (Oracle → Metis per turn); review/training = agenda jobs and window; all also on request by tool.
5. Teacher may auto-accept above threshold; Marko decides the rest; model switch only via Themis proposal + Hermes.
6. WebUI page sections + Telegram tools, §3.7.
7. Per-chat «non usare per l'allenamento»; delete chat = delete traces; Scarta in review; rollback model in Themis.
8. Docs: `hestia-metis.md`, `hestia-oracle.md`, `hestia-archive.md` (kinds), swagger (traces, review, versions),
   `.env.example` (trainer), `docs/ARCHITECTURE.md` (trace flow), TESTING.md, README feature line.

## 5. Acceptance criteria
- After a normal Telegram/WebUI chat with tools, Metis has one trace per turn with the exact messages + tool calls,
  and a 👍/👎 attaches to the right turn (test: vote on an older message).
- A planted bug turn (duplicate «mia mamma si chiama Laura» in People and memory) gets verdict `fix` with the
  duplicate write removed; a 👍 turn gets `keep`; a low-confidence one lands in «Da rivedere».
- Redaction (if A): no email/phone/People name of the fixture leaves Metis in the teacher request; the corrected
  text has the real values back.
- `sft.jsonl` / `dpo.jsonl` load in Unsloth/TRL without errors; eval split shares no session with train.
- On a tiny base model in the cloud bench (CPU, 20 steps) the script produces an adapter and a GGUF LoRA, and
  llama-server loads it; the benchmark returns real scores and a promote/hold verdict.
- Private-flagged chats and deleted chats never appear in any export.

## 6. Phases (v2.0: D1–D3 + download; D4–D5 out of scope)
- **D1 Registra** — trace emit in Oracle, Metis store, trace_id in clients' votes, implicit signals, private flag,
  retention. (Useful alone: from day one his data is collected correctly.)
- **D2 Correggi** — teacher use case, rules sheet, redaction (if A), review job, «Da rivedere» UI + Telegram.
- **D3 Esporta** — SFT/DPO/eval writer, card, dataset page.
- **D4 Allena** — `train_lora.py`, `metis-trainer` container, GGUF conversion, CPU smoke test in the bench.
- **D5 Prova e attiva** — real benchmark, adapter registry, llama-server/Ollama loading, Themis proposal, rollback.

D1 should start soon even if training comes later: every day without traces is data lost.

## 7. Open questions for Marko
1. ~~Teacher~~ — decided 2026-10-30: cloud with redaction (A).
2. ~~GPU~~ — RTX 4080 SUPER 16 GB VRAM, 64 GB RAM (Marko 2026-10-30). Fits a 9B QLoRA 4-bit with Unsloth
   (gradient checkpointing, batch 1 + accumulation, max length 8k by default; 16k only for a few long examples).
   The local LLM server must be stopped during training (same GPU): Metis pauses `llamacpp`/Ollama models for the
   run and restarts them after; that is why training stays in the night window and behind presence `work.heavy`.
3. Which local base model will Hestia use long-term (e.g. Gemma 4 9B / Qwen 9B)? The adapter is tied to it.
