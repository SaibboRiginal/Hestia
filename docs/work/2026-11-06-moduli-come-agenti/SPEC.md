# SPEC — Ogni modulo un agente di Oracle

| | |
|---|---|
| **Version** | 2.1 |
| **Source** | user via project chat (Marko, 2026-11-06: «non sarebbe più giusto che ogni modulo fosse un agente collegato ad Oracle?») |
| **Status** | Draft — waiting for Marko's approval |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code, main 4f45189)

- One chat turn (`oracle_engine.chat`, mode `auto`) = **classifier call** (`chat_classifier.py`, use case
  `oracle.generale`) → quick chat (1 more call, no tools) **or** one agent loop (`core/agent_loop.py`) that holds the
  tools of every module the classifier picked.
- ~265 MCP tools across 25 services (Chronos 31, Hercules 26, Hephaestus 25, Hygieia 19, …). All of them ≈ 30k
  tokens per call, more than a local model's context (bench 2026-10-30). The fix today is `_turn_tool_domains`: when
  the classifier is sure, only the tools of its domains; unsure → **all** tools again.
- Modules already declare `capabilities.when_to_use` (one line) + `capabilities.manual` (ModuleKit and 17 modules);
  Oracle prints a «MODULI» index and the tool `module_manual(service)`.
- Modules already declare their own LLM use cases (`capabilities.llm_usecases`) and each use case has a chain on the
  Modelli page (`llm_chains.usecase_config`).
- The loop already runs several tool calls of one step in parallel (`oracle.agent.max_parallel_tools`).
- Thinking frames are collected during the loop and sent **after** it ends (not live).

## 2. Goal

Every module is a **specialist agent**: it knows only its own tools and rules. The main brain no longer holds
every tool: it sees one «colleague» per module (≈25 short tools) and gives each one a job. Oracle stays the only
brain: every agent reasons **inside Oracle** with its own model chain; the module only declares its agent and
keeps doing the work (its tools).

Effects: no classifier, short prompts on every model (local too), natural parallel work (two agents at once), and
clients see what each agent is doing through one standard stream frame.

## 3. Scope and design

### 3.0 Operating modes (Marko 2026-11-06: «una modalità di funzionamento, così possiamo tornare indietro»)
One Themis setting `oracle.funzionamento` (live, scope profile → client → session like `oracle.chat.mode`) picks how a
turn works. It is not an on/off switch: it is a choice among ways of working, and more can be added later.
- `classica` — today's flow, untouched (classifier + one loop with the domains' tools). **Default** until Marko's
  real run says otherwise; going back = choose it again.
- `agenti` — Oracle orchestrates, agents in parallel (§3.2–3.4). Meant for cloud chains.
- `agenti_in_serie` — same agents, one at a time: Oracle plans the list of jobs, agent 1 works until done, agent 2
  starts and **also reads agent 1's result**, …, then Oracle joins and answers. Slower, but one model call at a time:
  meant for the local model (one GPU). Max agents per turn = `oracle.agenti.max_per_turno` (default 4).
The mode is chosen in WebUI Impostazioni (Cervello) and from Telegram settings like every Themis setting; Oracle
or Athena may only propose a change, Marko confirms. Clients get the mode used in `final.funzionamento`.

### 3.0a How the modes fit the rest
| Thing | classica | agenti / agenti_in_serie |
|---|---|---|
| Chat mode `quick` | one ask, no tools | the same (no agents) |
| `auto` | classifier → quick or loop | main brain decides: answers or calls agents |
| `thinking` / `cot` | think level on the loop | same think level on main **and** agents; `cot` keeps the «Passi:» recap on main |
| Brain `esterna` (Claude CLI) | Claude gets the domains' tools | Claude gets the small manifest; agents run in Oracle on their chains (in series: one at a time) |
| Chains, quota fallback | per use case | the same; each agent has use case `agente.<modulo>` |
| Origin levels, turn guards, Annulla, `ask_user`, Themis proposals | today | the same, inside each agent |
| Conversation goal rounds | loop with tools | rounds use the same small manifest |
| Spoken turns (Verity thread) | voice contract | voice contract on whoever answers (agent on a direct answer) |
| `oracle.agent.max_turns` | loop cap | main brain cap; each agent has `oracle.agenti.passi` |
| `oracle.agent.max_parallel_tools` | parallel tools | parallel tools inside an agent; agents capped by `oracle.agenti.max_paralleli` (ignored in series) |

