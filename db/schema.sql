-- ============================================================================
-- AKSHAR — schema, AKSHAR.md section 10.
--
-- Transcribed from the plan, with the column comments the plan argues for in
-- prose. Alembic owns migrations (db/migrations); this file is the readable
-- reference and what `docker compose` initialises a fresh database from, so
-- the two must not drift. `tests/unit/test_schema.py` asserts they agree.
--
-- THE ONE RULE THIS FILE ENFORCES ABOVE ALL OTHERS
--
--   "Images never go in the database. A Postgres row holding a 3 MB blob
--    wrecks query performance, backup times and replication."   -- section 6
--
-- `scans.image_key` is a MinIO object key. There is no BYTEA column anywhere in
-- this schema and there must never be one.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector 0.8, section 15b


-- ---------------------------------------------------------------------------
-- users — three roles, section 12
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email         TEXT NOT NULL UNIQUE,
  full_name     TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK (role IN ('officer', 'supervisor', 'admin')),
  district      TEXT,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- ---------------------------------------------------------------------------
-- skus — the repository that makes "never pay twice for the same label" work
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS skus (
  id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  brand        TEXT NOT NULL,

  -- Parent company. Lay's, Kurkure and Uncle Chipps are separate brands and one
  -- company, and "a legal notice is addressed to the parent" (section 11). This
  -- single column is what turns the dashboard from a list into an
  -- investigation tool.
  brand_group  TEXT,

  variant      TEXT,

  -- Part of IDENTITY, not metadata — see the unique constraint below.
  pack_size    TEXT NOT NULL,

  category     TEXT NOT NULL,     -- food | cosmetic | cement | electronics | ...
  barcode      TEXT,

  -- 64-bit perceptual hash. BIT(64) rather than BIGINT because Hamming distance
  -- is the query (section 4: <= 8 bits), and bit strings say what this is.
  phash        BIT(64),

  -- MobileNetV3-Small 576-d reduced to 512-d by a SHIPPED PCA matrix. The
  -- matrix is an artifact, never refitted at runtime: refitting would silently
  -- move every stored vector into a different space.
  embedding    VECTOR(512),

  -- Physical label dimensions, which is what scale tier B reads back. "The more
  -- the system has seen, the less it needs the marker" (section 17, M2).
  label_w_mm   NUMERIC,
  label_h_mm   NUMERIC,

  scan_count   INT NOT NULL DEFAULT 0,
  first_seen   TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Section 10: "`pack_size` sits inside the unique constraint because 30 g and
  -- 100 g of the same product have DIFFERENT HEIGHT THRESHOLDS. Treat them as
  -- one SKU and violations vanish silently, with no error to tell you."
  --
  -- Rule 7(2) Table I is keyed on net quantity: <=200 g needs 1 mm numerals,
  -- <=500 g needs 2 mm. Collapsing two pack sizes into one row would judge the
  -- 500 g pack against the 200 g threshold and pass a violation.
  CONSTRAINT skus_identity_unique UNIQUE (brand, variant, pack_size)
);


