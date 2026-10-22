import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';

/**
 * Esporta e importa (docs/work/2026-10-20-import-export): `/api/webui/transfer/*` → Hub → the module's
 * `/api/transfer/*` (hestia_common.transfer). Themis answers for the settings of every module.
 */

export type TransferMode = 'append' | 'merge' | 'replace';

export interface TransferSectionInfo {
  id: string; label: string; icon?: string; help?: string; count: number | null; depends_on: string[];
  has_files: boolean; schema: number; error?: string;
}
export interface TransferDescribe { module: string; format: number; sections: TransferSectionInfo[]; }
export interface TransferItem { key: string; title: string; subtitle: string; updated_at?: string | null; }

export interface ModuleExport {
  module: string; format: number; exported_at: string; since?: string | null;
  sections: Record<string, { schema: number; label: string; partial: boolean; records: Record<string, unknown>[] }>;
  pulled: Record<string, string[]>;
  files: string[];
}

export interface TransferFile {
  hestia: 'transfer';
  format: number;
  exported_at: string;
  since?: string | null;
  include_files?: boolean;
  /** owner module → its export (Themis = the settings of every module, one section per module) */
  modules: Record<string, ModuleExport>;
  /** owner module → blob id → file */
  files?: Record<string, Record<string, { mime: string; sha256?: string; meta?: unknown; data_b64: string }>>;
}

export interface SectionReport {
  mode: TransferMode; added: number; updated: number; unchanged: number; skipped: number; deleted: number;
  problems: number; related: number; partial?: boolean;
  items: { added: string[]; updated: string[]; skipped: string[]; deleted: string[]; problems: string[] };
}
export interface ImportReport { module: string; dry_run: boolean; sections: Record<string, SectionReport>; totals: Record<string, number>; }

export interface RestorePoint { id: string; created_at?: string | null; size: number; label?: string | null; modules?: string[] | null; }

export const FORMAT = 1;

@Injectable({ providedIn: 'root' })
export class TransferApi {
  private http = inject(HttpClient);
  private base = '/api/webui/transfer';

  modules() {
    return firstValueFrom(this.http.get<{ modules: { module: string; settings: boolean }[] }>(`${this.base}/modules`));
  }
  describe(module: string) {
    return firstValueFrom(this.http.get<TransferDescribe>(`${this.base}/${module}/describe`));
  }
  items(module: string, section: string, q = '', limit = 500) {
    return firstValueFrom(this.http.post<{ items: TransferItem[]; total: number }>(`${this.base}/${module}/items`,
      { section, q, limit }));
  }
  export(module: string, body: { sections: Record<string, { keys?: string[] }>; since?: string | null; include_files?: boolean }) {
    return firstValueFrom(this.http.post<ModuleExport>(`${this.base}/${module}/export`, body));
  }
  file(module: string, id: string) {
    return firstValueFrom(this.http.get<{ id: string; mime: string; sha256?: string; meta?: unknown; data_b64: string }>(
      `${this.base}/${module}/files/${encodeURIComponent(id)}`));
  }
  upload(module: string, body: { id: string; mime: string; meta?: unknown; data_b64: string }) {
    return firstValueFrom(this.http.post<{ old_id: string; new_id: string }>(`${this.base}/${module}/files`, body));
  }
  import(module: string, body: {
    data: ModuleExport; mode: TransferMode; modes?: Record<string, TransferMode>; dry_run: boolean;
    sections?: Record<string, object>; files_map?: Record<string, string>;
  }) {
    return firstValueFrom(this.http.post<ImportReport>(`${this.base}/${module}/import`, body));
  }
  restorePoints() {
    return firstValueFrom(this.http.get<{ items: RestorePoint[]; keep: number }>(`${this.base}/restore-points`));
  }
  saveRestorePoint(body: { label: string; modules: string[]; file: TransferFile }) {
    return firstValueFrom(this.http.post<{ id: string }>(`${this.base}/restore-points`, body));
  }
  restorePoint(id: string) {
    return firstValueFrom(this.http.get<TransferFile>(`${this.base}/restore-points/${encodeURIComponent(id)}`));
  }
  deleteRestorePoint(id: string) {
    return firstValueFrom(this.http.delete(`${this.base}/restore-points/${encodeURIComponent(id)}`));
  }
}

/** `.hestia` = gzip JSON (plain JSON is read too: the CLI or a hand-edited file). */
export async function encodeFile(file: TransferFile): Promise<Blob> {
  const json = new Blob([JSON.stringify(file)], { type: 'application/json' });
  if (typeof CompressionStream === 'undefined') return json;
  return new Response(json.stream().pipeThrough(new CompressionStream('gzip'))).blob();
}

export async function decodeFile(blob: Blob): Promise<TransferFile> {
  const head = new Uint8Array(await blob.slice(0, 2).arrayBuffer());
  let text: string;
  if (head[0] === 0x1f && head[1] === 0x8b) {
    if (typeof DecompressionStream === 'undefined') throw new Error('Questo browser non sa aprire il file compresso');
    text = await new Response(blob.stream().pipeThrough(new DecompressionStream('gzip'))).text();
  } else {
    text = await blob.text();
  }
  const file = JSON.parse(text) as TransferFile;
  if (file?.hestia !== 'transfer' || typeof file.modules !== 'object') throw new Error('Non è un file di Hestia');
  if ((file.format ?? 1) > FORMAT) throw new Error('File di una versione di Hestia più recente: aggiorna Hestia');
  return file;
}

export function fileName(date = new Date()): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `hestia-${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}.hestia`;
}
