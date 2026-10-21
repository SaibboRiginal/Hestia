/**
 * <chronos-cal-details> — content of the event popover: everything about one occurrence and its rule, with actions.
 * Events: cal-act (DetailAction), cal-pick-occ (CalEvent picked from a summary chip), close. Ported from the WebUI's
 * event-details component.
 */
import { LitElement, css, html, nothing, tokens, kitStyles } from '@hestia/webui-sdk';
import type { HestiaHost } from '@hestia/webui-sdk';
import { type CalEvent, STATUS_META, TYPE_META, WINDOW_TEXT, fire, ownerLabel } from './models';
import { fmt } from './date';
import { describeRRule } from './rrule';
import { type MenuItem, calStyles, ic } from './ui';

export type DetailAction = 'edit' | 'skip' | 'unskip' | 'run' | 'pause' | 'resume' | 'cancel' | 'restore' | 'reset-move'
  | 'duplicate' | 'ask' | 'logs';

export class ChronosCalDetails extends LitElement {
  static properties = { ev: { attribute: false }, host: { attribute: false } };
  declare ev: CalEvent; declare host: HestiaHost;
  static styles = [tokens, kitStyles, calStyles, css`
    :host { display: block; padding: 12px 12px 14px 16px; }
    .top { display: flex; align-items: flex-start; gap: 6px; }
    .sw { width: 12px; height: 12px; border-radius: 4px; background: var(--c); margin-top: 6px; flex-shrink: 0; }
    .grow { flex: 1; min-width: 0; }
    h3 { font-size: 16px; font-weight: 600; line-height: 1.3; margin: 0; }
    .when { font-size: 13px; color: var(--text-2); margin-top: 2px; }
    .ib { padding: 5px; border-radius: var(--radius-sm); color: var(--text-2); line-height: 0; }
    .ib:hover { background: var(--surface-2); color: var(--text); }
    .badges { display: flex; flex-wrap: wrap; gap: 5px; margin: 10px 0 8px 20px; }
    .ob { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; padding: 1px 8px; border-radius: 99px;
      background: var(--surface-2); color: var(--text-2); }
    .ob i { width: 7px; height: 7px; border-radius: 50%; background: var(--c); }
    dl { display: grid; grid-template-columns: 20px 1fr; gap: 6px 8px; font-size: 13px; color: var(--text-2); margin: 0 0 0 -2px; }
    dt { color: var(--text-3); padding-top: 1px; } dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
    .desc { white-space: pre-wrap; } .err { color: var(--danger); }
    .detail { display: block; color: var(--text-3); font-size: 12px; }
    .grp { margin: 10px 0 4px 20px; } .grp-h { font-size: 12.5px; color: var(--text-2); margin-bottom: 6px; }
    .grp-l { display: flex; flex-wrap: wrap; gap: 4px; max-height: 120px; overflow-y: auto; }
    .gi { font-size: 11.5px; font-variant-numeric: tabular-nums; padding: 2px 7px; border-radius: 99px; background: var(--surface-2); color: var(--text-2); }
    .gi:hover { color: var(--text); } .gi.ok { box-shadow: inset 0 -2px 0 var(--success); }
    .gi.ko { background: var(--danger-soft); color: var(--danger); } .gi.sk { text-decoration: line-through; opacity: .6; }
    .grp-n { font-size: 11.5px; color: var(--text-3); margin-top: 5px; }
    .explain { display: flex; gap: 7px; margin: 10px 0 2px 20px; font-size: 13px; color: var(--text-2); line-height: 1.45; }
    .actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; padding-left: 20px; }
  `];

  private act(a: DetailAction) { fire(this, 'cal-act', a); }

  private when(): string {
    const e = this.ev, day = fmt.dayLong(e.start);
    if (!e.end) return `${day} · ${fmt.time(e.start)}`;
    return e.start.toDateString() === e.end.toDateString() ? `${day} · ${fmt.time(e.start)} – ${fmt.time(e.end)}`
      : `${fmt.dateTime(e.start)} → ${fmt.dateTime(e.end)}`;
  }

