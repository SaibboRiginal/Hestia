import { uid } from '../core/uid';
import { Injectable, Injector, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { marked } from 'marked';
import { SignalRService } from './signalr.service';
import { ChatMessage, ChatNotice, ThinkingStep, ServerEvent, PendingQuestion } from '../models/chat.models';
import { NoticePrefsService } from './notice-prefs.service';
import { ToastService } from '../ui';
import { VoiceService } from './voice.service';

/**
 * Chat state over the SignalR stream. Root instance = the Chat page ("main" channel);
 * the "Crea con Hestia" drawer provides its own instance with channel "assistant".
 */
@Injectable({ providedIn: 'root' })
export class ChatService {
  /** Which chat this instance is: events are routed to the channel that sent last. */
  channel = 'main';
  private signalR = inject(SignalRService);
  private noticePrefs = inject(NoticePrefsService);
  private toast = inject(ToastService);
  private injector = inject(Injector);
  /** Last assistant message: notices (e.g. memory saved) can arrive after `final`. */
  private lastAssistantId: string | null = null;

  messages = signal<ChatMessage[]>([]);
  isStreaming = signal(false);
  currentStreamingId = signal<string | null>(null);
  pendingQuestion = signal<PendingQuestion | null>(null);
  /** Where the answer to the assistant's own question goes on (same chat, mode and page context). */
  private resumeTarget: { sessionId: string; mode: string; context?: string } | null = null;
  private restored = false;

  private thinkingBuffer: ThinkingStep[] = [];
  private stepCounter = 0;

  constructor() {
    this.signalR.events$.subscribe(event => {
      // Answers to messages queued while Oracle was offline reach every tab: the Chat page shows them.
      if (event.type === 'queued_answer') { if (this.channel === 'main') this.handleQueuedAnswer(event); return; }
      if (this.signalR.activeChannel === this.channel) this.handleEvent(event);
    });
    // Another chat took the connection: the server cancelled our stream.
    this.signalR.claims$.subscribe(ch => {
      const id = this.currentStreamingId();
      if (ch !== this.channel && id) this.finalizeStreaming(id, null);
    });
  }

  async sendMessage(text: string, sessionId: string, mode = 'auto', model = 'generic', context?: string,
                    userMessageId?: string): Promise<void> {
    this.signalR.claim(this.channel);
    this.isStreaming.set(true);
    this.thinkingBuffer = [];
    this.stepCounter = 0;

    // Create placeholder for streaming assistant message
    const streamId = uid();
    this.currentStreamingId.set(streamId);
    this.lastAssistantId = streamId;

    if (userMessageId && this.messages().some(m => m.id === userMessageId)) {
      // A voice message already on screen: its transcript becomes the text sent.
      this.messages.update(msgs => msgs.map(m => m.id === userMessageId ? { ...m, content: text, transcribing: false } : m));
    } else {
      const userMsg: ChatMessage = {
        id: uid(),
        role: 'user',
        content: text,
        timestamp: new Date()
      };
      this.messages.update(msgs => [...msgs, userMsg]);
    }

    const assistantMsg: ChatMessage = {
      id: streamId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
      thinkingSteps: []
    };
    this.messages.update(msgs => [...msgs, assistantMsg]);

    try {
      await this.signalR.send({
        type: 'chat',
        message: text,
        session_id: sessionId,
        mode,
        model,
        ...(context ? { context } : {}),
      });
    } catch (err: any) {
      // Do not leave the placeholder "streaming" forever.
      this.messages.update(msgs => msgs.map(m => m.id === streamId
        ? { ...m, isStreaming: false, error: true, content: err?.message || 'Invio non riuscito' } : m));
      this.currentStreamingId.set(null);
      this.isStreaming.set(false);
    }
  }

  /**
   * A voice message (dossier modulo-voce §7.2): the audio bubble appears at once, the voice module transcribes it
   * (recording kept with the message), then the text goes to Hestia exactly like a typed one.
   */
  async sendVoice(audio: Blob, mime: string, seconds: number, sessionId: string, mode = 'auto'): Promise<string | null> {
    if (this.isStreaming()) return null;
    const id = uid();
    this.messages.update(msgs => [...msgs, { id, role: 'user', content: '', timestamp: new Date(), transcribing: true,
                                             audio: { url: URL.createObjectURL(audio), seconds } }]);
    const voice = this.injector.get(VoiceService);
    let text = '';
    try {
      text = (await voice.transcribe(audio, mime, id)).text?.trim() || '';
    } catch { text = ''; }
    if (!text) {
      this.messages.update(msgs => msgs.map(m => m.id === id
        ? { ...m, transcribing: false, error: true, content: 'Non sono riuscita ad ascoltarlo: riprova o scrivilo.' } : m));
      return null;
    }
    await this.sendMessage(text, sessionId, mode, 'generic', undefined, id);
    return text;
  }

  /** Upload a file for analysis: POST /api/webui/chat/document, NDJSON streamed back. */
  async sendDocument(file: File, text: string, sessionId: string): Promise<void> {
    if (this.isStreaming()) return;
    this.isStreaming.set(true);
    this.thinkingBuffer = [];
    this.stepCounter = 0;
    const streamId = uid();
    this.currentStreamingId.set(streamId);
    this.lastAssistantId = streamId;
    this.messages.update(msgs => [...msgs,
      { id: uid(), role: 'user', icon: 'paperclip', content: `${file.name}${text ? ' — ' + text : ''}`, timestamp: new Date() },
      { id: streamId, role: 'assistant', content: '', timestamp: new Date(), isStreaming: true, thinkingSteps: [] }]);

    const form = new FormData();
    form.append('file', file, file.name);
    if (text) form.append('message', text);
    if (sessionId) form.append('sessionId', sessionId);
    try {
      const resp = await fetch('/api/webui/chat/document', {
        method: 'POST',
        headers: { 'X-Access-Token': localStorage.getItem('hestia_token') || '' },
        body: form,
      });
      if (!resp.ok || !resp.body) {
        const detail = await resp.text().catch(() => '');
        throw new Error(`Upload non riuscito (${resp.status}) ${detail.slice(0, 200)}`);
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buf.indexOf('\n')) >= 0) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          try { this.handleEvent(JSON.parse(line) as ServerEvent); } catch { /* skip bad line */ }
        }
      }
      if (this.currentStreamingId() === streamId) this.finalizeStreaming(streamId, null);
    } catch (err: any) {
      this.finalizeStreaming(streamId, err?.message || 'Upload non riuscito', undefined, undefined, true);
    }
  }

  cancelStream(): void {
    if (this.signalR.activeChannel !== this.channel) return;
    this.signalR.send({ type: 'cancel' }).catch(() => {});
  }

  retry(): void {
    if (this.isStreaming()) return;
    // New placeholder for the regenerated answer (events need a streaming target).
    this.signalR.claim(this.channel);
    this.isStreaming.set(true);
    this.thinkingBuffer = [];
    this.stepCounter = 0;
    const streamId = uid();
    this.currentStreamingId.set(streamId);
    this.lastAssistantId = streamId;
    this.messages.update(msgs => [...msgs,
      { id: streamId, role: 'assistant', content: '', timestamp: new Date(), isStreaming: true, thinkingSteps: [] }]);
    this.signalR.send({ type: 'retry' }).catch((err: any) =>
      this.finalizeStreaming(streamId, err?.message || 'Invio non riuscito', undefined, undefined, true));
  }

  answerQuestion(questionId: string, answer: string, sessionId = '', mode = 'auto', context?: string): void {
    this.signalR.claim(this.channel);
    this.resumeTarget = { sessionId, mode, context };
    this.signalR.send({ type: 'question_answer', question_id: questionId, answer }).catch(() => {});
    if (this.pendingQuestion()?.questionId === questionId) this.pendingQuestion.set(null);
  }

  /**
   * After a reload: draw again what is still waiting in this conversation — messages in the queue (hourglass) and the
   * assistant's open question (oracle-offline v3 A + G). Once per page load.
   */
  async restorePending(): Promise<void> {
    if (this.restored) return;
    this.restored = true;
    type Pending = { questions?: ServerEvent[]; queued?: { queue_id: number; text: string; created_at?: string }[] };
    let p: Pending;
    try {
      p = await firstValueFrom(this.injector.get(HttpClient).get<Pending>('/api/webui/chat/pending'));
    } catch { return; }
    const known = new Set(this.messages().map(m => m.queuedId).filter(Boolean));
    const add: ChatMessage[] = [];
    for (const q of p.queued ?? []) {
      if (known.has(q.queue_id)) continue;
      const at = q.created_at ? new Date(q.created_at) : new Date();
      add.push({ id: uid(), role: 'user', content: q.text, timestamp: at },
               { id: uid(), role: 'assistant', content: 'Non posso rispondere adesso: messaggio in coda, ti rispondo appena possibile.',
                 timestamp: at, queuedId: q.queue_id });
    }
    if (add.length) this.messages.update(msgs => [...msgs, ...add]);
    const open = (p.questions ?? [])[0];
    if (open && !this.pendingQuestion()) this.setQuestion({ ...open, type: 'question' });
  }

  /** Show the result of a command (palette) in the conversation. */
  addSystemReply(title: string, html: string): void {
    this.messages.update(msgs => [...msgs,
      { id: uid(), role: 'user', icon: 'zap', content: title, timestamp: new Date() },
      { id: uid(), role: 'assistant', content: html, timestamp: new Date() }]);
  }

  clearMessages(): void {
    this.messages.set([]);
    this.thinkingBuffer = [];
    this.lastAssistantId = null;
  }

  private handleEvent(event: ServerEvent): void {
    const streamId = this.currentStreamingId();

    switch (event.type) {
      case 'token':
        if (streamId && event.text) {
          this.appendToStreaming(streamId, event.text);
        }
        break;

      case 'thinking':
        this.handleThinking(event);
        break;

      case 'final':
        if (streamId && event.reply) {
          this.finalizeStreaming(streamId, event.reply, event.domain, event.session_id);
          if (event.origin?.label) this.patch(streamId, { origin: event.origin });
          if (event.trace_id) this.patch(streamId, { traceId: event.trace_id });
        }
        break;

      case 'changes': {
        // «Ho fatto» under the answer (Cindy 13): can arrive before or after `final`.
        const target = streamId ?? this.lastAssistantId;
        if (target && event.items?.length) this.patch(target, { changes: event.items.map(c => ({ ...c, done: false })) });
        break;
      }

      case 'error':
        if (streamId && event.content) {
          this.finalizeStreaming(streamId, event.content, undefined, undefined, true);
        }
        break;

      case 'queued':
        // Oracle offline: the message waits in Archive and gets its answer when Oracle is back.
        if (streamId) {
          this.finalizeStreaming(streamId, event.content || 'Messaggio in coda');
          this.messages.update(msgs => msgs.map(m => m.id === streamId ? { ...m, queuedId: event.queue_id } : m));
        }
        break;

      case 'stream_done':
        if (streamId) {
          this.finalizeStreaming(streamId, null, undefined, undefined);
        }
        break;

      case 'status':
        // Status updates are logged but not displayed inline
        break;

      case 'signal':
        // Legacy machine events; the user-facing version arrives as a `notice` packet.
        break;

      case 'notice':
        this.handleNotice(event);
        break;

      case 'question':
        this.setQuestion(event);
        break;

      case 'resume':
        // The answer to the assistant's own question goes on as the next message of the same chat.
        if (event.message && this.resumeTarget) {
          const t = this.resumeTarget;
          this.resumeTarget = null;
          void this.sendMessage(event.message, t.sessionId, t.mode, 'generic', t.context);
        }
        break;

      case 'needs_input':
        if (streamId && event.missing_fields?.length) {
          this.appendToStreaming(streamId, `\n<i>Servono altri dati: ${event.missing_fields.join(', ')}</i>`);
        }
        break;
    }
  }

  private setQuestion(event: ServerEvent): void {
    if (!event.question_id) return;
    const opts = (event.options || []).map(o => typeof o === 'string'
      ? { label: o, value: o }
      : { label: String(o.label ?? o.value ?? ''), value: String(o.value ?? o.label ?? '') });
    this.pendingQuestion.set({
      questionId: event.question_id,
      header: event.header || 'Domanda',
      prompt: event.prompt || '',
      kind: (event.kind || (opts.length ? 'single_choice' : 'free_text')) as PendingQuestion['kind'],
      options: event.kind === 'confirm' && !opts.length
        ? [{ label: 'Sì', value: 'yes' }, { label: 'No', value: 'no' }] : opts,
      required: event.required !== false,
      allowOther: !!event.allow_other,
      expiresAt: event.timeout_sec ? Date.now() + event.timeout_sec * 1000 : undefined,
    });
  }

  private handleQueuedAnswer(event: ServerEvent): void {
    const reply = event.reply || '';
    // Several queued messages answered together (v3 C): the reply goes under the last one.
    const ids = event.queue_ids?.length ? event.queue_ids : [event.queue_id];
    const last = ids[ids.length - 1];
    const waiting = this.messages().some(m => m.queuedId !== undefined && ids.includes(m.queuedId));
    if (waiting) {
      this.messages.update(msgs => msgs
        .filter(m => !(m.queuedId !== undefined && ids.includes(m.queuedId) && m.queuedId !== last))
        .map(m => m.queuedId === last
          ? { ...m, content: reply, queuedId: undefined, timestamp: new Date(), sessionId: event.session_id } : m));
      return;
    }
    // Page reloaded meanwhile: show the pair (Oracle saved it in the session history anyway).
    this.messages.update(msgs => [...msgs,
      { id: uid(), role: 'user', content: event.message || '', timestamp: new Date() },
      { id: uid(), role: 'assistant', content: reply, timestamp: new Date(), sessionId: event.session_id }]);
  }

  private handleNotice(event: ServerEvent): void {
    // A settings proposal decided from its chat card (e.g. a dashboard Hestia built): reload the WebUI's own config.
    const qid = String((event.data as Record<string, unknown> | undefined)?.['question_id'] ?? '');
    if (qid.startsWith('themis:')) {
      void import('../features/plugins/plugins.service').then(m => setTimeout(() => void this.injector.get(m.PluginsService).loadConfig(), 800));
    }
    const n: ChatNotice = {
      id: uid(), kind: event.kind || 'info', level: event.level || 'info',
      icon: event.icon || 'info', emoji: event.emoji, title: event.title || 'Info',
      detail: event.detail || '', data: event.data,
    };
    if (!this.noticePrefs.allows(n)) return;
    const target = this.currentStreamingId() ?? this.lastAssistantId;
    if (target) {
      this.messages.update(msgs => msgs.map(m => m.id === target ? { ...m, notices: [...(m.notices ?? []), n] } : m));
    }
    if (this.noticePrefs.toast()) {
      const tone = n.level === 'error' ? 'danger' : n.level;
      this.toast.show(n.detail ? `${n.title}: ${n.detail}` : n.title, tone);
    }
  }

  private handleThinking(event: ServerEvent): void {
    this.stepCounter++;
    const step: ThinkingStep = {
      stepNumber: this.stepCounter,
      type: (event.action as ThinkingStep['type']) || 'reasoning',
      content: event.content || event.tool || '',
      tool: event.tool,
      turn: event.turn || 0,
      metadata: event.metadata as any,
      isExpanded: false
    };

    this.thinkingBuffer.push(step);

    const streamId = this.currentStreamingId();
    if (streamId) {
      this.messages.update(msgs => msgs.map(m =>
        m.id === streamId
          ? { ...m, thinkingSteps: [...this.thinkingBuffer] }
          : m
      ));
    }
  }

  /** Merges fields into one message (e.g. a change marked undone). */
  patch(id: string, fields: Partial<ChatMessage>): void {
    this.messages.update(msgs => msgs.map(m => m.id === id ? { ...m, ...fields } : m));
  }

  /** Shows a past conversation (oldest first) instead of the current one; answers continue in it. */
  showHistory(items: Array<{ role: string; content: string; at?: string }>, sessionId: string): void {
    this.clearMessages();
    this.messages.set(items.filter(i => i.role === 'user' || i.role === 'assistant').map(i => ({
      id: uid(), role: i.role as 'user' | 'assistant', sessionId,
      // answers are kept as written by the model: markdown becomes HTML like a live answer
      content: i.role === 'assistant' && !/<[a-z][^>]*>/i.test(i.content || '')
        ? marked.parse(i.content || '', { gfm: true, async: false }) as string : i.content || '',
      timestamp: i.at ? new Date(i.at) : new Date(),
    })));
  }

  private appendToStreaming(streamId: string, text: string): void {
    this.messages.update(msgs => msgs.map(m =>
      m.id === streamId
        ? { ...m, content: m.content + text }
        : m
    ));
  }

  private finalizeStreaming(streamId: string, content: string | null, domain?: string, sessionId?: string, error = false): void {
    this.messages.update(msgs => msgs.map(m =>
      m.id === streamId
        ? {
            ...m,
            content: content ?? m.content,
            isStreaming: false,
            ...(error ? { error: true } : {}),
            domain: domain || m.domain,
            sessionId: sessionId || m.sessionId,
            thinkingSteps: [...this.thinkingBuffer]
          }
        : m
    ));

    if (this.currentStreamingId() === streamId) {
      this.currentStreamingId.set(null);
      this.isStreaming.set(false);
      this.pendingQuestion.set(null);
    }
  }
}
