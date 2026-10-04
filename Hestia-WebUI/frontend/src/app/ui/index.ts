/** Hestia UI kit — import from here: `import { ButtonComponent, ModalComponent } from '../../ui';` */
export * from './icon.component';
export * from './button.component';
export * from './basics';
export * from './overlays';
export * from './datetime';
export * from './diff';
export * from './markdown';

import { IconComponent } from './icon.component';
import { ButtonComponent } from './button.component';
import {
  BadgeComponent, EmptyStateComponent, FieldComponent, PageHeaderComponent, SegmentedComponent,
  SpinnerComponent, ToggleComponent,
} from './basics';
import { MenuComponent, ModalComponent, PopoverComponent } from './overlays';

/** Everything a feature page usually needs: `imports: [...UI]`. */
export const UI = [
  IconComponent, ButtonComponent, BadgeComponent, SpinnerComponent, EmptyStateComponent, FieldComponent,
  PageHeaderComponent, ToggleComponent, SegmentedComponent, ModalComponent, PopoverComponent, MenuComponent,
] as const;
