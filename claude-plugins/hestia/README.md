<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="../../docs/assets/banner-dark.png">
    <img src="../../docs/assets/banner-light.png" alt="Hestia" width="100%">
  </picture>
</p>

# Hestia in Claude

<img src=".claude-plugin/icon.png" alt="" width="64" align="right">

A band above Claude's prompt that turns **Claude into Hestia only when you want**. Off by default: nothing of
Hestia reaches your chats and it costs no context. Switch it on and Claude speaks with Hestia's personality,
your tone and instructions, and what Hestia remembers about you — the same things Hestia uses herself, read
live from your Hestia. What Claude learns about you goes back into Hestia's memory.

| Mode | What Claude gets |
|---|---|
| **off** | nothing: plain Claude, Hestia's tools refused |
| **strumenti** | Hestia's tools (development tasks, system health, settings proposals, memory), Claude's own voice |
| **Hestia** | the tools, plus Hestia's personality, your instructions and a short memory digest |

Buttons: **Ricorda** (Claude saves the lasting facts of this chat into Hestia), **Memoria**, **Stato**, **Sviluppo**.
Command: `/hestia on · strumenti · off · ricorda [fatto] · memoria [parole] · stato · sviluppo · importa-memoria · aggiorna`.
`importa-memoria` shows the personal facts in Claude's own memory and saves them into Hestia only after your ok.

## Install

In a terminal session of Claude Code:

```
/plugin install hestia --marketplace SaibboRiginal/Hestia
```

From a shell: `claude plugin install hestia --marketplace SaibboRiginal/Hestia`.
Desktop app: **+** next to the prompt → Plugins → Add marketplace `SaibboRiginal/Hestia` → Add plugin.

The install asks for **Indirizzo di Hestia** (your public address, e.g. `https://hestia.example.org`) and the
starting mode. The first time Hestia is switched on, your browser opens Hestia's consent page (*Accessi AI*):
press *Consenti*. You can revoke it there at any time.

## Privacy

The plugin talks only to **your own** Hestia, at the address you give, through Hestia's MCP door with the
OAuth grant you approve. It sends nothing anywhere else and stores nothing outside Claude's own session
state. While the mode is *off* it makes no network call at all. Notes Claude saves are listed on Hestia's
*Memoria* page, where you can delete them.

## Develop

```
claude --plugin-dir claude-plugins/hestia     # run it from the repo
claude plugin validate claude-plugins/hestia
claude plugin test claude-plugins/hestia
```

Design and decisions: `docs/work/2026-10-30-hestia-in-claude/SPEC.md`.
