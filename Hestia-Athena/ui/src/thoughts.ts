/**
 * <athena-thoughts> — "Thoughts": every Athena cycle, observe → think → gate (5 factors) → act, with accepted /
 * discarded candidates and why; open commitments; «Pensa ora» runs a cycle now and the list refreshes when done.
 * Two tracks (docs/work/2026-10-20-riflessione-a-livelli): Life (signals → links → details → observations for the
 * evening recap) and System (Hestia's own health).
 * Reads GET /api/athena/thinking/summary?track= · /api/athena/commitments; POST /api/athena/think?track=,
 * POST /api/athena/commitments/{id}/resolve.
 * Same page, no new one (docs/work/2026-11-13-prima-osserva-poi-propone): System shows what she is still collecting
 * proof for (GET /api/athena/evidence); the third tab «Writes to you» shows how much she wants to write now, why, what
 * she wrote and whether you answered (GET /api/athena/talk), with «Write to me now» (POST /api/athena/think?track=talk).
 */
import { HestiaElement, html, css, nothing, tr } from '@hestia/webui-sdk';
import { API, FACTORS, KINDS, OUTCOMES, ago, area, day, hours, linkText, pct, secs, when } from './util';

export class AthenaThoughts extends HestiaElement {
  static properties = { ...HestiaElement.properties, data: { state: true }, commitments: { state: true },
                        error: { state: true }, thinking: { state: true }, open: { state: true },
                        track: { state: true }, evidence: { state: true }, talk: { state: true } };
  declare track: 'life' | 'system' | 'talk';
  declare evidence: any; declare talk: any;
  declare data: any; declare commitments: any[] | null; declare error: string; declare thinking: boolean;
  declare open: Record<string, boolean>;
  private poll: number | undefined;

  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .sub { color: var(--text-3); font-size: 13px; }
    .line { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
    .chip { font-size: 11.5px; padding: 1px 7px; border-radius: var(--radius-full); background: var(--surface-2); color: var(--text-2); white-space: nowrap; }
    .chip.bad { background: var(--danger-soft); color: var(--danger); }
    .cycle { display: flex; flex-direction: column; gap: 10px; }
    .steps { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(min(100%, 200px), 1fr)); }
    .step { background: var(--surface-2); border-radius: var(--radius-md); padding: 8px 10px; font-size: 13px; }
    .step b { display: block; font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-3); margin-bottom: 2px; }
    .cand { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }
    .cand.ok { border-color: var(--success); }
    .title { font-weight: 600; }
    .factors { display: grid; grid-template-columns: 76px 1fr 40px; gap: 3px 8px; align-items: center; font-size: 12px; }
    .bar { height: 6px; border-radius: 3px; background: var(--surface-3, var(--surface-2)); overflow: hidden; }
    .bar i { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
    .bar.inv i { background: var(--warning); }
    .score { display: flex; align-items: center; gap: 8px; font-size: 12.5px; }
    .gauge { position: relative; flex: 1; height: 8px; border-radius: 4px; background: var(--surface-2); }
    .gauge i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 4px; }
    .gauge.ev { flex: 0 0 90px; align-self: center; overflow: hidden; }
    .gauge .thr { position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--text-2); }
    .num { font-variant-numeric: tabular-nums; white-space: nowrap; }
    .muted2 { color: var(--text-2); font-size: 13px; }
    .comm { display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-top: 1px solid var(--border); }
    .comm:first-child { border-top: 0; }
    .tabs { display: inline-flex; gap: 2px; padding: 2px; border-radius: var(--radius-full); background: var(--surface-2); }
    .tabs button { border: 0; background: none; font: inherit; font-size: 13px; padding: 4px 12px; border-radius: var(--radius-full); color: var(--text-2); cursor: pointer; }
    .tabs button[aria-pressed="true"] { background: var(--surface); color: var(--text-1); box-shadow: var(--shadow-1); }
    .items { margin: 4px 0 0; padding-left: 16px; }
    .items li { margin: 2px 0; }
    .link { background: none; border: 0; padding: 0; color: var(--accent); cursor: pointer; font: inherit; font-size: 12.5px; }
  `];

  constructor() { super(); this.data = null; this.commitments = null; this.error = ''; this.thinking = false; this.open = {}; this.track = 'life'; this.evidence = null; this.talk = null; }

  connectedCallback() {
    super.connectedCallback();
    this.load();
    this.onHost('refresh', () => this.load());
    this.onHost('visible', () => this.load());
  }
  disconnectedCallback() { super.disconnectedCallback(); window.clearTimeout(this.poll); }

  private async load(): Promise<any> {
    if (this.track === 'talk') return this.loadTalk();
    const [t, c, e] = await Promise.all([
      this.host.api('GET', `${API}/thinking/summary`, { query: { limit: 15, track: this.track } }),
      this.host.api('GET', `${API}/commitments`, { query: { limit: 20 } }),
      this.track === 'system' ? this.host.api('GET', `${API}/evidence`) : Promise.resolve({ ok: false } as any),
    ]);
    this.evidence = e.ok ? e.data : null;
    if (!t.ok) { this.error = t.status === 0 ? tr('Athena not reachable') : t.error || tr('Athena not reachable'); return null; }
    this.error = '';
    this.data = t.data;
    this.commitments = c.ok ? c.data.commitments || [] : null;
    if (t.data.running && !this.thinking) this.watch(t.data.cycles?.[0]?.record_id);
    return t.data;
  }

  private async loadTalk(): Promise<any> {
    const r = await this.host.api('GET', `${API}/talk`, { query: { days: 14 } });
    if (!r.ok) { this.error = r.status === 0 ? tr('Athena not reachable') : r.error || tr('Athena not reachable'); return null; }
    this.error = '';
    this.talk = r.data;
    return r.data;
  }

  private async writeNow() {
    const before = this.talk?.items?.[0]?.id;
    const r = await this.host.api('POST', `${API}/think`, { query: { track: 'talk' } });
    if (!r.ok) { this.host.toast(r.error || tr('Athena not reachable'), 'danger'); return; }
    this.host.toast(tr('Thinking about it: if there\'s something to tell you, you\'ll find it in chat'), 'info');
    this.thinking = true;
    window.clearTimeout(this.poll);
    const wait = (tries: number) => {
      this.poll = window.setTimeout(async () => {
        const d = await this.loadTalk();
        if (this.track !== 'talk') { this.thinking = false; return; }
        if ((d?.items?.[0]?.id ?? before) !== before || tries >= 30) { this.thinking = false; return; }
        wait(tries + 1);
      }, 4000);
    };
    wait(0);
  }

  /** Poll until the running cycle ends, then show it. */
  private watch(before?: string, tries = 0) {
    this.thinking = true;
    window.clearTimeout(this.poll);
    this.poll = window.setTimeout(async () => {
      const d = await this.load();
      if (d && !d.running) {
        this.thinking = false;
        const fresh = d.cycles?.[0];
        if (fresh && fresh.record_id !== before) {
          const n = (fresh.candidates || []).filter((x: any) => x.accepted).length;
          const what = this.track === 'life' ? (n === 1 ? tr('observation for the recap') : tr('observations for the recap'))
            : (n === 1 ? tr('useful idea') : tr('useful ideas'));
          this.host.toast(n ? tr("Athena thought: {0} {1}", n, what) : tr('Athena thought: nothing to say now'), n ? 'success' : 'info');
          this.open = { ...this.open, [fresh.record_id]: true };
        }
        return;
      }
      if (tries < 60) this.watch(before, tries + 1); else this.thinking = false;
    }, 3000);
  }

  private async thinkNow() {
    const before = this.data?.cycles?.[0]?.record_id;
    const r = await this.host.api('POST', `${API}/think`, { query: { track: this.track } });
    if (!r.ok) { this.host.toast(r.error || tr('Athena not reachable'), 'danger'); return; }
    if (r.data?.status === 'busy') this.host.toast(tr('Athena is already thinking'), 'info');
    else this.host.toast(tr('Athena is thinking…'), 'info');
    this.watch(before);
  }

  private async resolve(c: any, status: 'resolved' | 'dismissed') {
    const r = await this.host.api('POST', `${API}/commitments/${encodeURIComponent(c.brief_id)}/resolve`, { body: { status } });
    if (!r.ok) { this.host.toast(r.error || tr('alt::Failed'), 'danger'); return; }
    this.load();
  }

  private factors(c: any) {
    const s = c.signals || {};
    const w = this.data?.weights || {};
    return html`<div class="factors">${FACTORS.map(f => html`
      <span title=${`${tr("weight")} ${Math.round((w[f.key] || 0) * 100)}%${f.inverse ? tr(' (counts backwards: less trouble = better)') : ''}`}>${f.label}</span>
      <span class=${f.inverse ? 'bar inv' : 'bar'}><i style="width:${pct(s[f.key])}"></i></span>
      <span class="num muted">${pct(s[f.key])}</span>`)}</div>`;
  }

  private candidate(c: any, threshold: number) {
    const out = OUTCOMES[c.outcome] || (c.accepted ? { label: tr('f::accepted'), tone: 'success' } : OUTCOMES.discarded);
    const score = Number(c.score || 0);
    return html`<div class=${c.accepted ? 'cand ok' : 'cand'}>
      <div class="line"><span class="title grow">${c.title || tr('Untitled')}</span>
        <hxk-badge tone=${c.accepted ? 'success' : 'neutral'}>${c.accepted ? tr('f::accepted') : tr('f::discarded')}</hxk-badge></div>
      <div class="line"><span class="chip">${KINDS[c.kind] || c.kind}</span>${c.domain ? html`<span class="chip">${c.domain}</span>` : nothing}
        ${c.priority && c.priority !== 'normal' ? html`<span class="chip">${tr("priority")} ${c.priority}</span>` : nothing}
        ${c.kind === 'setting' && c.setting_key ? html`<span class="chip">${c.setting_key} → ${c.setting_value}</span>` : nothing}</div>
      ${c.summary ? html`<div class="muted2">${c.summary}</div>` : nothing}
      ${c.reasoning ? html`<div class="small muted">${tr("Why:")} ${c.reasoning}</div>` : nothing}
      <div class="score"><span class="num">${score.toFixed(2)}</span>
        <span class="gauge" title=${tr("Score and threshold")}><i style="width:${pct(score)};background:${c.accepted ? 'var(--success)' : 'var(--text-3)'}"></i>
          <span class="thr" style="left:${pct(threshold)}"></span></span>
        <span class="num muted">${tr("threshold")} ${threshold.toFixed(2)}</span></div>
      ${this.factors(c)}
      <div class="line">${c.gate_reason ? html`<span class="small muted grow">${c.gate_reason}</span>` : html`<span class="grow"></span>`}
        <hxk-badge tone=${out.tone}>${out.label}</hxk-badge></div>
    </div>`;
  }

  private setTrack(t: 'life' | 'system' | 'talk') {
    if (t === this.track) return;
    window.clearTimeout(this.poll); this.thinking = false;
    this.track = t; this.data = null; this.talk = null; this.load();
  }

  private tabs() {
    return html`<span class="tabs" role="group" aria-label=${tr("Track")}>
      <button aria-pressed=${String(this.track === 'life')} @click=${() => this.setTrack('life')}>${tr("Life")}</button>
      <button aria-pressed=${String(this.track === 'system')} @click=${() => this.setTrack('system')}>${tr("System")}</button>
      <button aria-pressed=${String(this.track === 'talk')} @click=${() => this.setTrack('talk')}>${tr("Writes to you")}</button></span>`;
  }

  /** System: findings she saw but does not propose yet (first observe, then propose). */
  private renderEvidence() {
    const e = this.evidence;
    if (!e) return nothing;
    const items: any[] = (e.items || []).filter((x: any) => (x.days || []).length);
    const observing = e.known_days < e.min_days;
    const subtitle = observing
      ? tr("She's still observing: day {0} of {1}. Before that she proposes no improvements or changes.", e.known_days, e.min_days)
      : tr("She proposes an improvement or a change only after seeing it on {0} different days.", e.seen_days);
    return html`<hxk-card heading=${tr("Collecting evidence")} subtitle=${subtitle}>
      ${items.length ? items.map(x => html`<div class="comm"><div class="grow">
          <div><b>${x.title || String(x.key || '').replace(/^(setting|improvement):/, '')}</b> <span class="chip">${KINDS[x.kind] || x.kind}</span></div>
          <div class="small muted">${tr("seen in")} ${x.days.length === 1 ? tr('1 day of {0}', e.seen_days) : tr('{0} days of {1}', x.days.length, e.seen_days)}
            ${tr("· last time")} ${day(x.days[x.days.length - 1])}</div></div>
        <span class="gauge ev" title=${tr("Days on which she saw it")}><i style="width:${pct(x.days.length / Math.max(1, e.seen_days))};background:var(--accent)"></i></span></div>`)
        : html`<div class="small muted">${tr("Nothing being collected now.")}</div>`}
      <div class="small muted">${tr("Faults are reported to you right away. «Think now» doesn't wait.")}</div>
    </hxk-card>`;
  }

  /** «Writes to you»: her drive to write now, the reasons, what she wrote and how it went. */
  private renderTalk() {
    const t = this.talk;
    if (!t) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const s = t.state;
    const items: any[] = t.items || [];
    const answer = (a: any) => a === true ? { label: tr('you answered'), tone: 'success' }
      : a === false ? { label: tr('no answer'), tone: 'warning' } : { label: tr('waiting'), tone: 'neutral' };
    return html`<div class="page">
      <div class="head"><h1>${tr("Thoughts")}</h1><span class="sub">${tr("When and why she writes to you first")}</span><span class="grow"></span>
        ${this.tabs()}
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>${tr("Refresh")}</hxk-button>
        <hxk-button variant="primary" icon="chat" ?loading=${this.thinking} @click=${() => this.writeNow()}>${this.thinking ? tr('Thinking about it…') : tr('Write to me now')}</hxk-button></div>
      ${s ? html`<hxk-card heading=${tr("Wants to write to you now")} subtitle=${tr("It grows if you haven't talked for a while and she has something true to tell you, it drops if you don't answer her, it's low in the first days")}>
        <div class="score"><span class="num">${Number(s.drive).toFixed(2)}</span>
          <span class="gauge" title=${tr("Desire and threshold")}><i style="width:${pct(s.drive)};background:${s.wants ? 'var(--success)' : 'var(--text-3)'}"></i>
            <span class="thr" style="left:${pct(s.bar)}"></span></span>
          <span class="num muted">${tr("threshold")} ${Number(s.bar).toFixed(2)}</span>
          <hxk-badge tone=${s.wants ? 'success' : 'neutral'}>${s.wants ? tr('would write to you') : tr('silent for now')}</hxk-badge></div>
        <div class="line" style="margin-top:8px">
          ${s.idle_seconds != null ? html`<span class="chip">${tr("your last message")} ${hours(s.idle_seconds)}</span>` : nothing}
          <span class="chip">${tr("has known you for")} ${s.known_days === 1 ? tr('1 day') : tr('{0} days', s.known_days)}</span>
          ${s.unanswered ? html`<span class="chip bad">${s.unanswered} ${tr("no answer")}</span>` : nothing}</div>
        ${(s.reasons || []).length ? html`<ul class="items small muted">${s.reasons.map((r: string) => html`<li>${r}</li>`)}</ul>`
          : html`<div class="small muted">${tr("Today she has no particular reasons.")}</div>`}
      </hxk-card>` : nothing}
      <hxk-card heading=${tr("What she wrote you")} subtitle=${tr("Last 14 days")}>
        ${items.length ? items.map(x => html`<div class="comm"><div class="grow">
            <div>${x.text}</div>
            <div class="small muted">${when(x.at)}${x.trigger === 'manual' ? tr(' · asked by you') : ''}${x.drive != null ? ` · ${tr('drive')} ${Number(x.drive).toFixed(2)}` : ''}</div>
            ${(x.reasons || []).length ? html`<div class="small muted">${tr("Why:")} ${x.reasons.join(' · ')}</div>` : nothing}</div>
          <hxk-badge tone=${answer(x.answered).tone}>${answer(x.answered).label}</hxk-badge></div>`)
          : html`<div class="small muted">${tr("She hasn't written to you first yet.")}</div>`}
      </hxk-card>
      <p class="small muted">${tr("How many times a day, how talkative and the pause between two messages are changed in Settings → System → Athena. The times are in Agenda.")}</p>
    </div>`;
  }

  /** Life cycle: what it read, the links it found, what it asked, what went to the recap. */
  private lifeSteps(r: any, cands: any[], threshold: number, verdict: string) {
    const l = r.life || {};
    const sig: any[] = l.signals || [];
    const links: any[] = l.links || [];
    const topics: any[] = l.topics || [];
    const strong = sig.filter(s => s.severity !== 'info').length;
    return html`<div class="steps">
      <div class="step"><b>${tr("1 · Reads the signals")}</b>${sig.length === 1 ? tr('1 signal') : tr('{0} signals', sig.length)} ${tr("of the areas")}${strong ? tr(", {0} to look at", strong) : ''}
        · ${l.series || 0} ${tr("weekly trends")}
        ${sig.length ? html`<ul class="items small muted">${sig.slice(0, 4).map(s => html`<li>${area(s.domain)}: ${s.text}</li>`)}</ul>` : nothing}</div>
      <div class="step"><b>${tr('2 · Links')}</b>${links.length ? tr("{0} {1} across different areas", links.length, links.length === 1 ? tr('link') : tr('links')) : tr('No link strong enough')}
        ${links.length ? html`<ul class="items small muted">${links.slice(0, 3).map(x => html`<li>${linkText(x)}</li>`)}</ul>` : nothing}</div>
      <div class="step"><b>${tr('3 · Looks deeper')}</b>${topics.length ? tr("{0} {1}, details asked to the areas", topics.length, topics.length === 1 ? tr('topic') : tr('topics')) : tr('Nothing new to look into')}
        ${topics.length ? html`<ul class="items small muted">${topics.map(t => html`<li>${t.text}</li>`)}</ul>` : nothing}</div>
      <div class="step"><b>${tr("4 · Thinks and filters")}</b>${cands.length ? (cands.length === 1 ? tr('1 idea, threshold {0}', threshold.toFixed(2)) : tr('{0} ideas, threshold {1}', cands.length, threshold.toFixed(2))) : tr('No observations')}
        <div class="small muted">${verdict} · ${secs(r.duration_ms)}</div></div>
      <div class="step"><b>${tr("5 · For the recap")}</b>${r.emitted_count ? tr("{0} in the evening recap", r.emitted_count) : tr('nothing for the recap')}
        ${r.error ? html`<div class="small" style="color:var(--danger)">${r.error}</div>` : nothing}</div>
    </div>`;
  }

  private cycle(r: any, first: boolean) {
    const o = r.observation || {};
    const cands: any[] = r.candidates || [];
    const accepted = cands.filter(c => c.accepted).length;
    const isOpen = this.open[r.record_id] ?? first;
    const threshold = Number(r.threshold || this.data?.threshold || 0);
    const verdict = !cands.length ? tr('no idea') : tr("{0} accepted out of {1}", accepted, cands.length);
    return html`<hxk-card>
      <div class="cycle">
        <div class="line"><b class="grow">${when(r.cycle_at)}</b>
          <hxk-badge tone=${r.trigger === 'manual' ? 'accent' : 'neutral'}>${r.trigger === 'manual' ? tr('on request') : tr('automatic')}</hxk-badge>
          <hxk-badge tone=${accepted ? 'success' : 'neutral'}>${verdict}</hxk-badge>
          ${r.error ? html`<hxk-badge tone="danger">${tr("error")}</hxk-badge>` : nothing}
          <button class="link" @click=${() => (this.open = { ...this.open, [r.record_id]: !isOpen })}>${isOpen ? tr('Close') : tr('Details')}</button></div>
        ${isOpen && r.track === 'life' ? html`${this.lifeSteps(r, cands, threshold, verdict)}
          ${cands.map(c => this.candidate(c, threshold))}` : nothing}
        ${isOpen && r.track !== 'life' ? html`
          <div class="steps">
            <div class="step"><b>${tr("1 · Observes")}</b>${o.services} ${tr("services")}${o.unhealthy_services?.length
              ? html`, <span style="color:var(--danger)">${o.unhealthy_services.length} ${tr("down (")}${o.unhealthy_services.join(', ')})</span>` : tr(', all ok')}
              · ${o.recent_errors} ${tr("errors in the last hour")}${o.active_commitments ? tr(" · {0} open commitments", o.active_commitments) : ''}
              ${(o.domains || []).length ? html`<div class="small muted">${o.domains.map((d: any) => tr("{0}: {1} new, {2} pending", d.domain, d.recent, d.pending)).join(' · ')}</div>` : nothing}
              ${(o.quality_issues || []).length ? html`<div class="small muted">${tr("Weak points:")} ${o.quality_issues.join(' · ')}</div>` : nothing}
              ${o.presence ? html`<div class="small muted">${o.presence}</div>` : nothing}</div>
            <div class="step"><b>${tr('2 · Thinks')}</b>${cands.length ? tr("{0} {1} from the model", cands.length, cands.length === 1 ? tr('idea') : tr('ideas')) : tr('No useful action found')}
              <div class="small muted">${secs(r.duration_ms)}</div></div>
            <div class="step"><b>${tr("3 · Filters")}</b>${tr("score on 5 factors, threshold")} ${threshold.toFixed(2)}
              <div class="small muted">${verdict}</div></div>
            <div class="step"><b>${tr("4 · Acts")}</b>${r.emitted_count ? tr("{0} sent", r.emitted_count) : tr('nothing sent')}
              ${r.error ? html`<div class="small" style="color:var(--danger)">${r.error}</div>` : nothing}</div>
          </div>
          ${cands.map(c => this.candidate(c, threshold))}` : nothing}
      </div></hxk-card>`;
  }

  private renderCommitments() {
    const list = this.commitments;
    if (list === null) return nothing;
    return html`<hxk-card heading=${tr("Open commitments")} subtitle=${tr("Ideas sent that Athena keeps an eye on until they expire")}>
      ${list.length ? list.map(c => html`<div class="comm"><div class="grow">
          <div><b>${c.title}</b> <span class="chip">${KINDS[c.kind] || c.kind}</span></div>
          ${c.summary ? html`<div class="small muted">${c.summary}</div>` : nothing}
          <div class="small muted">${tr("score")} ${Number(c.score || 0).toFixed(2)} · ${tr("expires {0}", when(c.expires_at))}</div></div>
        <div class="line"><hxk-button size="sm" variant="ghost" icon="check" @click=${() => this.resolve(c, 'resolved')}>${tr("Done")}</hxk-button>
          <hxk-button size="sm" variant="ghost" icon="x" @click=${() => this.resolve(c, 'dismissed')}>${tr("Ignore")}</hxk-button></div></div>`)
        : html`<div class="small muted">${tr("No open appointment.")}</div>`}
    </hxk-card>`;
  }

  render() {
    if (this.error) return html`<div class="page"><hxk-state kind="offline" text=${this.error} @retry=${() => this.load()}></hxk-state></div>`;
    if (this.track === 'talk') return this.renderTalk();
    const d = this.data;
    if (!d) return html`<div class="page"><hxk-state kind="loading"></hxk-state></div>`;
    const cycles: any[] = d.cycles || [];
    const last = cycles[0];
    return html`<div class="page">
      <div class="head"><h1>${tr("Thoughts")}</h1><span class="sub">${this.track === 'life' ? tr('What she notices about your life: it ends up in the evening recap') : tr('How Hestia is: services, errors, improvements')}</span><span class="grow"></span>
        ${this.tabs()}
        <hxk-button variant="ghost" icon="refresh" @click=${() => this.load()}>${tr("Refresh")}</hxk-button>
        <hxk-button variant="primary" icon="play" ?loading=${this.thinking} @click=${() => this.thinkNow()}>${this.thinking ? tr('alt::Thinking…') : tr('Think now')}</hxk-button></div>
      <div class="line">
        ${this.track === 'life' ? html`<hxk-badge tone="neutral">${tr("once a day, before the recap (time in Agenda)")}</hxk-badge>`
          : html`<hxk-badge tone=${d.loop_enabled ? 'success' : 'warning'}>${d.loop_enabled ? tr("thinks on its own every {0} min", Math.round(d.interval_seconds / 60)) : tr('automatic thinking off')}</hxk-badge>`}
        ${d.strategist_enabled ? nothing : html`<hxk-badge tone="warning">${tr("reasoning off: no idea")}</hxk-badge>`}
        <span class="chip">${tr("threshold")} ${Number(d.threshold).toFixed(2)}</span>
        ${last ? html`<span class="small muted">${tr("last cycle")} ${ago(last.cycle_at)}</span>` : nothing}</div>
      ${this.track === 'system' ? this.renderEvidence() : nothing}
      ${this.track === 'system' ? this.renderCommitments() : nothing}
      ${cycles.length ? cycles.map((r, i) => this.cycle(r, i === 0))
        : html`<hxk-state kind="empty" text=${this.track === 'life'
          ? tr('No reflection yet: it happens once a day before the evening recap. Press «Think now» to have one right away.')
          : tr('No cycle yet since Athena started. Press «Think now».')}></hxk-state>`}
      <p class="small muted">${tr("Score = 30% urgency + 25% usefulness + 20% novelty + 15% confidence + 10% (1 − trouble). Thresholds and times are changed in Settings → System → Athena.")}</p>
    </div>`;
  }
}
