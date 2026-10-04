type View =
  | "search"
  | "library"
  | "settings_indexers"
  | "settings_file_associations"
  | "settings_supplies"
  | "settings_about"
  | "pattern";

type LibrarySection =
  | "cross_stitch"
  | "crochet"
  | "knitting"
  | "diamond_painting"
  | "embroidery"
  | "sewing"
  | "quilting"
  | "other";

const SETTINGS_VIEWS: View[] = [
  "settings_file_associations",
  "settings_supplies",
  "settings_indexers",
  "settings_about",
];

const LIBRARY_SECTIONS: { id: LibrarySection; label: string; slug: string }[] = [
  { id: "cross_stitch", label: "Cross-stitch", slug: "cross-stitch" },
  { id: "crochet", label: "Crochet", slug: "crochet" },
  { id: "knitting", label: "Knitting", slug: "knitting" },
  { id: "diamond_painting", label: "Diamond Painting", slug: "diamond-painting" },
  { id: "embroidery", label: "Embroidery", slug: "embroidery" },
  { id: "sewing", label: "Sewing", slug: "sewing" },
  { id: "quilting", label: "Quilting", slug: "quilting" },
  { id: "other", label: "Other", slug: "other" },
];

function isSettingsView(v: View) {
  return SETTINGS_VIEWS.includes(v);
}

function isLibraryView(v: View) {
  return v === "library" || v === "pattern";
}

function librarySectionFromCraft(craft: string | null | undefined): LibrarySection {
  if (LIBRARY_SECTIONS.some((s) => s.id === craft)) return craft as LibrarySection;
  return "other";
}

function librarySectionLabel(section: LibrarySection = librarySection) {
  return LIBRARY_SECTIONS.find((s) => s.id === section)?.label || "Library";
}

function craftIdForLibrarySection(section: LibrarySection = librarySection): string {
  return section;
}

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
  fabric_count?: number | null;
  palette: {
    index: number;
    number: string;
    name: string;
    color: string;
    symbol?: string;
    stitch_count?: number;
    strands?: number;
  }[];
  full_stitches: { x: number; y: number; palindex: number }[];
  backstitches?: { x1: number; y1: number; x2: number; y2: number; palindex: number }[];
  part_stitches?: {
    x: number;
    y: number;
    palindex1: number;
    palindex2: number;
    direction: number;
    major?: number;
  }[];
  ornaments?: { x: number; y: number; palindex: number; objecttype: string; direction?: number }[];
  recognition?: { symbol_mode?: string; [key: string]: unknown };
}

/** mismatch.co.uk / Dyer formula: stitches_per_skein = 255 * count / strands */
function stitchesPerSkein(fabricCount: number, strands: number) {
  const count = Math.max(1, Math.round(fabricCount) || 14);
  const used = Math.max(1, Math.min(6, Math.round(strands) || 2));
  return (255 * count) / used;
}

function skeinsNeeded(stitchCount: number, fabricCount: number, strands: number) {
  if (stitchCount <= 0) return 0;
  return stitchCount / stitchesPerSkein(fabricCount, strands);
}

function formatSkeins(needed: number) {
  if (needed <= 0) return "—";
  return String(Math.max(1, Math.ceil(needed - 1e-9)));
}

/** Thread-Bare style: design inches = stitches / count; fabric = design + 2 × border. */
function fabricInches(stitches: number, fabricCount: number) {
  const count = Math.max(1, fabricCount);
  return Math.max(0, stitches) / count;
}

function formatInches(inches: number) {
  if (!Number.isFinite(inches) || inches <= 0) return "—";
  const quarters = Math.round(inches * 4) / 4;
  const whole = Math.floor(quarters + 1e-9);
  const frac = Math.round((quarters - whole) * 4);
  const fracMap: Record<number, string> = { 0: "", 1: "¼", 2: "½", 3: "¾" };
  if (frac === 0) return `${whole}"`;
  if (whole === 0) return `${fracMap[frac]}"`;
  return `${whole}${fracMap[frac]}"`;
}

function formatCm(inches: number) {
  if (!Number.isFinite(inches) || inches <= 0) return "—";
  return `${(inches * 2.54).toFixed(1)} cm`;
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
    view = "settings_file_associations";
    render();
  });
}

const VIEWS: View[] = [
  "search",
  "library",
  "settings_indexers",
  "settings_file_associations",
  "settings_supplies",
  "settings_about",
  "pattern",
];

function normalizeHash(hash: string) {
  const raw = (hash || "").replace(/^#/, "").replace(/^\/+|\/+$/g, "");
  return raw ? `#/${raw}` : "#/search";
}

function routeHash(nextView: View = view, patternId: number | null = selectedPatternId) {
  if (nextView === "pattern" && patternId != null) return `#/pattern/${patternId}`;
  if (nextView === "pattern") return `#/library/${LIBRARY_SECTIONS.find((s) => s.id === librarySection)?.slug || "cross-stitch"}`;
  if (nextView === "library") {
    const slug = LIBRARY_SECTIONS.find((s) => s.id === librarySection)?.slug || "cross-stitch";
    return `#/library/${slug}`;
  }
  if (nextView === "settings_file_associations") return "#/settings/file-associations";
  if (nextView === "settings_supplies") return "#/settings/supplies";
  if (nextView === "settings_indexers") return "#/settings/indexers";
  if (nextView === "settings_about") return "#/settings/about";
  return `#/${nextView}`;
}

function applyRouteFromLocation() {
  const raw = normalizeHash(location.hash).slice(2);
  const parts = raw.split("/").filter(Boolean);
  const name = parts[0] || "search";
  if (name === "pattern") {
    const id = Number(parts[1]);
    if (Number.isFinite(id) && id > 0) {
      view = "pattern";
      selectedPatternId = id;
      return;
    }
    view = "library";
    selectedPatternId = null;
    return;
  }
  if (name === "library") {
    view = "library";
    selectedPatternId = null;
    const slug = parts[1] || "cross-stitch";
    librarySection = LIBRARY_SECTIONS.find((s) => s.slug === slug)?.id || "cross_stitch";
    return;
  }
  if (name === "settings") {
    const sub = parts[1] || "file-associations";
    if (sub === "about") view = "settings_about";
    else if (sub === "indexers") view = "settings_indexers";
    else if (sub === "supplies") view = "settings_supplies";
    else view = "settings_file_associations";
    selectedPatternId = null;
    return;
  }
  // Back-compat hashes.
  if (name === "craft_files") {
    view = "settings_file_associations";
    selectedPatternId = null;
    return;
  }
  if (name === "indexers") {
    view = "settings_indexers";
    selectedPatternId = null;
    return;
  }
  view = VIEWS.includes(name as View) && name !== "pattern" ? (name as View) : "search";
  selectedPatternId = null;
}

let syncingRoute = false;
function syncRoute() {
  const next = routeHash();
  if (normalizeHash(location.hash) === next) return;
  syncingRoute = true;
  history.replaceState(null, "", next);
  syncingRoute = false;
}

let view: View = "search";
let selectedPatternId: number | null = null;
let librarySection: LibrarySection =
  (sessionStorage.getItem("knitarr_library_section") as LibrarySection) || "cross_stitch";
if (!LIBRARY_SECTIONS.some((s) => s.id === librarySection)) librarySection = "cross_stitch";
applyRouteFromLocation();
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

type FabricTexture = "blank" | "aida" | "linen";
const FABRIC_TEXTURES: { id: FabricTexture; label: string }[] = [
  { id: "blank", label: "Blank" },
  { id: "aida", label: "Aida" },
  { id: "linen", label: "Linen" },
];
const FABRIC_COLOURS = [
  { id: "cream", hex: "#f3ebe0", label: "Cream" },
  { id: "white", hex: "#f7f4ef", label: "White" },
  { id: "ivory", hex: "#efe2c8", label: "Ivory" },
  { id: "khaki", hex: "#d8c39a", label: "Khaki" },
  { id: "sage", hex: "#c5d1c0", label: "Sage" },
  { id: "sky", hex: "#d5e4ef", label: "Sky" },
  { id: "blush", hex: "#efd5d5", label: "Blush" },
  { id: "charcoal", hex: "#3a3a3a", label: "Charcoal" },
];

function loadFabricTexture(): FabricTexture {
  const raw = sessionStorage.getItem("knitarr_fabric_texture");
  return FABRIC_TEXTURES.some((t) => t.id === raw) ? (raw as FabricTexture) : "aida";
}

function loadFabricColour(): string {
  const raw = (sessionStorage.getItem("knitarr_fabric_colour") || "").toLowerCase();
  if (/^#[0-9a-f]{6}$/.test(raw)) return raw;
  return FABRIC_COLOURS[0].hex;
}

function loadCenterLines(): boolean {
  return sessionStorage.getItem("knitarr_center_lines") === "1";
}

const gridState = {
  zoom: 16,
  symbolMode: loadSymbolMode(),
  marked: new Set<string>(),
  fabricTexture: loadFabricTexture(),
  fabricColour: loadFabricColour(),
  centerLines: loadCenterLines(),
};

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

const SETTINGS_NAV: { view: View; label: string }[] = [
  { view: "settings_file_associations", label: "File Associations" },
  { view: "settings_supplies", label: "Supplies" },
  { view: "settings_indexers", label: "Indexers" },
  { view: "settings_about", label: "About" },
];

interface FlossBrandInfo {
  id: string;
  label: string;
  description: string;
  color_count: number;
  available: boolean;
}

interface SuppliesSettings {
  floss_brand: string;
  floss_brands: FlossBrandInfo[];
}

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
  if (activeView === "pattern") return `Library · ${librarySectionLabel()}`;
  if (activeView === "library") return `Library · ${librarySectionLabel()}`;
  if (isSettingsView(activeView)) {
    const sub = SETTINGS_NAV.find((n) => n.view === activeView)?.label;
    return sub ? `Settings · ${sub}` : "Settings";
  }
  if (activeView === "search") return "Search";
  return "Knitarr";
}

function closeMobileNav() {
  app.querySelector(".app-shell")?.classList.remove("nav-open");
}

function shell(content: string, activeView: View = view) {
  const settingsOpen = isSettingsView(activeView);
  const libraryOpen = isLibraryView(activeView);
  const librarySubs = LIBRARY_SECTIONS.map(
    (s) =>
      `<button type="button" data-view="library" data-library-section="${s.id}" class="nav-sub-btn${
        libraryOpen && librarySection === s.id ? " active" : ""
      }">${s.label}</button>`
  ).join("");
  const libraryBlock = `
    <div class="nav-group">
      <button type="button" data-view="library" data-library-section="${librarySection}" class="nav-parent${
        libraryOpen ? " active" : ""
      }" aria-expanded="${libraryOpen ? "true" : "false"}">Library</button>
      ${
        libraryOpen
          ? `<div class="nav-sub" role="group" aria-label="Library crafts">${librarySubs}</div>`
          : ""
      }
    </div>`;
  const settingsSubs = SETTINGS_NAV.map(
    (n) =>
      `<button type="button" data-view="${n.view}" class="nav-sub-btn${
        activeView === n.view ? " active" : ""
      }">${n.label}</button>`
  ).join("");
  const settingsBlock = `
    <div class="nav-group">
      <button type="button" data-view="settings_file_associations" class="nav-parent${
        settingsOpen ? " active" : ""
      }" aria-expanded="${settingsOpen ? "true" : "false"}">Settings</button>
      ${
        settingsOpen
          ? `<div class="nav-sub" role="group" aria-label="Settings">${settingsSubs}</div>`
          : ""
      }
    </div>`;
  const pageLabel = currentPageLabel(activeView);
  app.innerHTML = `
    <div class="app-shell">
      <div class="sidebar-backdrop" id="sidebarBackdrop" aria-hidden="true"></div>
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-brand">Knitarr</div>
        <div class="sidebar-label">Browse</div>
        <nav class="sidebar-nav">
          <button type="button" data-view="search" class="${activeView === "search" ? "active" : ""}">Search</button>
          ${libraryBlock}
          ${settingsBlock}
        </nav>
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

  app.querySelectorAll(".sidebar-nav button[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const el = btn as HTMLButtonElement;
      const next = el.dataset.view as View;
      const section = el.dataset.librarySection as LibrarySection | undefined;
      view = next;
      selectedPatternId = null;
      if (next === "library") {
        librarySection = section && LIBRARY_SECTIONS.some((s) => s.id === section) ? section : "cross_stitch";
        sessionStorage.setItem("knitarr_library_section", librarySection);
        selectedCraftId = craftIdForLibrarySection(librarySection);
        sessionStorage.setItem("knitarr_craft", selectedCraftId);
      }
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
        ${delBtn ? `<div class="card-actions">${delBtn}</div>` : ""}
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
  return `No results matched <strong>${escapeHtml(label)}</strong> extensions (${escapeHtml(exts)}). Indexers may have “${escapeHtml(label)}” items that are PDFs or images — add those types under <button type="button" class="linkish" data-view="settings_file_associations">File Associations</button> to include them.`;
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
      <p class="meta">Results include only file types configured under Settings → File Associations for the selected craft.</p>
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

async function renderSupplies() {
  const supplies = await api<SuppliesSettings>("/api/supplies");
  shell(`
    <div class="panel">
      <h2 style="margin:0">Supplies</h2>
      <p class="meta">Choose your preferred embroidery floss brand. The cross-stitch editor and chart conversion match colours to this range.</p>
    </div>
    <div class="panel">
      <h3 style="margin-top:0">Favourite floss brand</h3>
      <div class="supplies-brand-list" role="radiogroup" aria-label="Favourite floss brand">
        ${supplies.floss_brands
          .map((b) => {
            const checked = b.id === supplies.floss_brand;
            const disabled = !b.available;
            return `
          <label class="supplies-brand${checked ? " active" : ""}${disabled ? " disabled" : ""}">
            <input type="radio" name="flossBrand" value="${escapeHtml(b.id)}" ${checked ? "checked" : ""} ${
              disabled ? "disabled" : ""
            } />
            <span class="supplies-brand-body">
              <strong>${escapeHtml(b.label)}</strong>
              <span class="meta">${escapeHtml(b.description)}</span>
              <span class="meta">${b.available ? `${b.color_count} colours in palette` : "Palette unavailable"}</span>
            </span>
          </label>`;
          })
          .join("")}
      </div>
      <div class="indexer-actions" style="margin-top:1rem">
        <button type="button" class="primary" id="saveSupplies">Save</button>
      </div>
    </div>
  `);

  app.querySelectorAll('input[name="flossBrand"]').forEach((input) => {
    input.addEventListener("change", () => {
      app.querySelectorAll(".supplies-brand").forEach((el) => el.classList.remove("active"));
      const label = (input as HTMLElement).closest(".supplies-brand");
      label?.classList.add("active");
    });
  });

  document.getElementById("saveSupplies")?.addEventListener("click", async () => {
    const selected = app.querySelector('input[name="flossBrand"]:checked') as HTMLInputElement | null;
    if (!selected) {
      alert("Pick a floss brand");
      return;
    }
    try {
      await api("/api/supplies", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ floss_brand: selected.value }),
      });
      alert("Saved.");
      render();
    } catch (e) {
      alert(String(e));
    }
  });
}

async function renderFileAssociations() {
  const crafts = await loadCrafts();
  shell(`
    <div class="panel">
      <h2 style="margin:0">File Associations</h2>
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

async function createBlankProject(craftId: string, statusEl: HTMLElement) {
  const title = prompt("Project title", "Untitled")?.trim();
  if (title == null) return;
  if (craftId !== "cross_stitch") {
    statusEl.textContent = "Blank projects are currently only available for cross stitch.";
    return;
  }
  statusEl.textContent = "Creating blank project…";
  try {
    const detail = await api<{ id: number }>(`/api/patterns/blank`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: title || "Untitled",
        width: 20,
        height: 20,
        craft: craftId,
      }),
    });
    selectedPatternId = detail.id;
    view = "pattern";
    render();
  } catch (e) {
    statusEl.textContent = String(e);
  }
}

