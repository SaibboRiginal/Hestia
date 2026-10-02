import { Injectable, inject, signal } from '@angular/core';
import * as signalR from '@microsoft/signalr';
import { AuthService } from './auth.service';
import { Subject, Observable } from 'rxjs';
import { ServerEvent, ClientMessage } from '../models/chat.models';

@Injectable({ providedIn: 'root' })
export class SignalRService {
  private auth = inject(AuthService);
  private hub: signalR.HubConnection | null = null;
  private eventSubject = new Subject<ServerEvent>();

  connectionState = signal<'disconnected' | 'connecting' | 'connected'>('disconnected');
  events$: Observable<ServerEvent> = this.eventSubject.asObservable();

  async connect(): Promise<void> {
    const token = this.auth.getToken();
    this.connectionState.set('connecting');

    this.hub = new signalR.HubConnectionBuilder()
      .withUrl(`/hubs/chat?access_token=${token}`)
      .withAutomaticReconnect([0, 2000, 5000, 10000, 30000])
      .configureLogging(signalR.LogLevel.Warning)
      .build();

    this.hub.on('ReceiveEvent', (event: ServerEvent) => {
      this.eventSubject.next(event);
    });

    this.hub.onreconnecting(() => this.connectionState.set('connecting'));
    this.hub.onreconnected(() => this.connectionState.set('connected'));
    this.hub.onclose(() => this.connectionState.set('disconnected'));

    try {
      await this.hub.start();
      this.connectionState.set('connected');
    } catch (err) {
      this.connectionState.set('disconnected');
      console.error('SignalR connection failed:', err);
    }
  }

  async send(message: ClientMessage): Promise<void> {
    if (this.hub?.state !== signalR.HubConnectionState.Connected) {
      if (!this.hub || this.hub.state === signalR.HubConnectionState.Disconnected) {
        await this.connect();
      }
    }
    if (this.hub?.state !== signalR.HubConnectionState.Connected) {
      // Never drop silently: the caller marks the message as failed.
      throw new Error('Connessione al server non disponibile');
    }
    await this.hub.invoke('SendMessage', message);
  }

  async disconnect(): Promise<void> {
    if (this.hub) {
      await this.hub.stop();
      this.connectionState.set('disconnected');
    }
  }
}
