# SPEC — LLM bus: one queue for the local models

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via project chat (Marko, 2026-11-16: «siamo limitati ad un run alla volta quindi abbiamo bisogno di un "bus", poi se in futuro avremo più disponibilità possiamo avere più worker llm»; «tu intervieni su quello che devi poi aggiorni il thread dei multi agent») |
| **Status** | Done |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

Context: evaluation of the week's AI papers (`/mnt/project-files/valutazioni/paper-settimana-2026-11-09.md`,
s³ multi-agent paper) and the open design «Ogni modulo un agente di Oracle»
(`docs/work/2026-11-06-moduli-come-agenti`, SPEC v2.1). Agents multiply model calls; the owner's PC runs one at a time.

## 1. Today (verified in code, main 0a19768)

- Every model call goes through `ChainAgent` (`core/services/llm_chains.py`): chat, classifier, agent loop, memory
  threads, `/api/llm/generate` (modules), `/api/llm/chat` (Forge). Nothing queues them: concurrent callers reach Ollama
  together and Ollama serves them one by one in arrival order, with no priority. A recap or an Athena job can make the
  owner's chat wait.
- `oracle.provider.llamacpp.slots` keeps chat KV caches warm on llama-server; it is not a concurrency limit.
- `llm_providers.is_local(name)` already tells local providers (Ollama, llama-server, local OpenAI-compatible) from cloud.

## 2. Goal

One queue in Oracle (the only module that calls models) for the calls to local models: N workers (today 1, more
when the machine allows), the owner's turn first, background work after. The multi-agent modes then need no special
«serial» logic: with 1 worker agents run one after the other, with more they run together.

## 3. Scope and design

- `core/services/llm_bus.py`. The unit that waits is **one model call of one chain step**, not a turn: between two
  steps of a long job a chat call passes ahead.
- **Workers**: Themis setting `oracle.bus.local_workers` (int, default 1, 1–16, live) «Modelli locali · risposte
  preparate insieme». Raise it only if the runtime serves more at once (Ollama `OLLAMA_NUM_PARALLEL`, llama-server
  `--parallel`).
- **Priority** (context variable): `chat` before `background`; same priority = arrival order (ticket sequence).
  - `/api/chat`: `chat` when the origin level is `utente` (owner typing/speaking, external AI he connected), else
    `background` (routines, autonomous turns). The stream re-binds it at every `next()` (`llm_bus.bind`).
  - `/api/chat/document`: same rule from the client name.
  - `/api/llm/generate`: the request's origin; **promoted to `chat`** while an owner turn is waiting for its tools
    (`llm_bus.owner_waiting` around tool execution in `agent_loop`), because such a call is very likely that tool's
    work. Parallel tool threads copy the turn's context.
  - `/api/llm/chat` (Forge), memory threads, everything else: `background` (default for new threads).
- **Skips the queue**: cloud steps (no GPU of ours) and embeddings (tiny, other model; memory search inside a chat
  turn must not queue behind a long generation).
- **Re-entrant**: a thread holding a worker never waits again (no deadlock with 1 worker, e.g. vision bridge).
  A stream holds its worker until the stream ends or is closed.
- **No timeout in the queue**: a call waits its turn (no task abandoned); provider timeouts start once it runs.
- Log: `event=llm_bus_wait priority=… use_case=… provider=… waited_ms=… still_waiting=…` when a call waited ≥ 0.5 s.
- Out of scope: the multi-agent modes themselves (thread «Rendere ogni modulo un agente di Oracle»), a WebUI view of
  the queue.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: his chat is never stuck behind a background job on the one local model; ready for more workers.
2. Owner module (R1): Oracle (the only LLM caller). No module changes.
3. Configuration: `oracle.bus.local_workers` (Themis). No switch, no env.
4. Push or poll: n/a (inside each call).
5. Who confirms: nothing new.
6. WebUI/Telegram: the setting appears in Impostazioni → Cervello (group Contesto) and Telegram settings like every
   Themis setting. No new page.
7. Stop, correct, undo: setting live; 1 = today's behaviour on one GPU, with priority.
8. Docs: `Hestia-Oracle/hestia-oracle.md`, `docs/ARCHITECTURE.md` (rule 3b), `docs/AI-GUIDE.md` §3, root CHANGELOG.
   No endpoint change (swagger untouched).

## 5. Acceptance criteria
1. With 1 worker busy, a queued `background` call and a later `chat` call: the `chat` call runs first.
2. Same priority keeps arrival order.
3. Cloud calls and embeddings never wait for the local worker.
4. A nested call on the thread holding the worker does not deadlock.
5. With 2 workers two local calls run together.
6. Chat streams keep their priority across `next()`; module calls are promoted only while an owner turn waits for tools.
7. Existing Oracle tests unchanged and green (`tests/test_llm_bus.py` added).
