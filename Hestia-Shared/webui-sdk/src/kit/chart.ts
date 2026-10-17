import { LitElement, css, html, nothing, svg } from 'lit';
import { tokens } from '../styles';

export interface ChartSeries { name: string; values: number[]; color?: string }

const PALETTE = ['var(--cal-1)', 'var(--cal-2)', 'var(--cal-3)', 'var(--cal-4)', 'var(--cal-5)', 'var(--cal-6)', 'var(--cal-7)', 'var(--cal-8)'];
const fmt = (n: number) => Math.abs(n) >= 1000 ? new Intl.NumberFormat('it-IT', { notation: 'compact', maximumFractionDigits: 1 }).format(n) : String(Math.round(n * 10) / 10);

/**
 * Small dependency-free SVG chart: `type` line | bar | donut, `labels` (x), `series` [{name, values}], `unit`.
 * Colors from the categorical tokens --cal-1..8; hover shows the value.
 */
export class HxkChart extends LitElement {
  static properties = { type: {}, labels: { attribute: false }, series: { attribute: false }, unit: {}, height: { type: Number }, _hover: { state: true } };
  declare type: 'line' | 'bar' | 'donut';
  declare labels: string[];
  declare series: ChartSeries[];
  declare unit: string;
  declare height: number;
  declare _hover: { x: number; y: number; text: string } | null;
  constructor() { super(); this.type = 'line'; this.labels = []; this.series = []; this.unit = ''; this.height = 180; this._hover = null; }

  static styles = [tokens, css`
    :host { display: block; position: relative; }
    svg { width: 100%; display: block; overflow: visible; }
    .axis { stroke: var(--border); stroke-width: 1; }
    .lbl { fill: var(--text-3); font-size: 10.5px; }
    .legend { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--text-2); margin-top: 6px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; }
    .tip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--border-strong);
      box-shadow: var(--shadow-2); border-radius: var(--radius-sm); padding: 3px 8px; font-size: 12px; white-space: nowrap; transform: translate(-50%, -120%); }
  `];

  private color(i: number) { return this.series[i]?.color || PALETTE[i % PALETTE.length]; }

  private tip(e: MouseEvent, text: string) {
    const r = this.getBoundingClientRect();
    this._hover = { x: e.clientX - r.left, y: e.clientY - r.top, text };
  }

  render() {
    if (!this.series.length) return html`<hxk-state kind="empty"></hxk-state>`;
    const body = this.type === 'donut' ? this.donut() : this.xy();
    const legend = this.type === 'donut' ? this.labels : this.series.length > 1 ? this.series.map(s => s.name) : [];
    return html`${body}
      ${legend.length ? html`<div class="legend">${legend.map((n, i) => html`<span><i class="dot" style="background:${this.color(i)}"></i>${n}</span>`)}</div>` : nothing}
      ${this._hover ? html`<div class="tip" style="left:${this._hover.x}px;top:${this._hover.y}px">${this._hover.text}</div>` : nothing}`;
  }

  private xy() {
    const W = 600, H = this.height, L = 36, B = 22, T = 8;
    const n = Math.max(1, ...this.series.map(s => s.values.length));
    const all = this.series.flatMap(s => s.values);
    const max = Math.max(1, ...all), min = Math.min(0, ...all);
    const y = (v: number) => T + (H - T - B) * (1 - (v - min) / (max - min || 1));
    const step = (W - L) / n;
    const x = (i: number) => L + step * i + step / 2;
    const ticks = [min, (min + max) / 2, max];
    const every = Math.max(1, Math.ceil(n / 8));
    const unit = this.unit ? ` ${this.unit}` : '';
    const out = (e: MouseEvent, si: number, i: number) => this.tip(e, `${this.labels[i] ?? ''} · ${this.series[si].name}: ${fmt(this.series[si].values[i])}${unit}`);
    return html`<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px" @mouseleave=${() => (this._hover = null)}>
      ${ticks.map(t => svg`<line class="axis" x1=${L} x2=${W} y1=${y(t)} y2=${y(t)} stroke-dasharray="2 4"></line>
        <text class="lbl" x=${L - 6} y=${y(t) + 3} text-anchor="end">${fmt(t)}</text>`)}
      ${this.labels.map((l, i) => i % every ? nothing : svg`<text class="lbl" x=${x(i)} y=${H - 6} text-anchor="middle">${l}</text>`)}
      ${this.type === 'bar'
        ? this.series.map((s, si) => s.values.map((v, i) => {
            const bw = (step * 0.7) / this.series.length;
            const bx = L + step * i + step * 0.15 + bw * si;
            return svg`<rect x=${bx} y=${Math.min(y(v), y(0))} width=${bw} height=${Math.abs(y(0) - y(v))} rx="3"
              fill=${this.color(si)} @mousemove=${(e: MouseEvent) => out(e, si, i)}></rect>`;
          }))
        : this.series.map((s, si) => svg`<polyline fill="none" stroke=${this.color(si)} stroke-width="2.2" stroke-linejoin="round"
              vector-effect="non-scaling-stroke" points=${s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')}></polyline>
            ${s.values.map((v, i) => svg`<circle cx=${x(i)} cy=${y(v)} r="6" fill="transparent" @mousemove=${(e: MouseEvent) => out(e, si, i)}></circle>`)}`)}
    </svg>`;
  }

  private donut() {
    const values = this.series[0].values;
    const total = values.reduce((a, b) => a + b, 0) || 1;
    const R = 60, C = 2 * Math.PI * R;
    let acc = 0;
    return html`<svg viewBox="0 0 160 160" style="height:${this.height}px">
      ${values.map((v, i) => {
        const len = (v / total) * C;
        const seg = svg`<circle cx="80" cy="80" r=${R} fill="none" stroke=${this.color(i)} stroke-width="22"
          stroke-dasharray="${len} ${C - len}" stroke-dashoffset=${-acc} transform="rotate(-90 80 80)"
          @mousemove=${(e: MouseEvent) => this.tip(e, `${this.labels[i] ?? ''}: ${fmt(v)}${this.unit ? ' ' + this.unit : ''} (${Math.round((v / total) * 100)}%)`)}
          @mouseleave=${() => (this._hover = null)}></circle>`;
        acc += len;
        return seg;
      })}
      <text x="80" y="86" text-anchor="middle" style="fill:var(--text);font-size:20px;font-weight:600">${fmt(total)}</text>
    </svg>`;
  }
}
