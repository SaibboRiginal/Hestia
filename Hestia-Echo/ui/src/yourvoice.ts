/**
 * <echo-your-voice> — tab «La tua voce» of the page «Voce»: the voiceprint (record it once, at least 6 seconds of
 * speech, so the TV and other people do not end up in what you dictate; forget it) and the personal dictionary
 * (names and words passed to every listening engine; the ones learnt from your corrections become sure after a few
 * times). Calls GET/POST/DELETE /api/voice/voiceprint, GET/POST /api/voice/dictionary, DELETE /dictionary/{word}.
 * Dossier 2026-10-24-tutto-brainstorm-cindy Cindy 10 + 17 (W4) + W7.
 */
import { HestiaElement, html, css, nothing } from '@hestia/webui-sdk';
import { API, Recorder, blobToB64, secs, when } from './util';

const MIN_SECONDS = 6;
const SAMPLE = 'Leggi ad alta voce: «Ciao Hestia, questa è la mia voce. Oggi ti racconto la giornata, cosa ho fatto ' +
               'e cosa devo ricordare per domani, con calma e senza fretta.»';

export class EchoYourVoice extends HestiaElement {
  static properties = { ...HestiaElement.properties, print: { state: true }, words: { state: true }, error: { state: true },
                        recording: { state: true }, elapsed: { state: true }, busy: { state: true }, word: { state: true } };
  declare print: any; declare words: any; declare error: string; declare recording: boolean; declare elapsed: number;
  declare busy: string; declare word: string;
  private rec = new Recorder();
  private timer: number | undefined;
  private started = 0;

  static styles = [...HestiaElement.styles, css`
    .cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); align-items: start; }
    .mic { display: flex; align-items: center; gap: 12px; margin: 10px 0; }
    .mic button { width: 56px; height: 56px; border-radius: 50%; border: 1px solid var(--border-strong); background: var(--surface);
      color: var(--accent); cursor: pointer; display: grid; place-items: center; }
    .mic button.on { background: var(--danger); color: var(--accent-contrast); border-color: var(--danger); }
    .mic button:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .sample { font-size: 13px; color: var(--text-2); border-left: 2px solid var(--border-strong); padding-left: 8px; }
    .w { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-top: 1px solid var(--border); }
    .w:first-of-type { border-top: 0; }
    .add { display: flex; gap: 8px; align-items: flex-end; margin-top: 10px; }
    .add hxk-field { flex: 1; }
  `];

