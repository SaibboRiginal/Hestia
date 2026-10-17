#!/usr/bin/env node
/**
 * Hestia WebUI SDK build (esbuild).
 *
 *   node build.mjs runtime [outdir]            → <outdir>/sdk.js  (SDK + Lit, served once by the WebUI at /plugins/_sdk/sdk.js)
 *   node build.mjs plugin <entry.ts> <out.js>  → a module's bundle; `@hestia/webui-sdk` and `lit*` stay external
 *                                                (the WebUI import map points them to the shared runtime)
 *
 * Module Dockerfiles run the plugin build in a Node stage (SPEC §4.4); dist/ is never committed.
 */
import { build } from 'esbuild';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const [mode, a, b] = process.argv.slice(2);
const common = { bundle: true, format: 'esm', target: 'es2022', minify: true, sourcemap: false, legalComments: 'none',
                 tsconfigRaw: { compilerOptions: { useDefineForClassFields: false, experimentalDecorators: true } } };

if (mode === 'runtime') {
  const outfile = resolve(a || resolve(here, 'dist'), 'sdk.js');
  await build({ ...common, entryPoints: [resolve(here, 'src/index.ts')], outfile });
  console.log(`event=webui_sdk_built out=${outfile}`);
} else if (mode === 'plugin' && a && b) {
  await build({ ...common, entryPoints: [resolve(a)], outfile: resolve(b), external: ['@hestia/webui-sdk', 'lit', 'lit/*'] });
  console.log(`event=webui_plugin_built entry=${a} out=${b}`);
} else {
  console.error('usage: node build.mjs runtime [outdir] | node build.mjs plugin <entry.ts> <out.js>');
  process.exit(2);
}
