import { Injectable, inject, signal } from '@angular/core';
import { SignalRService } from './signalr.service';
import { ChatMessage, ThinkingStep, ServerEvent } from '../models/chat.models';

@Injectable({ providedIn: 'root' })
export class ChatService {
  private signalR = inject(SignalRService);

  messages = signal<ChatMessage[]>([]);
  isStreaming = signal(false);
  currentStreamingId = signal<string | null>(null);

  private thinkingBuffer: ThinkingStep[] = [];
  private stepCounter = 0;

  constructor() {
    this.signalR.events$.subscribe(event => this.handleEvent(event));
  }

  async sendMessage(text: string, sessionId: string, mode = 'auto', model = 'generic'): Promise<void> {
    this.isStreaming.set(true);
    this.thinkingBuffer = [];
    this.stepCounter = 0;

    // Create placeholder for streaming assistant message
    const streamId = crypto.randomUUID();
    this.currentStreamingId.set(streamId);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
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

    await this.signalR.send({
      type: 'chat',
      message: text,
      session_id: sessionId,
      mode,
      model
    });
  }

  cancelStream(): void {
    this.signalR.send({ type: 'cancel' });
  }

  retry(): void {
    this.signalR.send({ type: 'retry' });
  }

  answerQuestion(questionId: string, answer: string): void {
    this.signalR.send({ type: 'question_answer', question_id: questionId, answer });
  }

  clearMessages(): void {
    this.messages.set([]);
    this.thinkingBuffer = [];
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
        // Signals (tool.summary, memory.*) shown in dedicated components
        break;

      case 'question':
        // Questions handled by parent component
        break;
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
    }
  }
}
