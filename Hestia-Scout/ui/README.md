# Scout WebUI plugin

Pages *Case*, *Annuncio*, *Statistiche case*; widgets *Case in numeri*, *Nuove case*, *Case preferite*,
*Prezzi per città*; quick actions declared in `app/ui_api.py`. Contract: `docs/work/2026-10-17-client-plugins/SPEC.md`.

Built in Scout's Docker image (Node stage) with the shared SDK:

    node ../../Hestia-Shared/webui-sdk/build.mjs plugin src/index.ts dist/webui/scout.js

Type check (after `npm ci` in `Hestia-Shared/webui-sdk`): `npx -p typescript tsc -p .` from this folder.
`dist/` is git-ignored.
