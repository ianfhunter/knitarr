export type YarnCraft = "crochet" | "knitting";

export interface YarnSupplies {
  terminology: string;
  hook_size: string;
  needle_size: string;
  yarn: string;
  yarn_amount: string;
  gauge: string;
  notions: string;
  notes: string;
}

export interface YarnDoc {
  format: string;
  craft?: string;
  title: string;
  dialect: string;
  lines: string[];
  supplies?: YarnSupplies;
  warnings: string[];
}

function addLineControl(): string {
  return `
    <div class="yarn-add-line-wrap">
      <button type="button" class="yarn-add-line-btn" id="yarnAddLine" title="Add line" aria-label="Add line">+</button>
    </div>`;
}

export function emptySupplies(terminology = "US"): YarnSupplies {
  return {
    terminology,
    hook_size: "",
    needle_size: "",
    yarn: "",
    yarn_amount: "",
    gauge: "",
    notions: "",
    notes: "",
  };
}

export function normalizeSupplies(raw?: Partial<YarnSupplies> | null, dialect?: string): YarnSupplies {
  const base = emptySupplies(dialect === "UK" ? "UK" : dialect === "unknown" ? "unknown" : "US");
  if (!raw) return base;
  return {
    terminology: raw.terminology || base.terminology,
    hook_size: raw.hook_size || "",
    needle_size: raw.needle_size || "",
    yarn: raw.yarn || "",
    yarn_amount: raw.yarn_amount || "",
    gauge: raw.gauge || "",
    notions: raw.notions || "",
    notes: raw.notes || "",
  };
}

export function renderLineEditors(lines: string[], editable: boolean): string {
  if (!lines.length) {
    return `<p class="meta yarn-empty">No instruction lines yet. Extract from PDF or add a line below.</p>${addLineControl()}`;
  }
  if (!editable) {
    return (
      lines
        .map(
          (line, i) => `
    <div class="yarn-line yarn-line-view">
      <span class="yarn-line-num">${i + 1}</span>
      <p class="yarn-line-text">${escapeHtml(line)}</p>
    </div>`
        )
        .join("") + addLineControl()
    );
  }
  return (
    lines
      .map(
        (line, i) => `
    <div class="yarn-line yarn-line-edit" data-line-row="${i}">
      <span class="yarn-line-num">${i + 1}</span>
      <textarea class="yarn-line-input" data-line="${i}" rows="2">${escapeAttr(line)}</textarea>
    </div>`
      )
      .join("") + addLineControl()
  );
}

export function readLinesFromDom(root: ParentNode): string[] {
  const inputs = [...root.querySelectorAll<HTMLTextAreaElement>(".yarn-line-input")];
  if (inputs.length) {
    return inputs
      .sort((a, b) => Number(a.dataset.line) - Number(b.dataset.line))
      .map((el) => el.value.trim())
      .filter(Boolean);
  }
  return [...root.querySelectorAll<HTMLElement>(".yarn-line-text")]
    .map((el) => (el.textContent || "").trim())
    .filter(Boolean);
}

export function renderSupplies(supplies: YarnSupplies, craft: YarnCraft): string {
  const term = supplies.terminology || "US";
  const toolField =
    craft === "knitting"
      ? `<label class="yarn-supply-field">
        <span class="yarn-supply-label">Needle size</span>
        <input type="text" id="yarnSupplyNeedles" placeholder="e.g. 4.0 mm / US 6" value="${escapeAttr(
          supplies.needle_size
        )}" />
      </label>`
      : `<label class="yarn-supply-field">
        <span class="yarn-supply-label">Hook size</span>
        <input type="text" id="yarnSupplyHook" placeholder="e.g. 4.0 mm / G-6" value="${escapeAttr(
          supplies.hook_size
        )}" />
      </label>`;
  const gaugePh =
    craft === "knitting" ? "e.g. 22 sts × 30 rows = 10 cm" : "e.g. 16 sc × 18 rows = 10 cm";
  return `
    <div class="yarn-supplies-fields">
      <label class="yarn-supply-field">
        <span class="yarn-supply-label">Terminology</span>
        <select id="yarnSupplyTerminology">
          <option value="US"${term === "US" ? " selected" : ""}>US</option>
          <option value="UK"${term === "UK" ? " selected" : ""}>UK</option>
          <option value="unknown"${term === "unknown" ? " selected" : ""}>Unknown</option>
        </select>
      </label>
      ${toolField}
      <label class="yarn-supply-field">
        <span class="yarn-supply-label">Yarn / wool</span>
        <input type="text" id="yarnSupplyYarn" placeholder="e.g. DK weight wool" value="${escapeAttr(
          supplies.yarn
        )}" />
      </label>
      <label class="yarn-supply-field">
        <span class="yarn-supply-label">Amount needed</span>
        <input type="text" id="yarnSupplyAmount" placeholder="e.g. 100 g / 2 skeins" value="${escapeAttr(
          supplies.yarn_amount
        )}" />
      </label>
      <label class="yarn-supply-field">
        <span class="yarn-supply-label">Gauge / tension</span>
        <input type="text" id="yarnSupplyGauge" placeholder="${escapeAttr(gaugePh)}" value="${escapeAttr(
          supplies.gauge
        )}" />
      </label>
      <label class="yarn-supply-field">
        <span class="yarn-supply-label">Notions</span>
        <input type="text" id="yarnSupplyNotions" placeholder="e.g. stitch markers, tapestry needle" value="${escapeAttr(
          supplies.notions
        )}" />
      </label>
      <label class="yarn-supply-field">
        <span class="yarn-supply-label">Notes</span>
        <textarea id="yarnSupplyNotes" rows="3" placeholder="Other materials or notes">${escapeAttr(
          supplies.notes
        )}</textarea>
      </label>
    </div>`;
}

export function readSuppliesFromDom(craft: YarnCraft, root: ParentNode = document): YarnSupplies {
  const val = (id: string) =>
    (root.querySelector(`#${id}`) as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement | null)
      ?.value?.trim() || "";
  return {
    terminology: val("yarnSupplyTerminology") || "US",
    hook_size: craft === "crochet" ? val("yarnSupplyHook") : "",
    needle_size: craft === "knitting" ? val("yarnSupplyNeedles") : "",
    yarn: val("yarnSupplyYarn"),
    yarn_amount: val("yarnSupplyAmount"),
    gauge: val("yarnSupplyGauge"),
    notions: val("yarnSupplyNotions"),
    notes: val("yarnSupplyNotes"),
  };
}

export function apiBase(craft: YarnCraft): string {
  return craft === "knitting" ? "knitting" : "crochet";
}

function escapeHtml(s: string) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s: string) {
  return escapeHtml(s);
}