async function renderLibrary() {
  const sectionLabel = librarySectionLabel();
  const craftParam = encodeURIComponent(librarySection);
  const patterns = await api<PatternSummary[]>(
    `/api/patterns?downloaded=true&craft=${craftParam}`
  );
  const crafts = await loadCrafts();
  const sectionCrafts = crafts.filter((c) => c.craft_id === librarySection);
  selectedCraftId = craftIdForLibrarySection();
  sessionStorage.setItem("knitarr_craft", selectedCraftId);
  const accept = uploadAcceptExtensions(sectionCrafts.length ? sectionCrafts : crafts);
  shell(`
    <div class="panel">
      <h2 style="margin:0 0 0.75rem">${escapeHtml(sectionLabel)}</h2>
      <p class="meta">Import ${escapeHtml(sectionLabel.toLowerCase())} patterns you own — types configured under Settings → File Associations — or start a blank design.</p>
      <div class="library-actions">
        <div class="library-action library-action-upload">
          <h3>Upload file</h3>
          <label class="primary upload-btn">
            Choose files
            <input type="file" id="uploadInput" multiple accept="${escapeHtml(accept)}" hidden />
          </label>
          <div class="upload-dropzone" id="uploadDropzone" tabindex="0">
            <p>Drop files here or use Choose files</p>
            <p class="meta">Multiple files upload one pattern per file. Duplicates are skipped by checksum.</p>
          </div>
        </div>
        <div class="library-action library-action-blank${selectedCraftId === "cross_stitch" ? "" : " is-disabled"}">
          <h3>Create blank project</h3>
          <p class="meta">${
            selectedCraftId === "cross_stitch"
              ? "Start an empty cross-stitch chart and design it in the editor."
              : "Blank projects are currently only available for cross-stitch."
          }</p>
          <button type="button" class="secondary" id="createBlank"${
            selectedCraftId === "cross_stitch" ? "" : " disabled"
          }>Create blank project</button>
        </div>
      </div>
      <p class="meta" id="uploadStatus" aria-live="polite"></p>
    </div>
    <div class="card-grid">${
      patterns.length
        ? patterns.map(patternCard).join("")
        : `<p class="empty">No ${escapeHtml(sectionLabel.toLowerCase())} patterns yet — upload a file or create a blank project above.</p>`
    }</div>
  `, "library");
  const statusEl = document.getElementById("uploadStatus")!;
  const input = document.getElementById("uploadInput") as HTMLInputElement;
  const drop = document.getElementById("uploadDropzone")!;

  const doUpload = (files: FileList | File[]) => {
    void uploadFilesToLibrary(files, selectedCraftId, statusEl);
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

  document.getElementById("createBlank")?.addEventListener("click", () => {
    void createBlankProject(selectedCraftId, statusEl);
  });

  app.querySelectorAll(".card[data-pid]").forEach((card) => {
    card.addEventListener("click", (ev) => {
      if ((ev.target as HTMLElement).closest(".btn-del-pat")) return;
      selectedPatternId = Number((card as HTMLElement).dataset.pid);
      view = "pattern";
      render();
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

function shadeHex(raw: string, amount: number) {
  const h = raw.replace("#", "");
  if (h.length !== 6) return hexColor(raw);
  const clamp = (n: number) => Math.max(0, Math.min(255, Math.round(n)));
  const r = clamp(parseInt(h.slice(0, 2), 16) * (1 + amount));
  const g = clamp(parseInt(h.slice(2, 4), 16) * (1 + amount));
  const b = clamp(parseInt(h.slice(4, 6), 16) * (1 + amount));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

type PartHalf = "bl" | "tr" | "tl" | "br";

/**
 * Ursa partstitch:
 * - direction 1: \\ split — palindex1 = bottom-left, palindex2 = top-right
 * - direction 2: / split — palindex1 = top-left, palindex2 = bottom-right
 * - direction 3/4: tent/gobelin half-stitches (diagonal stroke), not triangles
 */
function partHalfFor(direction: number, which: 1 | 2): PartHalf {
  if (direction === 2 || direction === 4) return which === 1 ? "tl" : "br";
  return which === 1 ? "bl" : "tr";
}

function partTrianglePath(ctx: CanvasRenderingContext2D, x: number, y: number, cell: number, half: PartHalf) {
  const x0 = x * cell;
  const y0 = y * cell;
  const x1 = x0 + cell;
  const y1 = y0 + cell;
  ctx.beginPath();
  if (half === "bl") {
    ctx.moveTo(x0, y0);
    ctx.lineTo(x0, y1);
    ctx.lineTo(x1, y1);
  } else if (half === "tr") {
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y0);
    ctx.lineTo(x1, y1);
  } else if (half === "tl") {
    ctx.moveTo(x0, y0);
    ctx.lineTo(x1, y0);
    ctx.lineTo(x0, y1);
  } else {
    ctx.moveTo(x1, y0);
    ctx.lineTo(x1, y1);
    ctx.lineTo(x0, y1);
  }
  ctx.closePath();
}

function drawTentStroke(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  cell: number,
  direction: number,
  color: string,
  opts?: { preview?: boolean }
) {
  const pad = Math.max(0.8, cell * 0.18);
  const x0 = x * cell + pad;
  const y0 = y * cell + pad;
  const x1 = x * cell + cell - pad;
  const y1 = y * cell + cell - pad;
  const from = direction === 3 ? { x: x0, y: y0 } : { x: x1, y: y0 };
  const to = direction === 3 ? { x: x1, y: y1 } : { x: x0, y: y1 };
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  if (opts?.preview) {
    ctx.strokeStyle = "rgba(0,0,0,0.18)";
    ctx.lineWidth = Math.max(1.2, cell * 0.34);
    ctx.beginPath();
    ctx.moveTo(from.x + 0.4, from.y + 0.6);
    ctx.lineTo(to.x + 0.4, to.y + 0.6);
    ctx.stroke();
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1.1, cell * 0.28);
    ctx.beginPath();
    ctx.moveTo(from.x, from.y);
    ctx.lineTo(to.x, to.y);
    ctx.stroke();
    ctx.strokeStyle = shadeHex(color, 0.28);
    ctx.lineWidth = Math.max(0.6, cell * 0.1);
    ctx.beginPath();
    ctx.moveTo(from.x + cell * 0.04, from.y + cell * 0.02);
    ctx.lineTo(to.x - cell * 0.02, to.y - cell * 0.04);
    ctx.stroke();
    return;
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1.2, cell * 0.28);
  ctx.beginPath();
  ctx.moveTo(from.x, from.y);
  ctx.lineTo(to.x, to.y);
  ctx.stroke();
}

function drawPartStitches(
  ctx: CanvasRenderingContext2D,
  norm: Normalized,
  cell: number,
  palMap: Map<number, Normalized["palette"][number]>,
  opts?: { onlyPal?: number | null; forceColor?: string; preview?: boolean }
) {
  for (const ps of norm.part_stitches || []) {
    const dir = ps.direction || 1;
    const p1 = ps.palindex1 || 0;
    const p2 = ps.palindex2 || 0;
    if (dir === 3 || dir === 4) {
      const palindex = p1 > 0 ? p1 : p2;
      if (!palindex) continue;
      if (opts?.onlyPal != null && palindex !== opts.onlyPal) continue;
      const pal = palMap.get(palindex);
      drawTentStroke(
        ctx,
        ps.x,
        ps.y,
        cell,
        dir,
        opts?.forceColor || (pal ? hexColor(pal.color) : "#888"),
        { preview: opts?.preview }
      );
      continue;
    }
    for (const which of [1, 2] as const) {
      const palindex = which === 1 ? p1 : p2;
      if (!palindex || palindex <= 0) continue;
      if (opts?.onlyPal != null && palindex !== opts.onlyPal) continue;
      const pal = palMap.get(palindex);
      const color = opts?.forceColor || (pal ? hexColor(pal.color) : "#ccc");
      const half = partHalfFor(dir, which);
      if (opts?.preview) {
        // Clip a full faux cross to the half-triangle so partials read as thread, not blocks.
        ctx.save();
        partTrianglePath(ctx, ps.x, ps.y, cell, half);
        ctx.clip();
        drawFauxThreadX(ctx, ps.x, ps.y, cell, color);
        ctx.restore();
      } else {
        ctx.fillStyle = color;
        partTrianglePath(ctx, ps.x, ps.y, cell, half);
        ctx.fill();
      }
    }
  }
}

function drawOrnaments(
  ctx: CanvasRenderingContext2D,
  norm: Normalized,
  cell: number,
  palMap: Map<number, Normalized["palette"][number]>,
  opts?: { onlyPal?: number | null; forceColor?: string; preview?: boolean }
) {
  for (const o of norm.ornaments || []) {
    if (opts?.onlyPal != null && o.palindex !== opts.onlyPal) continue;
    const pal = palMap.get(o.palindex);
    const color = opts?.forceColor || (pal ? hexColor(pal.color) : "#444");
    const cx = o.x * cell;
    const cy = o.y * cell;
    const bead = (o.objecttype || "").toLowerCase().startsWith("bead");
    const r = Math.max(1.4, cell * (bead ? 0.22 : 0.16));
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    if (opts?.preview || bead) {
      ctx.strokeStyle = "rgba(0,0,0,0.35)";
      ctx.lineWidth = Math.max(0.8, cell * 0.04);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(cx - r * 0.25, cy - r * 0.25, r * 0.28, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(255,255,255,0.45)";
      ctx.fill();
    } else {
      ctx.strokeStyle = "rgba(0,0,0,0.45)";
      ctx.lineWidth = Math.max(0.8, cell * 0.05);
      ctx.stroke();
    }
  }
}

function drawFauxThreadX(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  cell: number,
  color: string
) {
  const pad = Math.max(0.8, cell * 0.14);
  const x0 = x * cell + pad;
  const y0 = y * cell + pad;
  const x1 = x * cell + cell - pad;
  const y1 = y * cell + cell - pad;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  // Soft shadow under-thread
  ctx.strokeStyle = "rgba(0,0,0,0.18)";
  ctx.lineWidth = Math.max(1.2, cell * 0.34);
  ctx.beginPath();
  ctx.moveTo(x0 + 0.4, y0 + 0.6);
  ctx.lineTo(x1 + 0.4, y1 + 0.6);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x1 + 0.4, y0 + 0.6);
  ctx.lineTo(x0 + 0.4, y1 + 0.6);
  ctx.stroke();
  // Main floss
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1.1, cell * 0.28);
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(x1, y0);
  ctx.lineTo(x0, y1);
  ctx.stroke();
  // Light sheen on top arm
  ctx.strokeStyle = shadeHex(color, 0.28);
  ctx.lineWidth = Math.max(0.6, cell * 0.1);
  ctx.beginPath();
  ctx.moveTo(x0 + cell * 0.05, y0 + cell * 0.02);
  ctx.lineTo(x1 - cell * 0.02, y1 - cell * 0.05);
  ctx.stroke();
}

function drawPreviewFabric(
  ctx: CanvasRenderingContext2D,
  widthPx: number,
  heightPx: number,
  cell: number,
  colour: string,
  texture: FabricTexture
) {
  const base = hexColor(colour);
  ctx.fillStyle = base;
  ctx.fillRect(0, 0, widthPx, heightPx);
  if (texture === "blank") return;

  if (texture === "aida") {
    const hole = Math.max(0.7, cell * 0.16);
    const gap = Math.max(0.35, cell * 0.05);
    const dark = shadeHex(base, -0.12);
    const light = shadeHex(base, 0.08);
    // Soft weave blocks
    for (let y = 0; y < heightPx; y += cell) {
      for (let x = 0; x < widthPx; x += cell) {
        ctx.fillStyle = light;
        ctx.fillRect(x + gap, y + gap, cell - gap * 2, cell - gap * 2);
        ctx.fillStyle = dark;
        const hx = x + cell / 2 - hole / 2;
        const hy = y + cell / 2 - hole / 2;
        ctx.fillRect(hx, hy, hole, hole);
        // corner pinholes typical of aida
        const pin = Math.max(0.5, hole * 0.45);
        for (const [px, py] of [
          [x + gap, y + gap],
          [x + cell - gap - pin, y + gap],
          [x + gap, y + cell - gap - pin],
          [x + cell - gap - pin, y + cell - gap - pin],
        ] as const) {
          ctx.fillRect(px, py, pin, pin);
        }
      }
    }
    ctx.strokeStyle = shadeHex(base, -0.18);
    ctx.lineWidth = Math.max(0.4, cell * 0.03);
    for (let x = 0; x <= widthPx; x += cell) {
      ctx.beginPath();
      ctx.moveTo(x + 0.5, 0);
      ctx.lineTo(x + 0.5, heightPx);
      ctx.stroke();
    }
    for (let y = 0; y <= heightPx; y += cell) {
      ctx.beginPath();
      ctx.moveTo(0, y + 0.5);
      ctx.lineTo(widthPx, y + 0.5);
      ctx.stroke();
    }
    return;
  }

  // linen — finer irregular weave
  const thread = Math.max(0.6, cell * 0.08);
  const dark = shadeHex(base, -0.1);
  const mid = shadeHex(base, -0.04);
  const light = shadeHex(base, 0.07);
  ctx.lineCap = "butt";
  for (let y = 0; y < heightPx; y += thread * 2) {
    ctx.strokeStyle = y % (thread * 4) < thread * 2 ? dark : mid;
    ctx.lineWidth = thread * 0.85;
    ctx.beginPath();
    ctx.moveTo(0, y + 0.3);
    // slight wobble for organic linen feel
    for (let x = 0; x <= widthPx; x += cell) {
      const wobble = ((x * 13 + y * 7) % 5) - 2;
      ctx.lineTo(x, y + wobble * 0.15);
    }
    ctx.stroke();
  }
  for (let x = 0; x < widthPx; x += thread * 2) {
    ctx.strokeStyle = x % (thread * 4) < thread * 2 ? mid : light;
    ctx.lineWidth = thread * 0.7;
    ctx.globalAlpha = 0.55;
    ctx.beginPath();
    ctx.moveTo(x + 0.3, 0);
    for (let y = 0; y <= heightPx; y += cell) {
      const wobble = ((x * 11 + y * 17) % 5) - 2;
      ctx.lineTo(x + wobble * 0.12, y);
    }
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawCenterLines(
  ctx: CanvasRenderingContext2D,
  widthStitches: number,
  heightStitches: number,
  cell: number
) {
  if (!gridState.centerLines) return;
  const w = widthStitches * cell;
  const h = heightStitches * cell;
  const cx = (widthStitches / 2) * cell;
  const cy = (heightStitches / 2) * cell;
  ctx.save();
  ctx.strokeStyle = "#e11d2e";
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  ctx.beginPath();
  ctx.moveTo(cx, 0);
  ctx.lineTo(cx, h);
  ctx.moveTo(0, cy);
  ctx.lineTo(w, cy);
  ctx.stroke();
  ctx.restore();
}

function drawGrid(
  canvas: HTMLCanvasElement,
  norm: Normalized,
  extras?: {
    pendingBack?: { x: number; y: number } | null;
    editMode?: boolean;
    highlightPal?: number | null;
    previewMode?: boolean;
  }
) {
  const cell = gridState.zoom;
  const w = norm.width_stitches * cell;
  const h = norm.height_stitches * cell;
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d")!;
  const palMap = new Map(norm.palette.map((p) => [p.index, p]));
  const highlightPal = extras?.highlightPal ?? null;
  const highlighting = highlightPal != null && highlightPal > 0;
  const previewMode = !!extras?.previewMode;

  if (previewMode) {
    drawPreviewFabric(ctx, w, h, cell, gridState.fabricColour, gridState.fabricTexture);
    for (const s of norm.full_stitches) {
      const pal = palMap.get(s.palindex);
      drawFauxThreadX(ctx, s.x, s.y, cell, pal ? hexColor(pal.color) : "#888");
    }
    drawPartStitches(ctx, norm, cell, palMap, { preview: true });
    ctx.lineCap = "round";
    for (const b of norm.backstitches || []) {
      const pal = palMap.get(b.palindex);
      ctx.strokeStyle = pal ? hexColor(pal.color) : "#222";
      ctx.lineWidth = Math.max(1.4, cell * 0.16);
      ctx.beginPath();
      ctx.moveTo(b.x1 * cell, b.y1 * cell);
      ctx.lineTo(b.x2 * cell, b.y2 * cell);
      ctx.stroke();
    }
    drawOrnaments(ctx, norm, cell, palMap, { preview: true });
    if (highlighting) {
      ctx.fillStyle = "rgba(0, 0, 0, 0.5)";
      ctx.fillRect(0, 0, w, h);
      for (const s of norm.full_stitches) {
        if (s.palindex !== highlightPal) continue;
        drawFauxThreadX(ctx, s.x, s.y, cell, "#00e5ff");
      }
      drawPartStitches(ctx, norm, cell, palMap, {
        onlyPal: highlightPal,
        forceColor: "#00e5ff",
        preview: true,
      });
      for (const b of norm.backstitches || []) {
        if (b.palindex !== highlightPal) continue;
        ctx.strokeStyle = "#00e5ff";
        ctx.lineWidth = Math.max(1.8, cell * 0.2);
        ctx.beginPath();
        ctx.moveTo(b.x1 * cell, b.y1 * cell);
        ctx.lineTo(b.x2 * cell, b.y2 * cell);
        ctx.stroke();
      }
      drawOrnaments(ctx, norm, cell, palMap, { onlyPal: highlightPal, forceColor: "#00e5ff", preview: true });
    }
    drawCenterLines(ctx, norm.width_stitches, norm.height_stitches, cell);
    return;
  }

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
  drawPartStitches(ctx, norm, cell, palMap);
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
  drawOrnaments(ctx, norm, cell, palMap);
  if (highlighting) {
    ctx.fillStyle = "rgba(0, 0, 0, 0.55)";
    ctx.fillRect(0, 0, w, h);
    for (const s of norm.full_stitches) {
      if (s.palindex !== highlightPal) continue;
      ctx.fillStyle = "#00e5ff";
      ctx.fillRect(s.x * cell, s.y * cell, cell, cell);
      const mark = symbolForPalette(norm.palette, s.palindex);
      if (mark) {
        ctx.fillStyle = "#003840";
        const shrink = mark.length > 1 ? 0.55 : 0.7;
        ctx.font = `600 ${Math.max(8, Math.floor(cell * shrink))}px "Segoe UI Symbol","Noto Sans Symbols","DejaVu Sans",sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(mark, s.x * cell + cell / 2, s.y * cell + cell / 2);
      }
    }
    drawPartStitches(ctx, norm, cell, palMap, { onlyPal: highlightPal, forceColor: "#00e5ff" });
    ctx.strokeStyle = "rgba(255,255,255,0.18)";
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
    for (const b of norm.backstitches || []) {
      if (b.palindex !== highlightPal) continue;
      ctx.strokeStyle = "#00e5ff";
      ctx.lineWidth = Math.max(2, cell * 0.22);
      ctx.beginPath();
      ctx.moveTo(b.x1 * cell, b.y1 * cell);
      ctx.lineTo(b.x2 * cell, b.y2 * cell);
      ctx.stroke();
    }
    drawOrnaments(ctx, norm, cell, palMap, { onlyPal: highlightPal, forceColor: "#00e5ff" });
  }
  if (extras?.pendingBack) {
    ctx.fillStyle = "#c0392b";
    ctx.beginPath();
    ctx.arc(extras.pendingBack.x * cell, extras.pendingBack.y * cell, Math.max(3, cell * 0.18), 0, Math.PI * 2);
    ctx.fill();
  }
  drawCenterLines(ctx, norm.width_stitches, norm.height_stitches, cell);
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
  librarySection = librarySectionFromCraft(p.craft);
  sessionStorage.setItem("knitarr_library_section", librarySection);
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
  const convertLabel = p.has_normalized ? "Reprocess Stitch Chart" : "Generate stitch chart";

  const iconGrid = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 3h8v8H3V3zm10 0h8v8h-8V3zM3 13h8v8H3v-8zm10 0h8v8h-8v-8z"/></svg>`;
  const iconEdit = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg>`;
  const iconEye = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 5c-5 0-9.27 3.11-11 7 1.73 3.89 6 7 11 7s9.27-3.11 11-7c-1.73-3.89-6-7-11-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 .001 6.001A3 3 0 0 0 12 9z"/></svg>`;
  // Stitch = cell with cross; erase = plain X (these were previously swapped).
  const iconStitch = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" d="M4 4h16v16H4z"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M8 8l8 8M16 8l-8 8"/></svg>`;
  const iconErase = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" d="M6 6l12 12M18 6L6 18"/></svg>`;
  const iconFill = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16.56 8.94 7.62 0 6.21 1.41l2.38 2.38-5.15 5.15a2 2 0 0 0 0 2.83l6.36 6.36c.78.78 2.05.78 2.83 0l7.07-7.07-3.14-2.12zM5.21 10.36 9.7 5.87l4.95 4.95-4.49 4.49-5-4.95zM19 11s-2 2.17-2 3.5a2 2 0 1 0 4 0C21 13.17 19 11 19 11z"/></svg>`;
  const iconBackstitch = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" d="M4 18l7-7M13 9l7-7"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/></svg>`;
  const iconPart = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M4 4h16v16H4V4zm2 2v12h12L6 6z"/></svg>`;
  const iconKnot = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5.2" fill="currentColor"/><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.6"/></svg>`;
  const iconUndo = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62A7.46 7.46 0 0 1 12.5 11c3.31 0 6.13 2.13 7.14 5.1l2.3-.76C20.63 11.14 16.92 8 12.5 8z"/></svg>`;
  const iconRedo = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M18.4 10.6A8.47 8.47 0 0 0 11.5 8C7.08 8 3.37 11.14 2.06 15.34l2.3.76A7.46 7.46 0 0 1 11.5 11c1.86 0 3.55.68 4.87 1.8L12.75 16H22V7l-3.6 3.6z"/></svg>`;
  const iconSave = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M17 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V7l-4-4zm-5 16a3 3 0 1 1 0-6 3 3 0 0 1 0 6zm3-10H5V5h10v4z"/></svg>`;
  const iconPlus = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>`;
  const iconCrosshair = `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="1.8" d="M12 3v18M3 12h18"/><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>`;

  const chartViewer = `
      <div class="chart-panel">
        <div class="chart-toolbar">
          <div class="chart-toolbar-left">
            <div class="icon-group" role="group" aria-label="Zoom">
              <button type="button" class="icon-btn" id="zoomOut" title="Zoom out" aria-label="Zoom out">−</button>
              <button type="button" class="icon-btn" id="zoomIn" title="Zoom in" aria-label="Zoom in">+</button>
            </div>
            <button type="button" class="icon-btn${
              gridState.centerLines ? " active" : ""
            }" id="toggleCenterLines" title="Center lines" aria-label="Toggle center lines" aria-pressed="${
              gridState.centerLines ? "true" : "false"
            }">${iconCrosshair}</button>
            <button type="button" class="chip-btn" id="toggleSym" title="Cycle symbol mode">${escapeHtml(symbolModeLabel())}</button>
            <div class="mode-slider" role="tablist" aria-label="Chart mode">
              <button type="button" class="mode-btn active" data-mode="chart" title="Chart view" aria-label="Chart view">${iconGrid}<span>Chart</span></button>
              <button type="button" class="mode-btn" data-mode="edit" title="Edit" aria-label="Edit">${iconEdit}</button>
              <button type="button" class="mode-btn" data-mode="preview" title="Thread preview" aria-label="Preview">${iconEye}</button>
            </div>
          </div>
          <div class="chart-toolbar-right">
            <button type="button" class="icon-btn save-btn is-hidden" id="saveChart" title="Save chart" aria-label="Save chart">${iconSave}</button>
          </div>
        </div>
        <div class="edit-tools is-hidden" id="editTools">
          <div class="icon-group tool-group" role="group" aria-label="Edit tools">
            <button type="button" class="icon-btn tool-btn active" data-tool="stitch" title="Stitch" aria-label="Stitch">${iconStitch}</button>
            <button type="button" class="icon-btn tool-btn" data-tool="erase" title="Erase stitch" aria-label="Erase">${iconErase}</button>
            <button type="button" class="icon-btn tool-btn" data-tool="fill" title="Bucket fill" aria-label="Bucket fill">${iconFill}</button>
            <button type="button" class="icon-btn tool-btn" data-tool="backstitch" title="Backstitch" aria-label="Backstitch">${iconBackstitch}</button>
            <button type="button" class="icon-btn tool-btn" data-tool="part" title="Partial stitch" aria-label="Partial stitch">${iconPart}</button>
            <button type="button" class="icon-btn tool-btn" data-tool="knot" title="French knot" aria-label="French knot">${iconKnot}</button>
          </div>
          <div class="icon-group" role="group" aria-label="History">
            <button type="button" class="icon-btn" id="undoEdit" disabled title="Undo (Ctrl+Z)" aria-label="Undo">${iconUndo}</button>
            <button type="button" class="icon-btn" id="redoEdit" disabled title="Redo (Ctrl+Y)" aria-label="Redo">${iconRedo}</button>
          </div>
          <div class="chart-size-fields" role="group" aria-label="Chart size">
            <label class="size-field">W
              <input type="number" id="chartWidth" min="1" max="800" step="1" value="${p.width_stitches || 20}" title="Width in stitches" aria-label="Width in stitches" />
            </label>
            <label class="size-field">H
              <input type="number" id="chartHeight" min="1" max="800" step="1" value="${p.height_stitches || 20}" title="Height in stitches" aria-label="Height in stitches" />
            </label>
          </div>
          <span class="meta edit-hint" id="editHint">Click a legend colour, then paint.</span>
        </div>
        <div class="preview-tools is-hidden" id="previewTools">
          <div class="icon-group fabric-swatches" role="group" aria-label="Fabric colour">
            ${FABRIC_COLOURS.map(
              (c) =>
                `<button type="button" class="fabric-swatch${
                  c.hex.toLowerCase() === gridState.fabricColour.toLowerCase() ? " active" : ""
                }" data-colour="${c.hex}" title="${c.label}" aria-label="${c.label}" style="--swatch:${c.hex}"></button>`
            ).join("")}
            <label class="fabric-custom" title="Custom fabric colour">
              <input type="color" id="fabricColourCustom" value="${gridState.fabricColour}" aria-label="Custom fabric colour" />
            </label>
          </div>
          <div class="icon-group texture-group" role="group" aria-label="Fabric texture">
            ${FABRIC_TEXTURES.map(
              (t) =>
                `<button type="button" class="chip-btn texture-btn${
                  t.id === gridState.fabricTexture ? " active" : ""
                }" data-texture="${t.id}">${t.label}</button>`
            ).join("")}
          </div>
        </div>
        <div class="viewer-layout">
          <div class="chart-canvas-wrap"><canvas id="gridCanvas"></canvas></div>
          <div class="legend panel">
            <div class="legend-header">
              <h3>Legend</h3>
              <button type="button" class="icon-btn is-hidden" id="addColor" title="Add colour" aria-label="Add colour">${iconPlus}</button>
            </div>
            <label class="legend-fabric-count">Fabric count
              <input type="number" id="legendFabricCount" min="6" max="40" step="1" value="14" title="Stitches per inch" aria-label="Fabric count" />
            </label>
            <div id="legendBody"></div>
            <div class="skein-estimate" id="skeinEstimate">
              <h4>Skein estimate</h4>
              <p class="meta">Based on ~8&nbsp;m skeins and the <a href="https://www.mismatch.co.uk/cross.htm#floss_amt" target="_blank" rel="noopener">mismatch.co.uk</a> floss-amount guide. Buy counts round up.</p>
              <div id="skeinEstimateBody"></div>
            </div>
            <div class="fabric-size-estimate" id="fabricSizeEstimate">
              <h4>Fabric size</h4>
              <p class="meta">Stitched image and suggested cut size with border, following the <a href="https://www.thread-bare.com/tools/cross-stitch-fabric-size-calculator" target="_blank" rel="noopener">Thread-Bare</a> calculator.</p>
              <label class="legend-fabric-count">Border each side
                <input type="number" id="legendFabricBorder" min="0" max="12" step="0.5" value="3" title="Extra fabric per side (inches)" aria-label="Border each side in inches" />
                <span class="meta">in</span>
              </label>
              <div id="fabricSizeEstimateBody"></div>
            </div>
          </div>
        </div>
      </div>`;

  let originalViewer = "";
  if (!p.has_normalized && pagedFile) {
    originalViewer = `
        ${pdfPageBarHtml("orig", pdfPageCount)}
        <div class="image-viewer" id="imgBox">
          <img data-pdf-page-img="orig" src="${pdfRasterPreviewUrl(p.id, 1)}" alt="${pagedKind} page" />
        </div>
        <p class="meta"><a href="/api/patterns/${selectedPatternId}/file/${pagedFile.id}" target="_blank" rel="noopener">Open full ${pagedKind}</a></p>`;
  } else if (!p.has_normalized && imgs.length) {
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
  if (p.has_normalized) {
    viewerHtml = chartViewer;
  } else if (originalViewer) {
    viewerHtml = originalViewer;
  }

  const uploadActions = isUserUpload(p.source)
    ? `<div class="pattern-actions">
        ${
          p.has_normalized
            ? `<button type="button" class="secondary" id="regeneratePackage" title="Rebuild chart preview, thumbnail, and Chart Export.pdf">Regenerate File Package</button>`
            : ""
        }
        <button type="button" class="secondary" id="deletePat">Delete</button>
      </div>`
    : p.has_normalized
      ? `<div class="pattern-actions">
          <button type="button" class="secondary" id="regeneratePackage" title="Rebuild chart preview, thumbnail, and Chart Export.pdf">Regenerate File Package</button>
        </div>`
      : "";

  const cropPanel = canRasterConvert
    ? `<details class="panel collapsible-panel" id="cropPanel"${p.has_normalized ? "" : " open"}>
        <summary><h3>Show Original File + Crop</h3></summary>
        <p class="meta">Drag the box or handles to focus on the pattern area${
          p.has_normalized ? ", then reprocess the stitch chart" : ""
        }.</p>
        ${pagedFile ? pdfPageBarHtml("crop", pdfPageCount) : ""}
        <div id="cropMount"></div>
        ${
          canConvert
            ? `<div class="pattern-actions" style="margin-top:0.75rem">
                <button type="button" class="primary" id="convertChart">${convertLabel}</button>
              </div>`
            : ""
        }
      </details>`
    : canConvert && !canRasterConvert
      ? `<div class="panel">
          <button type="button" class="primary" id="convertChart">${convertLabel}</button>
        </div>`
      : "";
  shell(`
    <div class="panel">
      <button class="secondary" id="backLib">← ${escapeHtml(librarySectionLabel())}</button>
      <div class="title-row">
        <h2 id="patternTitle">${escapeHtml(p.title)}</h2>
        <button type="button" class="secondary" id="renameTitle">Rename</button>
      </div>
      <p class="meta">${p.pattern_format.toUpperCase()} · ${escapeHtml(p.craft)}${p.source_url ? ` · <a href="${p.source_url}" target="_blank">source</a>` : ""}</p>
      ${uploadActions}
      <p>${escapeHtml(p.description || "")}</p>
      <details class="file-list collapsible-panel" open>
        <summary class="file-list-header">
          <h3>Files</h3>
          <span class="meta file-list-count">${files.length} file${files.length === 1 ? "" : "s"}</span>
        </summary>
        <div class="file-share-actions" aria-label="Export pattern files">
          <span class="file-export-label">Export:</span>
          <button type="button" class="secondary" id="exportTorrent" title="Download a .torrent of this pattern's files">Torrent</button>
          <button type="button" class="secondary" id="exportMagnet" title="Copy a magnet link for this pattern">Magnet</button>
          <button type="button" class="secondary" id="exportZip" title="Download a ZIP of this pattern's files">ZIP</button>
        </div>
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
        <p class="meta is-hidden" id="magnetStatus" aria-live="polite"></p>
      </details>
    </div>
    ${cropPanel}
    <div class="panel">${viewerHtml || `<p class="empty">No viewer for this format.</p>`}</div>
  `, "pattern");

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
    if (document.querySelector('[data-pdf-bar="orig"]')) wirePdfPageBar("orig");
  }

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
      librarySection = librarySectionFromCraft(p.craft);
      sessionStorage.setItem("knitarr_library_section", librarySection);
      view = "library";
      selectedPatternId = null;
      render();
    } catch (e) {
      alert(String(e));
    }
  });

  document.getElementById("exportTorrent")?.addEventListener("click", () => {
    window.location.href = `/api/patterns/${p.id}/torrent`;
  });

  document.getElementById("exportZip")?.addEventListener("click", () => {
    window.location.href = `/api/patterns/${p.id}/zip`;
  });

  document.getElementById("exportMagnet")?.addEventListener("click", async () => {
    const status = document.getElementById("magnetStatus");
    if (status) {
      status.classList.remove("is-hidden");
      status.textContent = "Creating magnet link…";
    }
    try {
      const res = await api<{ magnet: string; title: string }>(`/api/patterns/${p.id}/magnet`);
      try {
        await navigator.clipboard.writeText(res.magnet);
        if (status) status.textContent = `Magnet copied for “${res.title}”.`;
      } catch {
        if (status) status.textContent = res.magnet;
        prompt("Magnet link (copy):", res.magnet);
      }
    } catch (e) {
      if (status) status.textContent = String(e);
      else alert(String(e));
    }
  });

  document.getElementById("convertChart")?.addEventListener("click", async () => {
    try {
      const crop = cropApi?.getCrop();
      if (crop) persistCrop(crop);
      const body: { crop?: NormCrop; pdf_page?: number; symbol_mode?: string } = {
        symbol_mode: gridState.symbolMode,
      };
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

  document.getElementById("regeneratePackage")?.addEventListener("click", async () => {
    const btn = document.getElementById("regeneratePackage") as HTMLButtonElement | null;
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Regenerating…";
    }
    try {
      const r = await api<{ message: string }>(`/api/patterns/${p.id}/regenerate-package`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol_mode: gridState.symbolMode }),
      });
      alert(r.message);
      selectedPatternId = p.id;
      render();
    } catch (e) {
      alert(String(e));
      if (btn) {
        btn.disabled = false;
        btn.textContent = "Regenerate File Package";
      }
    }
  });

  document.getElementById("backLib")!.addEventListener("click", () => {
    librarySection = librarySectionFromCraft(p.craft);
    sessionStorage.setItem("knitarr_library_section", librarySection);
    view = "library";
    selectedPatternId = null;
    render();
  });

  if (p.has_normalized) {
    const loaded = await api<Normalized>(`/api/patterns/${selectedPatternId}/normalized`);
    if (!loaded.backstitches) loaded.backstitches = [];
    if (!loaded.part_stitches) loaded.part_stitches = [];
    if (!loaded.ornaments) loaded.ornaments = [];
    if (!loaded.fabric_count || loaded.fabric_count < 6) loaded.fabric_count = 14;
    for (const pal of loaded.palette) {
      const s = Number(pal.strands);
      pal.strands = Number.isFinite(s) ? Math.max(1, Math.min(6, Math.round(s))) : 2;
    }
    const savedMode = loaded.recognition?.symbol_mode;
    if (typeof savedMode === "string" && SYMBOL_MODES.some((m) => m.id === savedMode)) {
      gridState.symbolMode = savedMode as SymbolMode;
      sessionStorage.setItem("knitarr_symbol_mode", gridState.symbolMode);
    }
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
    let previewMode = false;
    let tool: "stitch" | "erase" | "fill" | "backstitch" | "part" | "knot" = "stitch";
    let partDirection: 1 | 2 | 3 | 4 = 1;
    let selectedPal = working.palette.find((x) => x.index > 0)?.index || 1;
    let hoverPal: number | null = null;
    let pendingBack: { x: number; y: number } | null = null;
    let painting = false;
    const MAX_HISTORY = 80;
    let undoStack: Normalized[] = [];
    let redoStack: Normalized[] = [];
    let strokeSnapshot: Normalized | null = null;

    const syncSizeInputs = () => {
      const wEl = document.getElementById("chartWidth") as HTMLInputElement | null;
      const hEl = document.getElementById("chartHeight") as HTMLInputElement | null;
      if (wEl) wEl.value = String(working.width_stitches);
      if (hEl) hEl.value = String(working.height_stitches);
    };

    const applyChartSize = (nextW: number, nextH: number) => {
      const w = Math.max(1, Math.min(800, Math.floor(nextW)));
      const h = Math.max(1, Math.min(800, Math.floor(nextH)));
      if (w === working.width_stitches && h === working.height_stitches) {
        syncSizeInputs();
        return;
      }
      const before = structuredClone(working);
      working.width_stitches = w;
      working.height_stitches = h;
      working.full_stitches = working.full_stitches.filter((s) => s.x < w && s.y < h);
      working.part_stitches = (working.part_stitches || []).filter((s) => s.x < w && s.y < h);
      working.backstitches = (working.backstitches || []).filter(
        (b) => b.x1 <= w && b.x2 <= w && b.y1 <= h && b.y2 <= h
      );
      working.ornaments = (working.ornaments || []).filter(
        (o) => o.x >= -1 && o.y >= -1 && o.x <= w + 1 && o.y <= h + 1
      );
      pushHistory(before);
      syncSizeInputs();
      setHint(`Chart size set to ${w}×${h}. Stitches outside the new bounds were removed.`);
      renderSupplyEstimates();
      redraw();
    };

    const chartFingerprint = (n: Normalized) =>
      [
        `${n.width_stitches}x${n.height_stitches}`,
        `fc:${n.fabric_count || 14}`,
        n.palette.map((p) => `${p.index}:${p.number}:${p.color}:${p.name}:${p.strands || 2}`).join(";"),
        [...n.full_stitches]
          .map((s) => `${s.x},${s.y},${s.palindex}`)
          .sort()
          .join(";"),
        [...(n.backstitches || [])]
          .map((b) => `${b.x1},${b.y1},${b.x2},${b.y2},${b.palindex}`)
          .sort()
          .join(";"),
        [...(n.part_stitches || [])]
          .map((s) => `${s.x},${s.y},${s.palindex1},${s.palindex2},${s.direction}`)
          .sort()
          .join(";"),
        [...(n.ornaments || [])]
          .map((o) => `${o.x},${o.y},${o.palindex},${o.objecttype}`)
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
      syncSizeInputs();
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
      for (const s of working.part_stitches || []) {
        if (s.palindex1 > 0) counts.set(s.palindex1, (counts.get(s.palindex1) || 0) + 1);
        if (s.palindex2 > 0) counts.set(s.palindex2, (counts.get(s.palindex2) || 0) + 1);
      }
      for (const o of working.ornaments || []) {
        if (o.palindex > 0) counts.set(o.palindex, (counts.get(o.palindex) || 0) + 1);
      }
      for (const b of working.backstitches || []) {
        if (b.palindex > 0) counts.set(b.palindex, (counts.get(b.palindex) || 0) + 1);
      }
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
          `/api/floss/nearest?hex=${encodeURIComponent(color)}`
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

    const deletePaletteColor = (palIndex: number) => {
      if (palIndex <= 0) return;
      const usable = working.palette.filter((p) => p.index > 0);
      if (usable.length <= 1) {
        alert("Keep at least one colour in the legend.");
        return;
      }
      const pal = working.palette.find((x) => x.index === palIndex);
      if (!pal) return;
      recount();
      const stitchCount = pal.stitch_count || 0;
      const backCount = (working.backstitches || []).filter((b) => b.palindex === palIndex).length;
      const label = pal.number || pal.name || `Colour ${palIndex}`;
      const detail =
        stitchCount || backCount
          ? ` This removes ${stitchCount} stitch${stitchCount === 1 ? "" : "es"}${
              backCount ? ` and ${backCount} backstitch${backCount === 1 ? "" : "es"}` : ""
            }.`
          : "";
      if (!confirm(`Delete ${label} from the legend?${detail}`)) return;
      const before = structuredClone(working);
      working.palette = working.palette.filter((p) => p.index !== palIndex);
      working.full_stitches = working.full_stitches.filter((s) => s.palindex !== palIndex);
      working.backstitches = (working.backstitches || []).filter((b) => b.palindex !== palIndex);
      working.part_stitches = (working.part_stitches || []).filter(
        (s) => s.palindex1 !== palIndex && s.palindex2 !== palIndex
      );
      working.ornaments = (working.ornaments || []).filter((o) => o.palindex !== palIndex);
      if (selectedPal === palIndex) {
        selectedPal = working.palette.find((p) => p.index > 0)?.index || 1;
      }
      if (hoverPal === palIndex) hoverPal = null;
      pushHistory(before);
      setHint(`Deleted ${label}`);
      renderLegend();
      redraw();
    };

    const fabricCountInput = document.getElementById("legendFabricCount") as HTMLInputElement | null;
    const fabricBorderInput = document.getElementById("legendFabricBorder") as HTMLInputElement | null;
    if (fabricCountInput) fabricCountInput.value = String(working.fabric_count || 14);
    let fabricBorderIn = 3;

    const renderSkeinEstimate = () => {
      const body = document.getElementById("skeinEstimateBody");
      if (!body) return;
      const fabricCount = Math.max(6, Math.min(40, Number(working.fabric_count) || 14));
      const rows = working.palette
        .filter((x) => x.index > 0 && (x.stitch_count || 0) > 0)
        .map((pal) => {
          const strands = Math.max(1, Math.min(6, Number(pal.strands) || 2));
          const needed = skeinsNeeded(pal.stitch_count || 0, fabricCount, strands);
          const label = pal.name && pal.name !== pal.number ? `${pal.number} ${pal.name}` : pal.number || pal.name;
          return `<tr>
              <td><span class="swatch" style="background:${hexColor(pal.color)}"></span></td>
              <td>${escapeHtml(label)}</td>
              <td class="num">${formatSkeins(needed)}</td>
            </tr>`;
        });
      if (!rows.length) {
        body.innerHTML = `<p class="meta">No stitches yet — estimates appear as you stitch.</p>`;
        return;
      }
      body.innerHTML = `<table class="skein-table">
          <tr><th></th><th>Colour</th><th>Skeins</th></tr>
          ${rows.join("")}
        </table>`;
    };

    const renderFabricSizeEstimate = () => {
      const body = document.getElementById("fabricSizeEstimateBody");
      if (!body) return;
      const wSt = working.width_stitches || 0;
      const hSt = working.height_stitches || 0;
      const currentCount = Math.max(6, Math.min(40, Number(working.fabric_count) || 14));
      const border = Math.max(0, Math.min(12, fabricBorderIn));
      if (fabricBorderInput) fabricBorderInput.value = String(border);
      if (wSt < 1 || hSt < 1) {
        body.innerHTML = `<p class="meta">Set a chart size to see fabric dimensions.</p>`;
        return;
      }
      const curW = fabricInches(wSt, currentCount);
      const curH = fabricInches(hSt, currentCount);
      const fabW = curW + 2 * border;
      const fabH = curH + 2 * border;
      body.innerHTML = `
        <p class="fabric-size-summary"><strong>${wSt} × ${hSt}</strong> stitches on <strong>${currentCount}-count</strong></p>
        <table class="skein-table fabric-size-table">
          <tr><th></th><th>Width</th><th>Height</th></tr>
          <tr><td>Stitched image</td><td class="num">${formatInches(curW)} (${formatCm(curW)})</td><td class="num">${formatInches(curH)} (${formatCm(curH)})</td></tr>
          <tr><td>Suggested fabric</td><td class="num">${formatInches(fabW)} (${formatCm(fabW)})</td><td class="num">${formatInches(fabH)} (${formatCm(fabH)})</td></tr>
        </table>`;
    };

    const renderSupplyEstimates = () => {
      renderSkeinEstimate();
      renderFabricSizeEstimate();
    };

    const renderLegend = () => {
      recount();
      const showSymCol = gridState.symbolMode !== "none";
      if (fabricCountInput) fabricCountInput.value = String(working.fabric_count || 14);
      legend.innerHTML = `<table class="legend-table"><tr><th></th>${
        showSymCol ? "<th>Sym</th>" : ""
      }<th>Code</th><th>Strands</th><th>Count</th></tr>${working.palette
        .filter((x) => x.index > 0)
        .map((pal) => {
          const mark = symbolForPalette(working.palette, pal.index);
          const strands = Math.max(1, Math.min(6, Number(pal.strands) || 2));
          return `<tr class="legend-row${editMode && pal.index === selectedPal ? " is-selected" : ""}" data-pal="${pal.index}">
              <td class="legend-swatch-cell">
                <span class="swatch" style="background:${hexColor(pal.color)}"></span>
                ${
                  editMode
                    ? `<button type="button" class="legend-edit" data-pal="${pal.index}" title="Edit colour" aria-label="Edit colour">✎</button>
                       <button type="button" class="legend-delete" data-pal="${pal.index}" title="Delete colour" aria-label="Delete colour">✕</button>`
                    : ""
                }
              </td>
              ${showSymCol ? `<td class="legend-sym">${escapeHtml(mark)}</td>` : ""}
              <td>${escapeHtml(pal.name && pal.name !== pal.number ? `${pal.number} ${pal.name}` : pal.number || pal.name)}</td>
              <td class="legend-strands-cell">
                <input type="number" class="legend-strands" data-pal="${pal.index}" min="1" max="6" step="1" value="${strands}" title="Strands for this colour" aria-label="Strands for ${escapeHtml(pal.number || pal.name || "colour")}" />
              </td>
              <td>${pal.stitch_count ?? ""}</td>
            </tr>`;
        })
        .join("")}</table>`;
      legend.querySelectorAll(".legend-row").forEach((row) => {
        const el = row as HTMLElement;
        row.addEventListener("click", (ev) => {
          if ((ev.target as HTMLElement).closest("input,button")) return;
          selectedPal = Number(el.dataset.pal);
          renderLegend();
        });
        row.addEventListener("mouseenter", () => {
          hoverPal = Number(el.dataset.pal);
          el.classList.add("is-hover");
          redraw();
        });
        row.addEventListener("mouseleave", () => {
          if (hoverPal === Number(el.dataset.pal)) hoverPal = null;
          el.classList.remove("is-hover");
          redraw();
        });
      });
      legend.querySelectorAll(".legend-strands").forEach((input) => {
        input.addEventListener("click", (ev) => ev.stopPropagation());
        input.addEventListener("change", () => {
          const el = input as HTMLInputElement;
          const palIndex = Number(el.dataset.pal);
          const pal = working.palette.find((x) => x.index === palIndex);
          if (!pal) return;
          const next = Math.max(1, Math.min(6, Math.round(Number(el.value) || 2)));
          if (pal.strands === next) {
            el.value = String(next);
            return;
          }
          const before = structuredClone(working);
          pal.strands = next;
          el.value = String(next);
          pushHistory(before);
          setHint(`${pal.number || pal.name}: ${next} strand${next === 1 ? "" : "s"}`);
          renderSupplyEstimates();
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
      legend.querySelectorAll(".legend-delete").forEach((btn) => {
        btn.addEventListener("click", (ev) => {
          ev.preventDefault();
          ev.stopPropagation();
          deletePaletteColor(Number((btn as HTMLElement).dataset.pal));
        });
      });
      renderSupplyEstimates();
    };

    fabricCountInput?.addEventListener("change", () => {
      const next = Math.max(6, Math.min(40, Math.round(Number(fabricCountInput.value) || 14)));
      if ((working.fabric_count || 14) === next) {
        fabricCountInput.value = String(next);
        return;
      }
      const before = structuredClone(working);
      working.fabric_count = next;
      fabricCountInput.value = String(next);
      pushHistory(before);
      setHint(`Fabric count set to ${next}`);
      renderSupplyEstimates();
    });

    fabricBorderInput?.addEventListener("change", () => {
      const next = Math.max(0, Math.min(12, Number(fabricBorderInput.value) || 0));
      fabricBorderIn = Math.round(next * 2) / 2;
      fabricBorderInput.value = String(fabricBorderIn);
      renderFabricSizeEstimate();
    });

    type ChartMode = "chart" | "edit" | "preview";
    let chartMode: ChartMode = "chart";

    const syncFabricUi = () => {
      document.querySelectorAll(".fabric-swatch").forEach((btn) => {
        const hex = ((btn as HTMLElement).dataset.colour || "").toLowerCase();
        btn.classList.toggle("active", hex === gridState.fabricColour.toLowerCase());
      });
      document.querySelectorAll(".texture-btn").forEach((btn) => {
        btn.classList.toggle("active", (btn as HTMLElement).dataset.texture === gridState.fabricTexture);
      });
      const custom = document.getElementById("fabricColourCustom") as HTMLInputElement | null;
      if (custom) custom.value = gridState.fabricColour;
    };

    const syncModeUi = () => {
      document.querySelectorAll(".mode-btn").forEach((btn) => {
        btn.classList.toggle("active", (btn as HTMLElement).dataset.mode === chartMode);
      });
      editTools.classList.toggle("is-hidden", chartMode !== "edit");
      document.getElementById("previewTools")?.classList.toggle("is-hidden", chartMode !== "preview");
      document.getElementById("saveChart")?.classList.toggle("is-hidden", chartMode !== "edit");
      document.getElementById("addColor")?.classList.toggle("is-hidden", chartMode !== "edit");
      canvas.classList.toggle("preview-mode", chartMode === "preview");
      document.getElementById("toggleSym")?.classList.toggle("is-disabled", chartMode === "preview");
      document.querySelector(".chart-panel")?.classList.toggle("is-editing", chartMode === "edit");
      if (chartMode === "preview") syncFabricUi();
    };

    const leaveEditMode = (discard: boolean) => {
      if (discard) {
        working = structuredClone(loaded);
        pendingBack = null;
        undoStack = [];
        redoStack = [];
        strokeSnapshot = null;
      }
      editMode = false;
      updateUndoRedoButtons();
    };

    const setChartMode = (mode: ChartMode) => {
      if (mode === chartMode) return;
      if (chartMode === "edit" && mode !== "edit") {
        const dirty = chartFingerprint(working) !== chartFingerprint(loaded);
        if (dirty && !confirm("Leave edit mode and discard unsaved changes?")) return;
        leaveEditMode(true);
      }
      if (mode === "edit") {
        previewMode = false;
        editMode = true;
        undoStack = [];
        redoStack = [];
        strokeSnapshot = null;
        updateUndoRedoButtons();
        setTool("stitch");
      } else if (mode === "preview") {
        previewMode = true;
        editMode = false;
      } else {
        previewMode = false;
        editMode = false;
      }
      chartMode = mode;
      syncModeUi();
      renderLegend();
      redraw();
    };

    const redraw = () =>
      drawGrid(canvas, working, { pendingBack, editMode, highlightPal: hoverPal, previewMode });
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
    const clearPartAt = (x: number, y: number) => {
      working.part_stitches = (working.part_stitches || []).filter((s) => !(s.x === x && s.y === y));
    };
    const setStitch = (x: number, y: number, palindex: number | null) => {
      if (x < 0 || y < 0 || x >= working.width_stitches || y >= working.height_stitches) return;
      working.full_stitches = working.full_stitches.filter((s) => !(s.x === x && s.y === y));
      clearPartAt(x, y);
      if (palindex && palindex > 0) working.full_stitches.push({ x, y, palindex });
    };
    /** Encode one of 4 half-cell triangle placements in Ursa OXS fields. */
    const encodeHalf = (colour: number, half: 0 | 1 | 2 | 3) => {
      // 0 BL, 1 TL, 2 TR, 3 BR
      if (half === 0) return { direction: 1 as const, palindex1: colour, palindex2: 0 };
      if (half === 1) return { direction: 2 as const, palindex1: colour, palindex2: 0 };
      if (half === 2) return { direction: 1 as const, palindex1: 0, palindex2: colour };
      return { direction: 2 as const, palindex1: 0, palindex2: colour };
    };
    const decodeHalf = (ps: { direction: number; palindex1: number; palindex2: number }, colour: number) => {
      const dir = ps.direction || 1;
      if (ps.palindex1 === colour && (!ps.palindex2 || ps.palindex2 <= 0)) return dir === 2 ? 1 : 0;
      if (ps.palindex2 === colour && (!ps.palindex1 || ps.palindex1 <= 0)) return dir === 2 ? 3 : 2;
      return null;
    };
    const nextPartDirection = (dir: number) => ((((dir || 1) % 4) + 1) as 1 | 2 | 3 | 4);
    const setPartStitch = (
      x: number,
      y: number,
      palindex: number,
      opts?: { rotateIfSame?: boolean; direction?: 1 | 2 | 3 | 4 }
    ) => {
      if (x < 0 || y < 0 || x >= working.width_stitches || y >= working.height_stitches) return;
      if (palindex <= 0) return;
      const rotateIfSame = opts?.rotateIfSame ?? true;
      const direction = opts?.direction ?? partDirection;
      working.full_stitches = working.full_stitches.filter((s) => !(s.x === x && s.y === y));
      working.part_stitches = working.part_stitches || [];
      const atCell = working.part_stitches.filter((s) => s.x === x && s.y === y);

      // Dual-colour cell: (A,B,\) → (A,B,/) → (B,A,\) → (B,A,/) → …
      const dual = atCell.find(
        (s) =>
          (s.direction === 1 || s.direction === 2) &&
          s.palindex1 > 0 &&
          s.palindex2 > 0 &&
          (s.palindex1 === palindex || s.palindex2 === palindex)
      );
      if (dual) {
        if (!rotateIfSame) return;
        if (dual.direction === 1) {
          dual.direction = 2;
        } else {
          const tmp = dual.palindex1;
          dual.palindex1 = dual.palindex2;
          dual.palindex2 = tmp;
          dual.direction = 1;
        }
        return;
      }

      // Single-colour half: cycle BL→TL→TR→BR via OXS left/right slots.
      const owned = atCell.find((s) => {
        if (s.direction === 3 || s.direction === 4) return s.palindex1 === palindex || s.palindex2 === palindex;
        return decodeHalf(s, palindex) != null;
      });
      if (owned) {
        if (!rotateIfSame) return;
        if (owned.direction === 3 || owned.direction === 4) {
          owned.direction = owned.direction === 3 ? 4 : 3;
          return;
        }
        const half = decodeHalf(owned, palindex);
        if (half == null) return;
        const next = encodeHalf(palindex, ((half + 1) % 4) as 0 | 1 | 2 | 3);
        owned.direction = next.direction;
        owned.palindex1 = next.palindex1;
        owned.palindex2 = next.palindex2;
        return;
      }

      // Add second colour into the complementary half of an existing single-colour triangle.
      const open = atCell.find((s) => {
        if (s.direction !== 1 && s.direction !== 2) return false;
        const only1 = s.palindex1 > 0 && (!s.palindex2 || s.palindex2 <= 0) && s.palindex1 !== palindex;
        const only2 = s.palindex2 > 0 && (!s.palindex1 || s.palindex1 <= 0) && s.palindex2 !== palindex;
        return only1 || only2;
      });
      if (open) {
        if (open.palindex1 > 0 && (!open.palindex2 || open.palindex2 <= 0)) open.palindex2 = palindex;
        else open.palindex1 = palindex;
        return;
      }

      // Fresh placement: map tool direction 1–4 onto the four triangle halves.
      const half = ((((direction || 1) - 1) % 4) as 0 | 1 | 2 | 3);
      const enc = encodeHalf(palindex, half);
      working.part_stitches.push({
        x,
        y,
        palindex1: enc.palindex1,
        palindex2: enc.palindex2,
        direction: enc.direction,
      });
    };
    const eraseOrnamentNear = (fx: number, fy: number) => {
      working.ornaments = (working.ornaments || []).filter((o) => Math.hypot(o.x - fx, o.y - fy) > 0.35);
    };
    const addKnotAt = (fx: number, fy: number) => {
      if (selectedPal <= 0) return;
      working.ornaments = working.ornaments || [];
      const dup = working.ornaments.some(
        (o) => o.objecttype === "knot" && Math.hypot(o.x - fx, o.y - fy) < 0.2 && o.palindex === selectedPal
      );
      if (!dup) working.ornaments.push({ x: fx, y: fy, palindex: selectedPal, objecttype: "knot" });
    };
    const palAt = (grid: Map<string, number>, x: number, y: number) => grid.get(stitchKey(x, y)) || 0;
    const bucketFill = (sx: number, sy: number, fillPal: number) => {
      const w = working.width_stitches;
      const h = working.height_stitches;
      if (sx < 0 || sy < 0 || sx >= w || sy >= h || fillPal <= 0) return 0;
      const grid = new Map<string, number>();
      for (const s of working.full_stitches) grid.set(stitchKey(s.x, s.y), s.palindex);
      const target = palAt(grid, sx, sy);
      if (target === fillPal) return 0;
      const stack: Array<[number, number]> = [[sx, sy]];
      const filled: Array<[number, number]> = [];
      const seen = new Set<string>();
      while (stack.length) {
        const [x, y] = stack.pop()!;
        const key = stitchKey(x, y);
        if (seen.has(key)) continue;
        seen.add(key);
        if (x < 0 || y < 0 || x >= w || y >= h) continue;
        if (palAt(grid, x, y) !== target) continue;
        filled.push([x, y]);
        stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
      }
      if (!filled.length) return 0;
      const replace = new Set(filled.map(([x, y]) => stitchKey(x, y)));
      working.part_stitches = (working.part_stitches || []).filter(
        (s) => !replace.has(stitchKey(s.x, s.y))
      );
      if (target === 0) {
        for (const [x, y] of filled) working.full_stitches.push({ x, y, palindex: fillPal });
      } else {
        for (const s of working.full_stitches) {
          if (replace.has(stitchKey(s.x, s.y))) s.palindex = fillPal;
        }
      }
      return filled.length;
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

    const setTool = (next: typeof tool) => {
      if (next === "part" && tool === "part") {
        partDirection = nextPartDirection(partDirection);
      } else {
        tool = next;
      }
      pendingBack = null;
      editTools.querySelectorAll(".tool-btn").forEach((b) => {
        b.classList.toggle("active", (b as HTMLElement).dataset.tool === tool);
      });
      if (tool === "fill") {
        setHint("Bucket fill: click a region to fill connected cells with the selected legend colour.");
      } else if (tool === "backstitch") {
        setHint("Backstitch snaps to grid corners.");
      } else if (tool === "part") {
        const corners = { 1: "BL", 2: "TL", 3: "TR", 4: "BR" } as const;
        setHint(
          `Partial stitch (start ${corners[partDirection]}). Click again to rotate (4 ways); a second colour fills the other half.`
        );
      } else if (tool === "knot") {
        setHint("French knot: click to place a knot in the selected colour.");
      } else if (tool === "erase") {
        setHint("Erase stitches, partials, knots, or click near a corner to remove backstitches.");
      } else {
        setHint("Click a legend colour, then paint.");
      }
      redraw();
    };

    renderLegend();
    syncModeUi();
    redraw();

    canvas.addEventListener("pointerdown", (ev) => {
      if (!editMode) {
        if (previewMode) return;
        const { x, y } = cellAt(ev);
        const key = stitchKey(x, y);
        if (gridState.marked.has(key)) gridState.marked.delete(key);
        else gridState.marked.add(key);
        redraw();
        void saveProgress(p.id, proj.status === "not_started" ? "in_progress" : proj.status);
        return;
      }
      if (tool === "backstitch") {
        painting = true;
        canvas.setPointerCapture(ev.pointerId);
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
      if (tool === "fill") {
        const { x, y } = cellAt(ev);
        const before = structuredClone(working);
        const n = bucketFill(x, y, selectedPal);
        if (n > 0) {
          pushHistory(before);
          setHint(`Filled ${n} cell${n === 1 ? "" : "s"} with selected colour.`);
          renderLegend();
          redraw();
        } else {
          setHint("Nothing to fill — same colour already, or click a cell.");
        }
        return;
      }
      if (tool === "knot") {
        const pos = canvasPos(ev);
        const before = structuredClone(working);
        addKnotAt(pos.x / gridState.zoom, pos.y / gridState.zoom);
        pushHistory(before);
        renderLegend();
        redraw();
        return;
      }
      painting = true;
      canvas.setPointerCapture(ev.pointerId);
      beginStroke();
      const { x, y } = cellAt(ev);
      if (tool === "erase") {
        setStitch(x, y, null);
        const pos = canvasPos(ev);
        eraseOrnamentNear(pos.x / gridState.zoom, pos.y / gridState.zoom);
        const c = cornerAt(ev);
        const near =
          Math.hypot(pos.x / gridState.zoom - c.x, pos.y / gridState.zoom - c.y) < 0.28;
        if (near) eraseBackNear(c);
      } else if (tool === "part") {
        setPartStitch(x, y, selectedPal, { rotateIfSame: true, direction: partDirection });
      } else {
        setStitch(x, y, selectedPal);
      }
      renderLegend();
      redraw();
    });
    canvas.addEventListener("pointermove", (ev) => {
      if (!editMode || !painting || tool === "backstitch" || tool === "fill" || tool === "knot") return;
      const { x, y } = cellAt(ev);
      if (tool === "erase") {
        setStitch(x, y, null);
        const pos = canvasPos(ev);
        eraseOrnamentNear(pos.x / gridState.zoom, pos.y / gridState.zoom);
      } else if (tool === "part") {
        // Drag places without spinning; click rotates.
        setPartStitch(x, y, selectedPal, { rotateIfSame: false, direction: partDirection });
      } else {
        setStitch(x, y, selectedPal);
      }
      redraw();
    });
    canvas.addEventListener("pointerup", () => {
      if (painting && editMode && tool !== "backstitch" && tool !== "fill" && tool !== "knot") {
        endStroke();
        renderLegend();
      }
      painting = false;
    });
    canvas.addEventListener("pointercancel", () => {
      if (painting && editMode && tool !== "backstitch" && tool !== "fill" && tool !== "knot") endStroke();
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
      if (previewMode) return;
      cycleSymbolMode();
      const btn = document.getElementById("toggleSym");
      if (btn) btn.textContent = symbolModeLabel();
      renderLegend();
      redraw();
    });
    document.getElementById("toggleCenterLines")?.addEventListener("click", () => {
      gridState.centerLines = !gridState.centerLines;
      sessionStorage.setItem("knitarr_center_lines", gridState.centerLines ? "1" : "0");
      const btn = document.getElementById("toggleCenterLines");
      if (btn) {
        btn.classList.toggle("active", gridState.centerLines);
        btn.setAttribute("aria-pressed", gridState.centerLines ? "true" : "false");
      }
      redraw();
    });
    document.querySelectorAll(".mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = (btn as HTMLElement).dataset.mode as ChartMode;
        if (mode) setChartMode(mode);
      });
    });
    const setFabricColour = (hex: string) => {
      const next = hexColor(hex).toLowerCase();
      gridState.fabricColour = next;
      sessionStorage.setItem("knitarr_fabric_colour", next);
      syncFabricUi();
      if (previewMode) redraw();
    };
    document.querySelectorAll(".fabric-swatch").forEach((btn) => {
      btn.addEventListener("click", () => {
        const hex = (btn as HTMLElement).dataset.colour;
        if (hex) setFabricColour(hex);
      });
    });
    document.getElementById("fabricColourCustom")?.addEventListener("input", (ev) => {
      setFabricColour((ev.target as HTMLInputElement).value);
    });
    document.querySelectorAll(".texture-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = (btn as HTMLElement).dataset.texture as FabricTexture;
        if (!FABRIC_TEXTURES.some((t) => t.id === id)) return;
        gridState.fabricTexture = id;
        sessionStorage.setItem("knitarr_fabric_texture", id);
        syncFabricUi();
        if (previewMode) redraw();
      });
    });
    document.getElementById("undoEdit")?.addEventListener("click", () => undoEdit());
    document.getElementById("redoEdit")?.addEventListener("click", () => redoEdit());
    const onSizeCommit = () => {
      const wEl = document.getElementById("chartWidth") as HTMLInputElement | null;
      const hEl = document.getElementById("chartHeight") as HTMLInputElement | null;
      if (!wEl || !hEl) return;
      applyChartSize(Number(wEl.value), Number(hEl.value));
    };
    document.getElementById("chartWidth")?.addEventListener("change", onSizeCommit);
    document.getElementById("chartHeight")?.addEventListener("change", onSizeCommit);
    syncSizeInputs();
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
        strands: 2,
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
            fabric_count: working.fabric_count || 14,
            palette: working.palette,
            full_stitches: working.full_stitches,
            backstitches: working.backstitches || [],
            part_stitches: working.part_stitches || [],
            ornaments: working.ornaments || [],
            symbol_mode: gridState.symbolMode,
          }),
        });
        loaded.full_stitches = structuredClone(working.full_stitches);
        loaded.backstitches = structuredClone(working.backstitches || []);
        loaded.part_stitches = structuredClone(working.part_stitches || []);
        loaded.ornaments = structuredClone(working.ornaments || []);
        loaded.palette = structuredClone(working.palette);
        loaded.width_stitches = working.width_stitches;
        loaded.height_stitches = working.height_stitches;
        loaded.fabric_count = working.fabric_count || 14;
        pendingBack = null;
        undoStack = [];
        redoStack = [];
        strokeSnapshot = null;
        leaveEditMode(false);
        chartMode = "chart";
        previewMode = false;
        syncModeUi();
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

async function renderAbout() {
  shell(`
    <div class="panel about-panel">
      <h2 style="margin:0">About Knitarr</h2>
      <p class="meta" id="aboutBlurb">Loading…</p>
      <dl class="about-meta">
        <div><dt>Version</dt><dd id="aboutVersion">…</dd></div>
        <div><dt>Updates</dt><dd id="aboutUpdates">Checking…</dd></div>
      </dl>
      <p class="meta is-hidden" id="aboutLatestNote"></p>
      <p id="aboutDownload" class="about-download is-hidden"></p>
    </div>
  `);

  const blurb = document.getElementById("aboutBlurb");
  const verEl = document.getElementById("aboutVersion");
  const updEl = document.getElementById("aboutUpdates");
  const noteEl = document.getElementById("aboutLatestNote");
  const dlEl = document.getElementById("aboutDownload");

  try {
    type AboutInfo = {
      name: string;
      version: string;
      description: string;
      github_repo?: string | null;
      update_available: boolean;
      release_check: string;
      latest?: {
        version: string;
        name?: string;
        url?: string;
        published_at?: string | null;
        note?: string;
      } | null;
    };
    const info = await api<AboutInfo>("/api/about");
    if (blurb) blurb.textContent = info.description;
    if (verEl) verEl.textContent = info.version;
    if (!updEl || !dlEl || !noteEl) return;

    if (info.release_check === "unconfigured") {
      updEl.textContent = "Release channel not configured.";
      noteEl.classList.remove("is-hidden");
      noteEl.textContent =
        "Set KNITARR_GITHUB_REPO (owner/repo) to check GitHub for newer Knitarr releases.";
      return;
    }
    if (info.release_check === "unavailable" || !info.latest) {
      updEl.textContent = "Could not check for updates right now.";
      return;
    }
    if (info.latest.note) {
      noteEl.classList.remove("is-hidden");
      noteEl.textContent = info.latest.note;
    }
    if (info.update_available) {
      updEl.innerHTML = `Newer release available: <strong>${escapeHtml(info.latest.version)}</strong>`;
      if (info.latest.url) {
        dlEl.classList.remove("is-hidden");
        dlEl.innerHTML = `<a class="primary-link" href="${escapeHtml(
          info.latest.url
        )}" target="_blank" rel="noopener">Download ${escapeHtml(info.latest.version)}</a>`;
      }
    } else {
      updEl.textContent = `You’re up to date (latest: ${info.latest.version}).`;
    }
  } catch (e) {
    if (blurb) blurb.textContent = "Knitarr is a self-hosted cross-stitch pattern library.";
    if (verEl) verEl.textContent = "unknown";
    if (updEl) updEl.textContent = String(e);
  }
}

function render() {
  syncRoute();
  if (view === "pattern") return renderPattern();
  if (view === "library") return renderLibrary();
  if (view === "settings_indexers") return renderIndexers();
  if (view === "settings_file_associations") return renderFileAssociations();
  if (view === "settings_supplies") return renderSupplies();
  if (view === "settings_about") return renderAbout();
  return renderSearch();
}

window.addEventListener("hashchange", () => {
  if (syncingRoute) return;
  const before = `${view}:${selectedPatternId ?? ""}:${librarySection}`;
  applyRouteFromLocation();
  const after = `${view}:${selectedPatternId ?? ""}:${librarySection}`;
  if (before !== after) render();
});

render();
