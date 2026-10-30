// «hestia» mod: Hestia inside Claude, only when you switch her on.
// SPEC docs/work/2026-10-30-hestia-in-claude. One door: Hestia's MCP (OAuth on «Accessi AI»); the mod holds no
// logic of Hestia's own, it switches, draws and forwards. Persona, instructions and memory come from Oracle's
// tool `assistant_profile`, so changing them in Hestia changes Claude at the next turn.
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { HestiaMode, HestiaProfile, HestiaRow, HestiaStatus } from '../types'

const mode = atom({ plugin: 'hestia', key: 'mode' } as const, null)
const profile = atom({ plugin: 'hestia', key: 'profile' } as const, null)
const status = atom({ plugin: 'hestia', key: 'status' } as const, null)
const notes = atom({ plugin: 'hestia', key: 'notes' } as const, 0)
const pane = atom({ plugin: 'hestia', key: 'pane' } as const, null)
const busy = atom({ plugin: 'hestia', key: 'busy' } as const, '')

const PANE = 'hestia-pane'
const MODES: { id: HestiaMode; label: string }[] = [
  { id: 'off', label: 'off' },
  { id: 'strumenti', label: 'strumenti' },
  { id: 'hestia', label: 'Hestia' },
]
const PROFILE_TTL_MS = 10 * 60 * 1000
const STATUS_TTL_MS = 60 * 1000
const ACCENT = '#C07A3A'
// Hestia's mark (WebUI logo): outer diamond stroke, inner diamond filled, amber like the README banner.
const LOGO =
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="18" height="18">` +
  `<path d="M12 2.5 21.5 12 12 21.5 2.5 12Z" fill="none" stroke="${ACCENT}" stroke-width="1.8" stroke-linejoin="round"/>` +
  `<path d="M12 7.2 16.8 12 12 16.8 7.2 12Z" fill="${ACCENT}"/></svg>`
const LOGO_OFF = LOGO.replaceAll(ACCENT, '#8A8F98')

// A Hestia tool, from this plugin's server or one the user added by hand: same Hestia, same switch.
export const isHestiaTool = (name: string): boolean => /^mcp__[^_]*_*.*hestia.*__/i.test(name)

export const parseResult = (result: { content: { type: string; text?: string }[]; isError: boolean; structuredContent?: unknown }): unknown => {
  if (result.structuredContent && typeof result.structuredContent === 'object') return result.structuredContent
  const text = result.content.map(b => (b.type === 'text' ? b.text ?? '' : '')).join('')
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export const IMPORT_PROMPT =
  "Leggi la tua memoria di Claude su di me (il mio CLAUDE.md personale in ~/.claude e i tuoi file di memoria). " +
  "Estrai SOLO fatti personali durevoli su di me: preferenze, abitudini, vincoli, persone, piani. " +
  "Niente lavoro, codice, percorsi, nomi di progetti di clienti, segreti o password. " +
  "Mostrameli come elenco numerato, frasi brevi in terza persona, e NON salvarli: aspetta il mio ok. " +
  "Al mio ok chiama lo strumento Hestia memory_note (al massimo 10 fatti per chiamata, uno per riga, topic «memoria di Claude»)."

export const REMEMBER_PROMPT =
  "Salva in Hestia (strumento memory_note) i fatti durevoli su di me emersi in questa conversazione: " +
  "frasi brevi in terza persona, niente lavoro temporaneo, codice o segreti. Se non ce ne sono, dillo in una riga."

type Cfg = { start: HestiaMode; configured: boolean }

async function currentMode($: EngineInterface, cfg: Cfg): Promise<HestiaMode> {
return (await read($, mode)) ?? cfg.start
}

async function call($: EngineInterface, tool: string, args: Record<string, unknown> = {}): Promise<unknown> {
  const server = await $.mcp.connect('hestia')
  if (!server.isConnected) throw new Error('Hestia non è collegata')
  const result = await $.mcp.call(server.server, tool, args)
  const value = parseResult(result)
  if (result.isError) throw new Error(typeof value === 'string' ? value : 'Hestia ha risposto con un errore')
  return value
}

async function loadProfile($: EngineInterface, force = false): Promise<HestiaProfile | null> {
  const cached = await read($, profile)
  const now = await $.clock.now()
  if (!force && cached && now - cached.at < PROFILE_TTL_MS) return cached
  try {
    const out = (await call($, 'assistant_profile', { client: 'claude' })) as Record<string, unknown>
    const fresh: HestiaProfile = {
      revision: String(out.revision ?? ''),
      text: String(out.text ?? ''),
      tokens: Number(out.tokens_estimate ?? 0),
      memories: Number(out.memories ?? 0),
      at: now,
    }
    if (!fresh.text) return cached
    await update($, profile, () => fresh)
    return fresh
  } catch (err) {
    $.ui.toast(`Hestia non disponibile: ${(err as Error).message}`)
    return cached
  }
}

async function loadStatus($: EngineInterface, force = false): Promise<void> {
  const cached = await read($, status)
  const now = await $.clock.now()
  if (!force && cached && now - cached.at < STATUS_TTL_MS) return
  const next: HestiaStatus = { online: false, services: '', queue: null, at: now }
  try {
    const health = (await call($, 'system_status')) as Record<string, unknown>
    const up = Number(health.healthy_count ?? 0)
    const down = Number(health.unhealthy_count ?? 0)
    next.online = true
    next.services = down ? `${up}/${up + down} servizi attivi` : 'tutto attivo'
    const forge = (await call($, 'forge_status')) as Record<string, unknown>
    next.queue = Array.isArray(forge.queue) ? forge.queue.length : null
  } catch {
    next.online = next.online && true
  }
  await update($, status, () => next)
}

async function setMode($: EngineInterface, cfg: Cfg, next: HestiaMode): Promise<string> {
  await update($, mode, () => next)
  if (next === 'off') return 'Hestia spenta: Claude è di nuovo solo Claude.'
  if (!cfg.configured) return "Manca l'indirizzo di Hestia: impostalo in /config, sezione hestia."
  void loadStatus($, true)
  if (next === 'strumenti') return 'Strumenti di Hestia attivi, voce di Claude.'
  const got = await loadProfile($, true)
  return got ? `Sono Hestia. (${got.tokens} token di profilo, ${got.memories} ricordi)` : 'Hestia non risponde: resto Claude finché non torna.'
}

async function openPane($: EngineInterface, kind: 'memoria' | 'stato' | 'sviluppo', query = ''): Promise<void> {
  await update($, pane, () => ({ kind, rows: [], error: '' }))
  void $.ui.open({ id: PANE, title: kind === 'memoria' ? 'Hestia · Memoria' : kind === 'stato' ? 'Hestia · Stato' : 'Hestia · Sviluppo' })
  try {
    let rows: HestiaRow[] = []
    if (kind === 'memoria') {
      const out = (await call($, 'memory_recall', { query })) as Record<string, unknown>
      const list = Array.isArray(out.memories) ? out.memories : Array.isArray(out.result) ? out.result : []
      rows = list.map((m: Record<string, unknown>) => ({ title: String(m.fact ?? ''), detail: String(m.since ?? '') }))
    } else if (kind === 'stato') {
      const out = (await call($, 'system_status')) as Record<string, unknown>
      const services = (out.services ?? {}) as Record<string, Record<string, unknown>>
      rows = Object.entries(services).map(([name, r]) => ({ title: name, detail: String(r.status ?? '') }))
      await loadStatus($, true)
    } else {
      const out = (await call($, 'forge_tasks', { limit: 15 })) as Record<string, unknown>
      const list = Array.isArray(out.tasks) ? out.tasks : []
      rows = list.map((t: Record<string, unknown>) => ({
        title: String(t.request ?? t.title ?? t.id ?? ''),
        detail: `${String(t.id ?? '').slice(0, 8)} · ${String(t.state ?? '')}`,
      }))
    }
    await update($, pane, () => ({ kind, rows, error: '' }))
  } catch (err) {
    await update($, pane, () => ({ kind, rows: [], error: (err as Error).message }))
  }
}

async function remember($: EngineInterface, text: string): Promise<string> {
  const facts = text.trim()
  if (!facts) {
    void $.prompt.submit({ text: REMEMBER_PROMPT })
    return 'Chiedo a Claude di salvare in Hestia i fatti di questa conversazione.'
  }
  try {
    const out = (await call($, 'memory_note', { facts, topic: 'da Claude' })) as Record<string, unknown>
    const saved = Array.isArray(out.saved) ? out.saved.length : 0
    await update($, notes, n => n + saved)
    return saved ? `Ricordato in Hestia (${saved}).` : 'Hestia lo sapeva già.'
  } catch (err) {
    return `Non salvato: ${(err as Error).message}`
  }
}

export const register: Register = (on, options) => {
  const cfg: Cfg = {
    start: (['off', 'strumenti', 'hestia'] as const).find(m => m === options.default_mode) ?? 'off',
    configured: typeof options.url === 'string' && options.url.trim() !== '',
  }

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'hestia',
      description: 'Hestia: on · strumenti · off · ricorda [fatto] · memoria [parole] · stato · sviluppo · importa-memoria · aggiorna',
      argumentHint: '[on|strumenti|off|ricorda|memoria|stato|sviluppo|importa-memoria|aggiorna]',
    })
    // Nothing reaches Hestia while off: no network, no consent prompt in sessions that never use her.
    if ((await currentMode($, cfg)) === 'hestia' && cfg.configured) void loadProfile($)
    return next(e)
  })

  on('command.run', { command: 'hestia' }, async ($, e) => {
    const [verb = '', ...rest] = e.args.trim().split(/\s+/)
    const arg = rest.join(' ')
    switch (verb.toLowerCase()) {
      case 'on':
      case 'hestia':
        return { text: await setMode($, cfg, 'hestia') }
      case 'strumenti':
      case 'tools':
        return { text: await setMode($, cfg, 'strumenti') }
      case 'off':
        return { text: await setMode($, cfg, 'off') }
      case 'ricorda':
        if ((await currentMode($, cfg)) === 'off') return { text: 'Hestia è spenta: accendila con /hestia on o /hestia strumenti.' }
        return { text: await remember($, arg) }
      case 'memoria':
      case 'stato':
      case 'sviluppo':
        if ((await currentMode($, cfg)) === 'off') return { text: 'Hestia è spenta: accendila con /hestia on o /hestia strumenti.' }
        await openPane($, verb.toLowerCase() as 'memoria' | 'stato' | 'sviluppo', arg)
        return { text: `Pannello ${verb.toLowerCase()} aperto.` }
      case 'importa-memoria':
        if ((await currentMode($, cfg)) === 'off') return { text: 'Hestia è spenta: accendila con /hestia on o /hestia strumenti.' }
        void $.prompt.submit({ text: IMPORT_PROMPT })
        return { text: 'Preparo l’anteprima della memoria di Claude: niente viene salvato senza il tuo ok.' }
      case 'aggiorna': {
        const got = await loadProfile($, true)
        await loadStatus($, true)
        return { text: got ? `Profilo aggiornato (${got.revision}).` : 'Hestia non risponde.' }
      }
      default: {
        const m = await currentMode($, cfg)
        return { text: `Hestia: ${m}. Comandi: on · strumenti · off · ricorda · memoria · stato · sviluppo · importa-memoria · aggiorna` }
      }
    }
  })

  // Off: Hestia's tools stay behind ToolSearch (the engine's own rule for MCP) and their calls are refused.
  on('tool.check', async ($, e, next) => {
    if (isHestiaTool(e.tool) && (await currentMode($, cfg)) === 'off') {
      return { decision: 'deny', reason: 'Hestia è spenta in questa sessione: chiedi di accenderla con /hestia on.' }
    }
    return next(e)
  }).catch(($, e, next) => (next.called ? next(e) : { decision: 'deny' as const }))

  // On as Hestia: one session section with Oracle's own persona, instructions and memory digest.
  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    if ((await currentMode($, cfg)) !== 'hestia') return composed
    const got = await read($, profile)
    if (!got?.text) return composed
    return {
      sections: [...composed.sections, { id: 'hestia:persona', text: got.text, scope: 'session' as const }],
    }
  })

  // A note Claude saved counts on the band; a profile older than its TTL is refreshed between turns.
  on('turn.complete', async ($, e, next) => {
    const m = await currentMode($, cfg)
    if (m === 'hestia') void loadProfile($)
    if (m !== 'off') void loadStatus($)
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    if (isHestiaTool(e.tool) && e.tool.endsWith('__memory_note') && !ran.isError && ran.deny === undefined) {
      await update($, notes, n => n + 1)
    }
    return ran
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const below = await next(e)
    if (e.props.hasSurvey) return below
    const t = $.ui.resolve(e)
    const { Box, Text, Button } = t
    const m = await currentMode($, cfg)
    const st = await read($, status)
    const count = await read($, notes)
    const wait = await read($, busy)
    const lit = m !== 'off'

    const Svg = 'Svg' in t ? t.Svg : null
    const mark = Svg ? (
      <Svg source={lit ? LOGO : LOGO_OFF} alt="Hestia" width={18} height={18} />
    ) : (
      <Text color={lit ? ACCENT : undefined} dimColor={!lit}>◈ </Text>
    )

    const pick = (id: HestiaMode) => async () => {
      await update($, busy, () => id)
      const text = await setMode($, cfg, id)
      await update($, busy, () => '')
      $.ui.toast(text)
    }

    const line = !lit
      ? ''
      : !cfg.configured
        ? "Imposta l'indirizzo di Hestia in /config"
        : wait
          ? 'Collego Hestia…'
          : st === null
            ? 'Collego Hestia…'
            : !st.online
              ? 'Non disponibile: Claude continua da solo'
              : [st.services, st.queue !== null ? `${st.queue} lavori in coda` : '', count ? `${count} ricordi salvati qui` : '']
                  .filter(Boolean)
                  .join(' · ')

    const band = (
      <Box flexDirection="column">
        <Box flexDirection="row" gap={1} alignItems="center" flexWrap="wrap">
          {mark}
          {MODES.map(o => (
            <Button key={`mode-${o.id}`} label={o.label} variant={m === o.id ? 'primary' : undefined} dimColor={m !== o.id} onPress={pick(o.id)} />
          ))}
          {lit && <Text dimColor> </Text>}
          {lit && <Button key="ricorda" label="Ricorda" onPress={async () => $.ui.toast(await remember($, ''))} />}
          {lit && <Button key="memoria" label="Memoria" onPress={() => openPane($, 'memoria')} />}
          {lit && <Button key="stato" label="Stato" onPress={() => openPane($, 'stato')} />}
          {lit && <Button key="sviluppo" label="Sviluppo" onPress={() => openPane($, 'sviluppo')} />}
        </Box>
        {line !== '' && <Text dimColor size="footnote">{line}</Text>}
      </Box>
    )
    return below ? (
      <Box flexDirection="column">
        {band}
        {below}
      </Box>
    ) : (
      band
    )
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const t = $.ui.resolve(e)
    const { Box, Text, Button } = t
    const view = await read($, pane)
    if (!view) return <Text dimColor>Niente da mostrare.</Text>
    const room = Math.max(3, (e.viewport?.rows ?? 24) - 6)
    const Input = 'Input' in t ? t.Input : null
    const input =
      view.kind === 'memoria' && Input ? (
        <Input
          key="nota"
          placeholder="Scrivi un fatto da ricordare e premi Invio"
          onSubmit={async (text: string) => {
            $.ui.toast(await remember($, text))
            await openPane($, 'memoria')
          }}
        />
      ) : null
    return (
      <Box flexDirection="column" gap={0}>
        {input}
        {view.error !== '' && <Text color="red">Non disponibile: {view.error}</Text>}
        {view.error === '' && view.rows.length === 0 && <Text dimColor>Carico…</Text>}
        {view.rows.slice(0, room).map((r, i) => (
          <Box key={`row-${i}`} flexDirection="row" gap={1}>
            <Text>{r.title}</Text>
            {r.detail !== '' && <Text dimColor>{r.detail}</Text>}
          </Box>
        ))}
        <Box flexDirection="row" gap={1}>
          <Button key="refresh" label="Aggiorna" onPress={() => openPane($, view.kind)} />
        </Box>
      </Box>
    )
  })
}
