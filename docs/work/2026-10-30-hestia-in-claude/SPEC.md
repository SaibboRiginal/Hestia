# SPEC — Hestia inside Claude: a mod with a Hestia band, on-demand persona, shared memory, and a marketplace

| | |
|---|---|
| **Version** | 2.1 |
| **Source** | User via external chat (project thread «Progettare un marketplace Claude per Hestia», 2026-10-30) |
| **Status** | Approved 2026-10-30 (Marko, cards) — implemented, see PROGRESS.md; Marko real run pending |

Versioning: minor = refinement, major = scope/design change.

| Version | Date | Change | Reason |
|---|---|---|---|
| 1.0 | 2026-10-30 | Plugin `hestia` (MCP + 5 skills + commands) + `hestia-dev` + marketplace | first request |
| 2.1 | 2026-10-30 | Answers: three modes, default *off*, Claude memory import only on command with preview. Implementation details: cap is `oracle.chat.profile_max_tokens` (group Contesto, advanced); the Memoria page already filters by origin (no change); the mod's MCP server uses OAuth only (no token header in the plugin); prompt section refreshed per request (no invalidate needed); `check.py` replaced by `claude plugin validate` + `claude plugin test` (the plugins' own tests), CI has no Claude CLI | Marko's answers on the cards; what the code showed |
| 2.0 | 2026-10-30 | Main piece becomes a **Claude Code mod** (function hooks): band above the prompt with modes like Ponytail v5, Hestia persona only when switched on, near-zero context when off, persona/instructions/memory served live by Hestia like Oracle, shared memory both ways, icon coherent with the README. Skills of plugin `hestia` dropped (their know-how is served by Hestia when on). | Marko: "like Ponytail v5" (screenshot of its band), "only when I want", "don't eat context", "work like Oracle", share memory, personality and system instructions |

User's words (summary, Italian originals in the thread): (v1) can we build something like Ponytail v5's add-on for Claude,
plus skills, a real Claude marketplace for Hestia? (v2) I meant the kind of add-on Ponytail v5 is; the repo is public so
I can add it; it needs a nice icon there too, coherent with the README. I want Claude to act and **impersonate Hestia,
only when I want** — not every chat pulling Hestia in, and having it installed must not eat much context. Personality
etc. should work a bit like Oracle, and the idea is to **share Claude's and Hestia's memory**, personality and system
instructions.

---

## 1. Today (verified in code, main `e678d9e`)

- **Hestia-MCP** is the only MCP server; external door WebUI `POST /mcp` → Hub → `/mcp/external`. Auth: access token
  `hst_…` or **OAuth 2.1** (consent card on *Accessi AI*). 15 tools open to external AIs (Forge 8, `system_status`,
  `system_log`, `settings_search|get|propose`, `memory_note`, `memory_recall`).
- **Oracle** builds every reply's system prompt from: persona `analyst_persona_default` and style contract
  `conversation_style_contract` (`app/core/services/prompt_config.py`, file overrides), the user's tone and instructions
  `oracle.chat.*` (Themis, `_with_personal_settings` in `app/main.py`), one line of presence, and memory. None of this is
  available to an external AI today.
