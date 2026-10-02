import { Component, inject, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ChatService } from '../../../services/chat.service';

@Component({
  selector: 'app-command-palette',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="cmd">
      <input [(ngModel)]="q" (input)="f()" placeholder="Search..." class="s" />
      @for (c of filtered(); track c.command) {
        <button class="r" (click)="select(c)" [disabled]="running()">
          <span class="t">{{ c.title }}</span><span class="d">{{ c.description }}</span>
        </button>
        @if (selected()?.command === c.command && argNames(c).length) {
          <div class="args">
            @for (a of argNames(c); track a) {
              <input [placeholder]="argLabel(c, a)" [(ngModel)]="args[a]" class="s" />
            }
            <button class="go" (click)="run(c)" [disabled]="running()">▶ Esegui</button>
          </div>
        }
      }
      @if (filtered().length === 0) { <p class="e">No commands</p> }
    </div>
  `,
  styles: [`
    .cmd { padding:4px; }
    .s { width:100%; padding:8px 12px; background:var(--bg-tertiary); border:1px solid var(--border); border-radius:8px; color:var(--text-primary); font-size:13px; font-family:Inter,sans-serif; outline:none; margin-bottom:8px; }
    .s:focus { border-color:var(--accent); }
    .r { display:flex; flex-direction:column; gap:2px; width:100%; padding:10px 12px; background:none; border:none; border-radius:8px; cursor:pointer; text-align:left; }
    .r:hover { background:var(--bg-hover); }
    .t { font-size:13px; color:var(--text-primary); font-weight:500; }
    .d { font-size:11px; color:var(--text-muted); }
    .args { padding:4px 12px 10px; display:flex; flex-direction:column; gap:4px; }
    .go { align-self:flex-end; background:var(--accent); color:#fff; border:none; border-radius:8px; padding:6px 12px; cursor:pointer; }
    .e { text-align:center; color:var(--text-muted); font-size:13px; padding:24px; }
  `]
})
export class CommandPaletteComponent implements OnInit {
  private http = inject(HttpClient);
  private chat = inject(ChatService);
  q = '';
  selected = signal<any | null>(null);
  running = signal(false);
  args: Record<string, string> = {};
  all = signal<any[]>([]);
  filtered = signal<any[]>([]);

  async ngOnInit() {
    try {
      const r = await firstValueFrom(this.http.get<{commands:any[],count:number}>('/api/webui/commands'));
      this.all.set(r.commands || []);
    } catch { }
    this.f();
  }

  f() {
    const s = this.q.toLowerCase();
    this.filtered.set(this.all().filter((c:any) => !s || (c.title||c.command||'').toLowerCase().includes(s)));
  }

  argNames(c: any): string[] {
    const props = c?.arguments_schema?.properties || {};
    return Object.keys(props);
  }

  argLabel(c: any, a: string): string {
    const req: string[] = c?.arguments_schema?.required || [];
    const d = c?.arguments_schema?.properties?.[a]?.description || a;
    return `${d}${req.includes(a) ? ' *' : ''}`;
  }

  select(c: any) {
    if (this.selected()?.command !== c.command) { this.selected.set(c); this.args = {}; }
    if (!this.argNames(c).length) void this.run(c);
  }

  async run(c: any) {
    const cleaned: Record<string, string> = {};
    for (const [k, v] of Object.entries(this.args)) if (String(v ?? '').trim()) cleaned[k] = String(v).trim();
    this.running.set(true);
    try {
      const r: any = await firstValueFrom(
        this.http.post('/api/webui/commands/execute', { command: c.command, args: cleaned }));
      const body = r?.ok
        ? (r.text || `<pre>${this.escape(JSON.stringify(r.result, null, 2)).slice(0, 4000)}</pre>`)
        : `⚠️ ${this.escape(r?.error || 'errore')}`;
      this.chat.addSystemReply(`${c.title || c.command}`, body);
      this.selected.set(null);
      this.args = {};
    } catch (err: any) {
      this.chat.addSystemReply(`${c.title || c.command}`, `⚠️ ${this.escape(err?.message || 'errore')}`);
    }
    this.running.set(false);
  }

  private escape(t: string): string {
    return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
}
