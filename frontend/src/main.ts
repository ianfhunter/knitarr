type View = "search" | "library" | "indexers" | "craft_files" | "pattern";

interface CraftConfig {
  craft_id: string;
  label: string;
  extensions: string[];
  enabled: boolean;
}

interface IndexerInfo {
  id: string;
  name: string;
  capabilities: {
    status: string;
    site_url: string;
    description: string;
    search_enabled: boolean;
    can_download: boolean;
    access_method: string;
  };
  craft_enabled: Record<string, boolean>;
}

interface ExternalHit {
  indexer_id: string;
  external_id: string;
  title: string;
  designer?: string;
  description?: string;
  source_url: string;
  license_class: string;
  thumbnail_url?: string;
  metadata?: { licenseurl?: string; license?: string };
}

interface PatternSummary {
  id: number;
  title: string;
  source?: string | null;
  craft: string;
  pattern_format: string;
  thumbnail_url?: string;
  width_stitches?: number;
  height_stitches?: number;
  color_count?: number;
  license_class: string;
}

interface PatternDetail extends PatternSummary {
  description?: string;
  source_url?: string;
  has_normalized: boolean;
  project_status?: string;
  file_count: number;
}

interface PatternFile {
  id: number;
  filename: string;
  mime_type: string;
  role?: string;
  size_bytes?: number;
}

interface Normalized {
  format: string;
  title?: string;
  width_stitches: number;
  height_stitches: number;
  palette: {
    index: number;
    number: string;
    name: string;
    color: string;
    symbol?: string;
    stitch_count?: number;
  }[];
  full_stitches: { x: number; y: number; palindex: number }[];
  backstitches?: { x1: number; y1: number; x2: number; y2: number; palindex: number }[];
}

const app = document.getElementById("app")!;
const SEARCH_CACHE_KEY = "knitarr_last_search";

interface SavedSearch {
  q: string;
  indexerId: string;
  craftId: string;
  results: ExternalHit[];
}

function loadSavedSearch(): SavedSearch | null {
  try {
    const raw = sessionStorage.getItem(SEARCH_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as SavedSearch;
    if (typeof parsed.q !== "string" || !Array.isArray(parsed.results)) return null;
    return parsed;
  } catch {
    return null;
  }
}

function saveSavedSearch(q: string, indexerId: string, craftId: string, results: ExternalHit[]) {
  const payload: SavedSearch = { q, indexerId, craftId, results };
  sessionStorage.setItem(SEARCH_CACHE_KEY, JSON.stringify(payload));
}

function bindEmptyCraftLink(container: HTMLElement) {
  container.querySelector("[data-view]")?.addEventListener("click", () => {
    view = "craft_files";
    render();
  });
}

let view: View = "search";
let selectedPatternId: number | null = null;
let selectedIndexerId = sessionStorage.getItem("knitarr_indexer") || "all";
let selectedCraftId = sessionStorage.getItem("knitarr_craft") || "cross_stitch";
let indexersCache: IndexerInfo[] = [];
type ResultSort = "title_asc" | "title_desc" | "source_asc" | "source_desc";
let searchResultHits: ExternalHit[] = [];
let searchResultsCacheNote = "";
let searchResultSourceFilter = sessionStorage.getItem("knitarr_result_source") || "all";
let searchResultSort = (sessionStorage.getItem("knitarr_result_sort") as ResultSort) || "title_asc";
type SymbolMode = "none" | "alphabet" | "numbers" | "symbols" | "alt";
const SYMBOL_MODES: { id: SymbolMode; label: string }[] = [
  { id: "none", label: "No symbols" },
  { id: "alphabet", label: "Alphabet" },
  { id: "numbers", label: "Numbers" },
  { id: "symbols", label: "Symbols" },
  { id: "alt", label: "Alt symbols" },
];
const SYMBOL_SET =
  "■□▲△▼▽◆◇●○★☆♠♥♦♣$€£¥¢§†‡¶※#@&%+×÷=¤⊕⊗•◦▬▪▫◐◑✚✕▣▤▥▦▧▨▩◊⊞⊟⊠";
const ALT_SYMBOL_SET =
  "ΑΒΓΔΘΛΞΠΣΦΨΩαβγδεθλσφω←↑→↓↔↕±∞√∑∏∂∇∫≈≠≤≥☀☁☂☎☑☒♪♫☺☼♀♂☾⚡⚓⚙❖❋✳✴";

function loadSymbolMode(): SymbolMode {
  const raw = sessionStorage.getItem("knitarr_symbol_mode");
  return SYMBOL_MODES.some((m) => m.id === raw) ? (raw as SymbolMode) : "none";
}

const gridState = { zoom: 16, symbolMode: loadSymbolMode(), marked: new Set<string>() };

function symbolModeLabel(mode: SymbolMode = gridState.symbolMode) {
  return SYMBOL_MODES.find((m) => m.id === mode)?.label || "No symbols";
}

function cycleSymbolMode(): SymbolMode {
  const i = SYMBOL_MODES.findIndex((m) => m.id === gridState.symbolMode);
  gridState.symbolMode = SYMBOL_MODES[(i + 1) % SYMBOL_MODES.length].id;
  sessionStorage.setItem("knitarr_symbol_mode", gridState.symbolMode);
  return gridState.symbolMode;
}

function paletteOrderIndex(palette: Normalized["palette"], palindex: number) {
  const used = palette.filter((p) => p.index > 0).sort((a, b) => a.index - b.index);
  return used.findIndex((p) => p.index === palindex);
}

function symbolForPalette(palette: Normalized["palette"], palindex: number, mode = gridState.symbolMode) {
  if (mode === "none" || palindex <= 0) return "";
  const order = paletteOrderIndex(palette, palindex);
  if (order < 0) return "";
  if (mode === "alphabet") {
    const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
    if (order < letters.length) return letters[order];
    return `${letters[order % 26]}${Math.floor(order / 26)}`;
  }
  if (mode === "numbers") return String(order + 1);
  const set = mode === "symbols" ? SYMBOL_SET : ALT_SYMBOL_SET;
  return set[order % set.length] || String(order + 1);
}

function contrastInk(raw: string) {
  const h = raw.replace("#", "");
  if (h.length !== 6) return "#111";
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b < 140 ? "#fff" : "#111";
}
let chartEditKeyHandler: ((ev: KeyboardEvent) => void) | null = null;

function clearChartEditKeys() {
  if (!chartEditKeyHandler) return;
  document.removeEventListener("keydown", chartEditKeyHandler);
  chartEditKeyHandler = null;
}

const NAV: { view: View; label: string }[] = [
  { view: "search", label: "Search" },
  { view: "library", label: "Library" },
  { view: "indexers", label: "Indexers" },
  { view: "craft_files", label: "Craft Files" },
];

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}

async function loadIndexers() {
  indexersCache = await api<IndexerInfo[]>("/api/indexers");
}

function indexerName(id: string) {
  return indexersCache.find((i) => i.id === id)?.name || id;
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}

function statusBadge(status: string) {
  if (status === "planned") return `<span class="badge badge-planned">Planned</span>`;
  if (status === "index_only") return `<span class="badge badge-index">Index only</span>`;
  return `<span class="badge">Active</span>`;
}

function currentPageLabel(activeView: View) {
  if (activeView === "pattern") return NAV.find((n) => n.view === "library")?.label || "Pattern";
  return NAV.find((n) => n.view === activeView)?.label || "Knitarr";
}

function closeMobileNav() {
  app.querySelector(".app-shell")?.classList.remove("nav-open");
}

function shell(content: string, activeView: View = view) {
  const nav = NAV.map(
    (n) =>
      `<button type="button" data-view="${n.view}" class="${activeView === n.view ? "active" : ""}">${n.label}</button>`
  ).join("");
  const pageLabel = currentPageLabel(activeView);
  app.innerHTML = `
    <div class="app-shell">
      <div class="sidebar-backdrop" id="sidebarBackdrop" aria-hidden="true"></div>
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-brand">Knitarr</div>
        <div class="sidebar-label">Library</div>
        <nav class="sidebar-nav">${nav}</nav>
      </aside>
      <div class="main-column">
        <header class="mobile-topbar">
          <button type="button" class="sidebar-toggle" id="sidebarToggle" aria-label="Open navigation menu">☰</button>
          <span class="mobile-title">Knitarr</span>
          <span class="mobile-page">${escapeHtml(pageLabel)}</span>
        </header>
        <div class="content">${content}</div>
      </div>
    </div>`;

  document.getElementById("sidebarToggle")?.addEventListener("click", () => {
    app.querySelector(".app-shell")?.classList.toggle("nav-open");
  });
  document.getElementById("sidebarBackdrop")?.addEventListener("click", closeMobileNav);

  app.querySelectorAll(".sidebar-nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      view = (btn as HTMLButtonElement).dataset.view as View;
      selectedPatternId = null;
      closeMobileNav();
      render();
    });
  });
}

async function loadCrafts(): Promise<CraftConfig[]> {
  return api<CraftConfig[]>("/api/craft-files");
}

function normalizeExtension(raw: string): string {
  const ext = raw.trim().toLowerCase();
  if (!ext) return "";
  return ext.startsWith(".") ? ext : `.${ext}`;
}

function extensionChipHtml(ext: string) {
  const safe = escapeHtml(ext);
  return `<span class="ext-chip" data-ext="${safe}">${safe}<button type="button" class="ext-remove" aria-label="Remove ${safe}">×</button></span>`;
}

function extensionsListHtml(extensions: string[]) {
  return extensions.map(extensionChipHtml).join("");
}

function readExtensionsFromCard(card: HTMLElement): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  card.querySelectorAll<HTMLElement>(".ext-chip").forEach((chip) => {
    const ext = normalizeExtension(chip.dataset.ext || chip.textContent || "");
    if (ext && !seen.has(ext)) {
      seen.add(ext);
      out.push(ext);
    }
  });
  return out;
}

function appendExtensionToCard(card: HTMLElement, raw: string): boolean {
  const ext = normalizeExtension(raw);
  if (!ext) return false;
  const list = card.querySelector(".ext-list")!;
  const existing = readExtensionsFromCard(card);
  if (existing.includes(ext)) return true;
  list.insertAdjacentHTML("beforeend", extensionChipHtml(ext));
  return true;
}

