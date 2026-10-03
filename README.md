# Knitarr v0.1.0

Self-hosted cross-stitch pattern library — search legitimate sources, track wanted patterns, import into a local library, and view charts in the browser.

Radarr/Sonarr-style flow for craft patterns (MVP focuses on cross-stitch).

## Quick start

```bash
cp .env.example .env   # optional
docker compose build
docker compose up -d
```

### Git remote (GitHub, etc.)

This repository has no `origin` yet. When you have a URL:

```bash
git remote add origin <your-github-url>
git push -u origin main
git push origin v0.1.0
```

Open `http://localhost:8765` (or `KNITARR_PORT`).

## MVP status

### What works (verified E2E)

- **Internet Archive indexer** — search, metadata, add to wanted, background download/import
- **Demo items imported:** `the-unicorn-book` (multi-page JPEG), `sigerus-hough-2023-charted-folk-designs` (PDF)
- **Dedupe:** re-importing sample OXS returns duplicate of pattern #1
- **Wanted queue** — worker polls every ~15s with polite User-Agent and rate-limit backoff
- **Library** — downloaded patterns with checksum deduplication
- **OXS** — parse, normalized JSON, grid viewer with legend, zoom, progress marks
- **PDF / images** — inline PDF iframe; multi-page JPEG sets with zoom
- **Sample OXS** — “Import sample OXS” on Search page (bundled `samples/sample.oxs`)
- **REST API** under `/api/*`

### Sources (MVP)

| Source | Status |
|--------|--------|
| Internet Archive | **Working** — Scrape Search + Metadata API |
| DMC / blogs / Etsy | **Not automated** — index-only or manual import only (see [docs/ECOSYSTEM.md](docs/ECOSYSTEM.md)) |

### Formats

| Format | Import | View |
|--------|--------|------|
| OXS | Yes | Stitch grid + legend |
| PDF | Yes (IA) | Browser iframe |
| JPEG/PNG scans | Yes (IA) | Pan/zoom |
| PCStitch `.pat` | No | — |

### Legal / automation limits

- Only sources with **documented machine access** are indexed automatically (IA).
- v0.1 is **local-only** with no multi-user sharing; source `licenseurl` is kept in metadata when IA provides it — no enforcement layer yet.
- Lending-only / access-restricted IA items are skipped.

### Next steps

1. Manifest indexer for curated CC/git pattern lists
2. Index-only adapter for DMC free library (link + user-owned import)
3. PCStitch import via user conversion to OXS/PDF
4. FTS / structured filters; optional AI query translation

### Technical viability

The **acquisition + library model is viable** for API-first and public-domain/CC collections. Most commercial/free blog patterns remain **manual or index-only**.

## Development

```bash
# Backend
cd backend
pip install -r requirements.txt
export KNITARR_DATA_DIR=/tmp/knitarr-data KNITARR_DB_PATH=/tmp/knitarr-data/db.sqlite KNITARR_LIBRARY_DIR=/tmp/knitarr-data/library
mkdir -p $KNITARR_DATA_DIR
PYTHONPATH=. uvicorn knitarr.main:app --reload --port 8765

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

## API (selected)

- `GET /api/search?q=…`
- `POST /api/wanted` `{ "indexer_id", "external_id" }`
- `GET /api/wanted`, `GET /api/patterns`
- `GET /api/patterns/{id}/normalized`
- `POST /api/import/sample-oxs`

## Environment

| Variable | Default |
|----------|---------|
| `KNITARR_DATA_DIR` | `/data` |
| `KNITARR_IA_USER_AGENT` | Knitarr/0.1 … |
| `KNITARR_WORKER_INTERVAL_SEC` | `15` |

See [docs/ECOSYSTEM.md](docs/ECOSYSTEM.md) for format and licensing research.
