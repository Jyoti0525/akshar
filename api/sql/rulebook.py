"""The two halves of tier 2, as Postgres queries. AKSHAR.md §15.

    "**Lexical:** Postgres native `tsvector` with `english` config. No new
     dependency"

`retrieval/search.py` owns the orchestration and takes these as callables, so
this module is the only place that knows tier 2 is backed by a database at all.

**`websearch_to_tsquery`, not `to_tsquery`.** The input is an officer's free
text. `to_tsquery` requires the caller to build a boolean expression and raises
a syntax error on a bare phrase — a question mark is enough to make it fail —
which turns a slightly odd query into a 500. `websearch_to_tsquery` accepts
what people actually type, handles quoted phrases, and cannot raise.

**No index is consulted, and both queries are sequential scans by design.** See
the comment on `rule_chunks` in `db/schema.sql`: at five thousand rows an index
costs more to maintain than the scan costs to run, and §15 sized the problem
before choosing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

LEXICAL_SQL = """
    SELECT key
      FROM rule_chunks
     WHERE tsv @@ websearch_to_tsquery('english', :query)
     ORDER BY ts_rank_cd(tsv, websearch_to_tsquery('english', :query)) DESC, key
     LIMIT :limit
"""

DENSE_SQL = """
    SELECT key
      FROM rule_chunks
     WHERE embedding IS NOT NULL
     ORDER BY embedding <=> CAST(:vector AS vector), key
     LIMIT :limit
"""

FETCH_SQL = """
    SELECT key, doc_id, ref, parent_ref, heading, text, page, kind, source
      FROM rule_chunks
     WHERE key = ANY(:keys)
"""

COUNT_SQL = "SELECT count(*) AS rows, count(embedding) AS vectors FROM rule_chunks"


def _literal(vector) -> str:
    """pgvector's text input form. Built here rather than by string formatting
    at the call site so the only place a vector becomes SQL text is one line."""
    return "[" + ",".join(f"{float(v):.6f}" for v in vector) + "]"


class SqlRulebook:
    """Tier-2 retrieval over `rule_chunks`."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    # -- retrievers, shaped for `retrieval.search.search` -------------------

    def lexical(self, query: str, limit: int) -> list[str]:
        from sqlalchemy import text as sql

        with self._engine.connect() as conn:
            rows = conn.execute(sql(LEXICAL_SQL), {"query": query, "limit": limit})
            return [row[0] for row in rows]

    def dense(self, query: str, limit: int) -> list[str]:
        """Encode the question, then scan. Returns nothing if no model is loaded.

        An empty list is a valid dense half — `fuse` handles it and the caller
        reports the degradation — so a missing model degrades tier 2 rather
        than failing the request.
        """
        from retrieval import embed

        try:
            vector = embed.shared().encode_query(query)
        except embed.EmbedderUnavailableError:
            return []

        from sqlalchemy import text as sql

        with self._engine.connect() as conn:
            rows = conn.execute(sql(DENSE_SQL), {"vector": _literal(vector), "limit": limit})
            return [row[0] for row in rows]

    def fetch(self, keys: Sequence[str]) -> Mapping[str, Mapping[str, Any]]:
        if not keys:
            return {}
        from sqlalchemy import text as sql

        with self._engine.connect() as conn:
            rows = conn.execute(sql(FETCH_SQL), {"keys": list(keys)})
            return {row.key: dict(row._mapping) for row in rows}

    # -- health ------------------------------------------------------------

    def counts(self) -> tuple[int, int]:
        """`(rows, rows_with_a_vector)` — what a health endpoint needs to say
        whether tier 2 is whole, lexical-only, or not loaded at all."""
        from sqlalchemy import text as sql

        with self._engine.connect() as conn:
            row = conn.execute(sql(COUNT_SQL)).one()
            return int(row.rows), int(row.vectors)


__all__ = ["COUNT_SQL", "DENSE_SQL", "FETCH_SQL", "LEXICAL_SQL", "SqlRulebook"]
