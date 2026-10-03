type View = "search" | "wanted" | "library" | "pattern";

interface ExternalHit {
  indexer_id: string;
  external_id: string;
  title: string;
  designer?: string;
  description?: string;
  source_url: string;
  license_class: string;
  redistribution_allowed: boolean;
  thumbnail_url?: string;
  metadata?: { licenseurl?: string };
}

interface PatternSummary {
  id: number;
  title: string;
  designer?: string;
  license_class: string;
  pattern_format: string;
  thumbnail_url?: string;
  width_stitches?: number;
  height_stitches?: number;
  color_count?: number;
}

interface PatternDetail extends PatternSummary {
  description?: string;
  source_url?: string;
  has_normalized: boolean;
  project_status?: string;
  file_count: number;
}

interface Normalized {
  format: string;
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
}

const app = document.getElementById("app")!;
let view: View = "search";
let selectedPatternId: number | null = null;
let gridState = {
  zoom: 16,
  showSymbols: false,
  marked: new Set<string>(),
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || r.statusText);
  }
  return r.json() as Promise<T>;
}

function shell(content: string) {
  app.innerHTML = `
    <header>
      <h1>Knitarr</h1>
      <nav>
        <button data-view="search" class="${view === "search" ? "active" : ""}">Search</button>
        <button data-view="wanted" class="${view === "wanted" ? "active" : ""}">Wanted</button>
        <button data-view="library" class="${view === "library" ? "active" : ""}">Library</button>
      </nav>
    </header>
    <main>${content}</main>
  `;
  app.querySelectorAll("nav button").forEach((btn) => {
    btn.addEventListener("click", () => {
      view = (btn as HTMLButtonElement).dataset.view as View;
      selectedPatternId = null;
      render();
    });
  });
}

function hitCard(hit: ExternalHit): string {
  const thumb = hit.thumbnail_url
    ? `<img src="${hit.thumbnail_url}" alt="" loading="lazy" />`
    : `<div style="height:140px;background:#ddd"></div>`;
  return `
    <article class="card" data-ext="${hit.indexer_id}|${hit.external_id}">
      ${thumb}
      <div class="card-body">
        <h3>${escapeHtml(hit.title)}</h3>
        <div class="meta">${escapeHtml(hit.designer || "Unknown")}</div>
        <div style="margin-top:0.5rem;display:flex;gap:0.35rem;flex-wrap:wrap">
          <button class="secondary btn-wanted">Add to Wanted</button>
          <a class="secondary" href="${hit.source_url}" target="_blank" rel="noopener">Open Source</a>
        </div>
      </div>
    </article>
  `;
}

function patternCard(p: PatternSummary): string {
  const thumb = p.thumbnail_url
    ? `<img src="${p.thumbnail_url}" alt="" loading="lazy" />`
    : `<div style="height:140px;background:#ddd;display:flex;align-items:center;justify-content:center;color:#888">${p.pattern_format.toUpperCase()}</div>`;
  return `
    <article class="card" data-pid="${p.id}">
      ${thumb}
      <div class="card-body">
        <h3>${escapeHtml(p.title)}</h3>
        <div class="meta">${p.width_stitches || "?"}×${p.height_stitches || "?"} · ${p.color_count ?? "?"} colours</div>
      </div>
    </article>
  `;
}

function escapeHtml(s: string) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
}

async function renderSearch() {
  shell(`
    <div class="panel">
      <div class="search-row">
        <input type="search" id="q" placeholder="e.g. dog cross stitch" value="" />
        <button class="primary" id="doSearch">Search Internet Archive</button>
        <button class="secondary" id="importSample">Import sample OXS</button>
      </div>
      <p class="meta">Searches cross-stitch items on Internet Archive via documented APIs.</p>
    </div>
    <div id="results" class="card-grid"></div>
  `);
  const results = document.getElementById("results")!;
  document.getElementById("doSearch")!.addEventListener("click", async () => {
    const q = (document.getElementById("q") as HTMLInputElement).value;
    results.innerHTML = `<p class="meta">Searching…</p>`;
    try {
      const data = await api<{ results: ExternalHit[] }>(
        `/api/search?q=${encodeURIComponent(q)}&limit=24`
      );
      if (!data.results.length) {
        results.innerHTML = `<p class="empty">No results.</p>`;
        return;
      }
      results.innerHTML = data.results.map(hitCard).join("");
      bindHitCards(results);
    } catch (e) {
      results.innerHTML = `<p class="empty">${escapeHtml(String(e))}</p>`;
    }
  });
  document.getElementById("importSample")!.addEventListener("click", async () => {
    try {
      const r = await api<{ pattern_id?: number; duplicate_of?: number; message: string }>(
        "/api/import/sample-oxs",
        { method: "POST" }
      );
      alert(r.message);
      if (r.pattern_id) {
        selectedPatternId = r.pattern_id;
        view = "pattern";
        render();
      }
    } catch (e) {
      alert(String(e));
    }
  });
}

