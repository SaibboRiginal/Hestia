# hestia-dev

Skills and guards for working **on** Hestia's code with Claude Code (local, cloud, or Forge).

- Skills (loaded only when the task matches): work protocol, new module, new MCP tool, settings and agenda, UI.
  They point to `CLAUDE.md` and `docs/REGOLE-DI-MARKO.md`, which stay the source of truth.
- Guards: Edit/Write refused on `.env*` (except `.env.example`) and `data/` folders, and on text that looks like
  a token; a reminder to run `tools/governance/precheck.py` before `git push`.

Install: `/plugin install hestia-dev --marketplace SaibboRiginal/Hestia` · run from the repo:
`claude --plugin-dir claude-plugins/hestia-dev`.
