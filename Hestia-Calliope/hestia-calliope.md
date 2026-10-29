# Hestia-Calliope 📄

**Role:** Real documents («Documenti», Cindy 21) — the assistant writes a small HTML draft, Calliope makes a PDF, a
Word or an Excel file with one of three shared themes, checks it and keeps it
**Node:** main host (with the other domain modules)
**Stack:** Python · FastAPI · Docker · reportlab · python-docx · openpyxl · pypdf
**Port:** 19027 · Dossier: `docs/work/2026-10-24-tutto-brainstorm-cindy/` (W5)

---

## Responsibility

- Draft: `h1–h3, p, ul/ol/li, table/tr/th/td, b/strong, i/em, br` (plain text = paragraphs on blank lines). One parser
  → blocks; the three renderers read the same blocks, so the formats say the same thing.
- Themes `classico` (Times, blue), `moderno` (Helvetica, teal, default = Themis `calliope.tema`), `sobrio`
  (Helvetica, grey). PDF: A4, title and date on top, page numbers. Excel: every table is a sheet named by the heading
  before it, numbers as numbers (Italian decimals), header row frozen; the rest goes to a «Note» sheet.
- **Final check** before delivering: the file opens again, has pages/sheets, contains the title (PDF/Word) and every
  `must_contain` text. A failed check returns `created: false` with what is missing and keeps nothing.
- Files in Archive blobs (`owner_module: calliope`), records in Archive `office-store` (kind `document`).
  Tool answers carry `display.files` (`hestia_common.display.file`): Telegram sends the file under the card.
- Export/import section `documenti` (with the files).

## API (`/api/office`)

`GET/POST /api/office` `{title, html, format pdf|docx|xlsx, theme?, must_contain?}` · `GET /{id}` ·
`GET /{id}/file` (download) · `DELETE /{id}` (record and blob).

## Tools (Telegram area «Documenti»)

`documento_crea`, `documento_creati`, `documento_creato_invia`, `documento_creato_elimina`.

## Tests

`Hestia-Calliope/tests/test_calliope.py` (every format × theme, check, blobs, endpoints).
