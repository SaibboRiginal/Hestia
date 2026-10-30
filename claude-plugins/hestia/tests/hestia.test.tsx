import { expect, test } from 'claude-code/testing'

// The engine beneath the mod: Hestia's MCP answers like Hestia-MCP does (text block + structuredContent).
const answers: Record<string, unknown> = {
  assistant_profile: { revision: 'r1', text: 'Sei Hestia, assistente personale.', tokens_estimate: 9, memories: 2 },
  system_status: { healthy_count: 9, unhealthy_count: 0, services: {} },
  forge_status: { queue: ['a', 'b'] },
  memory_note: { saved: [{ fact: 'Ama il caffè' }], skipped: [] },
}

const engine = (on: any) => {
  on('command.register', (_: unknown, e: { name: string }) => ({ value: { command: e.name } }))
  on('session.start', (_: unknown, e: { cwd: string }) => ({ cwd: e.cwd }))
  on('mcp.connect', () => ({ value: { isConnected: true, server: 'plugin:hestia:hestia' } }))
  on('mcp.call', (_: unknown, e: { tool: string }) => {
    const out = answers[e.tool] ?? {}
    return { value: { content: [{ type: 'text', text: JSON.stringify(out) }], isError: false, structuredContent: out } }
  })
  on('prompt.compose', () => ({ sections: [{ id: 'intro', text: 'You are Claude.', scope: 'shared' }] }))
  on('tool.check', () => ({ decision: 'allow' }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('clock.now', () => ({ value: 1_000 }))
  on('ui.render', ($: any, e: any) => {
    const { Box } = $.ui.resolve(e)
    return <Box />
  })
}

const OPTIONS = { options: { url: 'https://hestia.example.org', default_mode: 'off' } }
const TOOL = 'mcp__plugin_hestia_hestia__memory_recall'
const compose = { model: 'm', promptModel: 'm', surfaces: [], tools: [], outputStyle: null, traits: [] }

test('off: no persona and Hestia tools refused', OPTIONS, async ($, on) => {
  engine(on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const sections = (await $.prompt.compose(compose as any)).sections
  expect(sections.map(s => s.id)).toEqual(['intro'])
  expect((await $.tool.check({ tool: TOOL, input: {} } as any)).decision).toBe('deny')
  expect((await $.tool.check({ tool: 'Bash', input: { command: 'ls' } } as any)).decision).toBe('allow')
})

test('Hestia: persona section from assistant_profile, tools allowed', OPTIONS, async ($, on) => {
  engine(on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const { text } = await $.command.run({ command: 'hestia', args: 'on' })
  expect(text).toContain('Sono Hestia')
  const sections = (await $.prompt.compose(compose as any)).sections
  expect(sections.at(-1)?.id).toBe('hestia:persona')
  expect(sections.at(-1)?.text).toContain('Sei Hestia')
  expect((await $.tool.check({ tool: TOOL, input: {} } as any)).decision).toBe('allow')
})

test('strumenti: tools without persona; ricorda saves through memory_note', OPTIONS, async ($, on) => {
  engine(on)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'hestia', args: 'strumenti' })
  expect((await $.prompt.compose(compose as any)).sections.map(s => s.id)).toEqual(['intro'])
  expect((await $.tool.check({ tool: TOOL, input: {} } as any)).decision).toBe('allow')
  const { text } = await $.command.run({ command: 'hestia', args: 'ricorda Ama il caffè' })
  expect(text).toBe('Ricordato in Hestia (1).')
})

test('the band draws the three modes on every surface, and switches', OPTIONS, async ($, on) => {
  engine(on)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({
      plugin: 'hestia', surface, component: 'AbovePrompt', requestId: 'band',
      props: { hasSurvey: false, isWorking: false, maxRows: 10, bodyColumns: 80, scroll: { offset: 0, bodyRows: 10 } },
    } as any)
    expect(await ui.find({ key: 'mode-off' })).toBeDefined()
    expect(await ui.find({ key: 'mode-hestia' })).toBeDefined()
    expect(await ui.find({ key: 'ricorda' })).toBeUndefined()
    await ui.unmount()
  }
})
