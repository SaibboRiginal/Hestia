# PROGRESS — WebUI local access without token

Spec: `SPEC.md` v1.0 · resume from the first unchecked box.

- [x] Current auth studied (TokenAuthMiddleware, ChatHub, AdminGuard, PublicUrlService, Angular guard/interceptor)
- [x] Dossier (SPEC v1.0, PROGRESS, CHANGELOG)
- [x] Backend: `LocalAccess` decision, `WebUISettings` (Themis register/effective/reload), middleware + hub + `/auth/access`
- [x] Frontend: AuthService `local`, async guard, login page skip, no "Esci" when local, SignalR without token
- [x] Docs: hestia-webui.md, swagger, compose comment, root CHANGELOG
- [x] `ng build` green (the .NET backend is not buildable in the cloud container: not compiled)
- [ ] User: `up-all.bat --build`, open from LAN (no token) and from the tunnel (token asked)
- [x] Real run 1 (user): `/auth/access` answers `local` but the browser still showed the login → old cached
      `index.html` (no Cache-Control) kept loading the old bundles. Fix: `index.html` served `no-cache`.
      Frontend checked with Playwright + mock API: `/` and `/login` both land on `/chat` when local.