function bindCraftExtensionList(card: HTMLElement) {
  const list = card.querySelector(".ext-list")!;
  list.addEventListener("click", (ev) => {
    const btn = (ev.target as HTMLElement).closest(".ext-remove");
    if (!btn) return;
    const chip = btn.closest(".ext-chip");
    if (!chip) return;
    const remaining = readExtensionsFromCard(card).length;
    if (remaining <= 1) {
      alert("At least one extension is required.");
      return;
    }
    chip.remove();
  });

  const input = card.querySelector(".ext-add-input") as HTMLInputElement;
  const addBtn = card.querySelector(".btn-ext-add")!;
  const tryAdd = () => {
    const raw = input.value;
    if (!raw.trim()) return;
    if (appendExtensionToCard(card, raw)) input.value = "";
    input.focus();
  };
  addBtn.addEventListener("click", tryAdd);
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      tryAdd();
    }
  });
}

function craftOptions(crafts: CraftConfig[]) {
  return crafts
    .filter((c) => c.enabled)
    .map(
      (c) =>
        `<option value="${c.craft_id}"${selectedCraftId === c.craft_id ? " selected" : ""}>${escapeHtml(c.label)}</option>`
    )
    .join("");
}

function indexerEnabledForCraft(indexer: IndexerInfo, craftId: string) {
  if (!indexer.capabilities.search_enabled) return false;
  const map = indexer.craft_enabled || {};
  if (craftId in map) return map[craftId];
  return true;
}

function searchableIndexers(craftId: string = selectedCraftId) {
  return indexersCache.filter((i) => indexerEnabledForCraft(i, craftId));
}

function fairMergeHits(batches: ExternalHit[][], limit: number): ExternalHit[] {
  const merged: ExternalHit[] = [];
  let round = 0;
  while (merged.length < limit) {
    let added = false;
    for (const batch of batches) {
      if (round < batch.length) {
        merged.push(batch[round]!);
        added = true;
        if (merged.length >= limit) break;
      }
    }
    if (!added) break;
    round += 1;
  }
  return merged;
}

function refreshIndexerPick(pick: HTMLSelectElement) {
  const prev = pick.value;
  pick.innerHTML = indexerOptions();
  const allowed = new Set(searchableIndexers().map((i) => i.id));
  if (prev !== "all" && !allowed.has(prev)) {
    selectedIndexerId = "all";
    sessionStorage.setItem("knitarr_indexer", "all");
  }
  pick.value = selectedIndexerId;
}

function indexerOptions() {
  const searchable = searchableIndexers();
  const opts = [`<option value="all"${selectedIndexerId === "all" ? " selected" : ""}>All searchable sources</option>`];
  for (const i of searchable) {
    opts.push(
      `<option value="${i.id}"${selectedIndexerId === i.id ? " selected" : ""}>${escapeHtml(i.name)}</option>`
    );
  }
  return opts.join("");
}

function hitCard(hit: ExternalHit) {
  const thumb = hit.thumbnail_url
    ? `<img src="${hit.thumbnail_url}" alt="" loading="lazy" />`
    : `<div style="height:140px;background:#ddd"></div>`;
  return `
    <article class="card" data-ext="${hit.indexer_id}|${hit.external_id}">
      ${thumb}
      <div class="card-body">
        <h3>${escapeHtml(hit.title)}</h3>
        <div class="meta">${escapeHtml(hit.designer || "Unknown")} · <span class="badge">${escapeHtml(indexerName(hit.indexer_id))}</span></div>
        <div style="margin-top:0.5rem;display:flex;gap:0.35rem;flex-wrap:wrap">
          <button class="secondary btn-import">Add to Library</button>
          <a class="secondary" href="${hit.source_url}" target="_blank" rel="noopener">Open source</a>
        </div>
      </div>
    </article>`;
}

function isUserUpload(source: string | null | undefined) {
  return source === "user_import" || source === "manual";
}

function patternCard(p: PatternSummary) {
  const thumb = p.thumbnail_url
    ? `<img src="${p.thumbnail_url}" alt="" loading="lazy" />`
    : `<div style="height:140px;background:#ddd;display:flex;align-items:center;justify-content:center;color:#888">${p.pattern_format.toUpperCase()}</div>`;
  const delBtn = isUserUpload(p.source)
    ? `<button type="button" class="secondary btn-del-pat" data-pid="${p.id}">Delete</button>`
    : "";
  return `
    <article class="card" data-pid="${p.id}">
      ${thumb}
      <div class="card-body">
        <h3>${escapeHtml(p.title)}</h3>
        <div class="meta">${p.width_stitches || "?"}×${p.height_stitches || "?"} · ${p.color_count ?? "?"} colours</div>
        <div class="card-actions">
          <button type="button" class="secondary btn-rename-pat" data-pid="${p.id}">Rename</button>
          ${delBtn}
        </div>
      </div>
    </article>`;
}

function normalizeResultSort(raw: string): ResultSort {
  if (raw === "title_desc" || raw === "source_asc" || raw === "source_desc") return raw;
  return "title_asc";
}

function sortSearchHits(hits: ExternalHit[], sort: ResultSort): ExternalHit[] {
  const sorted = [...hits];
  sorted.sort((a, b) => {
    if (sort === "source_asc" || sort === "source_desc") {
      const bySource = indexerName(a.indexer_id).localeCompare(indexerName(b.indexer_id), undefined, {
        sensitivity: "base",
      });
      if (bySource !== 0) return sort === "source_desc" ? -bySource : bySource;
    }
    const byTitle = a.title.localeCompare(b.title, undefined, { sensitivity: "base" });
    return sort === "title_desc" ? -byTitle : byTitle;
  });
  return sorted;
}

function filterSearchHits(hits: ExternalHit[], sourceFilter: string): ExternalHit[] {
  if (sourceFilter === "all") return hits;
  return hits.filter((h) => h.indexer_id === sourceFilter);
}

function mountResultsToolbar(hits: ExternalHit[]) {
  const toolbar = document.getElementById("resultsToolbar");
  if (!toolbar) return;
  const sourceIds = [...new Set(hits.map((h) => h.indexer_id))].sort((a, b) =>
    indexerName(a).localeCompare(indexerName(b), undefined, { sensitivity: "base" })
  );
  const filterOpts = [
    `<option value="all">All sources</option>`,
    ...sourceIds.map(
      (id) => `<option value="${escapeHtml(id)}">${escapeHtml(indexerName(id))}</option>`
    ),
  ];
  toolbar.innerHTML = `
    <div class="results-toolbar-inner">
      <label class="results-control">Source
        <select id="resultSourceFilter">${filterOpts.join("")}</select>
      </label>
      <label class="results-control">Sort
        <select id="resultSort">
          <option value="title_asc">Title A→Z</option>
          <option value="title_desc">Title Z→A</option>
          <option value="source_asc">Source A→Z</option>
          <option value="source_desc">Source Z→A</option>
        </select>
      </label>
      <span class="meta" id="resultCount"></span>
    </div>`;
  const sourcePick = document.getElementById("resultSourceFilter") as HTMLSelectElement;
  const sortPick = document.getElementById("resultSort") as HTMLSelectElement;
  sourcePick.value = sourceIds.includes(searchResultSourceFilter) || searchResultSourceFilter === "all"
    ? searchResultSourceFilter
    : "all";
  searchResultSourceFilter = sourcePick.value;
  sortPick.value = normalizeResultSort(searchResultSort);
  searchResultSort = normalizeResultSort(sortPick.value);
  sourcePick.addEventListener("change", () => {
    searchResultSourceFilter = sourcePick.value;
    sessionStorage.setItem("knitarr_result_source", searchResultSourceFilter);
    paintSearchResults(searchResultHits);
  });
  sortPick.addEventListener("change", () => {
    searchResultSort = normalizeResultSort(sortPick.value);
    sessionStorage.setItem("knitarr_result_sort", searchResultSort);
    paintSearchResults(searchResultHits);
  });
}

function paintSearchResults(hits: ExternalHit[], cacheNote?: string) {
  if (cacheNote !== undefined) searchResultsCacheNote = cacheNote;
  searchResultHits = hits;
  const sourceSet = new Set(hits.map((h) => h.indexer_id));
  if (searchResultSourceFilter !== "all" && !sourceSet.has(searchResultSourceFilter)) {
    searchResultSourceFilter = "all";
    sessionStorage.setItem("knitarr_result_source", "all");
  }
  const toolbar = document.getElementById("resultsToolbar");
  if (toolbar) {
    toolbar.classList.toggle("is-hidden", hits.length === 0);
    if (hits.length > 0) mountResultsToolbar(hits);
  }
  const filtered = filterSearchHits(hits, searchResultSourceFilter);
  const viewed = sortSearchHits(filtered, normalizeResultSort(searchResultSort));
  const resultsEl = document.getElementById("results");
  const countEl = document.getElementById("resultCount");
  if (countEl) {
    countEl.textContent =
      viewed.length === hits.length
        ? `${hits.length} result${hits.length === 1 ? "" : "s"}`
        : `${viewed.length} of ${hits.length} results`;
  }
  if (!resultsEl) return;
  const prefix = searchResultsCacheNote;
  if (!hits.length) {
    resultsEl.innerHTML = prefix;
    return;
  }
  if (!viewed.length) {
    resultsEl.innerHTML = `${prefix}<p class="empty search-filter-empty">No results for the selected source.</p>`;
    return;
  }
  resultsEl.innerHTML = `${prefix}${viewed.map(hitCard).join("")}`;
  bindHitCards(resultsEl);
}

