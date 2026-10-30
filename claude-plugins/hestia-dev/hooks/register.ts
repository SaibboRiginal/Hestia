// «hestia-dev» guards (docs/work/2026-10-30-hestia-in-claude §3.8): CLAUDE.md «never touch .env, tokens, data/
// folders; never commit secrets» made a refusal instead of a hope. Only inside a Hestia checkout.
import type { Register } from 'claude-code'

// .env and its variants (.env.example is the documented template and stays editable), any data/ folder.
export const PROTECTED = /(^|[\\/])(\.env(\.(?!example$)[^\\/]+)?|data)($|[\\/])/
// Compared as strings: a build without one of these tools still loads the guard.
const FILE_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])
const TOKEN_LIKE = /(hst_|hso_|hsr_)[A-Za-z0-9_-]{16,}|sk-ant-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|\b\d{8,10}:[A-Za-z0-9_-]{35}\b/

export const register: Register = on => {
  on('tool.call', async ($, e, next) => {
    if (!FILE_TOOLS.has(String(e.tool))) return next(e)
    const path = String((e as { file_path?: string; notebook_path?: string }).file_path ?? (e as { notebook_path?: string }).notebook_path ?? '')
    if (PROTECTED.test(path)) return { deny: `hestia-dev: ${path} is a secret or data path; CLAUDE.md says never touch it.` }
    const text = String((e as { content?: string; new_string?: string }).content ?? (e as { new_string?: string }).new_string ?? '')
    if (TOKEN_LIKE.test(text)) return { deny: 'hestia-dev: this text looks like a token or key; secrets go in .env only.' }
    return next(e)
  }).catch(($, e, next) => (next.called ? next(e) : { deny: 'hestia-dev: its guard failed.' }))

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    if (/\bgit\s+push\b/.test(e.command) && !/precheck\.py/.test(e.command)) {
      $.ui.toast('Hestia: run python tools/governance/precheck.py before pushing (0 failed).')
    }
    return next(e)
  })
}
