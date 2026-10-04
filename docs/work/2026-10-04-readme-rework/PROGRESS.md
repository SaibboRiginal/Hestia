# Progress

- [x] Read old readme, compose files, env templates, service docs
- [x] Move old readme → `docs/ARCHITECTURE.md` (+ WebUI section, header, rules-doc pointer)
- [x] Governance gate + CLAUDE.md + AI-GUIDE + Forge prompt point to `docs/ARCHITECTURE.md`
- [x] `tools/init_env.py` (tested on a scratch copy: creates 8 files, second run creates 0)
- [x] `.env.example` for root, Telegram, Scout
- [x] New `readme.md` (all relative links checked)
- [x] Root CHANGELOG line
- [x] v1.1 MIT LICENSE + badge
- [x] v1.1 chat id only in Telegram: `owner` alias (Telegram resolve, Hermes/Chronos/Argus defaults, compose, legacy subscription cleanup, docs, regression test — not run, user rule)
- [ ] Owner: after deploy, check one reminder/alert still arrives (needs Telegram, Hermes, Chronos, Argus restart)