function bindHitCards(root: HTMLElement) {
  root.querySelectorAll(".card[data-ext]").forEach((card) => {
    const [indexer_id] = (card as HTMLElement).dataset.ext!.split("|");
    const idx = indexersCache.find((i) => i.id === indexer_id);
    const importBtn = card.querySelector(".btn-import") as HTMLButtonElement | null;
    if (importBtn && idx && !idx.capabilities.can_download) {
      importBtn.disabled = true;
      importBtn.title = "This source is index-only or manual import";
    }
    card.addEventListener("click", (ev) => {
      if ((ev.target as HTMLElement).closest("button, a")) return;
      const [, external_id] = (card as HTMLElement).dataset.ext!.split("|");
      showExternalDetail(indexer_id, external_id);
    });
    importBtn?.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const [, external_id] = (card as HTMLElement).dataset.ext!.split("|");
      await importHitToLibrary(indexer_id, external_id, importBtn);
    });
  });
}

function setSearchProgress(
  visible: boolean,
  opts: { percent?: number; indeterminate?: boolean; label?: string } = {}
) {
  const wrap = document.getElementById("searchProgress");
  const fill = document.getElementById("searchProgressFill");
  const label = document.getElementById("searchProgressLabel");
  const track = document.getElementById("searchProgressTrack");
  if (!wrap || !fill || !label || !track) return;
  wrap.classList.toggle("is-hidden", !visible);
  wrap.classList.toggle("is-indeterminate", !!opts.indeterminate);
  if (opts.label !== undefined) label.textContent = opts.label;
  const pct = opts.indeterminate ? 0 : Math.min(100, Math.max(0, opts.percent ?? 0));
  fill.style.width = `${pct}%`;
  track.setAttribute("aria-valuenow", String(pct));
}

async function emptySearchMessage(craftId: string): Promise<string> {
  const crafts = await loadCrafts();
  const craft = crafts.find((c) => c.craft_id === craftId);
  const label = craft?.label || craftId;
  const exts = craft?.extensions.join(", ") || "—";
  return `No results matched <strong>${escapeHtml(label)}</strong> extensions (${escapeHtml(exts)}). Indexers may have “${escapeHtml(label)}” items that are PDFs or images — add those types under <button type="button" class="linkish" data-view="craft_files">Craft Files</button> to include them.`;
}

async function runPatternSearch(
  q: string,
  indexerId: string,
  craftId: string,
  resultsEl: HTMLElement,
  limit = 24
) {
  const btn = document.getElementById("doSearch") as HTMLButtonElement | null;
  if (btn) btn.disabled = true;
  searchResultsCacheNote = "";
  resultsEl.innerHTML = "";
  document.getElementById("resultsToolbar")?.classList.add("is-hidden");
  setSearchProgress(true, { indeterminate: true, label: "Searching…", percent: 0 });

  const searchOne = (id: string) =>
    api<{ results: ExternalHit[] }>(
      `/api/search?q=${encodeURIComponent(q)}&indexer_id=${encodeURIComponent(id)}&craft=${encodeURIComponent(craftId)}&limit=${limit}`
    );

  try {
    let hits: ExternalHit[] = [];
    if (indexerId === "all") {
      const sources = searchableIndexers();
      const total = sources.length || 1;
      let done = 0;
      setSearchProgress(true, { percent: 0, indeterminate: false, label: `Searching 0 / ${total} sources…` });
      const batches = await Promise.all(
        sources.map(async (idx) => {
          try {
            return await searchOne(idx.id);
          } catch {
            return { results: [] as ExternalHit[] };
          } finally {
            done += 1;
            const pct = Math.round((done / total) * 100);
            setSearchProgress(true, {
              percent: pct,
              indeterminate: false,
              label: `Searching ${done} / ${total} — ${idx.name}`,
            });
          }
        })
      );
      hits = fairMergeHits(
        batches.map((b) => b.results),
        limit
      );
    } else {
      setSearchProgress(true, {
        indeterminate: true,
        label: `Searching ${indexerName(indexerId)}…`,
      });
      const data = await searchOne(indexerId);
      hits = data.results;
      setSearchProgress(true, { percent: 100, indeterminate: false, label: "Done" });
    }

    setSearchProgress(false);
    saveSavedSearch(q, indexerId, craftId, hits);
    if (!hits.length) {
      resultsEl.innerHTML = `<p class="empty">${await emptySearchMessage(craftId)}</p>`;
      bindEmptyCraftLink(resultsEl);
      return;
    }
    paintSearchResults(hits);
  } catch (e) {
    setSearchProgress(false);
    resultsEl.innerHTML = `<p class="empty">${escapeHtml(String(e))}</p>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function restoreSavedSearch(
  resultsEl: HTMLElement,
  qInput: HTMLInputElement,
  pick: HTMLSelectElement,
  craftPick: HTMLSelectElement
) {
  const saved = loadSavedSearch();
  if (!saved) return;
  selectedIndexerId = saved.indexerId;
  selectedCraftId = saved.craftId;
  sessionStorage.setItem("knitarr_indexer", saved.indexerId);
  sessionStorage.setItem("knitarr_craft", saved.craftId);
  qInput.value = saved.q;
  pick.value = saved.indexerId;
  craftPick.value = saved.craftId;

  const note = `<p class="meta search-cache-note">Showing your last search (no new query). Press Search to refresh.</p>`;
  if (!saved.results.length) {
    resultsEl.innerHTML = `${note}<p class="empty">${await emptySearchMessage(saved.craftId)}</p>`;
    bindEmptyCraftLink(resultsEl);
    return;
  }
  paintSearchResults(saved.results, note);
}

async function renderSearch() {
  await loadIndexers();
  const crafts = await loadCrafts();
  const saved = loadSavedSearch();
  if (saved) {
    selectedIndexerId = saved.indexerId;
    selectedCraftId = saved.craftId;
  }
  shell(`
    <div class="panel">
      <h2 style="margin:0 0 0.75rem">Search patterns</h2>
      <div class="search-row">
        <select id="craftPick" title="Craft">${craftOptions(crafts)}</select>
        <select id="indexerPick">${indexerOptions()}</select>
        <input type="search" id="q" placeholder="e.g. dog, unicorn, heart" />
        <button class="primary" id="doSearch">Search</button>
      </div>
      <div id="searchProgress" class="search-progress is-hidden" aria-live="polite">
        <div class="search-progress-label" id="searchProgressLabel">Searching…</div>
        <div
          class="search-progress-track"
          id="searchProgressTrack"
          role="progressbar"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-valuenow="0"
        >
          <div class="search-progress-fill" id="searchProgressFill"></div>
        </div>
      </div>
      <p class="meta">Results include only file types configured under Craft Files for the selected craft.</p>
    </div>
    <div id="resultsToolbar" class="results-toolbar is-hidden" aria-label="Result filters"></div>
    <div id="results" class="card-grid"></div>
  `);
  const pick = document.getElementById("indexerPick") as HTMLSelectElement;
  const craftPick = document.getElementById("craftPick") as HTMLSelectElement;
  pick.value = selectedIndexerId;
  craftPick.value = selectedCraftId;
  pick.addEventListener("change", () => {
    selectedIndexerId = pick.value;
    sessionStorage.setItem("knitarr_indexer", selectedIndexerId);
  });
  craftPick.addEventListener("change", () => {
    selectedCraftId = craftPick.value;
    sessionStorage.setItem("knitarr_craft", selectedCraftId);
    refreshIndexerPick(pick);
  });

  const results = document.getElementById("results")!;
  const qInput = document.getElementById("q") as HTMLInputElement;
  const triggerSearch = () => {
    const q = qInput.value;
    selectedIndexerId = pick.value;
    selectedCraftId = craftPick.value;
    sessionStorage.setItem("knitarr_indexer", selectedIndexerId);
    sessionStorage.setItem("knitarr_craft", selectedCraftId);
    void runPatternSearch(q, selectedIndexerId, selectedCraftId, results);
  };
  document.getElementById("doSearch")!.addEventListener("click", triggerSearch);
  qInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") triggerSearch();
  });

  await restoreSavedSearch(results, qInput, pick, craftPick);
}

async function renderCraftFiles() {
  const crafts = await loadCrafts();
  shell(`
    <div class="panel">
      <h2 style="margin:0">Craft Files</h2>
      <p class="meta">Allowed file extensions per craft. Search and downloads only consider matching files (e.g. .oxs, .pdf).</p>
    </div>
    <div class="indexer-list">
      ${crafts
        .map(
          (c) => `
        <article class="indexer-card" data-craft="${c.craft_id}">
          <h3>${escapeHtml(c.label)} <span class="badge">${escapeHtml(c.craft_id)}</span></h3>
          <label class="meta"><input type="checkbox" class="craft-enabled" ${c.enabled ? "checked" : ""} /> Enabled in search dropdown</label>
          <p class="meta" style="margin-top:0.5rem">File extensions:</p>
          <div class="ext-list">${extensionsListHtml(c.extensions)}</div>
          <div class="ext-add-row">
            <input type="text" class="ext-add-input" placeholder=".zip or zip" aria-label="Add extension" />
            <button type="button" class="secondary btn-ext-add">Add</button>
          </div>
          <div class="indexer-actions">
            <button type="button" class="primary btn-save-craft">Save</button>
          </div>
        </article>`
        )
        .join("")}
    </div>
  `);

  app.querySelectorAll(".indexer-card[data-craft]").forEach((el) => bindCraftExtensionList(el as HTMLElement));

  app.querySelectorAll(".btn-save-craft").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const card = btn.closest(".indexer-card") as HTMLElement;
      const craft_id = card.dataset.craft!;
      const extensions = readExtensionsFromCard(card);
      const enabled = (card.querySelector(".craft-enabled") as HTMLInputElement).checked;
      try {
        await api(`/api/craft-files/${craft_id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ extensions, enabled }),
        });
        alert("Saved.");
      } catch (e) {
        alert(String(e));
      }
    });
  });
}

