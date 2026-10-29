/**
 * <echo-voice> — page «Voce» (dossier docs/work/2026-10-20-modulo-voce §8): how Hestia listens and speaks.
 * Tabs: «Prova» (record the mic → text, text → voice, with the chain and provider that answered), «Motori»
 * (<echo-blocks>: providers, chains, uses), «Uso» (calls, minutes, characters, cost, errors by use and engine),
 * «Audio conservati» (space by class, recordings to listen/download/delete), «La tua voce» (<echo-your-voice>:
 * voiceprint + personal dictionary). In «Prova» a wrong transcript can be corrected: the words go to the dictionary.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, Recorder, blobToB64, bytes, money, playB64, secs, when } from './util';

const TABS = [{ id: 'prova', label: 'Prova' }, { id: 'tua', label: 'La tua voce' }, { id: 'motori', label: 'Motori' },
              { id: 'uso', label: 'Uso' }, { id: 'audio', label: 'Audio conservati' }];
const CLASSES: Record<string, string> = { recording: 'Le tue registrazioni', file: 'Audio mandati in chat',
                                          generated: 'Risposte lette', notification: 'Notifiche a voce' };

export class EchoVoice extends HestiaElement {
  static properties = { ...HestiaElement.properties, tab: { state: true }, recording: { state: true }, busy: { state: true },
                        heard: { state: true }, text: { state: true }, said: { state: true }, usage: { state: true },
                        kept: { state: true }, days: { state: true }, error: { state: true }, fix: { state: true } };
  declare tab: string; declare recording: boolean; declare busy: string; declare heard: any; declare text: string;
  declare said: any; declare usage: any; declare kept: any; declare days: number; declare error: string;
  declare fix: string | null;
  private rec = new Recorder();
  private playing: HTMLAudioElement | null = null;

  static styles = [...HestiaElement.styles, css`
    .tabs { display: flex; gap: 4px; margin: 4px 0 14px; border-bottom: 1px solid var(--border); overflow-x: auto; }
    .tabs button { font: inherit; background: none; border: 0; padding: 8px 12px; color: var(--text-2); cursor: pointer;
      border-bottom: 2px solid transparent; white-space: nowrap; }
    .tabs button[aria-selected=true] { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
    .cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr)); }
    .mic { display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 12px 0; }
    .mic button { width: 72px; height: 72px; border-radius: 50%; border: 0; cursor: pointer; display: grid; place-items: center;
      background: var(--accent-soft, var(--surface-2)); color: var(--accent); }
    .mic button.on { background: var(--danger); color: #fff; animation: pulse 1.2s ease-in-out infinite; }
    @keyframes pulse { 50% { transform: scale(1.06); } }
    @media (prefers-reduced-motion: reduce) { .mic button.on { animation: none; } }
    .out { padding: 10px 12px; background: var(--surface-2); border-radius: var(--radius-sm); white-space: pre-wrap; }
    .meta { font-size: 12px; color: var(--text-3); display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; }
    textarea { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm); padding: 8px 10px; width: 100%; box-sizing: border-box; min-height: 90px; resize: vertical; }
    .row { display: flex; justify-content: space-between; gap: 10px; padding: 8px 0; border-top: 1px solid var(--border); align-items: center; }
    .row:first-child { border-top: 0; }
    .num { font-variant-numeric: tabular-nums; white-space: nowrap; text-align: right; }
    .grow { min-width: 0; flex: 1; }
    .preview { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .actions { display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap; margin-top: 8px; }
    .bar { height: 8px; border-radius: var(--radius-full); background: var(--surface-2); overflow: hidden; margin: 6px 0 2px; }
    .bar span { display: block; height: 100%; background: var(--accent); }
  `];

  constructor() {
    super(); this.tab = 'prova'; this.recording = false; this.busy = ''; this.heard = null; this.text = 'Ciao, sono Hestia. Ti sento forte e chiaro.';
    this.said = null; this.usage = null; this.kept = null; this.days = 30; this.error = ''; this.fix = null;
  }

  connectedCallback() {
    super.connectedCallback();
    this.onHost('refresh', () => this.loadTab());
  }
  disconnectedCallback() { super.disconnectedCallback(); this.playing?.pause(); if (this.recording) this.rec.stop(); }

  private select(id: string) { this.tab = id; this.loadTab(); }

  private async loadTab() {
    if (this.tab === 'uso') {
      const r = await this.host.api('GET', `${API}/usage`, { query: { days: this.days } });
      this.usage = r.ok ? r.data : null; this.error = r.ok ? '' : r.error || 'Non raggiungibile';
    } else if (this.tab === 'audio') {
      const r = await this.host.api('GET', `${API}/audio`, { query: { limit: 200 } });
      this.kept = r.ok ? r.data : null; this.error = r.ok ? '' : r.error || 'Non raggiungibile';
    }
  }

  // ── Prova ──────────────────────────────────────────────────────────────
  private async toggleMic() {
    if (!this.recording) {
      try { await this.rec.start(); this.recording = true; this.heard = null; this.fix = null; }
      catch { this.host.toast('Il browser non mi dà il microfono', 'danger'); }
      return;
    }
    this.recording = false;
    const blob = await this.rec.stop();
    if (!blob) return;
    this.busy = 'ascolto';
    const r = await this.host.api('POST', `${API}/transcribe`, { body: {
      audio_b64: await blobToB64(blob), mime_type: this.rec.mime, use_case: 'echo.prova.ascolto' } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non sono riuscita ad ascoltare', 'danger'); return; }
    this.heard = r.data;
  }

  /** «Correggi»: the corrected text teaches the personal dictionary (new words become sure after a few times). */
  private async learn() {
    const corrected = (this.fix || '').trim();
    if (!corrected || corrected === this.heard?.text) { this.fix = null; return; }
    this.busy = 'impara';
    const r = await this.host.api('POST', `${API}/dictionary/learn`, { body: { heard: this.heard.text, corrected } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'warning'); return; }
    this.heard = { ...this.heard, text: corrected };
    this.fix = null;
    const n = (r.data?.confirmed || []).length;
    this.host.toast(n ? `Imparato: ${(r.data.confirmed || []).join(', ')}` : 'Grazie, me lo segno', 'success');
  }

  private async speak() {
    if (!this.text.trim()) return;
    this.busy = 'voce';
    const r = await this.host.api('POST', `${API}/speak`, { body: { text: this.text, format: 'ogg_opus', use_case: 'echo.prova.voce' } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non sono riuscita a parlare', 'danger'); return; }
    this.said = r.data;
    this.play(r.data.audio_b64, r.data.mime_type);
  }

  private play(b64: string, mime?: string) {
    this.playing?.pause();
    this.playing = playB64(b64, mime || 'audio/ogg');
  }

  private meta(d: any) {
    if (!d) return nothing;
    return html`<div class="meta">
      ${d.provider ? html`<hxk-badge tone="neutral">${d.provider}${d.model || d.voice ? ` · ${d.model || d.voice}` : ''}</hxk-badge>` : nothing}
      ${d.chain ? html`<span>catena ${d.chain}</span>` : nothing}
      ${d.mode === 'esterna' ? html`<hxk-badge tone="info">esterna</hxk-badge>` : nothing}
      ${d.fallback ? html`<hxk-badge tone="warning">ripiego</hxk-badge>` : nothing}
      ${d.duration_s ? html`<span>${secs(d.duration_s)}</span>` : nothing}
    </div>`;
  }

  private prova() {
    return html`<div class="cols">
      <hxk-card heading="Ascolto" subtitle="Parla e guarda cosa capisco">
        <div class="mic">
          <button class=${this.recording ? 'on' : ''} @click=${() => this.toggleMic()} aria-label=${this.recording ? 'Ferma e trascrivi' : 'Registra'}>
            <hxk-icon name=${this.recording ? 'stop' : 'mic'} size=${30}></hxk-icon></button>
          <span class="small muted">${this.recording ? 'Ti ascolto… tocca per finire' : this.busy === 'ascolto' ? 'Trascrivo…' : 'Tocca per parlare'}</span>
        </div>
        ${this.heard ? this.fix !== null && this.fix !== undefined ? html`<textarea .value=${this.fix} @input=${(e: any) => (this.fix = e.target.value)}></textarea>
            <div class="actions"><hxk-button variant="ghost" @click=${() => (this.fix = null)}>Annulla</hxk-button>
              <hxk-button variant="primary" icon="check" ?loading=${this.busy === 'impara'} @click=${() => this.learn()}>Correggi</hxk-button></div>`
          : html`<div class="out">${this.heard.text}</div>${this.meta(this.heard)}
            <div class="actions"><hxk-button size="sm" variant="ghost" icon="edit" @click=${() => (this.fix = this.heard.text)}>Correggi la trascrizione</hxk-button></div>` : nothing}
      </hxk-card>
      <hxk-card heading="Voce" subtitle="Scrivi e ascolta come lo leggo">
        <textarea .value=${this.text} @input=${(e: any) => (this.text = e.target.value)}></textarea>
        <div class="actions">
          ${this.said ? html`<hxk-button variant="ghost" icon="play" @click=${() => this.play(this.said.audio_b64, this.said.mime_type)}>Di nuovo</hxk-button>` : nothing}
          <hxk-button variant="primary" icon="volume" ?loading=${this.busy === 'voce'} @click=${() => this.speak()}>Leggi</hxk-button>
        </div>
        ${this.meta(this.said)}
      </hxk-card>
    </div>`;
  }

  // ── Uso ────────────────────────────────────────────────────────────────
  private uso() {
    if (this.error) return html`<hxk-state kind="error" text=${this.error} @retry=${() => this.loadTab()}></hxk-state>`;
    const u = this.usage;
    if (!u) return html`<hxk-state kind="loading"></hxk-state>`;
    const t = u.totals || {};
    const rows = (obj: Record<string, any>) => Object.entries<any>(obj || {}).sort((a, b) => b[1].calls - a[1].calls)
      .map(([k, v]) => html`<div class="row"><span class="grow preview">${k}</span>
        <span class="num small muted">${v.calls} · ${secs(v.seconds)} · ${v.chars} car.${v.errors ? html` · <span style="color:var(--danger)">${v.errors} errori</span>` : nothing}</span>
        <span class="num">${money(v.cost)}</span></div>`);
    return html`
      <div class="actions" style="justify-content:flex-start;margin:0 0 12px">
        ${[7, 30, 90].map(d => html`<hxk-button variant=${d === this.days ? 'primary' : 'ghost'} @click=${() => { this.days = d; this.loadTab(); }}>${d} giorni</hxk-button>`)}
      </div>
      <hxk-stat .items=${[{ label: 'Operazioni', value: t.calls || 0 }, { label: 'Minuti ascoltati', value: t.minutes || 0 },
        { label: 'Caratteri letti', value: t.chars || 0 }, { label: 'Costo', value: money(t.cost), hint: 'Dai prezzi in Impostazioni' },
        { label: 'Errori', value: t.errors || 0 }]}></hxk-stat>
      <div class="cols" style="margin-top:16px">
        <hxk-card heading="Per uso">${Object.keys(u.by_use || {}).length ? rows(u.by_use) : html`<span class="muted">Ancora niente.</span>`}</hxk-card>
        <hxk-card heading="Per motore">${Object.keys(u.by_provider || {}).length ? rows(u.by_provider) : html`<span class="muted">Ancora niente.</span>`}</hxk-card>
      </div>
      <hxk-card heading="Ultime operazioni" style="margin-top:16px">
        ${(u.recent || []).slice(0, 20).map((r: any) => html`<div class="row">
          <span class="num small muted">${when(r.at)}</span>
          <span class="grow preview">${r.kind === 'transcribe' ? 'Ascolto' : 'Voce'} · ${r.use_case || '–'}</span>
          <span class="small muted preview">${r.provider || '–'}${r.model ? ` · ${r.model}` : ''}</span>
          ${r.ok ? (r.fallback ? html`<hxk-badge tone="warning">ripiego</hxk-badge>` : nothing) : html`<hxk-badge tone="danger" title=${r.error || ''}>errore</hxk-badge>`}
        </div>`)}
      </hxk-card>`;
  }

  // ── Audio conservati ───────────────────────────────────────────────────
  private async listen(id: string) {
    const r = await this.host.api('GET', `${API}/audio/${id}`);
    if (!r.ok) { this.host.toast(r.error || 'Audio non trovato', 'danger'); return; }
    this.play(r.data.audio_b64, r.data.mime_type);
  }

  private async download(item: any) {
    const r = await this.host.api('GET', `${API}/audio/${item.blob_id}`);
    if (!r.ok) return;
    const a = document.createElement('a');
    a.href = `data:${r.data.mime_type};base64,${r.data.audio_b64}`;
    a.download = `hestia-${String(item.at || '').slice(0, 19).replace(/[:T]/g, '-')}.${String(r.data.mime_type).includes('ogg') ? 'ogg' : 'webm'}`;
    a.click();
  }

  private async dropAudio(item: any) {
    const mine = item.class === 'recording';
    if (!(await this.host.confirm('Eliminare questo audio?', mine ? 'È una tua registrazione: non si può rifare.' : 'Si potrà rigenerare dal testo.',
      { label: 'Elimina', danger: true }))) return;
    const r = await this.host.api('DELETE', `${API}/audio/${item.blob_id}`);
    if (!r.ok) { this.host.toast(r.error || 'Non eliminato', 'danger'); return; }
    this.loadTab();
  }

  private audio() {
    if (this.error) return html`<hxk-state kind="error" text=${this.error} @retry=${() => this.loadTab()}></hxk-state>`;
    const k = this.kept;
    if (!k) return html`<hxk-state kind="loading"></hxk-state>`;
    const sp = k.space || {};
    const pct = sp.limit_bytes ? Math.min(100, Math.round((sp.total_bytes / sp.limit_bytes) * 100)) : 0;
    return html`
      <hxk-card heading="Spazio" subtitle=${`${bytes(sp.total_bytes)} di ${bytes(sp.limit_bytes)}`}>
        <div class="bar"><span style=${`width:${pct}%`}></span></div>
        ${Object.entries<any>(sp.classes || {}).map(([c, v]) => html`<div class="row"><span>${CLASSES[c] || c}</span>
          <span class="num small muted">${v.count} · ${bytes(v.bytes)}</span></div>`)}
        <div class="small muted" style="margin-top:6px">Le tue registrazioni non le tolgo mai; le risposte lette e le notifiche
          si rifanno dal testo e vanno via per prime.</div>
      </hxk-card>
      <hxk-card heading="Audio" style="margin-top:16px">
        ${(k.items || []).length ? (k.items || []).map((it: any) => html`<div class="row">
          <hxk-button variant="ghost" icon="play" title="Ascolta" @click=${() => this.listen(it.blob_id)}></hxk-button>
          <div class="grow"><div class="preview">${it.text || CLASSES[it.class] || it.class}</div>
            <div class="small muted">${when(it.at)} · ${CLASSES[it.class] || it.class}${it.duration_s ? ` · ${secs(it.duration_s)}` : ''} · ${bytes(it.size)}</div></div>
          <hxk-button variant="ghost" icon="upload" title="Scarica" style="transform:rotate(180deg)" @click=${() => this.download(it)}></hxk-button>
          <hxk-button variant="ghost" icon="trash" title="Elimina" @click=${() => this.dropAudio(it)}></hxk-button>
        </div>`) : html`<span class="muted">Nessun audio conservato.</span>`}
      </hxk-card>`;
  }

  render() {
    return html`
      <div class="tabs" role="tablist">${TABS.map(t => html`<button role="tab" aria-selected=${this.tab === t.id}
        @click=${() => this.select(t.id)}>${t.label}</button>`)}</div>
      ${this.tab === 'prova' ? this.prova() : this.tab === 'tua' ? html`<echo-your-voice .host=${this.host}></echo-your-voice>` : this.tab === 'motori' ? html`<echo-blocks .host=${this.host}></echo-blocks>`
        : this.tab === 'uso' ? this.uso() : this.audio()}`;
  }
}
