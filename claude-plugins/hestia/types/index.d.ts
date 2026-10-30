// State contract of the «hestia» mod (docs/work/2026-10-30-hestia-in-claude).

export type HestiaMode = 'off' | 'strumenti' | 'hestia'

export type HestiaProfile = {
  revision: string
  text: string
  tokens: number
  memories: number
  at: number
}

export type HestiaStatus = {
  online: boolean
  services: string
  queue: number | null
  at: number
}

export type HestiaRow = { title: string; detail: string }

declare module 'claude-code' {
  interface PluginState {
    hestia: {
      mode: HestiaMode | null
      profile: HestiaProfile | null
      status: HestiaStatus | null
      notes: number
      pane: { kind: 'memoria' | 'stato' | 'sviluppo'; rows: HestiaRow[]; error: string } | null
      busy: string
    }
  }
}