-- ---------------------------------------------------------------------------
-- scans — immutable facts. Nothing is ever updated in place.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scans (
  -- Client-generated UUIDv7. Time-ordered, so it doubles as a sort key, and
  -- client-generated so an offline outbox can replay idempotently: the same
  -- scan arriving twice is the same primary key, not a duplicate row.
  id               UUID PRIMARY KEY,

  sku_id           UUID REFERENCES skus(id),
  officer_id       UUID REFERENCES users(id),
  district         TEXT,

  -- ADDITIVE, see docs/spec-deltas.md D16. The category the rules were
  -- EVALUATED under, which is not always the SKU's category and is not always
  -- known: an unmatched scan has no sku_id at all. It is stored because it
  -- gates which rules may lawfully be applied (PackageContext.category), so a
  -- verdict cannot be reproduced without it — and section 14 is explicit that
  -- "a finding you cannot reproduce is a finding you cannot defend". It is
  -- also what lets the categories view (section 11, Q4) cover scans that never
  -- matched a SKU.
  category         TEXT,

  source           TEXT NOT NULL
                     CHECK (source IN ('photo', 'bulk_image', 'listing_text')),
  degradation_tier TEXT NOT NULL
                     CHECK (degradation_tier IN ('L0', 'L1', 'L2', 'L3', 'L4')),

  -- A MinIO object key. NEVER the image itself. See the header.
  image_key        TEXT,
  image_sha256     CHAR(64),

  -- ADDITIVE. One entry per photograph when an officer photographed the same
  -- package from several angles: `{frame, exit_path, read, image_key,
  -- image_sha256, stored}`. NULL for the single-frame scan, which is what
  -- `image_key` above already describes in full.
  --
  -- NULL rather than an empty array on purpose. The hash chain covers whatever
  -- keys the payload carries, so a single-frame row that started carrying a
  -- `frames` key would hash differently from every single-frame row already
  -- chained. `_payload_from_row` therefore omits the key when the column is
  -- NULL, and every record written before this column existed still verifies.
  --
  -- The per-frame digests are here rather than in a side table because section
  -- 6 requires the photograph's digest to be INSIDE the chain, and the chain
  -- covers this row. Several photographs, several digests, one chained record.
  frames           JSONB,

  declaration_set  JSONB NOT NULL,
  coverage         NUMERIC,

  -- Stored so our performance claims come from production data rather than a
  -- benchmark we ran once (section 10).
  latency_ms       INT,
  cache_hit        BOOLEAN,

  -- Reduced precision, set by AKSHAR_GEO_PRECISION_DP. "Enough to identify a
  -- market, not a doorway" — section 18, and officer location is personal data
  -- under the DPDP Act 2023.
  geo              POINT,

  captured_at      TIMESTAMPTZ NOT NULL,
  synced_at        TIMESTAMPTZ,

  -- Reproducibility, section 14: "a finding you cannot reproduce is a finding
  -- you cannot defend." A measurement disputed six months later is re-run with
  -- exactly these versions.
  model_versions   JSONB NOT NULL,
  rulepack_version TEXT NOT NULL,

  -- Hash chain, section 6. `chain_seq` is assigned SERVER-SIDE on arrival
  -- because "offline clients cannot possibly agree on ordering among
  -- themselves" (section 5).
  record_sha256    CHAR(64) NOT NULL,
  prev_sha256      CHAR(64),
  chain_seq        BIGINT UNIQUE
);


-- ---------------------------------------------------------------------------
-- verdicts — one row per rule evaluated, not per rule failed
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS verdicts (
  id       BIGSERIAL PRIMARY KEY,
  scan_id  UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  rule_id  TEXT NOT NULL,          -- "LMPC.MRP.HEIGHT"
  rule_ref TEXT NOT NULL,          -- "Rule 7(2), Table I" — the gazette citation
  status   TEXT NOT NULL
             CHECK (status IN ('PASS', 'FAIL', 'NOT_APPLICABLE', 'REVIEW', 'NO_DATA')),
  severity TEXT NOT NULL CHECK (severity IN ('high', 'medium', 'low')),
  field    TEXT,
  found    TEXT,
  expected TEXT,

  -- ADDITIVE, see docs/spec-deltas.md D18. Everything below is on
  -- contracts.Verdict already; without it here, a verdict cannot survive a
  -- round trip through the database, and section 11's dashboard counts the
  -- wrong things.
  message  TEXT NOT NULL DEFAULT '',

  -- Section 13: the five unit-symbol checks are formatting defects and render
  -- in a SEPARATE advisory block. Lose this column and "violations by rule"
  -- reports that India's biggest labelling problem is capitalising the litre
  -- symbol, while a missing MRP sits below it.
  advisory BOOLEAN NOT NULL DEFAULT FALSE,

  -- Set when another rule measured the same thing and won. One measurement
  -- yields ONE verdict; counting both inflates every rate on the dashboard.
  suppressed_by TEXT,

  -- Rule 18(5) is the RETAILER's offence, not the manufacturer's. The notice
  -- goes to a different person, so the report has to say which.
  respondent TEXT NOT NULL DEFAULT 'manufacturer'
               CHECK (respondent IN ('manufacturer', 'packer', 'importer', 'dealer')),

  -- What was measured, against what, with what tolerance. Section 14: "a
  -- finding you cannot reproduce is a finding you cannot defend" — and a
  -- height verdict without its millimetres is not reproducible.
  measured  NUMERIC,
  threshold NUMERIC,
  tolerance NUMERIC
);

-- PASS and NOT_APPLICABLE rows are stored too, deliberately. The rules view
-- audits our own rulepack — "a rule failing on 95% of products is more likely a
-- bug in our regex than a national conspiracy" (section 11) — and that ratio
-- cannot be computed from failures alone.


