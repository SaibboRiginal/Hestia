import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import { firstValueFrom } from 'rxjs';
import { BadgeComponent, ButtonComponent, DialogService, EmptyStateComponent, IconComponent, PageHeaderComponent, SpinnerComponent, ToastService } from '../../ui';

interface Doc { id: string; document_id?: string; filename?: string; title?: string; mime_type?: string; created_at?: string; is_permanent?: boolean; domain?: string; chunk_count?: number; }

/** Documents stored in Archive (uploaded from chat). */
@Component({
  selector: 'app-documents-page',
  imports: [DatePipe, PageHeaderComponent, ButtonComponent, IconComponent, BadgeComponent, EmptyStateComponent, SpinnerComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header title="Documenti" subtitle="File che hai condiviso con Hestia (ricercabili in chat)">
      <button hx-btn variant="ghost" icon="refresh" iconOnly aria-label="Aggiorna" (click)="load()"></button>
    </hx-page-header>
    <div class="body">
      @if (loading()) { <div class="center"><hx-spinner /></div> }
      @else if (!docs().length) { <hx-empty icon="file" title="Nessun documento">Allega un file in chat con 📎.</hx-empty> }
      @else {
        <div class="grid">
          @for (d of docs(); track d.id) {
            <div class="card hx-card">
              <hx-icon name="file" [size]="22" />
              <div class="hx-grow">
                <div class="name hx-truncate">{{ d.filename || d.title || d.id }}</div>
                <div class="meta">{{ d.created_at | date:'d MMM y, HH:mm' }} @if (d.mime_type) { · {{ d.mime_type }} }</div>
                @if (d.is_permanent) { <hx-badge tone="accent">permanente</hx-badge> }
              </div>
              <button hx-btn variant="ghost" size="sm" icon="trash" iconOnly aria-label="Elimina" (click)="remove(d)"></button>
            </div>
          }
        </div>
      }
    </div>`,
  styles: [`
    :host { display: flex; flex-direction: column; flex: 1; min-height: 0; }
    hx-page-header { padding-left: 56px; }
    @media (min-width: 861px) { hx-page-header { padding-left: 24px; } }
    .body { flex: 1; overflow-y: auto; padding: 18px 24px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
    .card { display: flex; gap: 12px; align-items: flex-start; padding: 14px; }
    .card hx-icon { color: var(--accent); margin-top: 2px; }
    .name { font-weight: 500; }
    .meta { font-size: 12px; color: var(--text-3); margin: 2px 0 6px; }
    .center { display: grid; place-items: center; padding: 40px; }
  `],
})
export class DocumentsPageComponent implements OnInit {
  private http = inject(HttpClient);
  private dialogs = inject(DialogService);
  private toast = inject(ToastService);
  docs = signal<Doc[]>([]);
  loading = signal(false);

  ngOnInit() { void this.load(); }

  async load() {
    this.loading.set(true);
    try {
      const r = await firstValueFrom(this.http.get<any>('/api/webui/documents'));
      const rows: Doc[] = Array.isArray(r) ? r : (r?.documents ?? []);
      this.docs.set(rows.map(d => ({ ...d, id: d.id ?? d.document_id ?? '' })));
    } catch { this.docs.set([]); }
    this.loading.set(false);
  }

  async remove(d: Doc) {
    if (!await this.dialogs.confirm('Eliminare il documento?', d.filename || d.id, 'Elimina', true)) return;
    try {
      await firstValueFrom(this.http.delete(`/api/webui/documents/${encodeURIComponent(d.id)}`));
      this.docs.update(list => list.filter(x => x.id !== d.id));
      this.toast.success('Documento eliminato');
    } catch { this.toast.error('Eliminazione non riuscita'); }
  }
}