  private menu(): MenuItem[] {
    const e = this.ev, active = e.occ.status !== 'cancelled' && e.occ.status !== 'completed';
    return [
      { id: 'edit', label: 'Modifica', icon: 'edit' },
      { id: 'duplicate', label: 'Duplica', icon: 'copy' },
      { id: 'ask', label: 'Chiedi a Hestia…', icon: 'sparkle' },
      ...(e.item?.action || e.occ.run ? [{ id: 'logs', label: 'Log del modulo', icon: 'terminal' }] : []),
      ...(e.occ.moved ? [{ id: 'reset-move', label: 'Ripristina orario originale', icon: 'undo' }] : []),
      ...(active && e.occ.status !== 'paused' && e.occ.recurring ? [{ id: 'pause', label: 'Metti in pausa la regola', icon: 'pause' }] : []),
      ...(e.occ.status === 'paused' ? [{ id: 'resume', label: 'Riattiva', icon: 'play' }] : []),
      { id: 'd', label: '', divider: true },
      ...(active ? [{ id: 'cancel', label: e.occ.recurring ? 'Annulla tutta la regola' : 'Annulla', icon: 'trash', danger: true }] : []),
      ...(e.occ.status === 'cancelled' ? [{ id: 'restore', label: 'Ripristina', icon: 'undo' }] : []),
    ];
  }

