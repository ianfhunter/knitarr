from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LicenseClass(StrEnum):
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    CC0 = "CC0"
    CREATIVE_COMMONS = "CREATIVE_COMMONS"
    FREE_WITH_RESTRICTIONS = "FREE_WITH_RESTRICTIONS"
    FREE_DOWNLOAD_NONREDISTRIBUTABLE = "FREE_DOWNLOAD_NONREDISTRIBUTABLE"
    PURCHASE_REQUIRED = "PURCHASE_REQUIRED"
    UNKNOWN = "UNKNOWN"
    USER_OWNED = "USER_OWNED"


class ProjectStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class PatternFormat(StrEnum):
    OXS = "oxs"
    PDF = "pdf"
    IMAGE = "image"
    XPS = "xps"
    SAGA = "saga"
    XSP = "xsp"
    UNKNOWN = "unknown"


class IndexerStatus(StrEnum):
    ACTIVE = "active"
    INDEX_ONLY = "index_only"
    PLANNED = "planned"


class IndexerCapabilities(BaseModel):
    source: str
    access_method: str
    authentication: str
    automated_access_policy: str
    license_default: LicenseClass
    can_download: bool
    status: IndexerStatus = IndexerStatus.ACTIVE
    site_url: str = ""
    description: str = ""
    search_enabled: bool = True


class CraftFilesUpdate(BaseModel):
    label: str | None = None
    extensions: list[str] | None = None
    enabled: bool | None = None


class SuppliesUpdate(BaseModel):
    floss_brand: str | None = Field(
        default=None,
        description="Preferred embroidery floss brand id (e.g. dmc, anchor)",
    )


class IndexerCraftUpdate(BaseModel):
    craft_id: str
    enabled: bool


class ExternalHit(BaseModel):
    indexer_id: str
    external_id: str
    title: str
    designer: str | None = None
    description: str | None = None
    source_url: str
    pattern_url: str | None = None
    craft: str = "cross_stitch"
    license_class: LicenseClass = LicenseClass.UNKNOWN
    redistribution_allowed: bool = False
    thumbnail_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalDetail(ExternalHit):
    download_available: bool = False
    suggested_filename: str | None = None
    all_files: list[str] = Field(default_factory=list)


class DownloadSpec(BaseModel):
    url: str
    filename: str
    all_urls: list[tuple[str, str]] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str
    indexer_id: str
    craft: str
    results: list[ExternalHit]
    total_hint: int | None = None


class ImportFromIndexer(BaseModel):
    indexer_id: str
    external_id: str
    craft: str = "cross_stitch"


class PatternSummary(BaseModel):
    id: int
    title: str
    designer: str | None
    source: str | None
    source_url: str | None
    craft: str
    license_class: LicenseClass
    redistribution_allowed: bool
    pattern_format: PatternFormat
    downloaded: bool
    width_stitches: int | None
    height_stitches: int | None
    color_count: int | None
    thumbnail_url: str | None
    date_discovered: str | None
    date_downloaded: str | None


class PatternDetail(PatternSummary):
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    difficulty: str | None = None
    fabric_type: str | None = None
    fabric_count: int | None = None
    floss_brand: str | None = None
    checksum_sha256: str | None = None
    has_normalized: bool = False
    project_status: ProjectStatus | None = None
    file_count: int = 0


class ProjectUpdate(BaseModel):
    status: ProjectStatus | None = None
    progress_json: dict[str, Any] | None = None


class ImportResult(BaseModel):
    pattern_id: int | None
    duplicate_of: int | None = None
    message: str


class CropRect(BaseModel):
    """Normalized crop region (0–1) relative to full raster / PDF first page."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    def clamped(self) -> "CropRect":
        x = max(0.0, min(1.0, self.x))
        y = max(0.0, min(1.0, self.y))
        w = max(0.01, min(1.0 - x, self.w))
        h = max(0.01, min(1.0 - y, self.h))
        return CropRect(x=x, y=y, w=w, h=h)


class ConvertChartRequest(BaseModel):
    crop: CropRect | None = None
    pdf_page: int | None = Field(default=None, ge=1, description="1-based PDF page for conversion")
    symbol_mode: str | None = Field(
        default=None,
        description="Chart symbol mode: none|alphabet|numbers|symbols|alt",
    )


class RegeneratePackageRequest(BaseModel):
    symbol_mode: str | None = Field(
        default=None,
        description="Chart symbol mode for Chart Export.pdf / preview",
    )


class PatternUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class BlankPatternRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    width: int = Field(default=20, ge=1, le=800)
    height: int = Field(default=20, ge=1, le=800)
    craft: str = "cross_stitch"


class FileRenameRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=200)


class PaletteItemIn(BaseModel):
    index: int
    number: str = ""
    name: str = ""
    color: str
    symbol: str | None = None
    strands: int = Field(default=2, ge=1, le=6)


class FullStitchIn(BaseModel):
    x: int
    y: int
    palindex: int


class BackstitchIn(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    palindex: int


class PartStitchIn(BaseModel):
    x: int
    y: int
    palindex1: int = 0
    palindex2: int = 0
    direction: int = Field(default=1, ge=1, le=4)
    major: int | None = None


class OrnamentIn(BaseModel):
    x: float
    y: float
    palindex: int
    objecttype: str = "knot"
    direction: int | None = None


class ChartSaveRequest(BaseModel):
    title: str | None = None
    width_stitches: int = Field(ge=1, le=800)
    height_stitches: int = Field(ge=1, le=800)
    fabric_count: int | None = Field(default=None, ge=6, le=40)
    palette: list[PaletteItemIn]
    full_stitches: list[FullStitchIn]
    backstitches: list[BackstitchIn] = Field(default_factory=list)
    part_stitches: list[PartStitchIn] = Field(default_factory=list)
    ornaments: list[OrnamentIn] = Field(default_factory=list)
    symbol_mode: str | None = None