  constructor() {
    super(); this.print = null; this.words = null; this.error = ''; this.recording = false; this.elapsed = 0; this.busy = '';
    this.word = '';
  }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.clearInterval(this.timer);
    if (this.recording) this.rec.stop();
  }

  private async load() {
    const [p, d] = await Promise.all([this.host.api('GET', `${API}/voiceprint`), this.host.api('GET', `${API}/dictionary`)]);
    if (!p.ok && !d.ok) { this.error = p.error || 'Non raggiungibile'; return; }
    this.error = '';
    this.print = p.ok ? p.data : null;
    this.words = d.ok ? d.data : null;
  }

  private async toggle() {
    if (!this.recording) {
      try { await this.rec.start(); } catch { this.host.toast('Il browser non mi dà il microfono', 'danger'); return; }
      this.recording = true; this.started = Date.now(); this.elapsed = 0;
      this.timer = window.setInterval(() => (this.elapsed = (Date.now() - this.started) / 1000), 250);
      return;
    }
    window.clearInterval(this.timer);
    this.recording = false;
    const blob = await this.rec.stop();
    if (!blob) return;
    if (this.elapsed < MIN_SECONDS) { this.host.toast(`Parla almeno ${MIN_SECONDS} secondi`, 'warning'); return; }
    this.busy = 'enroll';
    const r = await this.host.api('POST', `${API}/voiceprint`, { body: { audio_b64: await blobToB64(blob), mime_type: this.rec.mime } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Impronta non salvata', 'danger'); return; }
    this.host.toast('Impronta della voce salvata', 'success');
    this.load();
  }

  private async forget() {
    if (!(await this.host.confirm('Togliere l\'impronta?', 'Ascolterò di nuovo tutte le voci.', { label: 'Togli', danger: true }))) return;
    this.busy = 'forget';
    const r = await this.host.api('DELETE', `${API}/voiceprint`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non riuscito', 'danger'); return; }
    this.host.toast('Impronta tolta', 'success');
    this.load();
  }

  private async addWord() {
    const w = this.word.trim();
    if (!w) return;
    this.busy = 'add';
    const r = await this.host.api('POST', `${API}/dictionary`, { body: { word: w } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Parola non aggiunta', 'warning'); return; }
    this.word = '';
    this.load();
  }

  private async dropWord(w: string) {
    this.busy = `w:${w}`;
    const r = await this.host.api('DELETE', `${API}/dictionary/${encodeURIComponent(w)}`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || 'Non tolta', 'warning'); return; }
    this.host.toast('Parola tolta', 'success', { label: 'Annulla', run: async () => {
      await this.host.api('POST', `${API}/dictionary`, { body: { word: w } }); this.load(); } });
    this.load();
  }

  render() {
    if (this.error) return html`<hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state>`;
    if (!this.print && !this.words) return html`<hxk-state kind="loading"></hxk-state>`;
    const p = this.print || {};
    const items: any[] = (this.words?.items || []).filter((d: any) => d.status !== 'removed');
    const needed = this.words?.needed || 3;
    return html`<div class="cols">
      <hxk-card heading="Impronta della voce" subtitle=${p.enrolled ? `Salvata ${when(p.at)}${p.seconds ? ` · ${secs(p.seconds)}` : ''}` : 'Non ancora registrata'}>
        <div class="small muted">Con l'impronta riconosco la tua voce: la TV e le altre persone non finiscono in quello che detti
          e non tengono aperto il turno della modalità live.</div>
        ${p.engine_error ? html`<div class="small" style="color:var(--warning);margin-top:6px">Riconoscimento non disponibile ora: ${p.engine_error}</div>` : nothing}
        <div class="sample" style="margin-top:10px">${SAMPLE}</div>
        <div class="mic">
          <button class=${this.recording ? 'on' : ''} @click=${() => this.toggle()} aria-label=${this.recording ? 'Ferma e salva' : 'Registra'}>
            <hxk-icon name=${this.recording ? 'stop' : 'mic'} size=${26}></hxk-icon></button>
          <span class="small muted">${this.recording ? `Ti ascolto… ${Math.floor(this.elapsed)} s${this.elapsed < MIN_SECONDS ? ` (almeno ${MIN_SECONDS})` : ', tocca per salvare'}`
            : this.busy === 'enroll' ? 'Salvo l\'impronta…' : p.enrolled ? 'Tocca per registrarla di nuovo' : 'Tocca e leggi la frase'}</span>
        </div>
        ${p.enrolled ? html`<hxk-button variant="ghost" icon="trash" ?loading=${this.busy === 'forget'} @click=${() => this.forget()}>Togli l'impronta</hxk-button>` : nothing}
      </hxk-card>
      <hxk-card heading="Il tuo dizionario" subtitle=${`${this.words?.confirmed ?? 0} parole sicure`}>
        <div class="small muted">Nomi e parole che i motori di ascolto devono aspettarsi. Quando correggi una trascrizione imparo
          le parole nuove: dopo ${needed} volte diventano sicure.</div>
        <div style="margin-top:8px">${items.length ? items.map(d => html`<div class="w">
          <span class="grow">${d.word}</span>
          ${d.status === 'confirmed' ? html`<hxk-badge tone="success">sicura</hxk-badge>` : html`<hxk-badge tone="neutral">${d.count || 0} di ${needed}</hxk-badge>`}
          <hxk-button size="sm" variant="ghost" icon="trash" title="Togli" ?loading=${this.busy === `w:${d.word}`} @click=${() => this.dropWord(d.word)}></hxk-button>
        </div>`) : html`<span class="muted small">Ancora nessuna parola.</span>`}</div>
        <div class="add"><hxk-field label="Nuova parola" .value=${this.word} @change=${(e: CustomEvent) => (this.word = String(e.detail ?? ''))}></hxk-field>
          <hxk-button icon="plus" ?loading=${this.busy === 'add'} @click=${() => this.addWord()}>Aggiungi</hxk-button></div>
      </hxk-card>
    </div>`;
  }
}
