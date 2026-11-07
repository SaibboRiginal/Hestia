/**
 * <hecate-devices> — «Dispositivi»: the accounts and devices that send data by themselves, as one list where every
 * service has the same card (<hecate-connections>: Google, Garmin, the Android phone… a new one is one more
 * connector in Hecate, no new card). The guided setup mounts the same list with `place="setup"`.
 */
import { HestiaElement, html, css } from '@hestia/webui-sdk';

export class HecateDevices extends HestiaElement {
  static styles = [...HestiaElement.styles, css`
    .head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }
    .sub { color: var(--text-3); font-size: 13px; }
    .wrap { max-width: 720px; }
  `];

  render() {
    return html`<div class="page">
      <div class="head"><h1>Dispositivi</h1><span class="sub">Gli account e i dispositivi che mandano dati da soli</span></div>
      <div class="wrap"><hecate-connections .host=${this.host}></hecate-connections></div>
    </div>`;
  }
}