### 3.0b Chats and clients
Agents live **inside one turn** of one conversation: they are not separate chats. Each client keeps its own
conversation (Telegram, WebUI, Claude mod…); whichever conversation the turn came from, Oracle passes the agents the
last messages of **that** conversation, and the `agent` frames go back to **that** client. What an agent learns stays
in its module's data and in Oracle's memory, so every client sees it next time.

### 3.1 What a module declares (no code per module)
- `when_to_use` = what the agent is for (one line, already there) · `manual` = the agent's rules (already there) ·
  its MCP tools (already there). ModuleKit adds nothing new to write: the agent comes from these three.
- Modules without `when_to_use`/`manual` today (Chronos, Hermes, Hephaestus, Themis, Argus, Athena, Iris, Archive,
  Atlas, Echo, Scout if missing) get them written in their registration. A service with no tools has no agent.
- Each agent is an LLM use case `agente.<modulo>` («Agente Spese», …), declared automatically by Oracle from the
  registry. Default chain: none of its own → it follows «Uso generale» (usual `usecase_config` fallback). On the
  Modelli page Marko can give any agent its own chain (Gemini, Claude subscription, local). **No switch**: local or
  not = put or remove the local step in that chain.

### 3.2 The main brain (one loop, no classifier)
- Tools of the main loop: one tool per agent `agente_<modulo>(compito)` (description = `when_to_use`), plus
  Oracle's own tools (memory, documents, chat, session, `ask_user`, goal tools) and the two cross-cutting ones
  `agenda_assistente_aggiungi`, `routine_create`. `module_manual` goes away (the manual lives in the agent).
- Chit-chat: the main brain answers with no tool call → **1 call** (today 2: classifier + answer).
- Domain request: main (decides) → agent loop (its tools) → answer. **Direct answer**: when the step called exactly
  one agent and nothing else, the agent's text is the reply, already in Hestia's voice (persona in the agent's
  prompt) → no third call. Two or more agents → the main brain joins the results (one more call).
- Parallel: two agents in the same step run together (existing parallel tool execution), capped by new setting
  `oracle.agenti.max_paralleli` (default 2; a chain with only the local model is in practice limited by what Ollama
  serves at once).
- Modes `agenti`/`agenti_in_serie` only. Mode `quick` stays as it is (one ask, no tools). Modes `thinking`/`cot` keep their think level for main and agents.
- In the agent modes there is no classifier call; `chat_classifier.py` and `_turn_tool_domains` stay for `classica`.
  The action policy line goes in every agent prompt (short).

### 3.3 The agent loop
- Same `run_agent_loop` (loop guard, truth about writes, turn guards, origin gate, parallel tools), with:
  - prompt: persona (short) + agent rules (`manual`) + the job (`compito`) + the last `oracle.agenti.storico`
    messages of the conversation (default 6) + the domain's preferences + date/time + origin line;
  - tools: only that module's tools;
  - turns: `oracle.agenti.passi` (default 8).
- **The agent writes** (the module owns its data): writes keep every gate of today. Turn guards judge the
  **owner's own words**, never the job text written by the main brain (a model can't turn a question into a write).
- An agent never calls another agent (depth 1). If it needs another module, it says so in its answer and the main
  brain calls that agent.
- Everything the agent did joins the turn: `tool_log` → `changes` with Annulla, notices, confirm cards, `ask_user`
  questions (an agent question stops the turn like today), turn trace for Metis, activity log.