async function renderIndexers() {
  await loadIndexers();
  const crafts = (await loadCrafts()).filter((c) => c.enabled);
  shell(`
    <div class="panel">
      <h2 style="margin:0">Indexers</h2>
      <p class="meta">Toggle which sources are included in Search for each craft. Indexers without automated search stay catalog-only.</p>
    </div>
    <div class="indexer-list">
      ${indexersCache
        .map((idx) => {
          const c = idx.capabilities;
          const craftToggles = crafts
            .map((craft) => {
              const on = idx.craft_enabled?.[craft.craft_id] ?? c.search_enabled;
              const disabled = !c.search_enabled;
              return `
              <label class="craft-toggle${disabled ? " craft-toggle-disabled" : ""}" title="${disabled ? "No automated search for this source" : `Include in ${craft.label} search`}">
                <input type="checkbox" class="idx-craft" data-craft="${craft.craft_id}" ${on ? "checked" : ""} ${disabled ? "disabled" : ""} />
                ${escapeHtml(craft.label)}
              </label>`;
            })
            .join("");
          return `
        <article class="indexer-card" data-id="${idx.id}">
          <h3>${escapeHtml(idx.name)} ${statusBadge(c.status)}</h3>
          <p class="meta">${escapeHtml(c.description)}</p>
          <p class="meta">Access: ${escapeHtml(c.access_method)} · Search: ${c.search_enabled ? "yes" : "no"} · Download: ${c.can_download ? "yes" : "no"}</p>
          <div class="indexer-craft-toggles">${craftToggles}</div>
          <div class="indexer-actions">
            ${c.site_url ? `<a class="secondary" href="${c.site_url}" target="_blank" rel="noopener">Visit site</a>` : ""}
            ${c.search_enabled ? `<button type="button" class="primary btn-search-here">Search this source</button>` : ""}
          </div>
        </article>`;
        })
        .join("")}
    </div>
  `);

  app.querySelectorAll(".idx-craft").forEach((input) => {
    input.addEventListener("change", async () => {
      const box = input as HTMLInputElement;
      const card = box.closest(".indexer-card") as HTMLElement;
      const indexerId = card.dataset.id!;
      const craftId = box.dataset.craft!;
      try {
        await api(`/api/indexers/${indexerId}/craft`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ craft_id: craftId, enabled: box.checked }),
        });
        await loadIndexers();
      } catch (e) {
        box.checked = !box.checked;
        alert(String(e));
      }
    });
  });

  app.querySelectorAll(".btn-search-here").forEach((btn) => {
    btn.addEventListener("click", () => {
      const id = (btn.closest(".indexer-card") as HTMLElement).dataset.id!;
      selectedIndexerId = id;
      sessionStorage.setItem("knitarr_indexer", id);
      view = "search";
      render();
    });
  });
}

async function showExternalDetail(indexer_id: string, external_id: string) {
  await loadIndexers();
  const idx = indexersCache.find((i) => i.id === indexer_id);
  const d = await api<ExternalHit & { download_available?: boolean; all_files?: string[] }>(
    `/api/external/${indexer_id}/${external_id}?craft=${encodeURIComponent(selectedCraftId)}`
  );
  shell(`
    <div class="panel">
      <button class="secondary" id="back">← Back to search</button>
      <h2>${escapeHtml(d.title)}</h2>
      <p class="meta">${escapeHtml(indexerName(indexer_id))}${d.metadata?.licenseurl ? ` · <a href="${d.metadata.licenseurl}" target="_blank" rel="noopener">license</a>` : ""}</p>
      <p>${escapeHtml(d.description || "")}</p>
      <div style="display:flex;gap:0.5rem;margin-top:0.75rem;flex-wrap:wrap">
        <button class="primary" id="addLib" ${idx && !idx.capabilities.can_download ? "disabled" : ""}>Add to Library</button>
        <a class="secondary" href="${d.source_url}" target="_blank" rel="noopener">Open on source site</a>
      </div>
      ${d.all_files?.length ? `<pre class="meta" style="white-space:pre-wrap;margin-top:1rem">${d.all_files.slice(0, 8).join("\n")}</pre>` : ""}
    </div>
  `, "search");
  document.getElementById("back")!.addEventListener("click", () => {
    view = "search";
    render();
  });
  document.getElementById("addLib")?.addEventListener("click", async (ev) => {
    await importHitToLibrary(indexer_id, external_id, ev.currentTarget as HTMLButtonElement);
  });
}

async function importHitToLibrary(indexer_id: string, external_id: string, btn?: HTMLButtonElement) {
  const label = btn?.textContent || "Add to Library";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Adding…";
  }
  try {
    const r = await api<{ pattern_id?: number | null; duplicate_of?: number | null; message: string }>(
      "/api/import/from-indexer",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ indexer_id, external_id, craft: selectedCraftId }),
      }
    );
    if (r.pattern_id) {
      selectedPatternId = r.pattern_id;
      view = "pattern";
      render();
      return;
    }
    if (r.duplicate_of) {
      if (confirm(`${r.message}\nOpen the existing pattern?`)) {
        selectedPatternId = r.duplicate_of;
        view = "pattern";
        render();
      }
      return;
    }
    alert(r.message || "Imported");
  } catch (e) {
    alert(String(e));
  } finally {
    if (btn && document.body.contains(btn)) {
      btn.disabled = false;
      btn.textContent = label;
    }
  }
}

function uploadAcceptExtensions(crafts: CraftConfig[]) {
  const seen = new Set<string>();
  for (const c of crafts) {
    for (const ext of c.extensions) {
      const e = ext.startsWith(".") ? ext : `.${ext}`;
      seen.add(e.toLowerCase());
    }
  }
  return [...seen].join(",");
}

async function uploadFilesToLibrary(files: FileList | File[], craftId: string, statusEl: HTMLElement) {
  const list = [...files];
  if (!list.length) return;
  statusEl.textContent = `Uploading ${list.length} file${list.length === 1 ? "" : "s"}…`;
  const form = new FormData();
  form.append("craft", craftId);
  for (const f of list) form.append("files", f);
  try {
    const results = await fetch("/api/import/upload-many", { method: "POST", body: form }).then(async (r) => {
      if (!r.ok) throw new Error(await r.text() || r.statusText);
      return r.json() as Promise<{ pattern_id?: number | null; duplicate_of?: number | null; message: string }[]>;
    });
      const imported = results.filter((r) => r.pattern_id);
      const dupes = results.filter((r) => r.duplicate_of);
      const failed = results.length - imported.length - dupes.length;
      const parts = [];
      if (imported.length) parts.push(`${imported.length} imported`);
      if (dupes.length) parts.push(`${dupes.length} duplicate`);
      if (failed) parts.push(`${failed} failed`);
      const notes = imported.map((r) => r.message).filter(Boolean);
      statusEl.textContent = [parts.join(" · "), ...notes.slice(0, 1)].filter(Boolean).join(" — ") || "Done";
    if (imported.length === 1 && imported[0]!.pattern_id) {
      selectedPatternId = imported[0]!.pattern_id!;
      view = "pattern";
      render();
      return;
    }
    render();
  } catch (e) {
    statusEl.textContent = String(e);
  }
}

