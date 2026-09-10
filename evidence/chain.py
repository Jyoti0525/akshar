"""M7 — the hash chain over scan records. AKSHAR.md sections 6 and 10.

    "Canonical JSON, SHA-256, chained to the previous record; photo hashed at
     upload into MinIO. Done when: `verify_chain()` detects any tampered
     historical record."                                  -- section 17, M7

    "Why not blockchain? A hash chain gives identical tamper-evidence.
     Blockchain solves trust between mutually distrusting parties; the
     department is sole authority over its own records."   -- section 20

**What this actually protects.** A Legal Metrology violation can lead to
compounding or prosecution. If a manufacturer disputes a 1.8 mm measurement six
months later, the department must be able to show that the record has not been
edited since it was written — including by the department. A chain does that
with two SHA-256 calls and one column, and it is checkable by anyone holding the
rows, with no server involved.

It is **tamper-evident, not tamper-proof.** Anyone with write access can rewrite
a record; what they cannot do is rewrite it without every subsequent record's
hash failing. Say that plainly rather than overclaiming — the audit trail for
*who* touched what is `access_log`, which is a different mechanism for a
different question (section 18).

---

### The three things that make a chain either work or quietly not

**1. Canonicalisation, or the chain is decorative.** Two servers must hash the
same record to the same bytes. `json.dumps` with default settings does not
guarantee that: key order follows insertion, and `NaN` is emitted as a bare
token that is not legal JSON at all. So keys are sorted, separators are fixed,
non-finite floats are refused rather than serialised, and every datetime is
normalised to UTC. Get this wrong and verification fails on records nobody
touched, which is worse than no chain — a false alarm teaches people to ignore
the alarm.

**2. The link must be inside the hash.** `prev_sha256` is hashed *with* the
payload, not merely stored beside it. If it were only stored, two records could
be swapped and each would still hash correctly on its own.

**3. `chain_seq` is assigned by the server, never the client.**

    "Hash-chain sequencing is assigned server-side on arrival, because offline
     clients cannot possibly agree on ordering among themselves."  -- section 5

An officer in a market with no signal has no idea what the previous record was.
The client supplies a UUIDv7 — time-ordered, so replay is idempotent — and the
server supplies the position in the chain. Both are in the hash.

---

### What is inside the hash, and one thing that is not

Everything the scan asserts: the declarations, the verdict inputs, the model and
rulepack versions, the timestamp, the district, and **`image_sha256`** — which
is how "later alteration [of the photograph] is detectable" (section 6) without
putting a single byte of image in the database.

`record_sha256` itself is excluded, because a value cannot contain its own hash.
`chain_seq` and `prev_sha256` are stripped from any incoming payload and then
re-added by this module, so passing a full database row back in is safe and
gives the same answer as passing the original scan.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

DOMAIN = "AKSHAR-CHAIN-v1"
"""Domain separation tag, hashed as the first field of every record.

Costs nothing and means a future canonicalisation change (v2) can never produce
a digest that collides with a v1 record. Without it, "we changed how we
serialise floats" would be indistinguishable from "someone edited this row".
"""

GENESIS_PREV = "0" * 64
"""The `prev_sha256` of the first record in a chain.

