import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { CommandInfo } from '../models/chat.models';

@Injectable({ providedIn: 'root' })
export class CommandService {
  private http = inject(HttpClient);
  private apiBase = '/api/webui/commands';

  async list(): Promise<CommandInfo[]> {
    const resp = await firstValueFrom(
      this.http.get<{ commands: CommandInfo[]; count: number }>(this.apiBase)
    );
    return resp.commands;
  }

  async execute(command: string, args?: Record<string, any>): Promise<any> {
    const resp = await firstValueFrom(
      this.http.post<{ ok: boolean; result: any }>(`${this.apiBase}/execute`, {
        command,
        args: args || {}
      })
    );
    return resp;
  }
}