-- ---------------------------------------------------------------------------
-- corrections — append-only, so they cannot conflict
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS corrections (
  id         BIGSERIAL PRIMARY KEY,
  scan_id    UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  box_index  INT,
  from_field TEXT,
  to_field   TEXT,
  officer_id UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Section 5: "There is no conflict resolution, by design. Scans are immutable
-- facts. Corrections are append-only rows, never edits. Nothing is ever updated
-- in place, so nothing can conflict."
--
-- This is also the training loop: every row here is a labelled example, and the
-- labelling is done by people already doing the job.


-- ---------------------------------------------------------------------------
-- review_resolutions — what a human decided where the rulepack would not
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_resolutions (
  id          BIGSERIAL PRIMARY KEY,
  scan_id     UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  rule_id     TEXT NOT NULL,
  decision    TEXT NOT NULL,     -- complies | does_not_comply | recapture
  officer_id  UUID NOT NULL REFERENCES users(id),
  note        TEXT NOT NULL DEFAULT '',
  resolved_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_review_resolutions_scan ON review_resolutions (scan_id);

-- Section 8b: "every REVIEW verdict lands there, one-click resolve, resolution
-- stored as a labelled example for retraining."
--
-- Three decisions, not two. Section 8b issues REVIEW when a measurement lands
-- inside tolerance of a threshold -- 1.96 mm against a 2.00 mm minimum -- and
-- the correct answer to that is frequently neither verdict but "photograph it
-- again with the card flat". Forcing that into complies/does_not_comply would
-- put a coin-flip into an enforcement record and then feed the coin-flip back
-- into training.
--
-- Deliberately NOT unique on (scan_id, rule_id), and deliberately never
-- updated. A supervisor revisiting a call writes a second row; the first one
-- stating what they concluded at the time is the record, and rewriting it would
-- destroy the only evidence that they concluded something else first. The queue
-- reads the distinct set of resolved rule ids, so a repeat is idempotent there.
--
-- The verdict this resolves is NOT touched. It lives inside the scan record
-- whose SHA-256 is in the evidence chain, so an UPDATE would make verify_chain()
-- fail at that row -- and it would be right to.


-- ---------------------------------------------------------------------------
-- access_log — who LOOKED, as distinct from who COULD look
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS access_log (
  id        BIGSERIAL PRIMARY KEY,
  user_id   UUID REFERENCES users(id),
  action    TEXT NOT NULL,       -- view | export | download_evidence | ...
  entity    TEXT NOT NULL,       -- scan | sku | report | summary
  entity_id TEXT,
  ip        INET,
  at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Section 18: "Role-based access says who CAN see something. An audit log
-- records who DID. The hash chain protects records from alteration but says
-- nothing about who read them — and in an enforcement context, who looked at a
-- pending case is exactly the question that eventually gets asked."


-- ---------------------------------------------------------------------------
-- bulk_jobs — a receipt for an upload nobody is waiting on
-- ---------------------------------------------------------------------------
--
-- ADDITIVE, see docs/spec-deltas.md D17. Section 8c puts bulk ingestion on the
-- low-priority queue precisely because the officer has gone home, which means
-- the request returns before any of the work happens and there has to be
-- something to poll.
--
-- The counters are separate columns rather than a derived count over `scans`
-- because a FAILED image produces no scan row at all — an unreadable file, a
-- PDF someone dropped in the folder — and a job whose progress is computed from
-- the rows it managed to create can never reach its total. That is a hang with
-- no error, which is the worst thing to hand a district office at 9 pm.

CREATE TABLE IF NOT EXISTS bulk_jobs (
  id          UUID PRIMARY KEY,
  officer_id  UUID REFERENCES users(id),
  total       INT NOT NULL,
  completed   INT NOT NULL DEFAULT 0,
  failed      INT NOT NULL DEFAULT 0,

  -- Text shown to a person: "brochure.pdf: upload is not a decodable image".
  -- A traceback belongs in the worker's log, not on an officer's screen.
  errors      JSONB NOT NULL DEFAULT '[]'::jsonb,

  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,

  CONSTRAINT bulk_jobs_counts_fit CHECK (completed + failed <= total)
);

-- Which scans a job produced. A separate table rather than an array column so
-- the foreign key is real: a scan cannot be deleted out from under the receipt
-- that claims it.
CREATE TABLE IF NOT EXISTS bulk_job_scans (
  job_id  UUID NOT NULL REFERENCES bulk_jobs(id) ON DELETE CASCADE,
  scan_id UUID NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  PRIMARY KEY (job_id, scan_id)
);


-- ---------------------------------------------------------------------------
-- Indexes — section 10's five, plus the one section 15b argues for separately
-- ---------------------------------------------------------------------------

-- SKU near-duplicate search. Section 15b: "Here an index IS justified: SKU
-- count grows without bound, unlike the rule corpus."
--
-- The rule corpus gets NO index — 1,700 vectors are ~1.3 ms by sequential scan
-- and an HNSW build costs more than brute force takes to run. That asymmetry is
-- deliberate and is worth being able to explain.
CREATE INDEX IF NOT EXISTS skus_embedding_hnsw
  ON skus USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS skus_phash_idx        ON skus (phash);
CREATE INDEX IF NOT EXISTS skus_brand_group_idx  ON skus (brand_group, category);
CREATE INDEX IF NOT EXISTS verdicts_rule_idx     ON verdicts (rule_id, status);

-- Section 11 counts only verdicts that are neither advisory nor suppressed, so
-- the partial index matches the query the dashboard actually runs rather than
-- the one the column list suggests.
CREATE INDEX IF NOT EXISTS verdicts_countable_idx
  ON verdicts (rule_id, status)
  WHERE NOT advisory AND suppressed_by IS NULL;
CREATE INDEX IF NOT EXISTS scans_district_idx    ON scans (district, captured_at DESC);

-- Not in section 10's list, but the barcode lookup endpoint is "the fastest
-- path to a cache hit we have" (section 12) and would otherwise scan the table.
CREATE INDEX IF NOT EXISTS skus_barcode_idx ON skus (barcode) WHERE barcode IS NOT NULL;

-- Chain verification walks in sequence order.
CREATE INDEX IF NOT EXISTS scans_chain_seq_idx ON scans (chain_seq);

-- The review queue is a worklist someone owes work to (section 8c), so it is
-- queried constantly and must not scan.
CREATE INDEX IF NOT EXISTS verdicts_review_idx
  ON verdicts (scan_id) WHERE status = 'REVIEW';

-- An officer polls their own jobs; a supervisor lists a district's.
CREATE INDEX IF NOT EXISTS bulk_jobs_officer_idx ON bulk_jobs (officer_id, created_at DESC);


-- ---------------------------------------------------------------------------
-- rule_chunks — tier 2 hybrid search over the gazette corpus (section 15)
--
-- One row per clause-level chunk. `key` is the tier-1 lookup key, so a hit
-- found by search resolves to exactly the citation an officer would have
-- reached by tapping "why" on a verdict — the two tiers cannot disagree about
-- what a reference means.
--
-- NO INDEX ON `embedding`, DELIBERATELY. Section 15: "Exact cosine over 1,700
-- vectors takes about 1.3 ms on CPU. An HNSW or IVF index would take longer to
-- build than brute force takes to run." The corpus is now 5,172 chunks rather
-- than the 1,700 the plan sized, which moves the scan to a few milliseconds
-- and leaves the conclusion intact.
--
-- NO GIN INDEX ON `tsv` either, for the same reason and not by oversight. The
-- vector is a STORED generated column, so it is computed once at write and the
-- query only matches it; at this row count a GIN index is maintenance cost
-- against an unmeasurable gain.
--
-- The tsvector uses the two-argument `to_tsvector` with an explicit 'english'
-- config: the one-argument form depends on `default_text_search_config` and is
-- therefore only STABLE, which a generated column will not accept.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS rule_chunks (
  key        TEXT PRIMARY KEY,
  doc_id     TEXT NOT NULL,
  ref        TEXT NOT NULL,
  parent_ref TEXT,
  heading    TEXT NOT NULL DEFAULT '',
  text       TEXT NOT NULL,
  page       INTEGER NOT NULL,
  kind       TEXT NOT NULL,
  source     TEXT NOT NULL,
  embedding  vector(384),
  tsv        tsvector GENERATED ALWAYS AS (to_tsvector('english', heading || ' ' || text)) STORED
);

CREATE INDEX IF NOT EXISTS rule_chunks_doc_idx ON rule_chunks (doc_id);
