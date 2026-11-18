import { LitElement, css, html, nothing } from 'lit';
import { tokens } from '../styles';
import { tr } from '../i18n';

export type ChainOpt = { value: string; label: string };
/** One step of a chain: where (provider) and what (model, or voice for a voice chain). Other keys are kept as they are. */
export type ChainStep = { provider: string; [key: string]: any };
/** What happens to a step now (one sentence) and whether «Try again now» makes sense. */
export type ChainStepState = { tone: 'success' | 'warning' | 'danger' | 'neutral'; text: string; retry?: boolean } | null;

const OTHER = '\u0000other';

/**
 * <hxk-chain> — the one editor of an ordered list of «provider + model» steps (dossier 2026-11-18-problemi-del-test E):
 * the first ready step is used, the next ones are the fallback. Same component for the brain chains, the memory
 * (embedding) chain and the voice chains.
 *
 * Properties: `steps` (ChainStep[]), `providers` (ChainOpt[] the user can pick), `choices` ({provider: ChainOpt[]} of
 * the models that fit this chain; missing = not loaded yet, empty = the provider gives no list → free text),
 * `states` (ChainStepState per step), `field` ('model' | 'voice'), `pickLabel`, `addLabel`, `max` (0 = no limit).
 * Events: `steps-change` (detail = new steps), `need-choices` (detail = provider, when its list is missing),
 * `retry` (detail = {index, step}).
 */
export class HxkChain extends LitElement {
  static properties = { steps: { attribute: false }, providers: { attribute: false }, choices: { attribute: false },
                        states: { attribute: false }, field: {}, pickLabel: { attribute: 'pick-label' },
                        addLabel: { attribute: 'add-label' }, max: { type: Number }, typing: { state: true } };
  declare steps: ChainStep[];
  declare providers: ChainOpt[];
  declare choices: Record<string, ChainOpt[] | undefined>;
  declare states: ChainStepState[];
  declare field: string;
  declare pickLabel: string;
  declare addLabel: string;
  declare max: number;
  declare typing: Record<number, boolean>;

  constructor() {
    super(); this.steps = []; this.providers = []; this.choices = {}; this.states = []; this.field = 'model';
    this.pickLabel = ''; this.addLabel = ''; this.max = 0; this.typing = {};
  }

  static styles = [tokens, css`
    :host { display: block; }
    ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
    li { display: grid; grid-template-columns: 22px minmax(0, 1fr) minmax(0, 1.5fr) auto; gap: 8px; align-items: center;
      padding: 8px 0; border-top: 1px solid var(--border); }
    li:first-child { border-top: 0; }
    .n { font-variant-numeric: tabular-nums; color: var(--text-3); font-size: 13px; text-align: center; }
    select, input { font: inherit; color: var(--text); background: var(--surface-2); border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm); padding: 7px 10px; outline: none; width: 100%; min-width: 0; box-sizing: border-box; }
    select:focus, input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--focus-ring); }
    .tools { display: flex; gap: 2px; }
    .tools button { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px;
      min-width: var(--tap, 0px); min-height: var(--tap, 0px); border: 0; border-radius: var(--radius-sm);
      background: transparent; color: var(--text-2); cursor: pointer; }
    .tools button:hover { background: var(--surface-2); color: var(--text); }
    .tools button:disabled { opacity: .35; pointer-events: none; }
    .tools button:focus-visible { outline: none; box-shadow: 0 0 0 3px var(--focus-ring); }
    .state { grid-column: 2 / -1; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; font-size: 12.5px; color: var(--text-2); }
    .empty { color: var(--text-3); font-size: 13px; padding: 6px 0; }
    .first { font-size: 11px; color: var(--text-3); }
    .add { margin-top: 6px; }
    @media (max-width: 560px) { li { grid-template-columns: 22px minmax(0, 1fr) auto; }
      li > .model { grid-column: 2 / 3; grid-row: 2; } li > .tools { grid-row: 1 / 3; grid-column: 3; flex-direction: column; } }
  `];

  private emit(steps: ChainStep[]) {
    this.dispatchEvent(new CustomEvent('steps-change', { detail: steps, bubbles: true, composed: true }));
  }

  private patch(i: number, patch: Record<string, any>) {
    const next = this.steps.slice(); next[i] = { ...next[i], ...patch }; this.emit(next);
  }

