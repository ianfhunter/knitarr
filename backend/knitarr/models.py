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


class WantedStatus(StrEnum):
    WANTED = "wanted"
    SEARCHING = "searching"
    DOWNLOADING = "downloading"
    IMPORTED = "imported"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class ProjectStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class PatternFormat(StrEnum):
    OXS = "oxs"
    PDF = "pdf"
    IMAGE = "image"
    UNKNOWN = "unknown"


class IndexerCapabilities(BaseModel):
    source: str
    access_method: str
    authentication: str
    automated_access_policy: str
    license_default: LicenseClass
    can_download: bool


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
    results: list[ExternalHit]
    total_hint: int | None = None


class WantedCreate(BaseModel):
    indexer_id: str
    external_id: str


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