  render() {
    const e = this.ev; if (!e) return nothing;
    const type = TYPE_META[e.occ.type] ?? TYPE_META.event;
    const status = STATUS_META[e.occ.status ?? 'confirmed'] ?? STATUS_META.confirmed;
    const rule = describeRRule(e.item?.recurrence);
    const forge = /^forge\.task\.([0-9a-f]{6,})$/.exec(e.occ.key)?.[1] ?? null;
    const lr = e.item?.last_result;
    const flex = (e.item?.params as any)?.flex as { earliest?: string; latest?: string } | undefined;
    const t = (d: Date) => fmt.time(d);
    return html`
      <div class="top" style="--c:${e.color}">
        <span class="sw"></span>
        <div class="grow"><h3>${e.occ.title}</h3><div class="when">${this.when()}</div></div>
        <button class="ib" aria-label="Modifica" title="Modifica" @click=${() => this.act('edit')}>${ic('edit', 16)}</button>
        <chronos-menu .items=${this.menu()} @select=${(x: CustomEvent) => { x.stopPropagation(); this.act(x.detail); }}>
          <button class="ib" aria-label="Altro">${ic('more', 16)}</button></chronos-menu>
        <button class="ib" aria-label="Chiudi" @click=${() => fire(this, 'close')}>${ic('x', 16)}</button>
      </div>
      ${e.group?.length ? html`<div class="grp">
        <div class="grp-h">${e.group.length} esecuzioni il ${fmt.dayLong(e.start)} · ${rule}</div>
        <div class="grp-l">${e.group.map(g => html`<button class="gi ${g.occ.run?.ok === false ? 'ko' : g.occ.run?.ok ? 'ok' : ''} ${g.occ.skipped ? 'sk' : ''}"
          title=${g.occ.run ? (g.occ.run.ok ? 'ok' : `fallita: ${g.occ.run.detail || ''}`) : 'non ancora eseguita'}
          @click=${() => fire(this, 'cal-pick-occ', g)}>${t(g.start)}</button>`)}</div>
        <div class="grp-n">Clic su un orario per aprire quella singola esecuzione.</div></div>` : nothing}
      ${e.occ.type === 'window' ? html`<p class="explain" style="--c:${e.color}">${ic('window', 14)}<span><b>Finestra ${t(e.start)}–${e.end ? t(e.end) : ''}.</b>
        ${WINDOW_TEXT[e.occ.owner] ?? `${ownerLabel(e.occ.owner)} può lavorare solo in questo intervallo; fuori dalla finestra le sue attività aspettano.`}</span></p>` : nothing}
      <div class="badges">
        <span class="ob" style="--c:${e.color}"><i></i>${ownerLabel(e.occ.owner)}</span>
        <span class="ob">${ic(type.icon, 11)} ${type.label}</span>
        <hxk-badge tone=${status.tone}>${status.label}</hxk-badge>
        ${e.occ.skipped ? html`<hxk-badge tone="warning">occorrenza saltata</hxk-badge>` : nothing}
        ${e.occ.moved ? html`<hxk-badge tone="info">spostata</hxk-badge>` : nothing}
        ${e.item?.user_modified ? html`<hxk-badge tone="accent">modificata da te</hxk-badge>` : nothing}
      </div>
      <dl>
        ${e.occ.recurring ? html`<dt>${ic('repeat', 14)}</dt><dd>${rule}</dd>` : nothing}
        ${e.item?.description ? html`<dt>${ic('list', 14)}</dt><dd class="desc">${e.item.description}</dd>` : nothing}
        ${flex ? html`<dt>${ic('clock', 14)}</dt><dd>Orario flessibile tra ${flex.earliest || '…'} e ${flex.latest || '…'}:
          parte prima o dopo i tuoi impegni${e.occ.run?.flex ? html`<span class="detail">Questa volta alle
          ${fmt.time(new Date(e.occ.run.flex.at))}, ${e.occ.run.flex.reason}</span>` : nothing}</dd>` : nothing}
        ${e.item?.action ? html`<dt>${ic('zap', 14)}</dt><dd><code>${e.item.action.method || 'POST'} ${e.item.action.service}${e.item.action.path}</code></dd>` : nothing}
        ${e.occ.run ? html`<dt>${ic(e.occ.run.ok ? 'check' : 'alert', 14)}</dt>
          <dd class=${e.occ.run.ok ? '' : 'err'}>Questa esecuzione: ${e.occ.run.ok ? 'ok' : 'fallita'}${e.occ.run.duration_ms ? ` · ${e.occ.run.duration_ms} ms` : ''}
            ${(e.failedCount ?? 0) > 1 ? ` · fallita ${e.failedCount} volte negli ultimi giorni` : ''}
            ${!e.occ.run.ok && e.occ.run.detail ? html`<span class="detail">${e.occ.run.detail}</span>` : nothing}</dd>`
          : lr ? html`<dt>${ic(lr.ok ? 'check' : 'alert', 14)}</dt>
          <dd class=${lr.ok ? '' : 'err'}>Ultima esecuzione della regola ${fmt.relative(new Date(lr.at))}: ${lr.ok ? 'ok' : 'fallita'}
            ${!lr.ok ? html`<span class="detail">${lr.detail}</span>` : nothing}</dd>` : nothing}
        ${e.item?.parent ? html`<dt>${ic('branch', 14)}</dt><dd>Collegata a <code>${e.item.parent}</code>: se annulli quella, si annulla anche questa</dd>` : nothing}
        <dt>${ic('info', 14)}</dt><dd><code>${e.occ.key}</code></dd>
      </dl>
      <div class="actions">
        ${e.occ.skipped ? html`<hxk-button size="sm" icon="undo" @click=${() => this.act('unskip')}>Ripristina</hxk-button>`
          : e.occ.status !== 'cancelled' && e.occ.status !== 'completed'
            ? html`<hxk-button size="sm" @click=${() => this.act('skip')}>${e.occ.recurring ? 'Salta questa' : 'Ignora'}</hxk-button>` : nothing}
        ${e.item?.action && e.occ.status !== 'cancelled' ? html`<hxk-button size="sm" icon="play" @click=${() => this.act('run')}>Esegui ora</hxk-button>` : nothing}
        ${e.occ.status === 'paused' ? html`<hxk-button size="sm" variant="primary" icon="play" @click=${() => this.act('resume')}>Riattiva</hxk-button>` : nothing}
        ${e.occ.status === 'cancelled' ? html`<hxk-button size="sm" variant="primary" icon="undo" @click=${() => this.act('restore')}>Ripristina regola</hxk-button>` : nothing}
        ${forge ? html`<hxk-button size="sm" @click=${() => this.host.navigate('sviluppo', { task: forge }, 'hephaestus')}>Apri in Sviluppo</hxk-button>` : nothing}
        <hxk-button size="sm" variant="ghost" icon="sparkle" title="Modifica o spiega questa voce a parole" @click=${() => this.act('ask')}>Chiedi a Hestia</hxk-button>
      </div>`;
  }
}
