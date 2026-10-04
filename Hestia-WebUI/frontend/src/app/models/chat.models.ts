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
  | 'token'
  | 'status'
  | 'thinking'
  | 'signal'
  | 'question'
  | 'final'
  | 'error'
  | 'needs_input'
  | 'notice'
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
  missing_fields?: string[];
  data?: any;
  metadata?: ThinkingMetadata;
}

/** Interactive question asked by Oracle mid-stream (answered via SignalR question_answer). */
export interface PendingQuestion {
  questionId: string;
  header: string;
  prompt: string;
  kind: 'free_text' | 'single_choice' | 'multi_choice' | 'confirm';
  options: { label: string; value: string }[];
  required: boolean;
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
