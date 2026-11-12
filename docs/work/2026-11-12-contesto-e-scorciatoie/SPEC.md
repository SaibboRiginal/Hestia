# SPEC — Contesto letto dal programma locale e scorciatoie alle impostazioni

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | user via external chat (thread «Sistemare i feedback sulla WebUI», points 13–17 of the plan agreed there) |
| **Status** | Implemented (owner's real run pending) |

Versioning: minor = refinement, major = scope/design change. Every bump goes in `CHANGELOG.md` (this folder).

## 1. Today (verified in code, before this work)

- Oracle sent `num_ctx` = setting `oracle.provider.ollama.num_ctx` (default 8192) on **every** Ollama call. The owner
  had set 64k in Ollama: Hestia replaced it with 8k, and a ~49k prompt was cut by Ollama without any error.
- The agent loop used that same local window for budget and compaction whatever model answered (a cloud model with
  a million tokens was compacted at 8k).
- `/api/chat/context`: the total came from the real call, the rows under it (tools = count × 120 chars, fixed 3,500
  chars of system) from a different rough guess, so they did not add up. The session total was marked «estimated»
  when a single call was, and the WebUI then wrote «Ollama: …» whatever model answered.
- WebUI: a single link to a setting in the whole app (Aggiornamenti → «cambia»). Impostazioni opened at most on a
  module (`?tab=system&module=`), never on one setting. No module page linked to its settings. The palette did not
  know settings.

## 2. Goal

The owner sets a thing once, where it naturally lives, and from any place that shows a value he reaches the setting
that changes it in one tap.

## 3. Scope and design

### 3.1 Window of the local model (Oracle)
- `core/services/local_window.py`. `oracle.provider.ollama.num_ctx`: default **0 = automatica** (label «Modello
  locale · finestra di contesto»). Automatic: no `num_ctx` in the request; the real window is read from Ollama
  `/api/ps` after the calls (background thread, ≤ 1 read / 30 s, 2 s timeout, never raises).
- Floor 8192: if Ollama's **own** window is smaller (bare install), Oracle asks for 8192 on every call (the old
  behaviour), remembers that the 8192 it then sees is its own (no reload ping-pong) and reads Ollama's own value
  again every 6 h. Before the first read the budget uses 8192.
- A number in the setting forces the window (sent on every call).
- OpenAI-compatible local servers: LM Studio `/api/v0/models`, llama-server `/props`, vLLM `/v1/models`; cached 60 s.
- `runtime_info(name, fallback, model)` adds `window_source`; `run_agent_loop(context_window=…)` = window of the
  answering model; Forge's `usecase_status` and the usage rows use the same source.
- Decision: no new setting and no new env. Not done: reading the window of a model that is not loaded (Ollama has
  no API for its server default); the first call after a start tells.

### 3.2 Context gauge (Oracle + WebUI)
- Agent loop notes what each prompt is made of (`llm_stats.note_breakdown`: system, tools, history, message,
  results, other); `/api/chat/context` returns `breakdown` scaled to the measured size (rows add up),
  `breakdown_measured`, `window_source`, `window_setting_key`, `over_window`; `session_usage.by_model`.
- WebUI popover: coloured stacked bar + legend with the same colours (theme tokens), free space, source of the
  window with shortcut, warning over the window, usage per model with «stimati» only where true.

### 3.3 Shortcuts to settings (WebUI + SDK)
- One component `<hx-setting-link>` (`ui/setting-link.component.ts`): `key` | `module` | `section`+`row`.
- Impostazioni: `/settings?key=<central key>` and `?section=&row=` open the right view, clear the filters, open
  «Avanzate» when needed, scroll to the setting and mark it for ~3.5 s (`.hx-flash`, reduced-motion aware). Works
  also while the page is open.
- Placed: context popover (model → Oracle's settings; window → its setting), chat mode picker («predefinita»),
  chat quick settings («predefinito» per row, «su questo browser»), one gear on **every module page** (drawn once by
  `plugin-page.component.ts` when the module has settings; SDK `.page` keeps the title line clear with
  `--head-inset-end`). SDK host: `openSetting(key?)`.
- Palette Ctrl+K: every central and personal setting, found by name, help or key, only while typing, name matches
  first. Personal rows moved to `features/settings/personal-rows.ts` (data, shared by page and palette).
- Not in this version (stay in the plan of the thread, sidebar/voice PR): shortcuts for Ascolta/Parla voice and the
  Notifiche page header beyond the common module gear.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)
1. Real job for the owner: his Ollama window is respected; he finds any setting from where he is.
2. Owner module (R1): Oracle (window, gauge data); WebUI (presentation, shortcuts).
3. Configuration: existing Themis setting, new default 0; no switch, no env.
4. Push or poll; automatic and manual: read after Oracle's own calls (no timer, no loop).
5. Who confirms: nothing is changed for the owner; shortcuts only open the setting.
6. WebUI: stroke icons only (settings, alert). Telegram: unchanged.
7. Stop, correct, undo: a number in the setting forces the window; history/undo of the setting as before.
8. Docs: hestia-oracle.md, hestia-webui.md, DESIGN-SYSTEM.md, webui-sdk README, swagger, ARCHITECTURE, TESTING.

## 5. Acceptance criteria
- Ollama set to 64k, Hestia setting 0 → requests carry no `num_ctx`, gauge shows 65.5k «letta dal programma».
- Bare Ollama (4096) → Hestia asks 8192, gauge says so, no reload at every call.
- Gauge rows add up to the total; over the window a red notice appears.
- From the gauge, «cambia» lands on the highlighted setting; Ctrl+K «contesto» lists it.
- Every module page with settings has the gear.