A literal 64 zeros rather than SQL NULL *inside the hash*, so the genesis record
is hashed by the same code path as every other one. The database column stays
nullable because that reads better in a row dump, and `link_of` converts.
"""

_CHAIN_FIELDS = frozenset({"record_sha256", "prev_sha256", "chain_seq"})


@dataclass(frozen=True, slots=True)
class ChainedRecord:
    """A scan payload with its position and digest. Immutable, like the scan."""

    payload: dict[str, Any]
    chain_seq: int
    prev_sha256: str
    record_sha256: str

    def as_row(self) -> dict[str, Any]:
        """The payload plus its chain columns, ready to insert into `scans`."""
        return {
            **self.payload,
            "chain_seq": self.chain_seq,
            "prev_sha256": None if self.prev_sha256 == GENESIS_PREV else self.prev_sha256,
            "record_sha256": self.record_sha256,
        }


class CanonicalisationError(ValueError):
    """A value that cannot be serialised deterministically.

    Raised rather than coerced. A record that cannot be hashed reproducibly must
    not enter the chain at all: it would verify today and fail next year for
    reasons nobody could reconstruct.
    """


def _encode(value: Any) -> Any:
    """JSON fallback for the types a scan record actually carries."""
    if isinstance(value, datetime):
        # Naive datetimes are treated as UTC rather than rejected: Postgres
        # hands back naive values for TIMESTAMP columns depending on the driver,
        # and silently shifting by a local offset would be far worse.
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        # `str`, not `float`. NUMERIC columns are exactly why Decimal exists;
        # routing them through binary floating point would make the digest
        # depend on rounding.
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, (set, frozenset)):
        raise CanonicalisationError(
            "sets have no defined order, so they cannot be hashed reproducibly; "
            "convert to a sorted list before chaining"
        )
    raise CanonicalisationError(f"cannot canonicalise {type(value).__name__}")


def _reject_non_finite(value: Any, path: str = "$") -> None:
    """Walk the payload and refuse NaN and Infinity.

    `json.dumps` emits these as bare `NaN` / `Infinity` tokens, which are not
    valid JSON. A different parser may reject them, coerce them, or round-trip
    them differently — so a record containing one might hash consistently here
    and inconsistently anywhere else. And `NaN != NaN`, which makes any later
    equality check on the record quietly untrue.

    In practice this catches a real bug, not a hypothetical: a division by a
    zero-pixel height in a measurement produces `inf`, and that would otherwise
    be written into the evidence record as a legal fact.
    """
    if isinstance(value, float) and not math.isfinite(value):
        raise CanonicalisationError(
            f"non-finite number {value!r} at {path}; a scan record must not "
            f"contain NaN or Infinity"
        )
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_non_finite(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_non_finite(item, f"{path}[{index}]")


def canonical_json(payload: Any) -> bytes:
    """Deterministic UTF-8 bytes for a payload. The same input always hashes the same.

    - keys sorted, so insertion order cannot change the digest
    - no whitespace, so a pretty-printer cannot
    - `ensure_ascii=False`, so a Devanagari declaration is hashed as the text it
      is rather than as escape sequences; UTF-8 fixes the byte order
    - `allow_nan=False`, so a non-finite float raises instead of producing
      something no other JSON parser will agree with
    """
    _reject_non_finite(payload)
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
            default=_encode,
        )
    except ValueError as exc:  # pragma: no cover - guarded by _reject_non_finite
        raise CanonicalisationError(str(exc)) from exc
    return text.encode("utf-8")


def strip_chain_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop the columns this module owns, so a database row can be re-hashed."""
    return {key: value for key, value in payload.items() if key not in _CHAIN_FIELDS}


def record_hash(payload: dict[str, Any], *, chain_seq: int, prev_sha256: str) -> str:
    """SHA-256 over the canonical form of the record, its position, and its link.

    The link is hashed *with* the content. If `prev_sha256` were only stored
    alongside, two records could be transposed and each would still hash
    correctly in isolation — the chain would record an order it could not
    defend.
    """
    if chain_seq < 0:
        raise ValueError(f"chain_seq must be non-negative, got {chain_seq}")
    envelope = {
        "domain": DOMAIN,
        "chain_seq": chain_seq,
        "prev_sha256": prev_sha256,
        "payload": strip_chain_fields(payload),
    }
    return hashlib.sha256(canonical_json(envelope)).hexdigest()


def link_of(previous: ChainedRecord | str | None) -> str:
    """The `prev_sha256` a record following `previous` must carry."""
    if previous is None:
        return GENESIS_PREV
    if isinstance(previous, str):
        return previous or GENESIS_PREV
    return previous.record_sha256


def append(payload: dict[str, Any], *, previous: ChainedRecord | None = None) -> ChainedRecord:
    """Chain one scan record onto the previous one.

    `previous` is `None` only for the genesis record. In the server this is the
    row with the highest `chain_seq`, read inside the same transaction that
    writes the new one — the sequence must be gapless, so two concurrent
    appends cannot both read the same tail.
    """
    prev_sha256 = link_of(previous)
    chain_seq = 0 if previous is None else previous.chain_seq + 1
    digest = record_hash(payload, chain_seq=chain_seq, prev_sha256=prev_sha256)
    return ChainedRecord(
        payload=strip_chain_fields(payload),
        chain_seq=chain_seq,
        prev_sha256=prev_sha256,
        record_sha256=digest,
    )


def from_row(row: dict[str, Any]) -> ChainedRecord:
    """Rebuild a `ChainedRecord` from a stored row, WITHOUT re-deriving its hash.

    The stored `record_sha256` is kept as-is rather than recomputed — that is
    the whole point. `verify_chain` recomputes it independently and compares;
    recomputing here would make every row verify by construction and the check
    would be theatre.
    """
    if "record_sha256" not in row:
        raise KeyError("row has no record_sha256; it was never chained")
    stored_prev = row.get("prev_sha256")
    return ChainedRecord(
        payload=strip_chain_fields(row),
        chain_seq=int(row["chain_seq"]),
        prev_sha256=stored_prev if stored_prev else GENESIS_PREV,
        record_sha256=str(row["record_sha256"]),
    )


__all__ = [
    "DOMAIN",
    "GENESIS_PREV",
    "CanonicalisationError",
    "ChainedRecord",
    "append",
    "canonical_json",
    "from_row",
    "link_of",
    "record_hash",
    "strip_chain_fields",
]
