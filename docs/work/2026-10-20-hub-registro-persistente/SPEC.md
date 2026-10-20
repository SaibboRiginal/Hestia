# Hub: persistent registry

| | |
|---|---|
| **Version** | 1.0 |
| **Source** | Hestia AI proactive (brainstorm 2026-10-19, item 11 «Registro Hub persistente»), started by Marko 2026-10-20 («voglio che venga fatto tutto») |
| **Status** | Draft, waiting for Marko's ok |

## Goal
When Hub restarts it knows at once where every service is, instead of being blind until each one re-registers
(keepalive every 60 s). Routing, discovery, catalog and the *Mappa* work from the first second after a restart.

## Today
- `ServiceRegistry` (`Hestia-Hub/src/modules/registry.py`) is a dict in memory. A Hub restart empties it.
- Every service re-registers every 60 s (`start_hub_keepalive`), so after a restart routes return
  "service unavailable" for up to ~60 s, Oracle's tool list and the WebUI catalog are empty meanwhile.
- The registry `revision` restarts from 0, so watchers (Telegram, Hermes) can see a lower number than before.
- A dead instance is never removed (only `deregister` removes it); it is just tried last.

## Design

### Where the data lives: a snapshot file owned by Hub (not Archive)
Hub cannot keep its registry in Archive: Archive itself registers through Hub, and every call to Archive goes
through the Hub route, so at boot Hub would need the registry to read the registry. The snapshot is a **cache of
Hub's own routing table**, not business data, so it stays inside Hub: one JSON file in a Docker volume.

- File: `/code/data/registry.json` in the container, volume `./Hestia-Hub/data:/code/data` (both compose files).
  `data/` is already git-ignored. No new env var: the path is a constant.
- Content: `{"version": 1, "saved_at", "revision", "services": [<instance as registered>, …]}`; each instance keeps
  `updated_at` (last heartbeat). Only what services sent at registration: no secrets are added.
- Write: atomic (temp file + `os.replace`). Immediately on a real change (created / updated / deregister);
  heartbeat refreshes (`refreshed`) are written at most once every 30 s, during the register call itself
  (no timer, no loop). Also written once on Hub shutdown. Small file, few writes: fine for the Pi's SD card.
- Read: once at startup. Missing, unreadable or corrupt file → log `event=hub_registry_restore_failed`
  `[🔄]` and start empty, exactly as today (Hub never fails to start because of the snapshot).

### Restore rules
- Instances whose last heartbeat is older than **24 h** are dropped at restore (a service removed or renamed
  while Hub was down does not come back as a ghost). Constant, not a setting: it is read before any other
  service, Themis included, can answer.
- Restored instances get `restored: true` until their first re-registration clears it. They are routable at once;
  `updated_at` is kept, so *Mappa* shows them online only if their last heartbeat is inside the usual 180 s
  window, which is the honest state.
- `revision` continues from the saved value and is bumped once (`reason="restore"`) so watchers refresh.
- Log `event=hub_registry_restored services=<n> instances=<n> dropped=<n> age_seconds=<s>`.

### Unchanged
- Services keep re-registering every 60 s: that stays the source of truth, the snapshot only covers the gap.
- No API change for callers. `GET /api/registry/services` and `/api/ui/map` may show `restored: true` on an instance.
- No feature switch: persistence is always on.

## Acceptance criteria
1. Restart Hub alone (`docker restart hestia_hub`): `GET /api/registry/services` lists the services immediately and
   `POST /api/route/archive/health` works before any keepalive arrives.
2. Revision after the restart is greater than before.
3. Corrupt or missing `registry.json` → Hub starts empty and logs the recovery line.
4. Instances older than 24 h are not restored.
5. Heartbeats alone write the file at most once every 30 s.
6. Unit tests for save/load/age filter/corrupt file/throttle (`Hestia-Hub/tests/test_hub_registry_persist.py`).

## Docs to update
`Hestia-Hub/hestia-hub.md` (Constraints: «No persistence dependency» becomes «local snapshot, optional»),
`Hestia-Swagger/swagger.yml` (`restored` field on service entries), compose files (volume + comment),
`docs/ARCHITECTURE.md` (Hub line), root `CHANGELOG.md`.
