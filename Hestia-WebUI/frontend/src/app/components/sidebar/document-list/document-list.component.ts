import { Component, inject, signal, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

@Component({
  selector: 'app-document-list',
  standalone: true,
  template: `
    <div class="doc-panel">
      <h3>Documents</h3>
      @if (loading()) {
        <p class="loading">Loading...</p>
      } @else if (documents().length === 0) {
        <p class="empty">No documents stored</p>
      } @else {
        <div class="doc-list">
          @for (doc of documents(); track doc.id) {
            <div class="doc-item">
              <span class="doc-icon">📄</span>
              <div class="doc-info">
                <span class="doc-name">{{ doc.filename || doc.id }}</span>
                <span class="doc-meta">{{ doc.mime_type || 'unknown' }}</span>
              </div>
              <button class="doc-delete" (click)="remove(doc.id)">🗑️</button>
            </div>
          }
        </div>
      }
    </div>
  `,
  styles: [`
    .doc-panel { padding: 4px; }
    h3 { font-size: 13px; font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 12px; }
    .loading, .empty { font-size: 13px; color: var(--text-muted); text-align: center; padding: 24px; }
    .doc-list { display: flex; flex-direction: column; gap: 4px; }
    .doc-item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: var(--radius-md); transition: background var(--transition-fast); }
    .doc-item:hover { background: var(--bg-hover); }
    .doc-icon { font-size: 20px; flex-shrink: 0; }
    .doc-info { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .doc-name { font-size: 13px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .doc-meta { font-size: 11px; color: var(--text-muted); }
    .doc-delete { background: none; border: none; cursor: pointer; font-size: 14px; padding: 4px; border-radius: var(--radius-sm); opacity: 0; transition: opacity var(--transition-fast); }
    .doc-item:hover .doc-delete { opacity: 1; }
  `]
})
export class DocumentListComponent implements OnInit {
  private http = inject(HttpClient);
  documents = signal<any[]>([]);
  loading = signal(true);

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  async load(): Promise<void> {
    try {
      const resp = await firstValueFrom(
        this.http.get<{ documents: any[]; count: number }>('/api/webui/documents')
      );
      this.documents.set(resp.documents || []);
    } catch { /* empty */ }
    this.loading.set(false);
  }

  async remove(id: string): Promise<void> {
    try {
      await firstValueFrom(this.http.delete(`/api/webui/documents/${id}`));
      this.documents.update(docs => docs.filter(d => d.id !== id));
    } catch { /* ignore */ }
  }
}
