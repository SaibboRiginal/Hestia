import { ChangeDetectionStrategy, Component, HostListener, inject, viewChild } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { UI } from '../../ui';
import { TrPipe } from '../../core/i18n';
import { ConnectionsComponent } from './connections.component';

/**
 * «Connections» — every account, device and program at home that Hestia links, from every module, with the same
 * card (Marko 2026-11-19: one way to link, like plugins; `.env` only for secrets). Replaces
 * Hecate's «Devices» page. `?open=<module>.<id>` opens one card (Ctrl+K, a setting's «Edit in Connections»).
 */
@Component({
  selector: 'app-connections-page',
  imports: [TrPipe, ...UI, ConnectionsComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <hx-page-header [title]="'Connections' | tr" [subtitle]="'Accounts, devices and programs at home that {assistant} uses: link them and test them here' | tr" />
    <div class="body"><div class="wrap"><hx-connections [open]="open()" /></div></div>`,
  styles: [`
    :host { display: flex; flex-direction: column; min-height: 0; flex: 1; }
    .body { padding: 0 var(--page-pad, 20px) 24px; overflow: auto; }
    .wrap { max-width: 760px; }
  `],
})
export class ConnectionsPageComponent {
  private route = inject(ActivatedRoute);
  private list = viewChild(ConnectionsComponent);
  readonly open = toSignal(this.route.queryParamMap.pipe(map(q => q.get('open') ?? '')), { initialValue: '' });

  @HostListener('document:visibilitychange')
  onVisible(): void { if (document.visibilityState === 'visible') this.list()?.reload(); }
}
