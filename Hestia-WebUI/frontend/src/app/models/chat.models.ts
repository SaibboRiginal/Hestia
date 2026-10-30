// ── Chat Message ──────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: Date;
  thinkingSteps?: ThinkingStep[];
  isStreaming?: boolean;
  domain?: string;
  sessionId?: string;
  /** System notices (memory saved, action done…) attached to this answer. */
  notices?: ChatNotice[];
  /** Oracle offline: id of the queued message this placeholder waits for (SPEC oracle-offline). */
  queuedId?: number;
  /** hx-icon drawn before a user bubble (paperclip = file, zap = command); never an emoji in the text. */
  icon?: string;
  /** The answer failed: drawn with an alert icon in the danger colour. */
  error?: boolean;
  /** A voice message (dossier modulo-voce §7.2): local recording, shown as an audio bubble with its transcript. */
  audio?: { url: string; seconds: number };
  /** The voice message is being transcribed (the text arrives, then it is sent like a typed one). */
  transcribing?: boolean;
  /** What this answer changed, each with its «Annulla» (Oracle `changes` frame, Cindy 13). */
  changes?: ChatChange[];
  /** Who started this turn when it was not you typing (routine, module, external AI — Cindy 6). */
  origin?: { kind: string; level: string; label: string };
  /** Oracle's id of this turn: 👍/👎 send it so the vote lands on this answer (training dataset). */
  traceId?: string;
}

/** One write of an answer: `undo` runs a tool through Hestia-MCP («Annulla»); `done` once undone. */
export interface ChatChange {
  tool: string;
  title: string;
  detail: string;
  undo: { tool: string; args: Record<string, unknown>; label: string } | null;
  done?: boolean;
}

/** Standard Oracle `notice` packet — see Hestia-Shared/hestia-shared.md § Response packets. */
export interface ChatNotice {
  id: string;
  kind: string;                       // memory.saved · action.done · subscription.added · info · error …
  level: 'info' | 'success' | 'warning' | 'error';
  icon: string;                       // hx-icon name
  emoji?: string;
  title: string;
  detail?: string;
  data?: any;
}

// ── Thinking / Chain of Thought — Mistral-style ───────────────────────────

export interface ThinkingStep {
  stepNumber: number;
  type: 'reasoning' | 'tool_call' | 'tool_result';
  content: string;
  tool?: string;
  turn: number;
  metadata?: ThinkingMetadata;
  isExpanded: boolean;
}

export interface ThinkingMetadata {
  ok?: boolean;
  result_count?: number;
  duration_ms?: number;
}

// ── SignalR / Server Events ───────────────────────────────────────────────

export type ServerEventType =
  | 'queued'
  | 'queued_answer'
  | 'token'
  | 'status'
  | 'thinking'
  | 'signal'
  | 'question'
  | 'final'
  | 'error'
  | 'needs_input'
  | 'notice'
  | 'resume'
  | 'changes'
  | 'stream_done';

export interface ServerEvent {
  type: ServerEventType;
  text?: string;
  content?: string;
  reply?: string;
  domain?: string;
  session_id?: string;
  action?: string;
  turn?: number;
  tool?: string;
  event?: string;
  question_id?: string;
  header?: string;
  prompt?: string;
  options?: Array<string | { label?: string; value?: string }>;
  /** question: free_text | single_choice | multi_choice | confirm · notice: memory.saved, action.done… */
  kind?: string;
  level?: 'info' | 'success' | 'warning' | 'error';
  icon?: string;
  emoji?: string;
  title?: string;
  detail?: string;
  required?: boolean;
  timeout_sec?: number;
  /** question: choice kinds that also take a free answer («Altro…»). */
  allow_other?: boolean;
  missing_fields?: string[];
  data?: any;
  metadata?: ThinkingMetadata;
  /** queued / queued_answer (Oracle offline). */
  queue_id?: number;
  /** queued_answer: every queued message the one answer covers (answered together, v3 C). */
  queue_ids?: number[];
  position?: number;
  message?: string;
  /** changes frame: what the answer changed. */
  items?: ChatChange[];
  /** final: origin of a turn not typed by the owner. */
  origin?: { kind: string; level: string; label: string };
  /** final: Oracle's id of the turn (a vote sends it back: training dataset). */
  trace_id?: string;
}

/** Interactive question asked by Oracle mid-stream (answered via SignalR question_answer). */
export interface PendingQuestion {
  questionId: string;
  header: string;
  prompt: string;
  kind: 'free_text' | 'single_choice' | 'multi_choice' | 'confirm';
  options: { label: string; value: string }[];
  required: boolean;
  /** Choice kinds: also accept a free answer («Altro…»). */
  allowOther?: boolean;
  expiresAt?: number;
}

// ── WebSocket messages (client → server) ──────────────────────────────────

export interface ClientMessage {
  type: 'chat' | 'cancel' | 'retry' | 'question_answer';
  message?: string;
  session_id?: string;
  mode?: string;
  model?: string;
  question_id?: string;
  answer?: string;
  /** "Crea con Hestia" drawer: page context packet, appended to this turn's client instructions. */
  context?: string;
}

// ── Session ───────────────────────────────────────────────────────────────

export interface SessionInfo {
  sessionId: string;
}

// ── Settings ──────────────────────────────────────────────────────────────

export interface SessionSettings {
  tone: string;
  customPrompt: string;
  thinkingDisplay: string;
}

// ── Commands ──────────────────────────────────────────────────────────────

export interface CommandInfo {
  command: string;
  title: string;
  description: string;
  method: string;
  path: string;
  clients: string[];
  responseMode: string;
  group?: string;
}