async function renderLibrary() {
  const patterns = await api<PatternSummary[]>("/api/patterns?downloaded=true");
  const crafts = await loadCrafts();
  const accept = uploadAcceptExtensions(crafts);
  shell(`
    <div class="panel">
      <h2 style="margin:0 0 0.75rem">Library</h2>
      <p class="meta">Import patterns you own — OXS, PDF, images, and other types configured under Craft Files.</p>
      <div class="upload-row">
        <select id="uploadCraft" title="Craft">${craftOptions(crafts)}</select>
        <label class="primary upload-btn">
          Choose files
          <input type="file" id="uploadInput" multiple accept="${escapeHtml(accept)}" hidden />
        </label>
      </div>
      <div class="upload-dropzone" id="uploadDropzone" tabindex="0">
        <p>Drop files here or use Choose files</p>
        <p class="meta">Multiple files upload one pattern per file. Duplicates are skipped by checksum.</p>
      </div>
      <p class="meta" id="uploadStatus" aria-live="polite"></p>
    </div>
    <div class="card-grid">${patterns.length ? patterns.map(patternCard).join("") : `<p class="empty">No patterns yet — upload a file above.</p>`}</div>
  `, "library");
  const craftPick = document.getElementById("uploadCraft") as HTMLSelectElement;
  craftPick.value = selectedCraftId;
  const statusEl = document.getElementById("uploadStatus")!;
  const input = document.getElementById("uploadInput") as HTMLInputElement;
  const drop = document.getElementById("uploadDropzone")!;

  const doUpload = (files: FileList | File[]) => {
    void uploadFilesToLibrary(files, craftPick.value, statusEl);
  };

  input.addEventListener("change", () => {
    if (input.files?.length) doUpload(input.files);
    input.value = "";
  });

  drop.addEventListener("dragover", (ev) => {
    ev.preventDefault();
    drop.classList.add("upload-dropzone-active");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("upload-dropzone-active"));
  drop.addEventListener("drop", (ev) => {
    ev.preventDefault();
    drop.classList.remove("upload-dropzone-active");
    if (ev.dataTransfer?.files?.length) doUpload(ev.dataTransfer.files);
  });
  drop.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" || ev.key === " ") input.click();
  });
  drop.addEventListener("click", () => input.click());

  app.querySelectorAll(".card[data-pid]").forEach((card) => {
    card.addEventListener("click", (ev) => {
      if ((ev.target as HTMLElement).closest(".btn-del-pat, .btn-rename-pat")) return;
      selectedPatternId = Number((card as HTMLElement).dataset.pid);
      view = "pattern";
      render();
    });
  });
  app.querySelectorAll(".btn-rename-pat").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = Number((btn as HTMLElement).dataset.pid);
      const current = patterns.find((x) => x.id === id);
      const next = prompt("Rename pattern", current?.title || "");
      if (next == null) return;
      const title = next.trim();
      if (!title) return;
      try {
        await api(`/api/patterns/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        });
        render();
      } catch (e) {
        alert(String(e));
      }
    });
  });
  app.querySelectorAll(".btn-del-pat").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = Number((btn as HTMLElement).dataset.pid);
      if (!confirm("Delete this pattern from your library?")) return;
      try {
        await api(`/api/patterns/${id}`, { method: "DELETE" });
        render();
      } catch (e) {
        alert(String(e));
      }
    });
  });
}

function hexColor(raw: string) {
  const h = raw.replace("#", "");
  return h.length === 6 ? `#${h}` : "#cccccc";
}

function drawGrid(
  canvas: HTMLCanvasElement,
  norm: Normalized,
  extras?: { pendingBack?: { x: number; y: number } | null; editMode?: boolean }
) {
  const cell = gridState.zoom;
  const w = norm.width_stitches * cell;
  const h = norm.height_stitches * cell;
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  const palMap = new Map(norm.palette.map((p) => [p.index, p]));
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  for (const s of norm.full_stitches) {
    const pal = palMap.get(s.palindex);
    ctx.fillStyle = pal ? hexColor(pal.color) : "#ccc";
    ctx.fillRect(s.x * cell, s.y * cell, cell, cell);
    const mark = symbolForPalette(norm.palette, s.palindex);
    if (mark) {
      ctx.fillStyle = contrastInk(pal?.color || "#ccc");
      const shrink = mark.length > 1 ? 0.55 : 0.7;
      ctx.font = `600 ${Math.max(8, Math.floor(cell * shrink))}px "Segoe UI Symbol","Noto Sans Symbols","DejaVu Sans",sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(mark, s.x * cell + cell / 2, s.y * cell + cell / 2);
    }
    const key = `${s.x},${s.y}`;
    if (gridState.marked.has(key)) {
      ctx.strokeStyle = "rgba(0,128,0,0.7)";
      ctx.lineWidth = 2;
      ctx.strokeRect(s.x * cell + 1, s.y * cell + 1, cell - 2, cell - 2);
    }
  }
  ctx.strokeStyle = "#e0e0e0";
  for (let x = 0; x <= norm.width_stitches; x++) {
    ctx.beginPath();
    ctx.moveTo(x * cell, 0);
    ctx.lineTo(x * cell, h);
    ctx.stroke();
  }
  for (let y = 0; y <= norm.height_stitches; y++) {
    ctx.beginPath();
    ctx.moveTo(0, y * cell);
    ctx.lineTo(w, y * cell);
    ctx.stroke();
  }
  ctx.lineCap = "round";
  for (const b of norm.backstitches || []) {
    const pal = palMap.get(b.palindex);
    ctx.strokeStyle = pal ? hexColor(pal.color) : "#222";
    ctx.lineWidth = Math.max(1.5, cell * 0.18);
    ctx.beginPath();
    ctx.moveTo(b.x1 * cell, b.y1 * cell);
    ctx.lineTo(b.x2 * cell, b.y2 * cell);
    ctx.stroke();
  }
  if (extras?.pendingBack) {
    ctx.fillStyle = "#c0392b";
    ctx.beginPath();
    ctx.arc(extras.pendingBack.x * cell, extras.pendingBack.y * cell, Math.max(3, cell * 0.18), 0, Math.PI * 2);
    ctx.fill();
  }
}

type NormCrop = { x: number; y: number; w: number; h: number };

const PATTERN_CROP_KEY = "knitarr_pattern_crop";

interface PatternCropState {
  pdfPage: number;
  crop: NormCrop;
}

function clampNormCrop(c: NormCrop): NormCrop {
  const minN = 0.04;
  const x = Math.max(0, Math.min(1, c.x));
  const y = Math.max(0, Math.min(1, c.y));
  const w = Math.max(minN, Math.min(1 - x, c.w));
  const h = Math.max(minN, Math.min(1 - y, c.h));
  return { x, y, w, h };
}

function loadPatternCropState(patternId: number): PatternCropState | null {
  try {
    const raw = sessionStorage.getItem(`${PATTERN_CROP_KEY}_${patternId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PatternCropState;
    if (!parsed?.crop || typeof parsed.pdfPage !== "number") return null;
    return { pdfPage: parsed.pdfPage, crop: clampNormCrop(parsed.crop) };
  } catch {
    return null;
  }
}

function savePatternCropState(patternId: number, pdfPage: number, crop: NormCrop) {
  const payload: PatternCropState = { pdfPage, crop: clampNormCrop(crop) };
  sessionStorage.setItem(`${PATTERN_CROP_KEY}_${patternId}`, JSON.stringify(payload));
}

function pdfRasterPreviewUrl(patternId: number, page: number) {
  return `/api/patterns/${patternId}/raster-preview?page=${page}`;
}

function pdfPageBarHtml(prefix: string, pageCount: number) {
  if (pageCount <= 1) return "";
  return `
    <div class="pdf-page-bar" data-pdf-bar="${prefix}">
      <button type="button" class="secondary" data-pdf-prev="${prefix}">Prev</button>
      <span class="pdf-page-label" data-pdf-page-label="${prefix}">Page 1 of ${pageCount}</span>
      <button type="button" class="secondary" data-pdf-next="${prefix}">Next</button>
    </div>`;
}

function mountCropEditor(
  container: HTMLElement,
  imageUrl: string,
  initialCrop?: NormCrop,
  onCropChange?: (crop: NormCrop) => void
): Promise<{ getCrop: () => NormCrop; reset: () => void }> {
  return new Promise((resolve, reject) => {
    container.innerHTML = `
      <div class="crop-editor">
        <img class="crop-img" alt="Crop preview" draggable="false" />
        <div class="crop-layer">
          <div class="crop-box">
            <span class="crop-handle" data-handle="nw"></span>
            <span class="crop-handle" data-handle="n"></span>
            <span class="crop-handle" data-handle="ne"></span>
            <span class="crop-handle" data-handle="w"></span>
            <span class="crop-handle" data-handle="e"></span>
            <span class="crop-handle" data-handle="sw"></span>
            <span class="crop-handle" data-handle="s"></span>
            <span class="crop-handle" data-handle="se"></span>
          </div>
        </div>
      </div>
      <button type="button" class="secondary crop-reset" style="margin-top:0.5rem">Reset crop</button>`;

    const editor = container.querySelector(".crop-editor") as HTMLElement;
    const img = container.querySelector(".crop-img") as HTMLImageElement;
    const layer = container.querySelector(".crop-layer") as HTMLElement;
    const box = container.querySelector(".crop-box") as HTMLElement;
    const resetBtn = container.querySelector(".crop-reset") as HTMLButtonElement;

    const setCropActive = (on: boolean) => {
      editor.classList.toggle("crop-active", on);
    };

    let crop: NormCrop = initialCrop ? clampNormCrop(initialCrop) : { x: 0, y: 0, w: 1, h: 1 };
    const minN = 0.04;

    const notifyCrop = () => onCropChange?.({ ...crop });

    const imgSize = () => ({ w: img.clientWidth, h: img.clientHeight });

    const syncBox = () => {
      const { w, h } = imgSize();
      if (!w || !h) return;
      box.style.left = `${crop.x * w}px`;
      box.style.top = `${crop.y * h}px`;
      box.style.width = `${crop.w * w}px`;
      box.style.height = `${crop.h * h}px`;
      layer.style.width = `${w}px`;
      layer.style.height = `${h}px`;
    };

    const reset = () => {
      crop = { x: 0, y: 0, w: 1, h: 1 };
      syncBox();
      notifyCrop();
    };

    resetBtn.addEventListener("click", reset);

    type DragMode =
      | { kind: "move"; startX: number; startY: number; startCrop: NormCrop }
      | { kind: "resize"; handle: string; startX: number; startY: number; startCrop: NormCrop };

    let drag: DragMode | null = null;
    let captureEl: HTMLElement | null = null;

    const applyDrag = (clientX: number, clientY: number) => {
      if (!drag) return;
      const { w, h } = imgSize();
      if (!w || !h) return;
      const dx = (clientX - drag.startX) / w;
      const dy = (clientY - drag.startY) / h;
      const s = drag.startCrop;
      if (drag.kind === "move") {
        const nx = Math.max(0, Math.min(1 - s.w, s.x + dx));
        const ny = Math.max(0, Math.min(1 - s.h, s.y + dy));
        crop = { x: nx, y: ny, w: s.w, h: s.h };
      } else {
        const hnd = drag.handle;
        let x1 = s.x;
        let y1 = s.y;
        let x2 = s.x + s.w;
        let y2 = s.y + s.h;
        if (hnd.includes("n")) y1 = Math.min(y2 - minN, Math.max(0, s.y + dy));
        if (hnd.includes("s")) y2 = Math.max(y1 + minN, Math.min(1, s.y + s.h + dy));
        if (hnd.includes("w")) x1 = Math.min(x2 - minN, Math.max(0, s.x + dx));
        if (hnd.includes("e")) x2 = Math.max(x1 + minN, Math.min(1, s.x + s.w + dx));
        crop = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
      }
      syncBox();
    };

    const endDrag = (ev: PointerEvent) => {
      const hadDrag = drag !== null;
      drag = null;
      setCropActive(false);
      if (captureEl?.hasPointerCapture(ev.pointerId)) {
        captureEl.releasePointerCapture(ev.pointerId);
      }
      captureEl = null;
      if (hadDrag) notifyCrop();
    };

    const bindPointerDrag = (
      el: HTMLElement,
      start: (ev: PointerEvent) => DragMode | null,
      stopBubble?: boolean
    ) => {
      el.addEventListener("pointerdown", (ev) => {
        if (ev.pointerType === "mouse" && ev.button !== 0) return;
        if (stopBubble) ev.stopPropagation();
        const mode = start(ev);
        if (!mode) return;
        drag = mode;
        setCropActive(true);
        captureEl = el;
        el.setPointerCapture(ev.pointerId);
        ev.preventDefault();
      });
      el.addEventListener("pointermove", (ev) => {
        if (!drag || !el.hasPointerCapture(ev.pointerId)) return;
        applyDrag(ev.clientX, ev.clientY);
        ev.preventDefault();
      });
      el.addEventListener("pointerup", endDrag);
      el.addEventListener("pointercancel", endDrag);
    };

    bindPointerDrag(box, (ev) => {
      if ((ev.target as HTMLElement).classList.contains("crop-handle")) return null;
      return { kind: "move", startX: ev.clientX, startY: ev.clientY, startCrop: { ...crop } };
    });

    container.querySelectorAll(".crop-handle").forEach((node) => {
      const handleEl = node as HTMLElement;
      bindPointerDrag(
        handleEl,
        (ev) => ({
          kind: "resize",
          handle: handleEl.dataset.handle!,
          startX: ev.clientX,
          startY: ev.clientY,
          startCrop: { ...crop },
        }),
        true
      );
    });

    const onResize = () => syncBox();
    img.onload = () => {
      syncBox();
      window.addEventListener("resize", onResize);
      notifyCrop();
      resolve({
        getCrop: () => ({ ...crop }),
        reset,
      });
    };
    img.onerror = () => reject(new Error("Could not load preview"));
    img.src = imageUrl;
  });
}

async function renderPattern() {
  clearChartEditKeys();
  if (!selectedPatternId) {
    view = "library";
    return render();
  }
  const p = await api<PatternDetail>(`/api/patterns/${selectedPatternId}`);
  const files = await api<PatternFile[]>(`/api/patterns/${selectedPatternId}/files`);
  const imgs = files.filter((f) => f.mime_type?.startsWith("image/"));
  const pagedFile = files.find((f) => {
    const name = f.filename.toLowerCase();
    return (
      f.mime_type === "application/pdf" ||
      f.mime_type === "application/vnd.ms-xpsdocument" ||
      f.mime_type === "application/oxps" ||
      name.endsWith(".pdf") ||
      name.endsWith(".xps") ||
      name.endsWith(".oxps")
    );
  });
  const sagaFile = files.find((f) => f.filename.toLowerCase().endsWith(".saga"));
  const xspFile = files.find((f) => f.filename.toLowerCase().endsWith(".xsp"));
  const pagedKind = pagedFile?.filename.toLowerCase().endsWith(".pdf") ? "PDF" : "XPS";
  let pdfPageCount = 1;
  if (pagedFile) {
    try {
      const pdfMeta = await api<{ is_pdf: boolean; is_paged?: boolean; page_count: number }>(
        `/api/patterns/${p.id}/pdf-info`
      );
      if (pdfMeta.is_paged || pdfMeta.is_pdf) pdfPageCount = Math.max(1, pdfMeta.page_count);
    } catch {
      /* ignore */
    }
  }
  const savedCropState = loadPatternCropState(p.id);
  let selectedPdfPage = savedCropState?.pdfPage ?? 1;
  const canRasterConvert =
    isUserUpload(p.source) &&
    p.craft === "cross_stitch" &&
    (p.pattern_format === "image" ||
      p.pattern_format === "pdf" ||
      p.pattern_format === "xps" ||
      imgs.length > 0 ||
      !!pagedFile);
  const canStructuredConvert =
    isUserUpload(p.source) && p.craft === "cross_stitch" && (!!sagaFile || !!xspFile || p.pattern_format === "saga" || p.pattern_format === "xsp");
  const canConvert = canRasterConvert || canStructuredConvert;
  const convertLabel = p.has_normalized ? "Regenerate stitch chart" : "Generate stitch chart";

  const chartViewer = `
      <div class="toolbar">
        <button class="secondary" id="zoomOut">−</button>
        <button class="secondary" id="zoomIn">+</button>
        <button class="secondary" id="toggleSym">${escapeHtml(symbolModeLabel())}</button>
        <button class="secondary" id="startProj">Start project</button>
        <button class="secondary" id="finishProj">Mark finished</button>
        <button class="secondary" id="editChart">Edit chart</button>
      </div>
      <div class="toolbar edit-tools is-hidden" id="editTools">
        <button type="button" class="secondary tool-btn active" data-tool="stitch">Stitch</button>
        <button type="button" class="secondary tool-btn" data-tool="erase">Erase stitch</button>
        <button type="button" class="secondary tool-btn" data-tool="backstitch">Backstitch</button>
        <button type="button" class="secondary" id="undoEdit" disabled title="Undo (Ctrl+Z)">Undo</button>
        <button type="button" class="secondary" id="redoEdit" disabled title="Redo (Ctrl+Y)">Redo</button>
        <button type="button" class="secondary" id="addColor">Add colour</button>
        <button type="button" class="primary" id="saveChart">Save chart</button>
        <button type="button" class="secondary" id="cancelEdit">Cancel</button>
        <span class="meta" id="editHint">Click a legend colour, then paint. Backstitch snaps to grid corners.</span>
      </div>
      <div class="viewer-layout">
        <div><canvas id="gridCanvas"></canvas></div>
        <div class="legend panel"><h3>Legend</h3><div id="legendBody"></div></div>
      </div>`;

  let originalViewer = "";
  if (pagedFile) {
    originalViewer = `
        ${pdfPageBarHtml("orig", pdfPageCount)}
        <div class="image-viewer" id="imgBox">
          <img data-pdf-page-img="orig" src="${pdfRasterPreviewUrl(p.id, 1)}" alt="${pagedKind} page" />
        </div>
        <p class="meta"><a href="/api/patterns/${selectedPatternId}/file/${pagedFile.id}" target="_blank" rel="noopener">Open full ${pagedKind}</a></p>`;
  } else if (imgs.length) {
    originalViewer = `
        <div class="toolbar">
          <button class="secondary" id="imgOut">Zoom out</button>
          <button class="secondary" id="imgIn">Zoom in</button>
        </div>
        <div class="image-viewer" id="imgBox">
          ${imgs.map((f) => `<img src="/api/patterns/${selectedPatternId}/file/${f.id}" alt="page" />`).join("")}
        </div>`;
  }

  let viewerHtml = "";
  if (p.has_normalized && originalViewer) {
    viewerHtml = `
      <div class="viewer-tabs">
        <button type="button" class="viewer-tab active" data-tab="chart">Stitch chart</button>
        <button type="button" class="viewer-tab" data-tab="original">Original file</button>
      </div>
      <div id="viewerTabChart">${chartViewer}</div>
      <div id="viewerTabOriginal" class="is-hidden">${originalViewer}</div>
      <p class="meta">Auto-generated chart is approximate — compare with the original.</p>`;
  } else if (p.has_normalized) {
    viewerHtml = chartViewer;
  } else if (originalViewer) {
    viewerHtml = originalViewer;
  }

  const uploadActions = isUserUpload(p.source)
    ? `<div class="pattern-actions">
        ${canConvert ? `<button type="button" class="primary" id="convertChart">${convertLabel}</button>` : ""}
        <button type="button" class="secondary" id="deletePat">Delete</button>
      </div>`
    : "";

  const cropPanel = canRasterConvert
    ? `<div class="panel" id="cropPanel">
        <h3>Crop for chart generation</h3>
        <p class="meta">Drag the box or handles to focus on the pattern area.</p>
        ${pagedFile ? pdfPageBarHtml("crop", pdfPageCount) : ""}
        <div id="cropMount"></div>
      </div>`
    : "";

  shell(`
    <div class="panel">
      <button class="secondary" id="backLib">← Library</button>
      <div class="title-row">
        <h2 id="patternTitle">${escapeHtml(p.title)}</h2>
        <button type="button" class="secondary" id="renameTitle">Rename</button>
      </div>
      <p class="meta">${p.pattern_format.toUpperCase()} · ${escapeHtml(p.craft)}${p.source_url ? ` · <a href="${p.source_url}" target="_blank">source</a>` : ""}</p>
      ${uploadActions}
      <p>${escapeHtml(p.description || "")}</p>
      <div class="file-list">
        <h3>Files</h3>
        ${
          files.length
            ? files
                .map(
                  (f) => `
          <div class="file-row">
            <a href="/api/patterns/${p.id}/file/${f.id}" target="_blank" rel="noopener">${escapeHtml(f.filename)}</a>
            <span class="meta">${escapeHtml(f.role || "")}</span>
            <button type="button" class="secondary btn-rename-file" data-fid="${f.id}" data-name="${escapeHtml(f.filename)}">Rename</button>
          </div>`
                )
                .join("")
            : `<p class="meta">No files stored.</p>`
        }
      </div>
    </div>
    ${cropPanel}
    <div class="panel">${viewerHtml || `<p class="empty">No viewer for this format.</p>`}</div>
  `, "library");

  let cropApi: { getCrop: () => NormCrop; reset: () => void } | null = null;
  let liveCropState: PatternCropState | null = savedCropState;

  const persistCrop = (crop: NormCrop) => {
    liveCropState = { pdfPage: selectedPdfPage, crop: clampNormCrop(crop) };
    savePatternCropState(p.id, selectedPdfPage, liveCropState.crop);
  };

  const cropForCurrentView = () =>
    liveCropState && liveCropState.pdfPage === selectedPdfPage ? liveCropState.crop : undefined;

  const syncPdfPageUi = () => {
    document.querySelectorAll("[data-pdf-page-label]").forEach((el) => {
      el.textContent = `Page ${selectedPdfPage} of ${pdfPageCount}`;
    });
    document.querySelectorAll("[data-pdf-page-img]").forEach((el) => {
      (el as HTMLImageElement).src = pdfRasterPreviewUrl(p.id, selectedPdfPage);
    });
  };

  const setPdfPage = async (page: number) => {
    if (cropApi) persistCrop(cropApi.getCrop());
    selectedPdfPage = Math.max(1, Math.min(pdfPageCount, page));
    syncPdfPageUi();
    const mount = document.getElementById("cropMount");
    if (mount && canRasterConvert) {
      try {
        cropApi = await mountCropEditor(
          mount,
          pdfRasterPreviewUrl(p.id, selectedPdfPage),
          cropForCurrentView(),
          persistCrop
        );
      } catch {
        mount.innerHTML = `<p class="meta">Preview unavailable for cropping.</p>`;
        cropApi = null;
      }
    }
  };

  const wirePdfPageBar = (prefix: string) => {
    document.querySelector(`[data-pdf-prev="${prefix}"]`)?.addEventListener("click", () => {
      void setPdfPage(selectedPdfPage - 1);
    });
    document.querySelector(`[data-pdf-next="${prefix}"]`)?.addEventListener("click", () => {
      void setPdfPage(selectedPdfPage + 1);
    });
  };

  if (pagedFile) syncPdfPageUi();

  if (canRasterConvert) {
    const mount = document.getElementById("cropMount");
    if (mount) {
      try {
        cropApi = await mountCropEditor(
          mount,
          pdfRasterPreviewUrl(p.id, selectedPdfPage),
          cropForCurrentView(),
          persistCrop
        );
      } catch {
        mount.innerHTML = `<p class="meta">Preview unavailable for cropping.</p>`;
      }
    }
  }
  if (pagedFile && pdfPageCount > 1) {
    wirePdfPageBar("crop");
    wirePdfPageBar("orig");
  }

  document.querySelectorAll(".viewer-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = (tab as HTMLElement).dataset.tab;
      document.querySelectorAll(".viewer-tab").forEach((t) => t.classList.toggle("active", t === tab));
      document.getElementById("viewerTabChart")?.classList.toggle("is-hidden", name !== "chart");
      document.getElementById("viewerTabOriginal")?.classList.toggle("is-hidden", name !== "original");
    });
  });

  document.getElementById("renameTitle")?.addEventListener("click", async () => {
    const next = prompt("Rename pattern", p.title);
    if (next == null) return;
    const title = next.trim();
    if (!title) return;
    try {
      await api(`/api/patterns/${p.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      selectedPatternId = p.id;
      render();
    } catch (e) {
      alert(String(e));
    }
  });

  document.querySelectorAll(".btn-rename-file").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const el = btn as HTMLElement;
      const fid = Number(el.dataset.fid);
      const current = el.dataset.name || "";
      const next = prompt("Rename file", current);
      if (next == null) return;
      const filename = next.trim();
      if (!filename) return;
      try {
        await api(`/api/patterns/${p.id}/files/${fid}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ filename }),
        });
        selectedPatternId = p.id;
        render();
      } catch (e) {
        alert(String(e));
      }
    });
  });

  document.getElementById("deletePat")?.addEventListener("click", async () => {
    if (!confirm("Delete this pattern from your library?")) return;
    try {
      await api(`/api/patterns/${p.id}`, { method: "DELETE" });
      view = "library";
      render();
    } catch (e) {
      alert(String(e));
    }
  });

  document.getElementById("convertChart")?.addEventListener("click", async () => {
    try {
      const crop = cropApi?.getCrop();
      if (crop) persistCrop(crop);
      const body: { crop?: NormCrop; pdf_page?: number } = {};
      if (crop) body.crop = crop;
      if (pagedFile) body.pdf_page = selectedPdfPage;
      const r = await api<{ message: string }>(`/api/patterns/${p.id}/convert-chart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      alert(r.message);
      selectedPatternId = p.id;
      render();
    } catch (e) {
      alert(String(e));
    }
  });

  document.getElementById("backLib")!.addEventListener("click", () => {
    view = "library";
    render();
  });

  if (p.has_normalized) {
    const loaded = await api<Normalized>(`/api/patterns/${selectedPatternId}/normalized`);
    if (!loaded.backstitches) loaded.backstitches = [];
    let working: Normalized = structuredClone(loaded);
    let proj = { status: "not_started", progress_json: { marked: [] as string[] } };
    try {
      proj = await api<{ status: string; progress_json: { marked?: string[] } }>(
        `/api/patterns/${selectedPatternId}/project`
      );
    } catch {
      /* older imports may not have a project row */
    }
    gridState.marked = new Set(proj.progress_json?.marked || []);
    const canvas = document.getElementById("gridCanvas") as HTMLCanvasElement;
    const legend = document.getElementById("legendBody")!;
    const editTools = document.getElementById("editTools")!;
    let editMode = false;
    let tool: "stitch" | "erase" | "backstitch" = "stitch";
    let selectedPal = working.palette.find((x) => x.index > 0)?.index || 1;
    let pendingBack: { x: number; y: number } | null = null;
    let painting = false;
    const MAX_HISTORY = 80;
    let undoStack: Normalized[] = [];
    let redoStack: Normalized[] = [];
    let strokeSnapshot: Normalized | null = null;

    const chartFingerprint = (n: Normalized) =>
      [
        n.palette.map((p) => `${p.index}:${p.number}:${p.color}:${p.name}`).join(";"),
        [...n.full_stitches]
          .map((s) => `${s.x},${s.y},${s.palindex}`)
          .sort()
          .join(";"),
        [...(n.backstitches || [])]
          .map((b) => `${b.x1},${b.y1},${b.x2},${b.y2},${b.palindex}`)
          .sort()
          .join(";"),
      ].join("|");

    const updateUndoRedoButtons = () => {
      const undoBtn = document.getElementById("undoEdit") as HTMLButtonElement | null;
      const redoBtn = document.getElementById("redoEdit") as HTMLButtonElement | null;
      if (undoBtn) undoBtn.disabled = undoStack.length === 0;
      if (redoBtn) redoBtn.disabled = redoStack.length === 0;
    };

    const pushHistory = (prev: Normalized) => {
      if (chartFingerprint(prev) === chartFingerprint(working)) return;
      undoStack.push(prev);
      if (undoStack.length > MAX_HISTORY) undoStack.shift();
      redoStack = [];
      updateUndoRedoButtons();
    };

    const beginStroke = () => {
      if (!strokeSnapshot) strokeSnapshot = structuredClone(working);
    };

    const endStroke = () => {
      if (!strokeSnapshot) return;
      pushHistory(strokeSnapshot);
      strokeSnapshot = null;
    };

    const applyHistoryState = (next: Normalized) => {
      working = next;
      pendingBack = null;
      strokeSnapshot = null;
      painting = false;
      renderLegend();
      redraw();
      updateUndoRedoButtons();
    };

    const undoEdit = () => {
      endStroke();
      const prev = undoStack.pop();
      if (!prev) return;
      redoStack.push(structuredClone(working));
      applyHistoryState(prev);
    };

    const redoEdit = () => {
      strokeSnapshot = null;
      const next = redoStack.pop();
      if (!next) return;
      undoStack.push(structuredClone(working));
      applyHistoryState(next);
    };

    const recount = () => {
      const counts = new Map<number, number>();
      for (const s of working.full_stitches) counts.set(s.palindex, (counts.get(s.palindex) || 0) + 1);
      for (const pal of working.palette) pal.stitch_count = counts.get(pal.index) || 0;
    };

    const resolvePaintColor = async (hexRaw: string, fallbackLabel: string) => {
      const color = hexRaw.replace("#", "").toUpperCase();
      if (!/^[0-9A-F]{6}$/.test(color)) {
        alert("Use a 6-digit hex colour");
        return null;
      }
      try {
        return await api<{ number: string; name: string; color: string }>(
          `/api/dmc/nearest?hex=${encodeURIComponent(color)}`
        );
      } catch {
        return { number: fallbackLabel, name: fallbackLabel, color };
      }
    };

    const pickHex = async (current: string) => {
      const input = document.createElement("input");
      input.type = "color";
      input.value = hexColor(current);
      input.style.cssText = "position:fixed;left:12px;top:12px;width:1px;height:1px;opacity:0;border:0;padding:0";
      document.body.appendChild(input);
      const picked = await new Promise<string | null>((resolve) => {
        let settled = false;
        const finish = (value: string | null) => {
          if (settled) return;
          settled = true;
          input.remove();
          resolve(value);
        };
        input.addEventListener("change", () => finish(input.value));
        input.addEventListener("cancel", () => finish(null));
        window.addEventListener("focus", () => window.setTimeout(() => finish(null), 250), { once: true });
        try {
          if (typeof input.showPicker === "function") input.showPicker();
          else input.click();
        } catch {
          finish(prompt("Colour hex (e.g. #310000)", hexColor(current)));
        }
      });
      return picked;
    };

    const applyPaletteColor = async (palIndex: number) => {
      const pal = working.palette.find((x) => x.index === palIndex);
      if (!pal) return;
      const picked = await pickHex(pal.color);
      if (!picked) return;
      const match = await resolvePaintColor(picked, pal.number || `Colour ${palIndex}`);
      if (!match) return;
      if (
        pal.color.replace("#", "").toUpperCase() === match.color.toUpperCase() &&
        pal.number === match.number &&
        pal.name === match.name
      ) {
        return;
      }
      const before = structuredClone(working);
      pal.number = match.number;
      pal.name = match.name;
      pal.color = match.color;
      selectedPal = palIndex;
      pushHistory(before);
      setHint(`Updated to ${match.number} ${match.name}`);
      renderLegend();
      redraw();
    };

    const renderLegend = () => {
      recount();
      const showSymCol = gridState.symbolMode !== "none";
      legend.innerHTML = `<table><tr><th></th>${showSymCol ? "<th>Sym</th>" : ""}<th>Code</th><th>Count</th></tr>${working.palette
        .filter((x) => x.index > 0)
        .map((pal) => {
          const mark = symbolForPalette(working.palette, pal.index);
          return `<tr class="legend-row${editMode && pal.index === selectedPal ? " is-selected" : ""}" data-pal="${pal.index}">
              <td class="legend-swatch-cell">
                <span class="swatch" style="background:${hexColor(pal.color)}"></span>
                ${
                  editMode
                    ? `<button type="button" class="legend-edit" data-pal="${pal.index}" title="Edit colour" aria-label="Edit colour">✎</button>`
                    : ""
                }
              </td>
              ${showSymCol ? `<td class="legend-sym">${escapeHtml(mark)}</td>` : ""}
              <td>${escapeHtml(pal.name && pal.name !== pal.number ? `${pal.number} ${pal.name}` : pal.number || pal.name)}</td>
              <td>${pal.stitch_count ?? ""}</td>
            </tr>`;
        })
        .join("")}</table>`;
      legend.querySelectorAll(".legend-row").forEach((row) => {
        row.addEventListener("click", () => {
          selectedPal = Number((row as HTMLElement).dataset.pal);
          renderLegend();
        });
      });
      legend.querySelectorAll(".legend-edit").forEach((btn) => {
        btn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          const palIndex = Number((btn as HTMLElement).dataset.pal);
          selectedPal = palIndex;
          void applyPaletteColor(palIndex);
        });
      });
    };

    const redraw = () => drawGrid(canvas, working, { pendingBack, editMode });
    const setHint = (text: string) => {
      const hint = document.getElementById("editHint");
      if (hint) hint.textContent = text;
    };

    const canvasPos = (ev: PointerEvent) => {
      const rect = canvas.getBoundingClientRect();
      const sx = canvas.width / rect.width;
      const sy = canvas.height / rect.height;
      return { x: (ev.clientX - rect.left) * sx, y: (ev.clientY - rect.top) * sy };
    };
    const cellAt = (ev: PointerEvent) => {
      const pos = canvasPos(ev);
      return { x: Math.floor(pos.x / gridState.zoom), y: Math.floor(pos.y / gridState.zoom) };
    };
    const cornerAt = (ev: PointerEvent) => {
      const pos = canvasPos(ev);
      return { x: Math.round(pos.x / gridState.zoom), y: Math.round(pos.y / gridState.zoom) };
    };

    const stitchKey = (x: number, y: number) => `${x},${y}`;
    const setStitch = (x: number, y: number, palindex: number | null) => {
      if (x < 0 || y < 0 || x >= working.width_stitches || y >= working.height_stitches) return;
      working.full_stitches = working.full_stitches.filter((s) => !(s.x === x && s.y === y));
      if (palindex && palindex > 0) working.full_stitches.push({ x, y, palindex });
    };
    const addBackstitch = (a: { x: number; y: number }, b: { x: number; y: number }) => {
      if (a.x === b.x && a.y === b.y) return;
      if (
        a.x < 0 ||
        b.x < 0 ||
        a.y < 0 ||
        b.y < 0 ||
        a.x > working.width_stitches ||
        b.x > working.width_stitches ||
        a.y > working.height_stitches ||
        b.y > working.height_stitches
      ) {
        return;
      }
      working.backstitches = working.backstitches || [];
      const dup = working.backstitches.some(
        (s) =>
          s.palindex === selectedPal &&
          ((s.x1 === a.x && s.y1 === a.y && s.x2 === b.x && s.y2 === b.y) ||
            (s.x1 === b.x && s.y1 === b.y && s.x2 === a.x && s.y2 === a.y))
      );
      if (!dup) working.backstitches.push({ x1: a.x, y1: a.y, x2: b.x, y2: b.y, palindex: selectedPal });
    };
    const eraseBackNear = (c: { x: number; y: number }) => {
      working.backstitches = (working.backstitches || []).filter((s) => {
        const nearStart = Math.abs(s.x1 - c.x) + Math.abs(s.y1 - c.y) <= 0;
        const nearEnd = Math.abs(s.x2 - c.x) + Math.abs(s.y2 - c.y) <= 0;
        return !(nearStart || nearEnd);
      });
    };

    renderLegend();
    redraw();

    canvas.addEventListener("pointerdown", (ev) => {
      if (!editMode) {
        const { x, y } = cellAt(ev);
        const key = stitchKey(x, y);
        if (gridState.marked.has(key)) gridState.marked.delete(key);
        else gridState.marked.add(key);
        redraw();
        void saveProgress(p.id, proj.status === "not_started" ? "in_progress" : proj.status);
        return;
      }
      painting = true;
      canvas.setPointerCapture(ev.pointerId);
      if (tool === "backstitch") {
        const c = cornerAt(ev);
        if (!pendingBack) {
          pendingBack = c;
          setHint("Click the other grid corner to finish the backstitch.");
        } else {
          const before = structuredClone(working);
          addBackstitch(pendingBack, c);
          pushHistory(before);
          pendingBack = null;
          setHint("Backstitch added. Click another start corner, or Erase stitch then a corner to remove lines.");
        }
        renderLegend();
        redraw();
        return;
      }
      beginStroke();
      const { x, y } = cellAt(ev);
      if (tool === "erase") {
        setStitch(x, y, null);
        const pos = canvasPos(ev);
        const c = cornerAt(ev);
        const near =
          Math.hypot(pos.x / gridState.zoom - c.x, pos.y / gridState.zoom - c.y) < 0.28;
        if (near) eraseBackNear(c);
      } else {
        setStitch(x, y, selectedPal);
      }
      renderLegend();
      redraw();
    });
    canvas.addEventListener("pointermove", (ev) => {
      if (!editMode || !painting || tool === "backstitch") return;
      const { x, y } = cellAt(ev);
      if (tool === "erase") setStitch(x, y, null);
      else setStitch(x, y, selectedPal);
      redraw();
    });
    canvas.addEventListener("pointerup", () => {
      if (painting && editMode && tool !== "backstitch") {
        endStroke();
        renderLegend();
      }
      painting = false;
    });
    canvas.addEventListener("pointercancel", () => {
      if (painting && editMode && tool !== "backstitch") endStroke();
      painting = false;
    });

    async function saveProgress(id: number, status: string) {
      await api(`/api/patterns/${id}/project`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, progress_json: { marked: [...gridState.marked] } }),
      });
    }
    document.getElementById("zoomIn")!.addEventListener("click", () => {
      gridState.zoom = Math.min(32, gridState.zoom + 2);
      redraw();
    });
    document.getElementById("zoomOut")!.addEventListener("click", () => {
      gridState.zoom = Math.max(6, gridState.zoom - 2);
      redraw();
    });
    document.getElementById("toggleSym")!.addEventListener("click", () => {
      cycleSymbolMode();
      const btn = document.getElementById("toggleSym");
      if (btn) btn.textContent = symbolModeLabel();
      renderLegend();
      redraw();
    });
    document.getElementById("startProj")!.addEventListener("click", () => saveProgress(p.id, "in_progress"));
    document.getElementById("finishProj")!.addEventListener("click", () => saveProgress(p.id, "finished"));

    const setTool = (next: typeof tool) => {
      tool = next;
      pendingBack = null;
      editTools.querySelectorAll(".tool-btn").forEach((b) => {
        b.classList.toggle("active", (b as HTMLElement).dataset.tool === tool);
      });
      redraw();
    };
    document.getElementById("editChart")?.addEventListener("click", () => {
      editMode = true;
      undoStack = [];
      redoStack = [];
      strokeSnapshot = null;
      updateUndoRedoButtons();
      editTools.classList.remove("is-hidden");
      document.getElementById("editChart")?.classList.add("is-hidden");
      setTool("stitch");
      renderLegend();
      redraw();
    });
    document.getElementById("undoEdit")?.addEventListener("click", () => undoEdit());
    document.getElementById("redoEdit")?.addEventListener("click", () => redoEdit());
    chartEditKeyHandler = (ev: KeyboardEvent) => {
      if (!editMode) return;
      const key = ev.key.toLowerCase();
      if ((ev.ctrlKey || ev.metaKey) && key === "z") {
        ev.preventDefault();
        if (ev.shiftKey) redoEdit();
        else undoEdit();
      } else if ((ev.ctrlKey || ev.metaKey) && key === "y") {
        ev.preventDefault();
        redoEdit();
      }
    };
    document.addEventListener("keydown", chartEditKeyHandler);
    document.getElementById("cancelEdit")?.addEventListener("click", () => {
      clearChartEditKeys();
      working = structuredClone(loaded);
      pendingBack = null;
      undoStack = [];
      redoStack = [];
      strokeSnapshot = null;
      editMode = false;
      editTools.classList.add("is-hidden");
      document.getElementById("editChart")?.classList.remove("is-hidden");
      renderLegend();
      redraw();
    });
    editTools.querySelectorAll(".tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => setTool((btn as HTMLElement).dataset.tool as typeof tool));
    });
    document.getElementById("addColor")?.addEventListener("click", async () => {
      const hex = prompt("New colour hex (e.g. 310000 or #310000)", "#222222");
      if (!hex) return;
      const nextIndex = Math.max(0, ...working.palette.map((x) => x.index)) + 1;
      const match = await resolvePaintColor(hex, `Colour ${nextIndex}`);
      if (!match) return;
      const number = match.number;
      const name = match.name;
      const stored = match.color;
      if (working.palette.some((p) => p.number === number || p.color.toUpperCase() === stored)) {
        const existing = working.palette.find((p) => p.number === number || p.color.toUpperCase() === stored);
        if (existing) selectedPal = existing.index;
        setHint(`Already have ${number} ${name}`);
        renderLegend();
        return;
      }
      const before = structuredClone(working);
      working.palette.push({
        index: nextIndex,
        number,
        name,
        color: stored,
        symbol: String.fromCharCode(33 + (nextIndex % 90)),
        stitch_count: 0,
      });
      selectedPal = nextIndex;
      pushHistory(before);
      setHint(`Added ${number} ${name}`);
      renderLegend();
    });
    document.getElementById("saveChart")?.addEventListener("click", async () => {
      try {
        await api(`/api/patterns/${p.id}/chart`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: p.title,
            width_stitches: working.width_stitches,
            height_stitches: working.height_stitches,
            palette: working.palette,
            full_stitches: working.full_stitches,
            backstitches: working.backstitches || [],
          }),
        });
        loaded.full_stitches = structuredClone(working.full_stitches);
        loaded.backstitches = structuredClone(working.backstitches || []);
        loaded.palette = structuredClone(working.palette);
        clearChartEditKeys();
        editMode = false;
        pendingBack = null;
        undoStack = [];
        redoStack = [];
        strokeSnapshot = null;
        editTools.classList.add("is-hidden");
        document.getElementById("editChart")?.classList.remove("is-hidden");
        renderLegend();
        redraw();
      } catch (e) {
        alert(String(e));
      }
    });
  }

  let imgScale = 1;
  document.getElementById("imgIn")?.addEventListener("click", () => {
    imgScale *= 1.2;
    document.querySelectorAll("#imgBox img").forEach((img) => {
      (img as HTMLImageElement).style.transform = `scale(${imgScale})`;
    });
  });
  document.getElementById("imgOut")?.addEventListener("click", () => {
    imgScale = Math.max(0.3, imgScale / 1.2);
    document.querySelectorAll("#imgBox img").forEach((img) => {
      (img as HTMLImageElement).style.transform = `scale(${imgScale})`;
    });
  });
}

function render() {
  if (view === "pattern") return renderPattern();
  if (view === "library") return renderLibrary();
  if (view === "indexers") return renderIndexers();
  if (view === "craft_files") return renderCraftFiles();
  return renderSearch();
}

render();
