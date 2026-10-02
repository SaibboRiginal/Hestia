import { Component, inject, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

@Component({
  selector: 'app-command-palette',
  standalone: true,
  imports: [FormsModule],
  template: `
    <div class="cmd">
      <input [(ngModel)]="q" (input)="f()" placeholder="Search..." class="s" />
      @for (c of filtered(); track c.command) {
        <button class="r" (click)="run(c)">
          <span class="t">{{ c.title }}</span><span class="d">{{ c.description }}</span>
        </button>
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
    .e { text-align:center; color:var(--text-muted); font-size:13px; padding:24px; }
  `]
})
export class CommandPaletteComponent implements OnInit {
  private http = inject(HttpClient);
  q = '';
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

  async run(c: any) {
    try {
      await firstValueFrom(this.http.post('/api/webui/commands/execute', { command: c.command }));
    } catch {}
  }
}
