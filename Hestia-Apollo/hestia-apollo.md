# Hestia-Apollo 🎨

**Role:** Images through a remote ComfyUI («Immagini») — flows per purpose, a job queue, images in Archive blobs
**Node:** main host; the generator runs where the GPU is (Marko's PC or a rented one)
**Stack:** Python · FastAPI · Docker · `websockets` · `hestia_common.module_kit`
**Port:** 19022 · Dossier: `docs/work/2026-10-24-tutto-brainstorm-cindy/` (W5, brainstorm A1)

---

## Responsibility

- The only module that talks to image generators. Env: `APOLLO_COMFYUI_URL`, `APOLLO_COMFYUI_KEY` (optional bearer
  token of a proxy). Empty → requests fail at once with `not_configured` and a notice.
- **Flows**: ComfyUI workflows in API format (ComfyUI → Save (API Format); the whole `/prompt` body is accepted too),
  one default per purpose (`generico, ritratto, sfondo, mascotte, icona, illustrazione`). Inputs (prompt, negative,
  width, height, seed) are detected on the usual txt2img nodes or given as `inputs: {prompt: "6.inputs.text", …}`.
  A purpose without a flow uses the `generico` one.
- **Jobs** (Archive `images-store`, kind `job`): one worker thread woken by new jobs (no timer); each job is queued on
  ComfyUI, followed on its websocket (`executing` with node null = done, `execution_error` = failed), the images are
  read from `/history` + `/view` and stored as Archive blobs. A job left `running` by a restart runs again.
- Results by **push**: `callback {service, path}` gets `{job_id, status, blob_ids, purpose, ref, error}` through Hub
  (the appearance module uses it); `notify` → a Hermes notice «Immagine pronta».
- Missing flow → job `failed` (`missing_flow`) and a Hermes notice saying where to upload one. Nothing is dropped.

## API (`/api/images`)

`GET /status` · `GET/POST /flows` · `PUT/DELETE /flows/{id}` · `GET/POST /jobs` (`POST` = request from a module) ·
`GET /jobs/{id}`. For the WebUI page:
`GET /jobs/{id}/image/{n}` (`{mime, data_b64}`).

## Tools (Telegram area «Immagini e aspetto»)

`immagine_crea` (waits up to 60 s, then says it will notify), `immagine_stato`, `immagine_lista`, `immagine_flussi`.
Images reach Telegram as photos through `display.files`.

## WebUI plugin

Pages **Immagini** (`apollo-images`: new image, grid of the jobs, refreshed every 4 s while one is queued or running), **Immagine** (`lavoro/:id`) and **Flussi** (`apollo-flows`: upload the ComfyUI API JSON per purpose, default flow). Built from `ui/` in the image (`hestia_common.module_kit` `kit.webui`).

## Tests

`Hestia-Apollo/tests/test_apollo.py` (fake ComfyUI, no network).
