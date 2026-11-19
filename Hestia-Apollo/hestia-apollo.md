# Hestia-Apollo 🎨

**Role:** Images through a remote ComfyUI («Images») — flows per purpose, a job queue, images in Archive blobs
**Node:** main host; the generator runs where the GPU is (Marko's PC or a rented one)
**Stack:** Python · FastAPI · Docker · `websockets` · `hestia_common.module_kit`
**Port:** 19022 · Dossier: `docs/work/2026-10-24-whole-cindy-brainstorm/` (W5, brainstorm A1)

---

## Responsibility

- The only module that talks to image generators. Linked from the **ComfyUI** card on the WebUI page Connections
  (`hestia_common.connections`, `ComfyConnector` in `main.py`): the address is the Themis setting
  `apollo.comfyui.address` (shown in Settings with «Edit in Connections»), the optional key of a proxy is
  `APOLLO_KEY_COMFYUI`, written by Hephaestus into Apollo's `.env` and re-read live (`POST /api/connections/reload-keys`).
  «Test» answers with the ComfyUI version, the video card and free VRAM, and the models in `checkpoints`
  (`ComfyUI.probe`). Not linked → requests fail at once with `not_configured` and a notice that points to Connections.
  On the same PC as Docker the address is `http://host.docker.internal:8188` (compose maps `host-gateway`).
- **Flows**: ComfyUI workflows in API format (ComfyUI → Save (API Format); the whole `/prompt` body is accepted too),
  one default per purpose (`generico, ritratto, sfondo, mascotte, icona, illustrazione`). Inputs (prompt, negative,
  width, height, seed) are detected on the usual txt2img nodes or given as `inputs: {prompt: "6.inputs.text", …}`.
  A purpose without a flow uses the `generic` one.
- **Jobs** (Archive `images-store`, kind `job`): one worker thread woken by new jobs (no timer); each job is queued on
  ComfyUI, followed on its websocket (`executing` with node null = done, `execution_error` = failed), the images are
  read from `/history` + `/view` and stored as Archive blobs. A job left `running` by a restart runs again.
- Results by **push**: `callback {service, path}` gets `{job_id, status, blob_ids, purpose, ref, error}` through Hub
  (the appearance module uses it); `notify` → a Hermes notice «Image ready».
- Missing flow → job `failed` (`missing_flow`) and a Hermes notice saying where to upload one. Nothing is dropped.

## API (`/api/images`)

`GET /status` · `GET/POST /flows` · `PUT/DELETE /flows/{id}` · `GET/POST /jobs` (`POST` = request from a module) ·
`GET /jobs/{id}` · `GET /connections` · `POST /connections/{id}` · `POST /connections/{id}/{action}` (`test`, `edit`,
`cancel`) · `DELETE /connections/{id}` (shared contract) · `POST /api/connections/reload-keys`. For the WebUI page:
`GET /jobs/{id}/image/{n}` (`{mime, data_b64}`).

## Tools (Telegram area «Images and look»)

`image_create` (waits up to 60 s, then says it will notify), `image_status`, `image_list`, `image_flows`.
Images reach Telegram as photos through `display.files`.

## WebUI plugin

Pages **Immagini** (`apollo-images`: new image, grid of the jobs, refreshed every 4 s while one is queued or running), **Immagine** (`job/:id`) and **Flussi** (`apollo-flows`: upload the ComfyUI API JSON per purpose, default flow). Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Apollo/tests/test_apollo.py`, `tests/test_connection.py` (the ComfyUI card; fake ComfyUI, no network).


**2026-11-14 (backend English, dossier `docs/work/2026-11-14-english-backend`)**: tool descriptions and the module manual are English (for the model). What people read about the tools comes from `hestia_common/locales/<lang>/tools.json`.

**2026-11-15 (owner's language, dossier `docs/work/2026-11-14-english-backend`)**: the notices, errors and cards this module shows go through `hestia_common.i18n.t` and follow «Language».

**2026-11-15 (WebUI page in the owner's language, dossier `docs/work/2026-11-14-english-backend`)**: the texts of this module's WebUI page and widgets go through `tr` of `@hestia/webui-sdk` and follow «Language»; source texts in English, Italian in `Hestia-Shared/hestia_common/locales/it/messages.json`.

**2026-11-16 (no Italian in the code, dossier `docs/work/2026-11-14-english-backend` v2.0)**: every text is English in the code; Italian lives only in `Hestia-Shared/hestia_common/locales/it/messages.json`. Labels declared at registration (manifest, capabilities, agenda rules, settings) are plain English, translated at the edge.

**2026-11-19 (unified connections, dossier `docs/work/2026-11-19-unified-connections`)**: ComfyUI is linked from the Connections page (address in Themis, key via Hephaestus); `APOLLO_COMFYUI_URL/KEY` are gone from env and compose. The «Images» page button «Link ComfyUI» opens that card.