- What Ponytail v5 is (from Marko's screenshot): a **Claude Code mod** — a plugin of function hooks that draws a band
  above the prompt (mode pills *off · lite · full · ultra*, buttons *Copy · Review · Audit · Board · Compact*, live cost,
  tokens, agent time). Claude Code mods can: draw that band (`ui.render` `AbovePrompt`) and panes; add or drop a
  **system-prompt section** per session (`prompt.compose`); add context blocks (`prompt.context`); move a tool **behind
  ToolSearch** or back (`tool.describe` `isDeferred`); allow/deny tool calls (`tool.call`); call an MCP server
  (`$.mcp.call`); register slash commands; keep state per session and across sessions; draw on terminal, desktop app,
  VS Code and mobile. Installed from a GitHub marketplace in one line.

## 2. Goal

Install once from the public repo; nothing changes in normal chats. Press **Hestia** on the band and that Claude
session *becomes* Hestia: her personality, Marko's tone and instructions, her memory of Marko, her tools — the same
things Oracle uses, served live by Hestia, so changing them in Hestia changes Claude too. Press **off** and it is plain
Claude again. What Claude learns about Marko in Hestia mode goes back into Hestia's memory.

## 3. Design

### 3.1 Pieces

```
.claude-plugin/marketplace.json     marketplace "hestia" (owner SaibboRiginal) → lists the two plugins
claude-plugins/
  hestia/                           THE MOD (function hooks) + MCP connection
    .claude-plugin/plugin.json      name, version, description, types, userConfig (url)
    .mcp.json                       server "hestia": http, "${user_config.url}/mcp"  (OAuth)
    hooks/hooks.json                { "modules": ["./register.tsx"] }
    hooks/register.tsx              band, modes, persona section, memory, commands
    types/index.d.ts                state contract (mode, persona cache, counters)
    assets/hestia.svg               the icon (same flame mark and palette as the README banner)
    README.md                       banner + install lines
  hestia-dev/                       plugin for working ON the repo (skills + guard hooks), unchanged from v1 §4.3
tools/claude_plugins/check.py       validation for precheck + CI
```

Install (README, from the repo):
`/plugin install hestia --marketplace SaibboRiginal/Hestia` (terminal) · Desktop app: **+** → Plugins → Add marketplace
`SaibboRiginal/Hestia` → Add plugin. The install screen asks one option, **Indirizzo di Hestia** (the tunnel hostname):
it lives in Claude's plugin settings on Marko's machine, never in the repo. First use opens Hestia's OAuth consent
(*Accessi AI* → *Consenti*): no token pasted, revocable there.

### 3.2 The band (above the prompt)

Same shape as Ponytail's, Hestia's look:

```
[flame]  off · strumenti · Hestia               Ricorda   Memoria   Stato   Sviluppo
         Hestia online · 2 task in coda · 14 ricordi in questa sessione
```

- **Modes** (pills, remembered per session; the default for new sessions is a mod option, default *off*):
  - **off** — nothing of Hestia reaches the model: no persona section, Hestia tools moved behind ToolSearch and their
    calls refused. Context cost ≈ zero (only deferred tool names, which ToolSearch already hides). The band shows
    only the small flame + pills (or hides fully with a *nascondi* setting, still reachable with `/hestia`).
  - **strumenti** — Claude stays Claude but has Hestia's tools loaded (Forge, health, settings, memory). For coding
    sessions where you want to file a Forge task or read a log without the persona.
  - **Hestia** — Claude *is* Hestia: persona + Marko's instructions + memory digest added as one session section,
    tools loaded. The band's flame lights up in the accent colour.
- **Buttons**: *Ricorda* (selected text or last answer → `memory_note`), *Memoria* (pane with what Hestia remembers,
  searchable, from `memory_recall`), *Stato* (health + Forge queue pane), *Sviluppo* (Forge tasks pane, open task diff).
- **Line 2**: Hestia reachable or not («Non disponibile», never module names), Forge queue, memory written this session.
- Icons: the same stroke icon set as the WebUI/README (`docs/assets/icons`), toned; **no emoji** (Marko's rule).
- Surfaces: terminal, desktop app, VS Code, mobile (the mod draws per surface; terminal gets a one-line text version).

### 3.3 Persona and instructions — "like Oracle" (one source of truth)

New Oracle tool **`assistant_profile`** (external, read; `clients` incl. `"external"`), argument `client="claude"`:
returns the block Oracle itself uses, built by the same code — persona, style contract, Marko's tone and instructions
(`oracle.chat.*`), presence line, plus a **client contract for Claude** (new prompt key
`client_contract_claude`, caveman style: who you are inside Claude, which Hestia tools exist and when to use them,
what you may not do: approve, merge, change settings without a proposal). Also a `revision` hash.

The mod, in Hestia mode, adds it with `prompt.compose` as one `session` section, cached by `revision` (refetched at
session start, on mode switch, and when the band's *Aggiorna* or a `revision` change on any call is seen). So: change
Hestia's tone in Impostazioni → next Claude turn in Hestia mode speaks the new way. Claude's own base prompt stays (its
tools and safety); the Hestia section sits on top, the same layering Oracle's `claude -p` provider already uses.

Budget: the section has a cap (Themis `oracle.chat.profile_max_tokens`, default ~1500) — the "do not eat context"
rule holds even when on.

### 3.4 Shared memory, both ways

- **Hestia → Claude** (Hestia mode only): `assistant_profile` includes a short **memory digest** (top facts about Marko
  by weight/recency, capped). During the turn Claude calls `memory_recall` for more (as Oracle does).
- **Claude → Hestia**: Claude calls `memory_note` when it learns a lasting fact (taught by the client contract); the
  band's *Ricorda* does it by hand. Notes are saved at once, quiet inbox entry, undoable on page Memoria (existing
  memory_note rules, unchanged). Source shows as «Claude (AI esterna)».
- **Claude's own memory**: Claude Code keeps memory as local files (CLAUDE.md, auto-memory). The mod's command
  `/hestia importa-memoria` reads them, shows the facts it would send, and on ok sends them with `memory_note` (one fact
  per line, no secrets, no code paths). The reverse — writing Hestia's memory into Claude's files — is **not** done:
  in Hestia mode the digest is injected live, so a second copy would only drift. claude.ai's chat memory cannot be read
  by any plugin; there the Hestia connector + memory tools are the bridge (§3.6).

### 3.5 What Hestia gets (small)

| Module | Change |
|---|---|
| Oracle | `assistant_profile` tool (external), prompt key `client_contract_claude`, Themis `oracle.chat.profile_max_tokens` |
| Hestia-MCP | nothing new for the mod (same door, OAuth, audit); *Accessi AI* gains a «Claude (mod)» setup block with the install lines |
| Oracle Memoria page | filter by source (Claude / Hestia) |
| docs | `hestia-oracle.md`, `hestia-mcp.md`, swagger (tool), `docs/ARCHITECTURE.md` (Hestia inside external AIs), `docs/SETUP.md` (install), readme one line + link |

No new service, no new door, no new LLM call: the mod never calls a model, Claude is the model.

### 3.6 claude.ai web / mobile chat (not Claude Code)

Mods run in Claude Code (terminal, desktop app Code tab, VS Code, cloud). In plain claude.ai chats there is no band;
there Marko adds the Hestia **connector** (OAuth, exists) and one small **skill** «Hestia» (zip from
`build_skills_zip.py`) whose only job is: when Marko says «Hestia» / «parla come Hestia», call `assistant_profile` and
follow it. Same persona and memory, switched on by asking.

### 3.7 Icon

`claude-plugins/hestia/assets/hestia.svg`: the flame mark from the README banner as a single-colour stroke icon (works
in light/dark, tinted by the band's accent), plus `banner-dark/light.png` reused in the plugin README. If the banner has
no clean vector mark, I draw one in the same style and show it to Marko before using it.

### 3.8 Plugin `hestia-dev`

Unchanged from v1.0 §4.3 (skills for the work protocol pointing to CLAUDE.md, guard hooks on `.env`/`data/`, rules
reviewer agent, Forge can load it). Its skills only load inside the Hestia repo, so they cost nothing elsewhere.

## 4. New feature checklist (`docs/REGOLE-DI-MARKO.md`)

1. Real job: talk to Hestia from Claude when wanted, with her personality and memory; Claude's learnings come home.
2. Owner modules: Oracle (persona, instructions, memory — it is the brain), Hestia-MCP (door); the mod is a client like
   Telegram/WebUI, it holds no logic of its own beyond display and switching.
3. Configuration: Themis `oracle.chat.profile_max_tokens`; mod options (address, default mode) live in Claude.
4. Push or poll: pull on demand (mode switch, session start); no loops.
5. Who confirms: unchanged — proposals via Hermes/Themis/Forge; OAuth consent per client; memory notes immediate +
   undo (existing rule).
6. WebUI: «Claude (mod)» setup block, Memoria source filter (icons, no emoji). Telegram: nothing.
7. Stop / undo: mode *off*; revoke on *Accessi AI*; `/plugin uninstall hestia`; delete notes on Memoria.
8. Docs: listed in §3.5.

## 5. Phases

| Phase | Content |
|---|---|
| P1 | Oracle `assistant_profile` + client contract + Themis cap; tests |
| P2 | Mod `hestia`: band, three modes, persona section, tool deferral, commands, panes; icon; check.py; marketplace file |
| P3 | Shared memory: digest, *Ricorda*, `/hestia importa-memoria`, Memoria source filter |
| P4 | `hestia-dev` plugin; claude.ai skill zip; *Accessi AI* setup block; docs |

## 6. Acceptance criteria

- Clean Claude Code: `/plugin install hestia --marketplace SaibboRiginal/Hestia` works; the band appears in mode *off*.
- In *off*, the system prompt has no Hestia section and no Hestia tool schema is loaded (checked with `/context`).
- *Hestia*: «chi sei?» answers as Hestia in Marko's tone; changing `oracle.chat` tone in Hestia shows on the next turn.
- «Ricordati che…» in Hestia mode → note on page Memoria with source Claude; next session in Hestia mode knows it.
- *strumenti*: `/hestia task "…"` files a Forge task as external proposal, persona absent.
- Hestia unreachable → band says «Non disponibile», Claude keeps working as plain Claude.
- `claude plugin validate`, `claude plugin test`, check.py and precheck green; no personal data in any plugin file.

## 7. Questions for Marko (answered 2026-10-30)

1. Three modes → **three** (off · strumenti · Hestia).
2. Default mode → **off**.
3. Claude's memory into Hestia → **only on command, with a preview**.