function bindHitCards(root: HTMLElement) {
  root.querySelectorAll(".card[data-ext]").forEach((card) => {
    card.addEventListener("click", (ev) => {
      if ((ev.target as HTMLElement).closest("button, a")) return;
      const [indexer_id, external_id] = (card as HTMLElement).dataset.ext!.split("|");
      showExternalDetail(indexer_id, external_id);
    });
    card.querySelector(".btn-wanted")?.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const [indexer_id, external_id] = (card as HTMLElement).dataset.ext!.split("|");
      try {
        await api("/api/wanted", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ indexer_id, external_id }),
        });
        alert("Added to Wanted — background worker will download when available.");
      } catch (e) {
        alert(String(e));
      }
    });
  });
}

async function showExternalDetail(indexer_id: string, external_id: string) {
  const d = await api<ExternalHit & { download_available?: boolean; all_files?: string[] }>(
    `/api/external/${indexer_id}/${external_id}`
  );
  shell(`
    <div class="panel">
      <button class="secondary" id="back">← Back</button>
      <h2>${escapeHtml(d.title)}</h2>
      <p class="meta">${escapeHtml(d.designer || "")}${d.metadata?.licenseurl ? ` · <a href="${d.metadata.licenseurl}" target="_blank" rel="noopener">source license</a>` : ""}</p>
      <p>${escapeHtml(d.description || "")}</p>
      <div style="display:flex;gap:0.5rem;margin-top:0.75rem">
        <button class="primary" id="addW">Add to Wanted</button>
        <a class="secondary" href="${d.source_url}" target="_blank">Open on Archive.org</a>
      </div>
      ${d.all_files?.length ? `<pre class="meta" style="white-space:pre-wrap;margin-top:1rem">${d.all_files.slice(0, 8).join("\n")}</pre>` : ""}
    </div>
  `);
  document.getElementById("back")!.addEventListener("click", () => {
    view = "search";
    render();
  });
  document.getElementById("addW")!.addEventListener("click", async () => {
    await api("/api/wanted", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ indexer_id, external_id }),
    });
    alert("Added to Wanted");
  });
}

