"""The anchor log — the copy the rewriter does not control. AKSHAR.md section 6.

`verify_chain` proves that a set of records is internally consistent. It cannot
prove the set is the one that was written, and `evidence/verify.py` says so at
the top: *"Someone with write access can rewrite a record and every record after
it, producing a chain that verifies."* `tests/unit/test_evidence_chain.py`
asserts that limit deliberately, so nobody overclaims it.

This closes it, at the cost the plan quotes — one row.

**How.** Periodically, the head digest is appended to a file that is not the
database, together with the sequence number it describes. Later, every anchor is
re-checked against the live chain: the record that now sits at sequence 42 must
still hash to what was anchored for sequence 42. A rewrite of record 17
re-computes every digest from 17 onward, so *every anchor at or after 17*
disagrees — and the report names the earliest one, which is the record that was
touched.

**Why the anchors are themselves chained.** An append-only file on the same disk
as the database is one `>` away from being rewritten too. Each line therefore
carries the digest of the line before it, exactly as the scan records do. That
does not make the file unforgeable — nothing local can — but it means a forger
must rewrite *every* subsequent anchor line rather than editing one, and any
copy of the file taken at any point (the controller's inbox, a printout in a
case file, a second machine) pins everything up to the moment it was taken.

**What this is not.** It is not a timestamping authority and it does not claim
to be. The honest statement to a court is: *this digest was recorded at this
time in a file held separately from the database, and the department's copy of
that file agrees*. The strength of the anchor is exactly the independence of the
place it is kept, which is an operational fact and not a property of this
module. `docs/deployment.md` is where that independence has to be arranged.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evidence.verify import as_records

ANCHOR_GENESIS = "0" * 64
"""The `prev` of the first anchor. Same convention as the scan chain's genesis,
so a truncated-from-the-front anchor file is as visible as a truncated chain."""

SCHEMA = 1


@dataclass(frozen=True, slots=True)
class Anchor:
    """One published statement: at this time, the chain looked like this."""

    anchored_at: str
    chain_seq: int
    head_sha256: str
    records: int
    prev_anchor_sha256: str
    anchor_sha256: str

    def to_line(self) -> str:
        return json.dumps(
            {
                "schema": SCHEMA,
                "anchored_at": self.anchored_at,
                "chain_seq": self.chain_seq,
                "head_sha256": self.head_sha256,
                "records": self.records,
                "prev_anchor_sha256": self.prev_anchor_sha256,
                "anchor_sha256": self.anchor_sha256,
            },
            separators=(",", ":"),
            sort_keys=True,
        )


def _anchor_hash(
    *, anchored_at: str, chain_seq: int, head_sha256: str, records: int, prev: str
) -> str:
    """Digest of one anchor's content plus its link.

    Hand-built from a sorted, separator-fixed JSON document for the same reason
    `evidence/chain.py` canonicalises a scan: a digest computed over "whatever
    `json.dumps` did today" verifies today and fails next year.
    """
    body = json.dumps(
        {
            "schema": SCHEMA,
            "anchored_at": anchored_at,
            "chain_seq": chain_seq,
            "head_sha256": head_sha256,
            "records": records,
            "prev_anchor_sha256": prev,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Reading and writing


def read_anchors(path: Path) -> list[Anchor]:
    """Every anchor in the file, in the order written.

    A malformed line raises rather than being skipped. An anchor file with a
    line nobody can parse is a file whose contents are partly unknown, and
    quietly ignoring the unreadable part is how an anchor log ends up attesting
    to less than its reader believes.
    """
    if not path.exists():
        return []

    anchors: list[Anchor] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number} is not readable as an anchor: {exc}") from exc
        if body.get("schema") != SCHEMA:
            raise ValueError(f"{path}:{number} carries schema {body.get('schema')!r}, not {SCHEMA}")
        anchors.append(
            Anchor(
                anchored_at=body["anchored_at"],
                chain_seq=int(body["chain_seq"]),
                head_sha256=body["head_sha256"],
                records=int(body["records"]),
                prev_anchor_sha256=body["prev_anchor_sha256"],
                anchor_sha256=body["anchor_sha256"],
            )
        )
    return anchors


def append_anchor(
    path: Path,
    rows: Iterable[Any],
    *,
    now: datetime | None = None,
) -> Anchor | None:
    """Publish the current head. Returns the anchor written, or None.

    None means there was nothing new to say: either the chain is empty, or its
    head has not moved since the last anchor. Re-anchoring an unchanged head
    would fill the file with lines that attest to nothing and make the real ones
    harder to find.
    """
    records = sorted(as_records(rows), key=lambda record: record.chain_seq)
    if not records:
        return None

    head = records[-1]
    existing = read_anchors(path)
    if existing and existing[-1].chain_seq == head.chain_seq:
        if existing[-1].head_sha256 == head.record_sha256:
            return None
        # Same sequence, different digest: the record at that position has been
        # rewritten since it was anchored. Writing a second anchor for it would
        # bury the disagreement under an agreement.
        raise ValueError(
            f"sequence {head.chain_seq} is already anchored to "
            f"{existing[-1].head_sha256[:12]}... but now hashes to "
            f"{head.record_sha256[:12]}...; the record has been altered. "
            f"Do not re-anchor — investigate."
        )

    anchored_at = (now or datetime.now(UTC)).isoformat()
    prev = existing[-1].anchor_sha256 if existing else ANCHOR_GENESIS
    anchor = Anchor(
        anchored_at=anchored_at,
        chain_seq=head.chain_seq,
        head_sha256=head.record_sha256,
        records=len(records),
        prev_anchor_sha256=prev,
        anchor_sha256=_anchor_hash(
            anchored_at=anchored_at,
            chain_seq=head.chain_seq,
            head_sha256=head.record_sha256,
            records=len(records),
            prev=prev,
        ),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    # Append, flush and fsync. A power cut between the write and the flush would
    # otherwise lose the one line whose whole purpose is to have been written
    # before something happened.
    with path.open("a", encoding="utf-8") as handle:
        handle.write(anchor.to_line() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return anchor


# ---------------------------------------------------------------------------
# Verifying


@dataclass(frozen=True, slots=True)
class AnchorReport:
    """What the anchors say about the chain as it stands now."""

    anchors: int
    checked: int
    """Anchors that could be compared — one whose sequence is no longer present
    is reported separately rather than counted as agreement."""

    failures: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def first_failure(self) -> str | None:
        return self.failures[0] if self.failures else None


def verify_anchors(path: Path, rows: Iterable[Any]) -> AnchorReport:
    """Does the live chain still match everything that was published about it?

    Two independent questions, both asked:

      1. Is the anchor file itself intact — does each line link to the one
         before it?
      2. Does the record now at each anchored sequence still hash to what was
         anchored?

    Keeps going after the first failure, for the reason `verify_chain` does: the
    person holding this needs to know which records are intact, not merely that
    one is not.
    """
    anchors = read_anchors(path)
    by_seq = {record.chain_seq: record for record in as_records(rows)}

    failures: list[str] = []
    checked = 0
    previous = ANCHOR_GENESIS

    for index, anchor in enumerate(anchors):
        recomputed = _anchor_hash(
            anchored_at=anchor.anchored_at,
            chain_seq=anchor.chain_seq,
            head_sha256=anchor.head_sha256,
            records=anchor.records,
            prev=anchor.prev_anchor_sha256,
        )
        if recomputed != anchor.anchor_sha256:
            failures.append(
                f"ANCHOR_ALTERED at line {index + 1}: the anchor for sequence "
                f"{anchor.chain_seq} does not hash to its own digest"
            )
        elif anchor.prev_anchor_sha256 != previous:
            failures.append(
                f"ANCHOR_BROKEN_LINK at line {index + 1}: the anchor for sequence "
                f"{anchor.chain_seq} points at a predecessor that is not the line above it"
            )
        previous = anchor.anchor_sha256

        record = by_seq.get(anchor.chain_seq)
        if record is None:
            failures.append(
                f"ANCHOR_UNMATCHED at sequence {anchor.chain_seq}: anchored on "
                f"{anchor.anchored_at} but no record with that sequence is stored now"
            )
            continue

        checked += 1
        if record.record_sha256 != anchor.head_sha256:
            failures.append(
                f"ANCHOR_MISMATCH at sequence {anchor.chain_seq}: anchored on "
                f"{anchor.anchored_at} as {anchor.head_sha256[:12]}... but the stored "
                f"record now hashes to {record.record_sha256[:12]}...; this record or "
                f"one before it has been rewritten"
            )

    return AnchorReport(anchors=len(anchors), checked=checked, failures=tuple(failures))


def default_path() -> Path:
    """Where the log lives unless told otherwise.

    An environment variable, because the whole value of the anchor is that it is
    kept somewhere the database is not — a different volume, a mounted share, a
    machine the API cannot write to twice. A default beside the repository is
    honest about being the weakest arrangement, not a recommendation of it.
    """
    configured = os.environ.get("AKSHAR_ANCHOR_LOG")
    if configured:
        return Path(configured)
    return Path("data") / "evidence" / "anchors.jsonl"


__all__ = [
    "ANCHOR_GENESIS",
    "Anchor",
    "AnchorReport",
    "append_anchor",
    "default_path",
    "read_anchors",
    "verify_anchors",
]


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - CLI
    import argparse

    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--log", type=Path, default=None, help="anchor file (default: $AKSHAR_ANCHOR_LOG)"
    )
    parser.add_argument(
        "--verify", action="store_true", help="check the anchors instead of writing one"
    )
    args = parser.parse_args(argv)

    from api.deps import get_scan_store

    path = args.log or default_path()
    records = get_scan_store().all_records()

    if args.verify:
        report = verify_anchors(path, records)
        print(f"{report.anchors} anchors, {report.checked} compared against stored records")
        for failure in report.failures:
            print(f"  {failure}")
        print("OK" if report.ok else f"{len(report.failures)} FAILURE(S)")
        return 0 if report.ok else 1

    anchor = append_anchor(path, records)
    if anchor is None:
        print(f"nothing new to anchor in {path}")
        return 0
    print(f"anchored sequence {anchor.chain_seq} = {anchor.head_sha256} in {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
