"""Load the gazette corpus into `rule_chunks` for tier-2 search. AKSHAR.md §15.

    python -m scripts.index_corpus              # chunk, embed, upsert
    python -m scripts.index_corpus --no-vectors # lexical half only
    python -m scripts.index_corpus --stats      # report, write nothing

**The lexical half does not need the model.** `tsv` is a generated column, so
inserting rows is enough to make BM25-style search work; the embedding is a
separate column that can be filled later or never. `--no-vectors` exists
because a deployment with no weights should still get tier 2's lexical half
rather than nothing, which is the same degradation ladder §5 applies elsewhere.

**Chunks are embedded as `heading + text`, which is exactly what `tsv`
indexes.** If the two halves saw different strings they would be searching
different corpora, and RRF would be fusing rankings over documents that are not
the same documents. Keeping them identical is not a detail.

**Idempotent.** Re-running replaces rows by `key`, so re-ingesting a gazette or
fixing a chunker bug is a re-run rather than a migration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from retrieval import embed  # noqa: E402
from retrieval.citations import CitationIndex  # noqa: E402

BATCH = 64
"""Passages per ONNX call. Large enough that per-call overhead disappears,
small enough that a 512-token batch stays well inside cache."""


def corpus() -> list:
    index = CitationIndex.from_directory()
    return [chunk for group in index.chunks.values() for chunk in group]


def passage_text(chunk) -> str:
    """What both retrievers see. Mirrors `rule_chunks.tsv`'s expression."""
    return f"{chunk.heading} {chunk.text}".strip()


def _row_key(chunk, seen: dict[str, int]) -> str:
    """A key unique to the *row*, which is not the same as the citation.

    `doc_id::ref` is the citation identity, and it is deliberately not unique:
    a gazette may print two clauses under one number (tier 1 surfaces that as
    `ambiguous`), and the General Rules is a compendium whose every Part
    restarts at "1. Scope", so 2,763 of 5,086 chunks share a reference with
    another.

    Keying rows on the citation therefore made `ON CONFLICT DO UPDATE` collapse
    them: 5,172 chunks went in and 2,341 rows came out, with no error and no
    warning. Tier 2 would have been searching a corpus missing more than half
    its clauses. The ordinal suffix keeps the row identity distinct while
    `(doc_id, ref)` stays the citation.
    """
    base = f"{chunk.doc_id}::{chunk.ref.lower()}"
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}#{count + 1}"


def upsert(engine, chunks: list, vectors) -> int:
    from sqlalchemy import text as sql

    statement = sql(
        """
        INSERT INTO rule_chunks
            (key, doc_id, ref, parent_ref, heading, text, page, kind, source, embedding)
        VALUES
            (:key, :doc_id, :ref, :parent_ref, :heading, :text, :page, :kind, :source,
             CAST(:embedding AS vector))
        ON CONFLICT (key) DO UPDATE SET
            doc_id = EXCLUDED.doc_id, ref = EXCLUDED.ref,
            parent_ref = EXCLUDED.parent_ref, heading = EXCLUDED.heading,
            text = EXCLUDED.text, page = EXCLUDED.page, kind = EXCLUDED.kind,
            source = EXCLUDED.source, embedding = EXCLUDED.embedding
        """
    )
    rows = []
    seen: dict[str, int] = {}
    for position, chunk in enumerate(chunks):
        vector = None
        if vectors is not None:
            vector = "[" + ",".join(f"{v:.6f}" for v in vectors[position]) + "]"
        rows.append(
            {
                "key": _row_key(chunk, seen),
                "doc_id": chunk.doc_id,
                "ref": chunk.ref,
                "parent_ref": chunk.parent_ref,
                "heading": chunk.heading,
                "text": chunk.text,
                "page": chunk.page,
                "kind": chunk.kind,
                "source": chunk.source,
                "embedding": vector,
            }
        )
    # Rows the corpus no longer contains must go, in the same transaction.
    # Upsert alone leaves the previous run's output behind: re-indexing after
    # the chunker stopped emitting 86 spurious "rule 0" chunks left all 86 in
    # the table, searchable, with the run reporting success. Idempotent has to
    # mean the table equals the corpus, not that it has absorbed it.
    prune = sql("DELETE FROM rule_chunks WHERE key <> ALL(:keys)")

    with engine.begin() as conn:
        for start in range(0, len(rows), 500):
            conn.execute(statement, rows[start : start + 500])
        removed = conn.execute(prune, {"keys": [r["key"] for r in rows]}).rowcount
    if removed:
        print(f"  pruned {removed} rows no longer in the corpus")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-vectors", action="store_true", help="skip the dense half")
    parser.add_argument("--stats", action="store_true", help="report only")
    args = parser.parse_args(argv)

    chunks = corpus()
    if not chunks:
        print("No corpus. Run scripts/ingest_gazettes.py first.", file=sys.stderr)
        return 1

    documents = {c.doc_id for c in chunks}
    ocr = sum(1 for c in chunks if c.source == "ocr")
    print(f"{len(chunks)} chunks across {len(documents)} documents")
    print(f"  {len(chunks) - ocr} from a publisher's text layer, {ocr} machine-read")
    state = embed.availability()
    print(f"  embedder: {state.detail}")
    if args.stats:
        return 0

    vectors = None
    if not args.no_vectors:
        if not state.ready:
            print(
                f"  no embedder ({state.detail}); writing the lexical half only. "
                f"Tier 2 will run BM25-only until this is fixed.",
                file=sys.stderr,
            )
        else:
            import numpy as np

            encoder = embed.shared()
            batches = []
            for start in range(0, len(chunks), BATCH):
                window = chunks[start : start + BATCH]
                batches.append(encoder.encode_passages([passage_text(c) for c in window]))
                print(f"\r  embedding {min(start + BATCH, len(chunks))}/{len(chunks)}", end="")
            vectors = np.vstack(batches)
            print()

    from api.sql.engine import get_engine

    engine = get_engine()
    if engine is None:
        print(
            "No database. Set AKSHAR_STORAGE=sql and AKSHAR_DATABASE_URL, "
            "or start it with `docker compose up -d db`.",
            file=sys.stderr,
        )
        return 1

    written = upsert(engine, chunks, vectors)
    print(f"Wrote {written} rows to rule_chunks" + ("" if vectors is not None else " (no vectors)"))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
