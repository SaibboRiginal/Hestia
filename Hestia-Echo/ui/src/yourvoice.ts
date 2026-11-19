/**
 * <echo-your-voice> — tab «Your voice» of the page «Voice»: the voiceprint (record it once, at least 6 seconds of
 * speech, so the TV and other people do not end up in what you dictate; forget it) and the personal dictionary
 * (names and words passed to every listening engine; the ones learnt from your corrections become sure after a few
 * times). Calls GET/POST/DELETE /api/voice/voiceprint, GET/POST /api/voice/dictionary, DELETE /dictionary/{word}.
 * Dossier 2026-10-24-whole-cindy-brainstorm Cindy 10 + 17 (W4) + W7.
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, Recorder, blobToB64, secs, when } from './util';

const MIN_SECONDS = 6;
const SAMPLE = tr('Read aloud: «Hi {assistant}, this is my voice. Today I\'ll tell you about my day, what I did ') +
               tr('and what I need to remember for tomorrow, calmly and without hurry.»');

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
    if (!p.ok && !d.ok) { this.error = p.error || tr('Not reachable'); return; }
    this.error = '';
    this.print = p.ok ? p.data : null;
    this.words = d.ok ? d.data : null;
  }

  private async toggle() {
    if (!this.recording) {
      try { await this.rec.start(); } catch { this.host.toast(tr('The browser doesn\'t give me the microphone'), 'danger'); return; }
      this.recording = true; this.started = Date.now(); this.elapsed = 0;
      this.timer = window.setInterval(() => (this.elapsed = (Date.now() - this.started) / 1000), 250);
      return;
    }
    window.clearInterval(this.timer);
    this.recording = false;
    const blob = await this.rec.stop();
    if (!blob) return;
    if (this.elapsed < MIN_SECONDS) { this.host.toast(tr("Speak for at least {0} seconds", MIN_SECONDS), 'warning'); return; }
    this.busy = 'enroll';
    const r = await this.host.api('POST', `${API}/voiceprint`, { body: { audio_b64: await blobToB64(blob), mime_type: this.rec.mime } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('Voice print not saved'), 'danger'); return; }
    this.host.toast(tr('Voice print saved'), 'success');
    this.load();
  }

  private async forget() {
    if (!(await this.host.confirm(tr('Remove the voiceprint?'), tr('I\'ll listen to every voice again.'), { label: tr('Remove'), danger: true }))) return;
    this.busy = 'forget';
    const r = await this.host.api('DELETE', `${API}/voiceprint`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('alt::Failed'), 'danger'); return; }
    this.host.toast(tr('Voice print removed'), 'success');
    this.load();
  }

  private async addWord() {
    const w = this.word.trim();
    if (!w) return;
    this.busy = 'add';
    const r = await this.host.api('POST', `${API}/dictionary`, { body: { word: w } });
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('Word not added'), 'warning'); return; }
    this.word = '';
    this.load();
  }

  private async dropWord(w: string) {
    this.busy = `w:${w}`;
    const r = await this.host.api('DELETE', `${API}/dictionary/${encodeURIComponent(w)}`);
    this.busy = '';
    if (!r.ok) { this.host.toast(r.error || tr('f::Not removed'), 'warning'); return; }
    this.host.toast(tr('Word removed'), 'success', { label: tr('Cancel'), run: async () => {
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
      <hxk-card heading=${tr("Voice print")} subtitle=${p.enrolled ? tr("Saved {0}{1}", when(p.at), p.seconds ? ` · ${secs(p.seconds)}` : '') : tr('Not recorded yet')}>
        <div class="small muted">${tr("With the voice print I recognise your voice: the TV and other people don't end up in what you dictate and don't keep the live mode turn open.")}</div>
        ${p.engine_error ? html`<div class="small" style="color:var(--warning);margin-top:6px">${tr("Recognition not available now:")} ${p.engine_error}</div>` : nothing}
        <div class="sample" style="margin-top:10px">${SAMPLE}</div>
        <div class="mic">
          <button class=${this.recording ? 'on' : ''} @click=${() => this.toggle()} aria-label=${this.recording ? tr('Stop and save') : tr('f::Log')}>
            <hxk-icon name=${this.recording ? 'stop' : 'mic'} size=${26}></hxk-icon></button>
          <span class="small muted">${this.recording ? tr("I'm listening… {0} s{1}", Math.floor(this.elapsed), this.elapsed < MIN_SECONDS ? tr(' (at least {0})', MIN_SECONDS) : tr(', tap to save'))
            : this.busy === 'enroll' ? tr('Saving the voice print…') : p.enrolled ? tr('Tap to record it again') : tr('Tap and read the sentence')}</span>
        </div>
        ${p.enrolled ? html`<hxk-button variant="ghost" icon="trash" ?loading=${this.busy === 'forget'} @click=${() => this.forget()}>${tr("Remove the voiceprint")}</hxk-button>` : nothing}
      </hxk-card>
      <hxk-card heading=${tr("Your dictionary")} subtitle=${tr('{0} sure words', this.words?.confirmed ?? 0)}>
        <div class="small muted">${tr("Names and words the listening engines must expect. When you fix a transcription I learn the new words: after")} ${needed} ${tr("times they become safe.")}</div>
        <div style="margin-top:8px">${items.length ? items.map(d => html`<div class="w">
          <span class="grow">${d.word}</span>
          ${d.status === 'confirmed' ? html`<hxk-badge tone="success">${tr("safe")}</hxk-badge>` : html`<hxk-badge tone="neutral">${tr('{0} of {1}', d.count || 0, needed)}</hxk-badge>`}
          <hxk-button size="sm" variant="ghost" icon="trash" title=${tr("Remove")} ?loading=${this.busy === `w:${d.word}`} @click=${() => this.dropWord(d.word)}></hxk-button>
        </div>`) : html`<span class="muted small">${tr("No word yet.")}</span>`}</div>
        <div class="add"><hxk-field label=${tr("New word")} .value=${this.word} @change=${(e: CustomEvent) => (this.word = String(e.detail ?? ''))}></hxk-field>
          <hxk-button icon="plus" ?loading=${this.busy === 'add'} @click=${() => this.addWord()}>${tr("Add")}</hxk-button></div>
      </hxk-card>
    </div>`;
  }
}
