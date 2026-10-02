import { Component, output } from '@angular/core';

@Component({
  selector: 'app-file-dropzone',
  standalone: true,
  template: `
    <div class="dropzone-overlay" (click)="close.emit()">
      <div class="dropzone" (click)="$event.stopPropagation()">
        <div class="dropzone-icon">📤</div>
        <p>Drop files here or click to browse</p>
        <p class="dropzone-hint">Images, PDFs, audio, video, documents, code</p>
        <input type="file" #fileInput class="file-input" multiple
          (change)="onFilesSelected($event)" />
        <button class="browse-btn" (click)="fileInput.click()">Choose Files</button>
      </div>
    </div>
  `,
  styles: [`
    .dropzone-overlay {
      position: fixed; inset: 0; background: rgba(0,0,0,0.6);
      display: flex; align-items: center; justify-content: center;
      z-index: 100; animation: fadeIn 0.2s ease;
    }
    .dropzone {
      background: var(--bg-secondary); border: 2px dashed var(--border-light);
      border-radius: var(--radius-lg); padding: 48px; text-align: center;
      max-width: 480px; width: 90%;
    }
    .dropzone-icon { font-size: 48px; margin-bottom: 16px; }
    .dropzone p { color: var(--text-primary); margin-bottom: 8px; }
    .dropzone-hint { color: var(--text-muted); font-size: 13px; margin-bottom: 20px; }
    .file-input { display: none; }
    .browse-btn {
      padding: 12px 24px; background: var(--accent); color: white;
      border: none; border-radius: var(--radius-lg); font-size: 14px;
      font-weight: 600; cursor: pointer;
    }
    .browse-btn:hover { background: var(--accent-hover); }
  `]
})
export class FileDropzoneComponent {
  close = output<void>();
  filesSelected = output<FileList>();

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (input.files && input.files.length > 0) {
      this.filesSelected.emit(input.files);
      this.close.emit();
    }
  }
}
