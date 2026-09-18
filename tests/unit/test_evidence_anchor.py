"""The anchor log — AKSHAR.md section 6.

`test_evidence_chain.py` ends with `test_a_wholesale_rewrite_verifies_which_is_
why_the_head_is_published`, which asserts the chain's honest limit: an actor with
write access can rewrite a record and re-chain everything after it, and the
result verifies cleanly.

This file is the other half. Same attack, and now something catches it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from evidence.anchor import (
    ANCHOR_GENESIS,
    append_anchor,
    read_anchors,
    verify_anchors,
)
from evidence.chain import append
from evidence.verify import verify_chain


def _scan(index: int) -> dict:
    """A scan payload that differs from its neighbours in a way that hashes."""
    return {
        "captured_at": datetime(2026, 9, 18, 10, index, tzinfo=UTC).isoformat(),
        "source": "photo",
        "coverage": 0.9,
        "degradation_tier": "L0",
        "rulepack_version": "lmpc-2011-2026.09",
        "declaration_set": {
            "declarations": [{"field": "mrp", "text": f"MRP Rs {10 + index}", "height_mm": 1.9}]
        },
    }


def _build(count: int, *, tamper_at: int | None = None) -> list:
    records = []
    previous = None
    for index in range(count):
        payload = _scan(index)
        if index == tamper_at:
            payload["declaration_set"]["declarations"][0]["height_mm"] = 2.40
        previous = append(payload, previous=previous)
        records.append(previous)
    return records


@pytest.fixture
def log(tmp_path):
    return tmp_path / "anchors.jsonl"


# -- the attack this module exists for ---------------------------------------


def test_a_rewritten_chain_still_verifies_but_no_longer_matches_its_anchor(log):
    """The whole point, in one test.

    The manufacturer's height was 1.9 mm — below Rule 6's minimum. Someone with
    write access edits it to 2.40 and re-chains every record after it. The chain
    verifies. The anchor does not.
    """
    honest = _build(5)
    append_anchor(log, honest)
    assert verify_anchors(log, honest).ok

    tampered = _build(5, tamper_at=2)

    # The limit, restated here so this test fails loudly if the chain ever
    # starts catching this on its own and the anchor becomes redundant.
    assert verify_chain(tampered).ok, "a re-chained rewrite is internally consistent"

    report = verify_anchors(log, tampered)
    assert not report.ok
    assert "ANCHOR_MISMATCH" in (report.first_failure or "")
    assert "rewritten" in (report.first_failure or "")


def test_the_anchor_names_the_earliest_sequence_that_disagrees(log):
    """A rewrite at 2 poisons 2, 3 and 4. The officer needs to know it began at 2.

    Anchoring after every scan is the arrangement that localises the damage: the
    earliest disagreeing anchor is the record that was touched, and every anchor
    before it still agreeing is what lets the department say the rest is intact.
    """
    honest = _build(5)
    for count in range(1, 6):
        append_anchor(log, honest[:count], now=datetime(2026, 9, 18, 10, count, tzinfo=UTC))
    assert len(read_anchors(log)) == 5

    report = verify_anchors(log, _build(5, tamper_at=2))
    assert not report.ok
    mismatches = [f for f in report.failures if "ANCHOR_MISMATCH" in f]
    assert len(mismatches) == 3, "sequences 2, 3 and 4 all disagree"
    assert "sequence 2" in mismatches[0]

    # And the untouched half is still vouched for.
    assert all("sequence 0" not in f and "sequence 1" not in f for f in report.failures)


# -- the anchor file's own integrity -----------------------------------------


def test_the_anchor_lines_are_chained_to_each_other(log):
    records = _build(3)
    first = append_anchor(log, records[:1], now=datetime(2026, 9, 18, 10, 1, tzinfo=UTC))
    second = append_anchor(log, records[:2], now=datetime(2026, 9, 18, 10, 2, tzinfo=UTC))

    assert first is not None and second is not None
    assert first.prev_anchor_sha256 == ANCHOR_GENESIS
    assert second.prev_anchor_sha256 == first.anchor_sha256


def test_editing_one_anchor_line_is_detected(log):
    """The file is on the same disk as the database, so it gets the same
    treatment: a digest over its own content, and a link to the line above."""
    records = _build(3)
    for count in (1, 2, 3):
        append_anchor(log, records[:count], now=datetime(2026, 9, 18, 10, count, tzinfo=UTC))

    lines = log.read_text(encoding="utf-8").splitlines()
    tampered_head = _build(3, tamper_at=1)[-1].record_sha256
    lines[2] = lines[2].replace(records[-1].record_sha256, tampered_head)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_anchors(log, records)
    assert not report.ok
    assert any("ANCHOR_ALTERED" in failure for failure in report.failures)


def test_deleting_a_middle_anchor_line_is_detected(log):
    records = _build(4)
    for count in (1, 2, 3, 4):
        append_anchor(log, records[:count], now=datetime(2026, 9, 18, 10, count, tzinfo=UTC))

    lines = log.read_text(encoding="utf-8").splitlines()
    del lines[1]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    report = verify_anchors(log, records)
    assert not report.ok
    assert any("ANCHOR_BROKEN_LINK" in failure for failure in report.failures)


def test_an_unreadable_line_raises_rather_than_being_skipped(log):
    append_anchor(log, _build(1))
    with log.open("a", encoding="utf-8") as handle:
        handle.write("{not json at all\n")

    with pytest.raises(ValueError, match="not readable as an anchor"):
        read_anchors(log)


# -- the ordinary operating behaviour ----------------------------------------


def test_anchoring_an_unmoved_head_writes_nothing(log):
    """A cron job that runs hourly on a quiet day must not fill the file with
    lines that attest to nothing."""
    records = _build(3)
    assert append_anchor(log, records) is not None
    assert append_anchor(log, records) is None
    assert append_anchor(log, records) is None
    assert len(read_anchors(log)) == 1


def test_re_anchoring_an_altered_head_refuses_instead_of_overwriting(log):
    """The dangerous case: the nightly job runs *after* the rewrite.

    Appending a second, agreeing anchor for the same sequence would bury the
    disagreement under an agreement — the anchor log quietly ratifying the edit
    it exists to expose. It raises instead.
    """
    honest = _build(3)
    append_anchor(log, honest)

    with pytest.raises(ValueError, match="has been altered"):
        append_anchor(log, _build(3, tamper_at=1))

    assert len(read_anchors(log)) == 1, "nothing was written"


def test_an_empty_chain_anchors_nothing(log):
    assert append_anchor(log, []) is None
    assert not log.exists()
    assert verify_anchors(log, []).ok


def test_a_missing_log_is_not_a_failure(tmp_path):
    """Before the first anchor there is nothing to disagree with, and reporting
    that as tampering would teach an operator to ignore this report."""
    report = verify_anchors(tmp_path / "never-written.jsonl", _build(3))
    assert report.ok
    assert report.anchors == 0
    assert report.checked == 0


def test_an_anchor_for_a_sequence_no_longer_stored_is_reported_separately(log):
    """Deleting the tail is not the same failure as editing it, and an operator
    who reads 'MISMATCH' would go looking for the wrong thing."""
    records = _build(5)
    append_anchor(log, records)

    report = verify_anchors(log, records[:3])
    assert not report.ok
    assert "ANCHOR_UNMATCHED" in (report.first_failure or "")
    assert report.checked == 0


def test_the_anchor_records_when_it_was_taken(log):
    """Without a time the line says a digest existed, not that it existed
    *before* the thing it is being used to disprove."""
    when = datetime(2026, 9, 18, 4, 30, tzinfo=UTC)
    anchor = append_anchor(log, _build(2), now=when)
    assert anchor is not None
    assert anchor.anchored_at == when.isoformat()

    later = append_anchor(log, _build(3), now=when + timedelta(days=1))
    assert later is not None
    assert later.anchored_at > anchor.anchored_at
