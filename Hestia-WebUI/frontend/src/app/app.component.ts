import { Component, inject } from '@angular/core';
import { Router, RouterOutlet } from '@angular/router';
import { AuthService } from './services/auth.service';
import { ThemeService } from './core/theme/theme.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet],
  template: `<router-outlet />`,
})
export class AppComponent {
  private auth = inject(AuthService);
  private router = inject(Router);
  // Instantiated at boot so the theme is applied before the first page renders.
  private theme = inject(ThemeService);

  constructor() {
    const t = new URLSearchParams(window.location.search).get('token');
    if (t) {
      void this.auth.login(t).then(ok => {
        history.replaceState({}, '', '/');
        this.router.navigate([ok ? '/' : '/login']);
      });
    }
  }
}