  private move(i: number, d: number) {
    const next = this.steps.slice(); const [s] = next.splice(i, 1); next.splice(i + d, 0, s);
    this.typing = {}; this.emit(next);
  }

  private drop(i: number) { this.typing = {}; this.emit(this.steps.filter((_, j) => j !== i)); }

  private add() {
    const provider = this.steps[this.steps.length - 1]?.provider || this.providers[0]?.value || '';
    this.emit([...this.steps, { provider, [this.field]: '' }]);
  }

  private asked = new Set<string>();

  /** Ask the page once for the models of a provider whose list is missing. */
  private want(provider: string) {
    if (!provider || this.choices?.[provider] !== undefined || this.asked.has(provider)) return;
    this.asked.add(provider);
    this.dispatchEvent(new CustomEvent('need-choices', { detail: provider, bubbles: true, composed: true }));
  }

  private picker(i: number, step: ChainStep) {
    const value = String(step[this.field] || '');
    const list = this.choices?.[step.provider];
    const label = this.pickLabel || tr('Model');
    if ((list && !list.length) || this.typing[i])
      return html`<input aria-label=${label} .value=${value} placeholder=${tr('Name of the model')}
        @change=${(e: any) => this.patch(i, { [this.field]: String(e.target.value).trim() })}>`;
    const opts = list || [];
    const known = !value || opts.some(o => o.value === value);
    return html`<select aria-label=${label}
      @change=${(e: any) => {
        if (e.target.value === OTHER) { this.typing = { ...this.typing, [i]: true }; return; }
        this.patch(i, { [this.field]: e.target.value });
      }}>
      ${!value ? html`<option value="" selected disabled>${list ? tr('Choose…') : tr('Loading…')}</option>` : nothing}
      ${!known ? html`<option value=${value} selected>${value}</option>` : nothing}
      ${opts.map(o => html`<option value=${o.value} ?selected=${o.value === value}>${o.label}</option>`)}
      <option value=${OTHER}>${tr('Another one (write its name)…')}</option>
    </select>`;
  }

  updated() { for (const s of this.steps || []) this.want(s.provider); }

  render() {
    const full = this.max > 0 && this.steps.length >= this.max;
    return html`
      ${this.steps.length ? nothing : html`<div class="empty">${tr('No model yet: add the first one.')}</div>`}
      <ol>${this.steps.map((step, i) => {
        const st = this.states?.[i];
        const provs = this.providers.some(p => p.value === step.provider) || !step.provider
          ? this.providers : [{ value: step.provider, label: step.provider }, ...this.providers];
        return html`<li>
          <span class="n" title=${i === 0 ? tr('Used first') : tr('Used when the ones above are not available')}>${i + 1}</span>
          <select aria-label=${tr('Where')} @change=${(e: any) => { this.typing = {}; this.patch(i, { provider: e.target.value, [this.field]: '' }); }}>
            ${provs.map(p => html`<option value=${p.value} ?selected=${p.value === step.provider}>${p.label}</option>`)}
          </select>
          <div class="model">${this.picker(i, step)}</div>
          <div class="tools">
            <button ?disabled=${i === 0} aria-label=${tr('Move up')} @click=${() => this.move(i, -1)}><hxk-icon name="chevron-up" size="16"></hxk-icon></button>
            <button ?disabled=${i === this.steps.length - 1} aria-label=${tr('Move down')} @click=${() => this.move(i, 1)}><hxk-icon name="chevron-down" size="16"></hxk-icon></button>
            <button aria-label=${tr('alt::Remove')} @click=${() => this.drop(i)}><hxk-icon name="trash" size="15"></hxk-icon></button>
          </div>
          ${st ? html`<div class="state"><hxk-badge tone=${st.tone}>${st.text}</hxk-badge>
            ${st.retry ? html`<hxk-button size="sm" variant="ghost" @click=${() => this.dispatchEvent(new CustomEvent('retry', { detail: { index: i, step }, bubbles: true, composed: true }))}>${tr('Try again now')}</hxk-button>` : nothing}</div>` : nothing}
        </li>`; })}</ol>
      ${full ? nothing : html`<hxk-button class="add" variant="ghost" icon="plus" ?disabled=${!this.providers.length} @click=${() => this.add()}>${this.addLabel || tr('Add a model')}</hxk-button>`}`;
  }
}
