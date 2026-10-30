import { expect, test } from 'claude-code/testing'

test('secrets and data paths are refused, normal files pass', async ($, on) => {
  on('tool.call', () => ({ result: {} }))
  on('ui.toast', () => ({ value: undefined }))
  const env = await $.tool.call({ tool: 'Edit', file_path: '/repo/.env', old_string: 'a', new_string: 'b' } as any)
  expect((env as any).deny).toBeDefined()
  const data = await $.tool.call({ tool: 'Write', file_path: '/repo/Hestia-Archive/data/db.sqlite', content: 'x' } as any)
  expect((data as any).deny).toBeDefined()
  const token = await $.tool.call({ tool: 'Write', file_path: '/repo/a.py', content: 'T = "hst_abcdefghijklmnopqrstuvwxyz"' } as any)
  expect((token as any).deny).toBeDefined()
  const example = await $.tool.call({ tool: 'Edit', file_path: '/repo/.env.example', old_string: 'a', new_string: 'b' } as any)
  expect((example as any).deny).toBeUndefined()
  const ok = await $.tool.call({ tool: 'Write', file_path: '/repo/Hestia-Oracle/app/main.py', content: 'x = 1' } as any)
  expect((ok as any).deny).toBeUndefined()
})
