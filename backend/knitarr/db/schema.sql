PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS indexers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    access_method TEXT NOT NULL,
    auth_required TEXT NOT NULL DEFAULT 'none',
    automated_access_policy TEXT NOT NULL,
    default_license_class TEXT NOT NULL,
    can_download INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS external_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    indexer_id TEXT NOT NULL REFERENCES indexers(id),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    designer TEXT,
    source_url TEXT NOT NULL,
    pattern_url TEXT,
    description TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    license_class TEXT NOT NULL,
    redistribution_allowed INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT NOT NULL,
    UNIQUE (indexer_id, external_id)
);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_release_id INTEGER REFERENCES external_releases(id),
    title TEXT NOT NULL,
    designer TEXT,
    source TEXT,
    source_url TEXT,
    pattern_url TEXT,
    download_url TEXT,
    craft TEXT NOT NULL DEFAULT 'cross_stitch',
    description TEXT,
    difficulty TEXT,
    width_stitches INTEGER,
    height_stitches INTEGER,
    stitch_count INTEGER,
    fabric_type TEXT,
    fabric_count INTEGER,
    floss_brand TEXT,
    color_count INTEGER,
    estimated_finished_size TEXT,
    pattern_format TEXT NOT NULL DEFAULT 'unknown',
    language TEXT,
    publication_date TEXT,
    license_class TEXT NOT NULL,
    redistribution_allowed INTEGER NOT NULL DEFAULT 0,
    owned INTEGER NOT NULL DEFAULT 0,
    downloaded INTEGER NOT NULL DEFAULT 0,
    checksum_sha256 TEXT,
    structure_fingerprint TEXT,
    version TEXT,
    date_discovered TEXT NOT NULL,
    date_downloaded TEXT,
    thumbnail_path TEXT,
    normalized_path TEXT,
    pattern_group_id INTEGER
);

CREATE TABLE IF NOT EXISTS wanted_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_release_id INTEGER NOT NULL REFERENCES external_releases(id),
    status TEXT NOT NULL DEFAULT 'wanted',
    added_at TEXT NOT NULL,
    last_checked_at TEXT,
    error TEXT,
    pattern_id INTEGER REFERENCES patterns(id)
);

CREATE TABLE IF NOT EXISTS pattern_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'original',
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT,
    checksum_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS pattern_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS pattern_tag_map (
    pattern_id INTEGER NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES pattern_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (pattern_id, tag_id)
);

CREATE TABLE IF NOT EXISTS dedupe_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id_a INTEGER NOT NULL REFERENCES patterns(id),
    pattern_id_b INTEGER NOT NULL REFERENCES patterns(id),
    score REAL NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id INTEGER NOT NULL UNIQUE REFERENCES patterns(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'not_started',
    progress_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT,
    finished_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_patterns_checksum ON patterns(checksum_sha256);
CREATE INDEX IF NOT EXISTS idx_patterns_structure_fp ON patterns(structure_fingerprint);
CREATE INDEX IF NOT EXISTS idx_wanted_status ON wanted_items(status);
