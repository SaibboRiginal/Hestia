# Progress
- [x] Scan all branches + full history (gitleaks 8.21, grep for keys/tokens/emails/IPs, env/appsettings versions) → no real secrets
- [x] Compose: DB password from .env with current default, port 5432 bound to 127.0.0.1 (global + Archive)
- [x] Root `.env.example`
- [x] Validated with `docker compose config` (default and override)
- [ ] User: optionally set a new password (ALTER USER, then HESTIA_DB_PASSWORD in .env) and restart
