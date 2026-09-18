"""B5 — the evidence plan, decided before anything is read. AKSHAR.md section 5.

The thing under test is a shortcut, and a shortcut in front of a compliance
check earns its place only by being provably conservative. So most of what is
below asks the opposite question to the obvious one: not "does it skip work",
but "does it ever skip work it should have done".
"""

from __future__ import annotations

import pytest

from contracts import PackageContext
from rules.applicability import plan_evidence
from rules.loader import cached_rulepack
from rules.quantity import parse_quantity


@pytest.fixture(scope="module")
def pack():
    return cached_rulepack()


def quantity(text: str):
    match = parse_quantity(text)
    assert match is not None, f"the fixture quantity {text!r} does not parse"
    return match.to_parsed()


# -- the ordinary case -------------------------------------------------------


def test_a_retail_package_is_in_scope_and_asks_for_the_mandatory_six(pack):
    plan = plan_evidence(PackageContext(), pack)

    assert plan.out_of_scope is None
    # Rule 6(1)'s six, plus importer for the conditional rule.
    assert {"mrp", "net_quantity", "mfg_date", "manufacturer", "generic_name", "consumer_care"} <= (
        plan.need
    )
    assert plan.need_geometry <= plan.need, "a field can only be measured if it is read"
    assert plan.need_pdp_polygon is True
    assert plan.must_declare is None


# -- ending the scan before OCR ----------------------------------------------


@pytest.mark.parametrize(
    ("label", "ctx", "rule_ref"),
    [
        ("Rule 3(b) institutional buyer", PackageContext(consumer_type="institutional"), "3(b)"),
        ("Rule 3(b) industrial buyer", PackageContext(consumer_type="industrial"), "3(b)"),
        ("Rule 26(a) 5 g sachet", PackageContext(net_quantity=quantity("5 g")), "26(a)"),
        ("Rule 3(a) 60 kg sack", PackageContext(net_quantity=quantity("60 kg")), "3(a)"),
    ],
)
def test_an_exempt_package_is_settled_without_reading_anything(pack, label, ctx, rule_ref):
    plan = plan_evidence(ctx, pack)

    assert plan.out_of_scope is not None, f"{label} should end the scan before OCR"
    assert plan.out_of_scope.in_scope is False
    assert rule_ref in (plan.out_of_scope.reason or ""), (
        "the officer is told which rule exempted it"
    )

    # Nothing is asked for, because nothing is being judged. A caller that reads
    # the label anyway has only wasted time; a caller that reads `need` and
    # finds it non-empty would go on to produce evidence for a question nobody
    # is entitled to ask.
    assert plan.need == frozenset()
    assert plan.need_geometry == frozenset()
    assert plan.need_pdp_polygon is False


# -- the conservative half, which is the half that matters -------------------


def test_an_unknown_quantity_never_exempts_a_package(pack):
    """The 10 g exemption is the tempting one, and it is a trap.

    The net quantity is normally printed on the pack — which is exactly what has
    not been read when this runs. If a missing quantity were treated as "small",
    every scan would end before OCR with the pack declared exempt, and the tool
    would clear every package in India while reporting success.
    """
    assert plan_evidence(PackageContext(), pack).out_of_scope is None
    assert plan_evidence(PackageContext(category="food"), pack).out_of_scope is None


def test_the_plan_agrees_with_the_engine_about_scope(pack):
    """The shortcut and the real gate must not drift apart.

    `plan_evidence` runs the same `evaluate_applicability` the engine runs, and
    this asserts that rather than trusting it: whenever the plan says "stop",
    the full engine must also find the package out of scope.
    """
    from datetime import UTC, datetime

    from contracts import DeclarationSet
    from rules.engine import evaluate

    for ctx in (
        PackageContext(consumer_type="institutional"),
        PackageContext(net_quantity=quantity("5 g")),
        PackageContext(net_quantity=quantity("60 kg")),
    ):
        plan = plan_evidence(ctx, pack)
        assert plan.out_of_scope is not None

        ds = DeclarationSet(source="photo", captured_at=datetime.now(UTC))
        verdicts = evaluate(ds, ctx, pack)
        statuses = {v.status for v in verdicts}
        assert statuses == {"NOT_APPLICABLE"}, (
            f"the plan stopped the scan but the engine would have returned {statuses}"
        )


def test_wholesale_narrows_what_must_be_declared_without_narrowing_what_is_read(pack):
    """Rule 24, and the distinction the whole gate turns on.

    A wholesale carton must declare three things. It is not thereby licensed to
    print an unreadable price: `LMPC.CHAR.WIDTH_RATIO` still governs an MRP that
    *is* printed. So `must_declare` shrinks to three and `mrp` stays in `need`.
    Conflating the two is how a wholesale scan grows four false violations.
    """
    plan = plan_evidence(PackageContext(package_type="wholesale"), pack)

    assert plan.must_declare == frozenset({"manufacturer", "generic_name", "net_quantity"})
    assert "mrp" in plan.need, "a printed MRP is still governed by the format rules"
    assert plan.out_of_scope is None


def test_every_field_an_enabled_rule_targets_is_asked_for(pack):
    """No rule may run against evidence the plan did not request.

    This is the regression that a hand-written field list would cause: a rule
    added to the pack, its field never requested, and the only symptom a NO_DATA
    on a rule that used to work.
    """
    from rules.applicability import _NOTHING_READ_YET as EMPTY
    from rules.applicability import evaluate_applicability

    ctx = PackageContext()
    plan = plan_evidence(ctx, pack)
    gate = evaluate_applicability(EMPTY, ctx, pack.applicability)

    for rule in pack.all_rules(True):
        if not rule.enabled:
            continue
        targets = rule.target_fields()
        if gate.blocks(targets) is not None:
            continue
        missing = set(targets) - plan.need
        assert not missing, f"{rule.id} will read {sorted(missing)}, which the plan did not request"


def test_a_disabled_rule_does_not_make_the_scan_do_work(pack):
    """`LMPC.UNIT.LITRE_SYMBOL` ships disabled (section 13c, disputed).

    A disabled rule asking for evidence would be the shortcut costing time
    rather than saving it.
    """
    disabled = [r for r in pack.all_rules(True) if not r.enabled]
    assert disabled, "this test asserts nothing if the pack has no disabled rules"

    plan = plan_evidence(PackageContext(), pack)
    for rule in disabled:
        only_its_own = set(rule.target_fields()) - {
            f for r in pack.all_rules(True) if r.enabled for f in r.target_fields()
        }
        assert not (only_its_own & plan.need), f"{rule.id} is disabled but still asks for evidence"


def test_geometry_is_only_requested_for_the_checks_that_measure_millimetres(pack):
    """If nothing needs millimetres, the scan does not need scale at all.

    That is the saving worth having on a phone: no marker search, no ruler, and
    no NO_DATA rows explaining that a height could not be measured.
    """
    from rules import checks

    plan = plan_evidence(PackageContext(), pack)
    measuring = {
        field
        for rule in pack.all_rules(True)
        if rule.enabled and rule.check in checks.REQUIRES_MILLIMETRES
        for field in rule.target_fields()
    }
    assert plan.need_geometry == measuring & plan.need


def test_the_sentinel_never_leaks_into_a_record(pack):
    """`_NOTHING_READ_YET` is shared and frozen in intent; nothing may mutate it."""
    from rules.applicability import _NOTHING_READ_YET as EMPTY

    before = EMPTY.model_dump_json()
    for ctx in (PackageContext(), PackageContext(package_type="wholesale")):
        plan_evidence(ctx, pack)
    assert EMPTY.model_dump_json() == before
    assert EMPTY.declarations == []