async function renderWanted() {
  const items = await api<
    {
      id: number;
      status: string;
      title: string;
      external_id: string;
      indexer_id: string;
      error?: string;
      pattern_id?: number;
    }[]
  >("/api/wanted");
  shell(`
    <div class="panel"><h2>Wanted</h2><p class="meta">Background worker checks every ~15s.</p></div>
    ${
      items.length
        ? `<div class="panel">${items
            .map(
              (w) => `
          <div style="padding:0.5rem 0;border-bottom:1px solid var(--border)">
            <strong>${escapeHtml(w.title)}</strong>
            <span class="badge">${w.status}</span>
            ${w.pattern_id ? `<button class="secondary btn-open" data-pid="${w.pattern_id}">View #${w.pattern_id}</button>` : ""}
            ${w.error ? `<div class="meta">${escapeHtml(w.error)}</div>` : ""}
          </div>`
            )
            .join("")}</div>`
        : `<p class="empty">Nothing wanted yet.</p>`
    }
  `);
  app.querySelectorAll(".btn-open").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedPatternId = Number((btn as HTMLButtonElement).dataset.pid);
      view = "pattern";
      render();
    });
  });
}

async function renderLibrary() {
  const patterns = await api<PatternSummary[]>("/api/patterns?downloaded=true");
  shell(`
    <div class="panel"><h2>Downloaded patterns</h2></div>
    <div class="card-grid">${patterns.length ? patterns.map(patternCard).join("") : `<p class="empty">Library empty — search and add to Wanted, or import sample OXS.</p>`}</div>
  `);
  app.querySelectorAll(".card[data-pid]").forEach((card) => {
    card.addEventListener("click", () => {
      selectedPatternId = Number((card as HTMLElement).dataset.pid);
      view = "pattern";
      render();
    });
  });
}

function hexColor(raw: string) {
  const h = raw.replace("#", "");
  if (h.length === 6) return `#${h}`;
  return "#cccccc";
}

function drawGrid(canvas: HTMLCanvasElement, norm: Normalized) {
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
    const col = pal ? hexColor(pal.color) : "#ccc";
    ctx.fillStyle = col;
    ctx.fillRect(s.x * cell, s.y * cell, cell, cell);
    if (gridState.showSymbols && pal?.symbol) {
      ctx.fillStyle = "#000";
      ctx.font = `${Math.max(8, cell - 4)}px sans-serif`;
      ctx.fillText(pal.symbol, s.x * cell + 2, s.y * cell + cell - 2);
    }
    const key = `${s.x},${s.y}`;
    if (gridState.marked.has(key)) {
      ctx.strokeStyle = "rgba(0,128,0,0.7)";
      ctx.lineWidth = 2;
      ctx.strokeRect(s.x * cell + 1, s.y * cell + 1, cell - 2, cell - 2);
    }
  }

  ctx.strokeStyle = "#e0e0e0";
  ctx.lineWidth = 1;
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
}

async function renderPattern() {
  if (!selectedPatternId) {
    view = "library";
    return render();
  }
  const p = await api<PatternDetail>(`/api/patterns/${selectedPatternId}`);
  const files = await api<{ id: number; filename: string; mime_type: string }[]>(
    `/api/patterns/${selectedPatternId}/files`
  );
  let viewerHtml = "";
  if (p.has_normalized) {
    viewerHtml = `
      <div class="toolbar">
        <button class="secondary" id="zoomOut">−</button>
        <button class="secondary" id="zoomIn">+</button>
        <button class="secondary" id="toggleSym">Symbols</button>
        <button class="secondary" id="startProj">Start project</button>
        <button class="secondary" id="finishProj">Mark finished</button>
      </div>
      <div class="viewer-layout">
        <div><canvas id="gridCanvas"></canvas></div>
        <div class="legend panel"><h3>Legend</h3><div id="legendBody"></div></div>
      </div>`;
  } else if (p.pattern_format === "pdf" && files[0]) {
    const url = `/api/patterns/${selectedPatternId}/file/${files[0].id}`;
    viewerHtml = `<iframe class="pdf-frame" src="${url}" title="PDF"></iframe>`;
  } else if (files.length) {
    const imgs = files.filter((f) => f.mime_type?.startsWith("image/"));
    if (imgs.length) {
      viewerHtml = `
        <div class="toolbar">
          <button class="secondary" id="imgOut">Zoom out</button>
          <button class="secondary" id="imgIn">Zoom in</button>
        </div>
        <div class="image-viewer" id="imgBox">
          ${imgs.map((f, i) => `<img data-idx="${i}" src="/api/patterns/${selectedPatternId}/file/${f.id}" alt="page" />`).join("")}
        </div>`;
    }
  }

  shell(`
    <div class="panel">
      <button class="secondary" id="backLib">← Library</button>
      <h2>${escapeHtml(p.title)}</h2>
      <p class="meta">${p.pattern_format.toUpperCase()} · ${p.license_class} · ${p.source_url ? `<a href="${p.source_url}" target="_blank">source</a>` : ""}</p>
      <p>${escapeHtml(p.description || "")}</p>
    </div>
    <div class="panel">${viewerHtml || `<p class="empty">No viewer for this format.</p>`}</div>
  `);

  document.getElementById("backLib")!.addEventListener("click", () => {
    view = "library";
    render();
  });

  if (p.has_normalized) {
    const norm = await api<Normalized>(`/api/patterns/${selectedPatternId}/normalized`);
    const proj = await api<{ status: string; progress_json: { marked?: string[] } }>(
      `/api/patterns/${selectedPatternId}/project`
    );
    gridState.marked = new Set(proj.progress_json?.marked || []);
    const canvas = document.getElementById("gridCanvas") as HTMLCanvasElement;

    const legend = document.getElementById("legendBody")!;
    legend.innerHTML = `<table><tr><th></th><th>Code</th><th>Count</th></tr>${norm.palette
      .filter((x) => x.index > 0)
      .map(
        (pal) =>
          `<tr><td><span class="swatch" style="background:${hexColor(pal.color)}"></span></td><td>${escapeHtml(pal.number)}</td><td>${pal.stitch_count ?? ""}</td></tr>`
      )
      .join("")}</table>`;

    const redraw = () => drawGrid(canvas, norm);
    redraw();

    canvas.addEventListener("click", (ev) => {
      const rect = canvas.getBoundingClientRect();
      const cell = gridState.zoom;
      const x = Math.floor((ev.clientX - rect.left) / cell);
      const y = Math.floor((ev.clientY - rect.top) / cell);
      const key = `${x},${y}`;
      if (gridState.marked.has(key)) gridState.marked.delete(key);
      else gridState.marked.add(key);
      redraw();
      saveProgress(p.id, proj.status === "not_started" ? "in_progress" : proj.status);
    });

    async function saveProgress(id: number, status: string) {
      await api(`/api/patterns/${id}/project`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          status,
          progress_json: { marked: [...gridState.marked] },
        }),
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
      gridState.showSymbols = !gridState.showSymbols;
      redraw();
    });
    document.getElementById("startProj")!.addEventListener("click", () => saveProgress(p.id, "in_progress"));
    document.getElementById("finishProj")!.addEventListener("click", () => saveProgress(p.id, "finished"));
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
  if (view === "wanted") return renderWanted();
  if (view === "library") return renderLibrary();
  return renderSearch();
}

render();
