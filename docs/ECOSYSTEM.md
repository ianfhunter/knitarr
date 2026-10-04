# Knitarr — ecosystem research

Phase 1 research for cross-stitch pattern acquisition and library management.

## Pattern file formats

| Format | Nature | Knitarr handling |
|--------|--------|------------------|
| **OXS (.oxs)** | Open UTF-8 XML ([Ursa OXSFormat](https://www.ursasoftware.com/OXSFormat/)) | Canonical interchange: import/export, grid viewer, DMC extraction |
| **PCStitch (.pat)** | Proprietary binary, version-locked | Store original only; no server parser in MVP |
| **Pattern Maker (.xsd)** | Proprietary | Store original only |
| **Cross Stitch Saga (.saga)** | Unencrypted ZIP. Designer packs contain a symbol TTF plus Base64 `.xpub` members; no public spec for the inner bytes | Convert to OXS when the archive contains readable OXS/XML; `.xpub` packs stay original-only |
| **Microsoft XPS (.xps / .oxps)** | Open XML paper package | Rasterize with PyMuPDF, then the same chart-recognition path as PDF |
| **XSPro Platinum (.xsp)** | ZIP with `XSPPLAT\\0` local-header magic, member `adesignfile.xsu`, traditional ZIP encryption flag | Store original; convert only if the bytes are actually XPS |
| **Stitch Fiddle (.fcjson)** | Proprietary | Future |
| **PDF / PNG / JPG** | Delivery formats | Viewer-first; no invented stitch grid |
| **Internal JSON** | Knitarr normalized representation | Derived from OXS when available |

OXS note: some files use GBR hex order; parser treats colors as RGB unless configured.

## Open-source applications

- **Embroiderly** (GPL-3.0) — OXS read/write reference implementation in Rust
- **KXstitch** (GPL-2.0) — desktop editor
- **Stitchlet / Yarnl** — self-hosted craft libraries (crochet); architecture reference, not indexers
- **SugarStitch** — blog scraper; not used as default due to licensing ambiguity
- **ThreadMaster** — floss/kit organizer, not pattern discovery

No established OSS “Sonarr for cross-stitch” product exists.

## Legitimate data sources

| Source | Access | Knitarr mode |
|--------|--------|--------------|
| **Internet Archive** | Search scrape + metadata API | MVP indexer: search, metadata, download when files exist |
| **Wikimedia Commons** | MediaWiki API | Small category; supplement |
| **Openverse** | REST API | Poor fit (images, not charts; strict ToS) |
| **DMC / LoveCrafts** | Web storefront | Index-only + user-owned import |
| **Antique Pattern Library** | Public catalog HTML + PDFs | Search + download (public-domain scans) |
| **Cross Stitch Quest** | WordPress.com REST API | Search + download free posts (skip Patreon-only) |
| **Wizardi free charts** | Shopify `products.json` | Search only — free checkout on wizardi.com, then import |
| **Cyberstitchers** | HTML catalog + `/free_patterns/search_{q}` | Search + PDF/PAT download (personal use) |
| **Cross-Stitch.com** | `/api/semantic-search` + `/api/designs` | Search + CDN PDF download (site asks for registration) |
| **FreePatternsOnline** | HTML categories; live site Cloudflare-gated | Search via Wayback snapshots; download original chart files (no hotlink) |
| **Free pattern blogs** | HTML | Index-only or manual import per site T&C |

## APIs (MVP)

- `GET https://archive.org/services/search/v1/scrape` — search with cursor
- `GET https://archive.org/metadata/{identifier}` — item files and license
- `GET https://archive.org/download/{identifier}/{filename}` — file download

Use a descriptive `User-Agent`, honor HTTP 429 and `Retry-After`.

## Licensing model (v0.1)

Schema reserves `license_class` for later. The local-only MVP stores IA `licenseurl` in item metadata when present; no redistribution enforcement until sharing features exist.
