"""How each page of the corpus was read, and therefore how far to trust it.

**A quoted clause is only as good as the reading that produced it.** 43 of the
corpus's pages come from a publisher's own text layer and are verbatim by
construction. The rest were read off photocopied scans by a recogniser that is
right about 97% of the time per line — which is very good, and still means a
statute page will occasionally contain a wrong character. A wrong character in
`8 mm` is a confident, specific, wrong notice served on a manufacturer.

So the corpus records, per page, how the text was obtained, and every chunk
carries it forward. Tier 1 can then quote text-layer clauses plainly and mark
OCR'd ones for verification against the page image. The alternative — a corpus
that presents both identically — is the overclaiming this project's own
provenance register warns about: *"an earlier register wrote 'read' against a
document that had only been sampled."*

`scripts/ingest_gazettes.py` writes the manifest this reads.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "rulebook" / "manifest.json"

TEXT_LAYER = "text-layer"
OCR = "ocr"
NOT_READ = "not-read"

QUOTABLE = frozenset({TEXT_LAYER})
"""Sources that may be quoted without a verification caveat.

OCR is deliberately not in this set. It is good enough to search, good enough
to point an officer at the right provision, and not good enough to reproduce as
the words of a statute in a document that may be served.
"""


@lru_cache(maxsize=1)
def _manifest() -> dict[str, dict[int, str]]:
    """`{doc_id: {page: source}}`, empty when the corpus has not been ingested.

    A missing manifest is not an error. The repository ships the hand-verified
    primary source, and someone working only on the rules engine has no reason
    to have run a five-hour OCR pass.
    """
    if not MANIFEST.exists():
        return {}
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    by_document: dict[str, dict[int, str]] = {}
    for row in payload.get("pages", ()):
        by_document.setdefault(row["doc_id"], {})[int(row["page"])] = row["source"]
    return by_document


def sources_for(doc_id: str) -> dict[int, str]:
    return _manifest().get(doc_id, {})


def describe(source: str) -> str:
    """The caveat a reader needs, or nothing when none is needed."""
    if source == OCR:
        return "Machine-read from a scanned gazette. Verify against the page before citing."
    if source == NOT_READ:
        return "Held but not machine-readable."
    return ""


def reset_cache() -> None:
    """Tests build manifests on disk; the cache would outlive them."""
    _manifest.cache_clear()


__all__ = [
    "MANIFEST",
    "NOT_READ",
    "OCR",
    "QUOTABLE",
    "TEXT_LAYER",
    "describe",
    "reset_cache",
    "sources_for",
]
