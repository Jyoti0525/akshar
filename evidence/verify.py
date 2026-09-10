"""M7's acceptance criterion — `verify_chain()` detects any tampered record.

    "Done when: `verify_chain()` detects any tampered historical record."
                                                          -- section 17, M7

A chain that only says *"something is wrong"* is nearly useless to the person
holding it. When a manufacturer disputes a finding, the department needs to be
able to say which record, in what way, and — just as importantly — that every
*other* record is intact. So this returns a report rather than a boolean, and it
keeps checking after the first failure.

**Four distinct failures, and they mean different things.** Conflating them
would let the most serious one hide inside the mildest:

`CONTENT_ALTERED`
    The record's own digest does not match its content. Somebody edited a
    stored scan — the measurement, the verdict inputs, the image hash. This is
    the one that matters.

`BROKEN_LINK`
    The record hashes correctly but points at the wrong predecessor. Its
    content is intact and its *position* is not: a record was deleted, or two
    were transposed. A chain that only recomputed digests would report this as
    fine.

`SEQUENCE_GAP`
    `chain_seq` skips or repeats. Records were removed wholesale, or two
    appends raced and both read the same tail.

`BAD_GENESIS`
    The first record does not carry the genesis link. The chain being verified
    is a fragment, and an earlier record may have been dropped from the front —
    where deletions are easiest to miss.

**One honest limit, and it is worth stating before a judge does.** A chain is
tamper-*evident*, not tamper-*proof*. Someone with write access can rewrite a
record and every record after it, producing a chain that verifies. What stops
that in practice is not this function: it is that the digests are also written
to append-only storage and reported outward, so a wholesale rewrite has to
match copies the rewriter does not control. Publishing the head digest
periodically is what turns evidence of tampering into an anchor, and it costs
one row.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from evidence.chain import GENESIS_PREV, ChainedRecord, from_row, record_hash

FailureKind = Literal["CONTENT_ALTERED", "BROKEN_LINK", "SEQUENCE_GAP", "BAD_GENESIS"]


@dataclass(frozen=True, slots=True)
class ChainFailure:
    kind: FailureKind
    chain_seq: int
    scan_id: str | None
    detail: str

    def __str__(self) -> str:
        where = f"seq {self.chain_seq}"
        if self.scan_id:
            where += f" (scan {self.scan_id})"
        return f"{self.kind} at {where}: {self.detail}"


@dataclass(frozen=True, slots=True)
class ChainReport:
    checked: int
    failures: tuple[ChainFailure, ...] = field(default=())

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def first_failure(self) -> ChainFailure | None:
        return self.failures[0] if self.failures else None

    def summary(self) -> str:
        """One line, suitable for an officer-facing screen or a report footer."""
        if self.ok:
            return f"{self.checked} records verified; chain intact."
        return (
            f"{self.checked} records checked, {len(self.failures)} problem"
            f"{'s' if len(self.failures) != 1 else ''} found. "
            f"First: {self.failures[0]}"
        )


def _as_records(rows: Iterable[ChainedRecord | dict[str, Any]]) -> list[ChainedRecord]:
    return [row if isinstance(row, ChainedRecord) else from_row(row) for row in rows]


def verify_chain(
    rows: Iterable[ChainedRecord | dict[str, Any]],
    *,
    expect_genesis: bool = True,
) -> ChainReport:
    """Check a run of scan records for tampering, deletion and reordering.

    Accepts `ChainedRecord`s or raw database rows. Rows are sorted by
    `chain_seq` first, so a query returning them in any order still verifies —
    but a *gap* in that sequence is still reported, because sorting hides
    disorder and must not hide loss.

    `expect_genesis=False` verifies a slice from the middle of a longer chain,
    where the first record legitimately has a predecessor that is not present.
    Default is True, because silently accepting a missing front is exactly the
    deletion that is easiest to overlook.
    """
    records: Sequence[ChainedRecord] = sorted(_as_records(rows), key=lambda r: r.chain_seq)
    failures: list[ChainFailure] = []

    if not records:
        return ChainReport(checked=0)

    def scan_id_of(record: ChainedRecord) -> str | None:
        value = record.payload.get("id")
        return str(value) if value is not None else None

    first = records[0]
    if expect_genesis and first.chain_seq != 0:
        failures.append(
            ChainFailure(
                "SEQUENCE_GAP",
                first.chain_seq,
                scan_id_of(first),
                f"chain starts at {first.chain_seq}, not 0; "
                f"{first.chain_seq} record(s) are missing from the front",
            )
        )
    if expect_genesis and first.chain_seq == 0 and first.prev_sha256 != GENESIS_PREV:
        failures.append(
            ChainFailure(
                "BAD_GENESIS",
                first.chain_seq,
                scan_id_of(first),
                "the first record does not carry the genesis link",
            )
        )

    previous: ChainedRecord | None = None
    for record in records:
        # 1. Does the record hash to what it claims? Recomputed independently
        #    from the stored content — this is the check that catches an edit.
        recomputed = record_hash(
            record.payload,
            chain_seq=record.chain_seq,
            prev_sha256=record.prev_sha256,
        )
        if recomputed != record.record_sha256:
            failures.append(
                ChainFailure(
                    "CONTENT_ALTERED",
                    record.chain_seq,
                    scan_id_of(record),
                    f"stored digest {record.record_sha256[:12]}... but the content "
                    f"hashes to {recomputed[:12]}...; this record was edited after "
                    f"it was written",
                )
            )

        if previous is not None:
            # 2. Is the sequence gapless? Sorting above hid disorder; it must
            #    not hide loss.
            expected_seq = previous.chain_seq + 1
            if record.chain_seq != expected_seq:
                failures.append(
                    ChainFailure(
                        "SEQUENCE_GAP",
                        record.chain_seq,
                        scan_id_of(record),
                        f"expected sequence {expected_seq}, found {record.chain_seq}"
                        + (
                            "; a duplicate sequence number means two appends raced"
                            if record.chain_seq == previous.chain_seq
                            else "; record(s) removed"
                        ),
                    )
                )

            # 3. Does it point at the record that actually precedes it? A record
            #    can hash perfectly and still be in the wrong place.
            if record.prev_sha256 != previous.record_sha256:
                failures.append(
                    ChainFailure(
                        "BROKEN_LINK",
                        record.chain_seq,
                        scan_id_of(record),
                        f"links to {record.prev_sha256[:12]}... but the preceding "
                        f"record hashes to {previous.record_sha256[:12]}...; a record "
                        f"was deleted or two were transposed",
                    )
                )

        previous = record

    return ChainReport(checked=len(records), failures=tuple(failures))


def head_digest(rows: Iterable[ChainedRecord | dict[str, Any]]) -> str | None:
    """The digest of the highest-sequence record — the value worth publishing.

    Anchoring this outside the database (an append-only log, a daily email to
    the controller, a printed page in a file) is what upgrades the chain from
    "we can detect an edit" to "we can detect an edit *by ourselves*". Without
    an external copy, an actor with full write access can rewrite the tail and
    leave a chain that verifies cleanly.
    """
    records = sorted(_as_records(rows), key=lambda r: r.chain_seq)
    return records[-1].record_sha256 if records else None


__all__ = [
    "ChainFailure",
    "ChainReport",
    "FailureKind",
    "head_digest",
    "verify_chain",
]