- Esterna mode (Claude CLI as brain): the external brain gets the same small manifest (agent tools + Oracle tools);
  the agents run in Oracle on their own chain.

### 3.4 Stream frame `agent` (standard, every client)
`{"type":"agent","agent_id":"a1","module":"plutus","label":"Spese","event":"start|tool|end","task":"…",
"model":"…","provider":"…","tool":"finance_search","ok":true,"summary":"…","ms":1234}`
- `start` when the job begins, one `tool` per tool call of the agent, `end` with outcome and time.
- Frames go **live**: the loop runs in a worker thread and the engine yields its frames from a queue while it works
  (this makes the existing `thinking` frames live too). A client that does not know `agent` ignores it.
- Documented in `Hestia-Swagger/swagger.yml`, `hestia-oracle.md`, `Hestia-Shared/hestia-shared.md` § Response packets.
- First rendering, kept minimal (how to show it better is decided later): WebUI reasoning block lists each agent
  with its stroke icon and state; Telegram shows one status line «Spese: al lavoro…»; Hestia-MCP / Claude mod pass
  the frame through.

### 3.5 Logs and measuring
`event=agent_start|agent_done module=… ms=… tools=… model=…` and the turn summary gets `agents=…`. The speed on
Marko's PC is read from these logs in his real run (cloud tests use fake models).

### 3.6 Coordination
The Verity thread (branch `claude/project-thread-j7apmm`, dossier `docs/work/2026-11-06-hestia-viva`) keeps the classifier untouched and adds no «voice without classifier». Agents use its persona from `prompt_config.analyst_persona_default()` (key `analyst_persona_default`) and, on spoken turns, `voice_turn_contract()`. Its reaction marker is filtered in `main.py`, outside `chat()`.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: faster chit-chat, domain answers that fit a local model, parallel work, visible agents.
2. Owner module (R1): Oracle (the brain, agents included). Modules only declare `when_to_use`/`manual`/tools.
3. Configuration: Themis `oracle.funzionamento` (classica · agenti · agenti_in_serie), `oracle.agenti.max_per_turno`, `oracle.agenti.max_paralleli`, `oracle.agenti.storico`, `oracle.agenti.passi`; each
   agent's chain on Modelli. No switches, no env.
4. Push or poll: n/a (inside the chat turn).
5. Who confirms: same gates as today (origin levels, turn guards, Themis proposals, Annulla).
6. WebUI: stroke icons, no emoji; Telegram: status line. Same frame for every client.
7. Stop, correct, undo: unchanged (Annulla per change, loop guard, turn cap per agent).
8. Docs: `hestia-oracle.md`, `docs/ARCHITECTURE.md` (agent rule), `docs/AI-GUIDE.md`, swagger, shared response
   packets, module docs of the services that get `when_to_use`/`manual`, README if it names the classifier.

## 5. Acceptance criteria
0. `oracle.funzionamento = classica` behaves exactly as main today (existing tests unchanged).
1. In `agenti`, a chit-chat turn in `auto` makes exactly one model call (no classifier).
2. The main loop's manifest holds one tool per agent + Oracle tools only (no module tool), on every model.
3. «quanto ho speso questo mese?» → `agente_plutus` → reply from the agent with no extra main call; frames
   `agent start/tool/end` arrive before `final`.
4. «quanto ho speso e com'è andato l'allenamento?» → `agenti`: two agents in parallel; `agenti_in_serie`: one after
   the other, the second gets the first's result; one joined answer.
5. A write by an agent appears in `changes` with Annulla and its notice; an agent's `ask_user` stops the turn.
6. A question turned into a write job by the main brain is still refused by the turn guards (owner's words).
7. Every agent appears on Modelli as `agente.<modulo>` and follows «Uso generale» until changed.
8. Unit tests for all of the above with fake models; precheck 0 failed; CI green.
