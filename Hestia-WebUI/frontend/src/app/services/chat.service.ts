import { uid } from '../core/uid';
import { Injectable, inject, signal } from '@angular/core';
import { SignalRService } from './signalr.service';
import { ChatMessage, ChatNotice, ThinkingStep, ServerEvent, PendingQuestion } from '../models/chat.models';
import { NoticePrefsService } from './notice-prefs.service';
import { ToastService } from '../ui';

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
  /** Last assistant message: notices (e.g. memory saved) can arrive after `final`. */
  private lastAssistantId: string | null = null;

  messages = signal<ChatMessage[]>([]);
  isStreaming = signal(false);
  currentStreamingId = signal<string | null>(null);
  pendingQuestion = signal<PendingQuestion | null>(null);

  private thinkingBuffer: ThinkingStep[] = [];
  private stepCounter = 0;

  constructor() {
    this.signalR.events$.subscribe(event => {
      if (this.signalR.activeChannel === this.channel) this.handleEvent(event);
    });
    // Another chat took the connection: the server cancelled our stream.
    this.signalR.claims$.subscribe(ch => {
      const id = this.currentStreamingId();
      if (ch !== this.channel && id) this.finalizeStreaming(id, null);
    });
  }

  async sendMessage(text: string, sessionId: string, mode = 'auto', model = 'generic', context?: string): Promise<void> {
    this.signalR.claim(this.channel);
    this.isStreaming.set(true);
    this.thinkingBuffer = [];
    this.stepCounter = 0;

    // Create placeholder for streaming assistant message
    const streamId = uid();
    this.currentStreamingId.set(streamId);
    this.lastAssistantId = streamId;

    const userMsg: ChatMessage = {
      id: uid(),
      role: 'user',
      content: text,
      timestamp: new Date()
    };
    this.messages.update(msgs => [...msgs, userMsg]);

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
        ? { ...m, isStreaming: false, content: `⚠️ ${err?.message || 'Invio non riuscito'}` } : m));
      this.currentStreamingId.set(null);
      this.isStreaming.set(false);
    }
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
      { id: uid(), role: 'user', content: `📎 ${file.name}${text ? ' — ' + text : ''}`, timestamp: new Date() },
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
      this.finalizeStreaming(streamId, `⚠️ ${err?.message || 'Upload non riuscito'}`);
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
      this.finalizeStreaming(streamId, `⚠️ ${err?.message || 'Invio non riuscito'}`));
  }

  answerQuestion(questionId: string, answer: string): void {
    this.signalR.claim(this.channel);
    this.signalR.send({ type: 'question_answer', question_id: questionId, answer }).catch(() => {});
    if (this.pendingQuestion()?.questionId === questionId) this.pendingQuestion.set(null);
  }

  /** Show the result of a command (palette) in the conversation. */
  addSystemReply(title: string, html: string): void {
    this.messages.update(msgs => [...msgs,
      { id: uid(), role: 'user', content: `⚡ ${title}`, timestamp: new Date() },
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
        }
        break;

      case 'error':
        if (streamId && event.content) {
          this.finalizeStreaming(streamId, `⚠️ ${event.content}`, undefined, undefined);
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
        if (event.question_id) {
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
            expiresAt: event.timeout_sec ? Date.now() + event.timeout_sec * 1000 : undefined,
          });
        }
        break;

      case 'needs_input':
        if (streamId && event.missing_fields?.length) {
          this.appendToStreaming(streamId, `\n<i>Servono altri dati: ${event.missing_fields.join(', ')}</i>`);
        }
        break;
    }
  }

  private handleNotice(event: ServerEvent): void {
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

  private appendToStreaming(streamId: string, text: string): void {
    this.messages.update(msgs => msgs.map(m =>
      m.id === streamId
        ? { ...m, content: m.content + text }
        : m
    ));
  }

  private finalizeStreaming(streamId: string, content: string | null, domain?: string, sessionId?: string): void {
    this.messages.update(msgs => msgs.map(m =>
      m.id === streamId
        ? {
            ...m,
            content: content ?? m.content,
            isStreaming: false,
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
