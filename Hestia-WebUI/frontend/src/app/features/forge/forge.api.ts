import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  Branch, Commit, CommitDetail, Compare, Dossier, ForgeStatus, ForgeTask, RepoFile, Tag, TaskFiles, TaskLogs,
  TaskTests, TaskWorkdoc, TranscriptPage, TreeEntry,
} from './forge.models';

/** WebUI backend → Hub → Hephaestus (/api/hephaestus/forge/* and /repo/*). Every action is by=user. */
@Injectable({ providedIn: 'root' })
export class ForgeApi {
  private http = inject(HttpClient);
  private base = '/api/webui/forge';

  private get<T>(path: string, query: Record<string, string | number | boolean | null | undefined> = {}) {
    let params = new HttpParams();
    for (const [k, v] of Object.entries(query)) if (v !== null && v !== undefined && v !== '') params = params.set(k, String(v));
    return firstValueFrom(this.http.get<T>(`${this.base}/${path}`, { params }));
  }

  status() { return this.get<ForgeStatus>('status'); }
  async tasks(limit = 150): Promise<ForgeTask[]> {
    return (await this.get<{ tasks: ForgeTask[] }>('tasks', { limit }))?.tasks ?? [];
  }
  async task(id: string): Promise<ForgeTask> { return (await this.get<{ task: ForgeTask }>(`tasks/${id}`)).task; }
  transcript(id: string, offset = 0, limit = 500) { return this.get<TranscriptPage>(`tasks/${id}/transcript`, { offset, limit }); }
  files(id: string, diff = true) { return this.get<TaskFiles>(`tasks/${id}/files`, { diff }); }
  workdoc(id: string) { return this.get<TaskWorkdoc>(`tasks/${id}/workdoc`); }
  tests(id: string) { return this.get<TaskTests>(`tasks/${id}/tests`); }
  logs(id: string) { return this.get<TaskLogs>(`tasks/${id}/logs`); }

  submit(body: { request: string; services?: string[]; engine?: string; workdoc?: string; parent_task?: string }) {
    return firstValueFrom(this.http.post<{ task: ForgeTask }>(`${this.base}/tasks`, body));
  }
  act(id: string, verb: 'approve' | 'reject' | 'rollback' | 'retry', body: { reason?: string; now?: boolean } = {}) {
    return firstValueFrom(this.http.post<{ task: ForgeTask }>(`${this.base}/tasks/${id}/${verb}`, body));
  }

  // ── repo ───────────────────────────────────────────────────────────────
  branches() { return this.get<{ base: string; current: string; branches: Branch[] }>('repo/branches'); }
  async tags(): Promise<Tag[]> { return (await this.get<{ tags: Tag[] }>('repo/tags'))?.tags ?? []; }
  log(q: { ref?: string; path?: string; limit?: number; skip?: number; all?: boolean }) {
    return this.get<{ commits: Commit[]; has_more: boolean }>('repo/log', q);
  }
  commit(sha: string) { return this.get<CommitDetail>(`repo/commits/${encodeURIComponent(sha)}`); }
  compare(base: string, head: string) { return this.get<Compare>('repo/compare', { base, head }); }
  tree(ref: string, path: string) { return this.get<{ entries: TreeEntry[] }>('repo/tree', { ref, path }); }
  file(ref: string, path: string) { return this.get<RepoFile>('repo/file', { ref, path }); }
  async dossiers(): Promise<Dossier[]> { return (await this.get<{ dossiers: Dossier[] }>('repo/dossiers'))?.dossiers ?? []; }
}
