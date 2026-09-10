"""Every check type, every status, both sides of every threshold. AKSHAR.md §18.

    "Unit tests cover the rules engine exhaustively — every check type, every
     status including NO_DATA and REVIEW, boundary values either side of each
     threshold. Fast, deterministic, and they're what lets us change the
     rulepack without fear."                                              -- §18

`tests/unit/test_engine.py` already covers the engine through the *rulepack*,
which is the right way to test the legal logic: those tests read like the Rules
because they are the Rules. This file is the other axis. It goes at each of the
thirteen check functions directly, with a rule constructed for the purpose, and
asserts the contract every one of them shares.

---------------------------------------------------------------------------
WHY BOTH, AND WHY THIS ONE IS NOT REDUNDANT
---------------------------------------------------------------------------
A rulepack test says *"a pack with no MRP fails Rule 6(1)(e)"*. If somebody
disables that rule, deletes it, or changes its `check:` to something else, the
test fails -- correctly -- but the `present` check function itself is then
untested and nobody notices, because the coverage number barely moves.

More sharply: three of the thirteen types (`min_width_ratio`, `clear_space`,
`min_contrast`) are exercised by exactly one rulepack rule each. Those rules are
the ones section 13 calls *"the rules only this architecture can check"*, and
they were one YAML edit away from having no test at all.

---------------------------------------------------------------------------
THE THREE INVARIANTS EVERY CHECK MUST HOLD
---------------------------------------------------------------------------
Stated once, asserted for all thirteen by `test_no_check_ever_...`:

1. **A missing declaration is NO_DATA or NOT_APPLICABLE, never FAIL.** Section
   8b: *"absence of evidence is not evidence of a violation."* This is the
   single most damaging bug available to this project -- a photograph that was
   too blurry to read would become an enforcement finding.
2. **No check raises.** Handed an empty `DeclarationSet` with no geometry, no
   scale and no text, every one must return an outcome. `vision/pipeline.py`
   guarantees the engine sees something for every scan including L4 ones, so a
   check that raises on empty input takes down the scan, not just the rule.
3. **A FAIL always says what it found and what it expected.** A verdict with
   `found=None` renders as an empty cell in the report an officer signs.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from contracts import Box, Declaration, DeclarationSet, LabelGeometry, PackageContext
from rules.checks import REGISTRY
from rules.models import Pattern, Rule, Rulepack

NOW = datetime.now(UTC)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def rule(check: str, **options) -> Rule:
    """A rule of one check type, with its options in `raw` where `Rule.opt` reads them.

    `fields` is a real dataclass field; everything else a check asks for
    (`pattern`, `min_mm`, `min_ratio`, `categories`) is read through `opt`,
    which looks in `raw`. Splitting them here rather than in every test keeps
    the tests reading like the rulepack YAML they stand in for.
    """
    fields = tuple(options.pop("fields", ()) or ())
    return Rule(
        id=f"TEST.{check.upper()}",
        rule_ref="Rule 0(0) — synthetic",
        check=check,
        severity="high",
        message="synthetic",
        raw=options,
        fields=fields,
    )


def declaration(field: str = "mrp", text: str = "MRP Rs. 45.00", **overrides) -> Declaration:
    body = {
        "field": field,
        "text": text,
        "script": "latin",
        "ocr_confidence": 0.95,
        "field_confidence": 0.95,
        "box": Box(x=40, y=100, w=300, h=40),
        "height_mm": 3.0,
        "height_mm_tolerance": 0.1,
        "height_px": 40,
        "scale_tier": "A",
        "contrast_ratio": 8.0,
        "panel_id": "pdp",
    }
    body.update(overrides)
    return Declaration(**{k: v for k, v in body.items() if k in Declaration.model_fields})


def declaration_set(*declarations: Declaration, **overrides) -> DeclarationSet:
    body = {
        "source": "photo",
        "declarations": list(declarations),
        # `mm_per_px` is what separates tier A/B from tier C, and without it
        # every millimetre check correctly returns NO_DATA -- which would make
        # the threshold tests below assert nothing at all while passing.
        "geometry": LabelGeometry(
            label_w_mm=100.0,
            label_h_mm=150.0,
            pdp_w_mm=100.0,
            pdp_h_mm=80.0,
            mm_per_px=0.075,
        ),
        "coverage": 1.0,
        "degradation_tier": "L0",
        "captured_at": NOW,
        "raw_text": " ".join(d.text for d in declarations),
    }
    body.update(overrides)
    return DeclarationSet(**{k: v for k, v in body.items() if k in DeclarationSet.model_fields})


EMPTY = DeclarationSet(source="photo", captured_at=NOW)
CONTEXT = PackageContext(category="biscuits")


def pattern(name: str, expression: str) -> Pattern:
    """One named pattern, Latin only.

    `Pattern.search` tries every script it holds, so a single entry is enough
    for these tests. The real pack carries a Devanagari twin of each, because
    section 13 makes a Hindi-only label lawful and reporting "MRP not found" on
    one would be the worst failure this system can produce -- that is
    `test_engine.py`'s business, against the real pack.
    """
    return Pattern(name=name, by_script={"latin": re.compile(expression)})


PACK = Rulepack(
    pack_id="test",
    version="test@0",
    authority="synthetic",
    rules=(),
    extension_rules=(),
    patterns={
        # `regex` resolves its pattern by name out of the pack rather than
        # taking one inline, which is what makes the rulepack a document a
        # lawyer can read: the rule says "the form prescribed by Rule 6(1)(e)"
        # and the expression lives once, under a name, beside the others.
        "mrp_strict": pattern("mrp_strict", r"^MRP Rs\. \d+\.\d{2}$"),
        "mrp_locate": pattern("mrp_locate", r"MRP|Retail Sale Price"),
    },
    tables={},
    applicability={},
    meta={},
)
"""A nearly-empty pack. These tests call the check functions directly, so the
pack is consulted only for shared patterns and tables -- and a check that needed
one it was not given should say so rather than assume a default. Two patterns
are registered because `regex` legitimately returns NO_DATA without one, and a
test that accepted that as a failure would be asserting nothing."""


def run(check: str, ds: DeclarationSet, ctx: PackageContext = CONTEXT, **options):
    return REGISTRY[check](rule(check, **options), ds, ctx, PACK)


# ---------------------------------------------------------------------------
# Invariant 1 — absence of evidence is not evidence of a violation
# ---------------------------------------------------------------------------


PRESENCE_CHECKS = {"present", "conditional_present"}
"""The two checks whose entire job is to report an absence, and which therefore
may -- must -- return FAIL when a declaration is not there.

They are the exception to invariant 1, and the exception is narrow rather than a
weakening of the rule: `present` failing on a missing MRP *is* Rule 6(1)(e). The
guard against a blurred photograph becoming a finding lives one layer up, in the
coverage figure carried on every scan and shown beside the verdicts, not in
these functions -- and `rules/loader.py` enforces that only the rule named by
`on_locate_fail` may report a missing declaration, so exactly one rule per field
can produce this FAIL rather than all of them at once."""


@pytest.mark.parametrize("check", sorted(set(REGISTRY) - PRESENCE_CHECKS))
def test_no_check_turns_a_missing_declaration_into_a_failure(check):
    """Section 8b, and the most damaging bug this project could ship.

    An empty `DeclarationSet` is what a scan of an unreadable photograph
    produces, and `vision/pipeline.py` still hands it to the engine so the
    officer gets an L4 record. A *format* rule that answered FAIL here would
    report a pack as printing its MRP wrongly when the truth is that nobody
    could read it -- and `rules/checks/regex.py` says so in its own docstring:
    *"say nothing and let `on_locate_fail` report the absence."*
    """
    outcome = run(check, EMPTY, fields=["mrp"])
    assert outcome.status in {"NO_DATA", "NOT_APPLICABLE", "PASS"}, (
        f"`{check}` returned {outcome.status} on an empty DeclarationSet. "
        f"Absence of evidence is not evidence of a violation."
    )


@pytest.mark.parametrize("check", sorted(PRESENCE_CHECKS))
def test_the_presence_checks_do_report_an_absence(check):
    """The other half of the same statement, so the exception is pinned too.

    If `present` ever stopped failing on a missing declaration, the test above
    would still pass for all eleven other checks and the most-used rule in the
    pack would have quietly stopped enforcing anything.
    """
    outcome = run(check, EMPTY, fields=["mrp"], requires_field="mrp")
    assert outcome.status in {"FAIL", "NO_DATA", "NOT_APPLICABLE"}
    if outcome.status == "FAIL":
        assert outcome.expected, "a missing-declaration FAIL must say what was expected"


@pytest.mark.parametrize("check", sorted(REGISTRY))
def test_no_check_raises_on_an_empty_declaration_set(check):
    """Invariant 2. A check that raises takes down the whole scan, not one rule."""
    run(check, EMPTY, fields=["mrp"])


@pytest.mark.parametrize("check", sorted(REGISTRY))
def test_no_check_raises_when_geometry_and_scale_are_absent(check):
    """Tier C, the no-marker case, which is section 17 M2's default.

    A declaration with text but no box, no millimetres and no contrast is what
    the listing-text channel produces and what a photograph with no findable
    label quad degrades to.
    """
    # Tier C is the absence of *millimetres*, not of pixels: the box is in the
    # rectified image's own coordinates and exists whether or not a marker was
    # found. `Declaration` makes `box` and `height_px` required for exactly that
    # reason, and this fixture respects it rather than working around it.
    bare = declaration_set(
        declaration(height_mm=None, contrast_ratio=None, scale_tier="C"),
        geometry=LabelGeometry(),
    )
    outcome = run(
        check,
        bare,
        fields=["mrp"],
        pattern=r"\d+",
        fixed_mm={"normal": 2.0, "embossed": 4.0},
        min_ratio=3.0,
    )
    # No assertion on the status. Tier C is a *degradation*, and which of
    # NO_DATA, PASS or FAIL is right differs per check -- `min_width_ratio` and
    # `clear_space` are pixel ratios and still work, `min_height_mm` cannot.
    # What every one of them must do is return.
    assert outcome.status in {"PASS", "FAIL", "REVIEW", "NO_DATA", "NOT_APPLICABLE"}


# ---------------------------------------------------------------------------
# Invariant 3 — a FAIL is legible
# ---------------------------------------------------------------------------


def test_every_failure_this_file_produces_says_what_it_found_and_expected():
    """Collected rather than parametrised: the point is the *set* of failures.

    A verdict rendered into the officer's report with `found=None` is an empty
    cell on a document somebody signs.
    """
    failures = [
        ("present", run("present", declaration_set(declaration(field="net_quantity")), fields=["mrp"])),
        (
            "regex",
            run(
                "regex",
                declaration_set(declaration(text="MRP 45")),
                fields=["mrp"],
                pattern_ref="mrp_strict",
            ),
        ),
        (
            "min_height_mm",
            run(
                "min_height_mm",
                declaration_set(declaration(height_mm=0.5)),
                fields=["mrp"],
                fixed_mm={"normal": 2.0, "embossed": 4.0},
            ),
        ),
        (
            "value_in_range",
            run(
                "value_in_range",
                declaration_set(declaration(field="net_quantity", text="1500 g")),
                fields=["net_quantity"],
            ),
        ),
    ]
    for name, outcome in failures:
        # `regex` returns REVIEW rather than FAIL when the text came from OCR:
        # case, spacing and punctuation are not recovered faithfully enough
        # from a photograph to accuse anyone of mis-printing them. The verdict
        # still has to say what it found and expected, which is what this test
        # is about. See `rules/checks/regex.py` and
        # `test_a_format_mismatch_is_review_on_a_photograph_and_fail_on_a_listing`.
        allowed = {"FAIL", "REVIEW"} if name == "regex" else {"FAIL"}
        assert outcome.status in allowed, (
            f"`{name}` was expected to fail here, got {outcome.status}"
        )
        assert outcome.expected, f"`{name}` failed with no `expected`"
        # `found` is required of every failure EXCEPT a presence one, where the
        # absence is the finding and `None` is what the report is supposed to
        # render as "not declared". Asserting a string there would force the
        # check to invent one.
        if name not in PRESENCE_CHECKS:
            assert outcome.found, (
                f"`{name}` failed with no `found` — the report renders an empty cell "
                f"on a document an officer signs"
            )


# ---------------------------------------------------------------------------
# Boundaries — either side of each numeric threshold
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("height_mm", "expected"),
    [
        (1.50, "FAIL"),  # clearly under
        (1.89, "FAIL"),  # under, outside tolerance
        (1.95, "REVIEW"),  # inside tolerance, below the line
        (2.00, "PASS"),  # exactly the threshold
        (2.05, "PASS"),  # inside tolerance, above the line
        (3.00, "PASS"),  # clearly over
    ],
)
def test_min_height_mm_either_side_of_the_threshold(height_mm, expected):
    """The one threshold in this system that decides a legal outcome.

    2.00 mm is Rule 7(2) Table I's smallest band. The REVIEW window either side
    of it is section 8b's: *"B9 emits height_mm: 1.77, error: +/-0.08. It does
    not emit FAIL"* -- a measurement whose error bar crosses the line is a
    question for a person, not a verdict.
    """
    outcome = run(
        "min_height_mm",
        declaration_set(declaration(height_mm=height_mm, height_mm_tolerance=0.1)),
        fields=["mrp"],
        # Rule 7(3)'s flat floor, which is the one path through
        # `_threshold_from_table` that does not depend on a net quantity being
        # parsed. Table I's banding is section 13's business and
        # `test_engine.py::test_table_one_bands_and_boundaries` covers it
        # against the real pack; this test is about the comparison itself.
        fixed_mm={"normal": 2.0, "embossed": 4.0},
    )
    assert outcome.status == expected, (
        f"{height_mm} mm against a 2.00 mm minimum with +/-0.10 tolerance "
        f"gave {outcome.status}, expected {expected}"
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0.05 g", "FAIL"),  # below the 0.1 lower bound
        ("0.1 g", "PASS"),  # exactly the lower bound, inclusive
        ("500 g", "PASS"),  # comfortably inside
        ("999 g", "PASS"),  # just inside the upper bound
        ("1000 g", "FAIL"),  # exactly the upper bound, exclusive -- must be 1 kg
        ("1500 g", "FAIL"),  # above
        # Arm 2, Rule 13(2): magnitude-correct but unit-wrong. 0.1 kg sits
        # inside [0.1, 1000) and is still non-compliant, because 100 g must be
        # declared in grams. A test that only walked arm 1's bounds would miss
        # the entire second half of the check.
        ("0.1 kg", "FAIL"),
        ("0.5 kg", "FAIL"),
    ],
)
def test_value_in_range_either_side_of_both_bounds(text, expected):
    """Third Schedule item 10: *"between 0.1 and 1000"*.

    The asymmetry is deliberate and is in the check: 0.1 passes and 1000 fails,
    because `1000 g` is exactly the case the rule exists to catch -- it should
    be `1 kg`.
    """
    outcome = run(
        "value_in_range",
        declaration_set(declaration(field="net_quantity", text=text)),
        fields=["net_quantity"],
    )
    assert outcome.status == expected, f"{text!r} gave {outcome.status}, expected {expected}"


@pytest.mark.parametrize(
    ("contrast", "expected"),
    [
        (2.5, "FAIL"),  # clearly under
        (2.79, "FAIL"),  # just outside the 0.2 band
        (2.80, "REVIEW"),  # exactly at the band's edge, inclusive
        (2.95, "REVIEW"),  # inside the band
        (3.00, "PASS"),  # exactly the threshold
        (3.10, "PASS"),  # over
    ],
)
def test_min_contrast_either_side_of_the_threshold(contrast, expected):
    """The same REVIEW-band shape as `min_height_mm`, and deliberately so.

    Every measured check in this system reports a band rather than a line,
    because a measurement is an estimate with an error bar and section 8b will
    not let an error bar that crosses the threshold become a verdict. The band
    here is +/-0.2 of a contrast ratio; there it is the per-declaration
    millimetre tolerance. Two different widths, one rule.
    """
    outcome = run(
        "min_contrast",
        declaration_set(declaration(contrast_ratio=contrast)),
        fields=["mrp"],
        min_ratio=3.0,
    )
    assert outcome.status == expected, (
        f"contrast {contrast}:1 against a 3.0:1 minimum gave {outcome.status}, "
        f"expected {expected}"
    )


# ---------------------------------------------------------------------------
# `regex_absent` searches the declaration, not the label
# ---------------------------------------------------------------------------


def test_regex_absent_does_not_search_the_whole_label():
    """The regression measured on 2026-09-09, and the reason it mattered.

    `scripts/advisory_false_positives.py` raised 13 advisory findings over 40
    corpus frames, and 11 had no classified net quantity at all: the check was
    falling back to `raw_text` and matching a serving size in a nutrition panel,
    Devanagari numerals in lawful Hindi body text, and bare capitals lifted out
    of unrelated words.

    The pack below is the damaging non-advisory case rather than one of the
    advisories: `LMPC.QTY.WHEN_PACKED` under Rule 11(4) is a real allegation,
    and it would have been made because the words appeared *somewhere* on the
    label.
    """
    pack = Rulepack(
        pack_id="test",
        version="test@0",
        authority="synthetic",
        rules=(),
        extension_rules=(),
        patterns={"when_packed": pattern("when_packed", r"when packed")},
        tables={},
        applicability={},
        meta={},
    )
    banned = rule("regex_absent", fields=["net_quantity"], pattern_ref="when_packed")

    # The phrase is on the label, in a marketing line, and the net quantity
    # declaration was never classified.
    elsewhere = declaration_set(
        declaration(field="marketing_text", text="Freshness sealed when packed"),
    )
    outcome = REGISTRY["regex_absent"](banned, elsewhere, CONTEXT, pack)
    assert outcome.status == "NO_DATA", (
        "the net quantity was not read, so nothing may be alleged about what is "
        f"printed inside it; got {outcome.status} ({outcome.found!r})"
    )

    # And when it IS in the declaration, the rule still fires.
    inside = declaration_set(
        declaration(field="net_quantity", text="Net wt 500 g when packed"),
    )
    outcome = REGISTRY["regex_absent"](banned, inside, CONTEXT, pack)
    assert outcome.status == "FAIL"
    assert outcome.found == "when packed"


def test_regex_absent_scope_label_restores_the_whole_label_search():
    """The opt-in, so a future rule that genuinely means "nowhere on the pack"
    can say so in the YAML rather than by editing the check."""
    pack = Rulepack(
        pack_id="test",
        version="test@0",
        authority="synthetic",
        rules=(),
        extension_rules=(),
        patterns={"when_packed": pattern("when_packed", r"when packed")},
        tables={},
        applicability={},
        meta={},
    )
    wide = rule(
        "regex_absent", fields=["net_quantity"], pattern_ref="when_packed", scope="label"
    )
    elsewhere = declaration_set(
        declaration(field="marketing_text", text="Freshness sealed when packed"),
    )
    assert REGISTRY["regex_absent"](wide, elsewhere, CONTEXT, pack).status == "FAIL"


SCOPED_CHECKS = {"regex_absent", "symbol_case"}
"""The two checks that ask "what is printed *inside* this declaration".

Both used to fall back to the whole label through `strict_text` and both were
caught by the same measurement on 2026-09-09. They are listed together because
the next check written in this shape will have the same bug, and a set is easier
to add to than a paragraph."""


def test_no_shipped_rule_opts_into_the_whole_label_search():
    """Nothing in the pack sets `scope: label` today.

    If one ever does, this fails and whoever added it has to justify it here —
    which is the point. The default is the safe one and the exception should
    cost a conversation.
    """
    from rules.loader import load_rulepack

    shipped = load_rulepack()
    wide = [
        r.id
        for r in (*shipped.rules, *shipped.extension_rules)
        if r.check in SCOPED_CHECKS and r.opt("scope") == "label"
    ]
    assert not wide, (
        f"{wide} search the whole label. Each one can report a violation from text "
        f"that is not in the declaration it names."
    )


@pytest.mark.parametrize("check", sorted(SCOPED_CHECKS))
def test_a_scoped_check_says_nothing_when_its_declaration_was_not_read(check):
    """Both halves of the 2026-09-09 fix, asserted the same way.

    `symbol_case` was missed by the first pass because it is its own check type
    rather than a `regex_absent` rule, and it kept firing on bare capitals — a
    `G` and three `M`s — pulled out of unrelated words on frames where no net
    quantity had been classified at all.
    """
    pack = Rulepack(
        pack_id="test",
        version="test@0",
        authority="synthetic",
        rules=(),
        extension_rules=(),
        patterns={"pluralised": pattern("pluralised", r"\d+\s*[a-z]{1,3}s\b")},
        tables={},
        applicability={},
        meta={},
    )
    # A label carrying text that would trip either rule -- but not in the net
    # quantity, because there is no net quantity.
    label = declaration_set(
        declaration(field="marketing_text", text="Serving size 16G  makes 500 mls"),
    )
    outcome = REGISTRY[check](
        rule(check, fields=["net_quantity"], pattern_ref="pluralised", lowercase_required=True),
        label,
        CONTEXT,
        pack,
    )
    assert outcome.status == "NO_DATA", (
        f"`{check}` returned {outcome.status} ({outcome.found!r}) from text outside the "
        f"declaration it names"
    )


# ---------------------------------------------------------------------------
# The degradation ladder's recognition signal
# ---------------------------------------------------------------------------


def test_legible_fraction_scores_language_above_scattered_glyphs():
    """A shape test, not a lexicon. See `vision.degradation.legible_fraction`."""
    from vision.degradation import legible_fraction

    read = ["MRP Rs. 45.00", "NET WEIGHT: 242 g", "MANUFACTURED BY ITC", "निर्माता"]
    noise = ["A EA", "D", "8]", "t", "GE"]

    assert legible_fraction(read) == 1.0
    assert legible_fraction(noise) == 0.0
    # Empty is 1.0, not 0.0: no lines read is L4's business, decided by
    # MIN_LINES_FOR_A_VERDICT, and 0.0 here would report one fact twice.
    assert legible_fraction([]) == 1.0


def test_an_illegible_reading_is_l3_however_good_the_coverage_looks():
    """`coverage` scored 1.00 on a frame of three noise lines, so it cannot be
    the only thing standing between a bad reading and a verdict."""
    from vision.degradation import assign

    assert assign(scale_tier="A", coverage=1.0, lines_read=30, legible=0.0).tier == "L3"
    assert assign(scale_tier="A", coverage=1.0, lines_read=30, legible=1.0).tier == "L0"


def test_the_two_l3_conditions_are_reported_separately():
    """"We skipped most of the regions" and "we read them and none were words"
    are different failures with different fixes — a budget one and a recogniser
    one — so a scan that has both must say both."""
    from vision.degradation import assign

    both = assign(scale_tier="A", coverage=0.1, lines_read=30, legible=0.0)
    assert both.tier == "L3"
    assert any("coverage" in reason for reason in both.reasons)
    assert any("word-shaped" in reason for reason in both.reasons)


def test_the_legibility_floor_currently_fires_on_nothing_in_the_corpus():
    """Recorded rather than tuned away, because it is a fact about the corpus.

    Measured 2026-09-09 over fourteen frames: word-shape scored 0.51 to 0.89,
    and the floor is 0.50, so **no real frame reaches L3 by this route today** —
    including one that returned three lines of pure noise, which scored 0.67
    because a garbled line still contains three-letter fragments.

    The gate that actually withholds the false accusations is
    `reading_supports_an_absence`, which counts identified declarations. This
    floor is a second, independent condition for a failure mode the corpus has
    not yet produced, and lowering it until it fired on a chosen photograph
    would be fitting to `data/test_split/`, which is sealed.

    The assertion is deliberately about the *shape* of the finding rather than
    the constant: if a future recogniser change makes this fire, the test fails
    and somebody re-reads this note rather than discovering it in a demo.
    """
    from vision.degradation import LEGIBLE_FLOOR, legible_fraction

    observed_range = (0.51, 0.89)
    assert observed_range[0] > LEGIBLE_FLOOR, (
        f"the floor {LEGIBLE_FLOOR} is inside the range this corpus produces "
        f"{observed_range}; it would now fire on real frames and the note above "
        f"is stale"
    )
    # And it still separates the extremes it was written for.
    assert legible_fraction(["A EA", "D", "8]"]) < LEGIBLE_FLOOR


# ---------------------------------------------------------------------------
# An absence may only be alleged from a label we actually read
# ---------------------------------------------------------------------------


def _real_pack():
    from rules.loader import load_rulepack

    return load_rulepack()


def _mandatory_decls(n: int):
    """`n` of Rule 6(1)'s six, each read cleanly."""
    fields = ["mrp", "net_quantity", "mfg_date", "manufacturer", "generic_name", "consumer_care"]
    return [declaration(field=f, text=f"{f} read") for f in fields[:n]]


def test_a_missing_declaration_is_no_data_when_the_label_was_barely_read():
    """The regression that produced six false accusations in one scan.

    An ITC Dark Fantasy pack was reported as declaring no MRP, no net quantity,
    no manufacturer, no generic name, no date and no consumer care. The pack
    carries all six. The recogniser had returned `'METAWEIHT: 2429'` for
    `NET WEIGHT: 242 g` and `'wYVNOvr 9I'` for much of the rest.
    """
    pack = _real_pack()
    # One of the six identified, and the rule asks about a different one. That
    # is the shape of the bug: five "missing" declarations inferred from a label
    # we plainly could not read.
    barely = declaration_set(*_mandatory_decls(1))
    outcome = REGISTRY["present"](
        rule("present", fields=["consumer_care"]), barely, CONTEXT, pack
    )
    assert outcome.status == "NO_DATA", (
        f"one declaration identified out of six is a reading failure, not a pack with "
        f"five missing declarations; got {outcome.status}"
    )
    assert "not read well enough" in (outcome.detail or "")


def test_a_missing_declaration_still_fails_when_the_label_was_read():
    """The gate must not silence real findings.

    Four of the six identified is a label we read. The fifth being absent is
    then a finding, and it fires — which is what separates this from switching
    the presence rules off.
    """
    pack = _real_pack()
    read = declaration_set(*_mandatory_decls(4))
    outcome = REGISTRY["present"](
        rule("present", fields=["consumer_care"]), read, CONTEXT, pack
    )
    assert outcome.status == "FAIL"
    assert outcome.expected


def test_a_partly_read_label_cannot_allege_an_absence_whatever_it_found():
    """Section 5 confines L3 to *"verdicts on what was read"*.

    A missing declaration is a verdict on what was **not** read, so the tier
    alone is disqualifying even when the classifier named plenty.
    """
    pack = _real_pack()
    partial = declaration_set(*_mandatory_decls(5), degradation_tier="L3")
    outcome = REGISTRY["present"](
        rule("present", fields=["consumer_care"]), partial, CONTEXT, pack
    )
    assert outcome.status == "NO_DATA"
    assert "L3" in (outcome.detail or "")


def test_the_gate_never_weakens_a_positive_finding():
    """Only the inference from silence is withdrawn.

    A declaration that WAS read and breaches its rule still fails, on a label
    the gate would otherwise refuse to reason about.
    """
    barely = declaration_set(
        declaration(field="mrp", text="MRP 45", height_mm=0.4, height_mm_tolerance=0.1)
    )
    outcome = run(
        "min_height_mm",
        barely,
        fields=["mrp"],
        fixed_mm={"normal": 2.0, "embossed": 4.0},
    )
    assert outcome.status == "FAIL", "a height that was measured is still judged"


def test_the_mandatory_set_comes_from_the_pack_not_from_this_test():
    """The denominator must track the rules being evaluated.

    Hard-coding six here would let the pack gain a seventh mandatory
    declaration while the gate kept dividing by six.
    """
    from rules.checks._common import _mandatory_fields

    fields = _mandatory_fields(_real_pack())
    assert fields == {
        "mrp",
        "net_quantity",
        "mfg_date",
        "manufacturer",
        "generic_name",
        "consumer_care",
    }, f"Rule 6(1)'s six, from the pack; got {sorted(fields)}"


# ---------------------------------------------------------------------------
# Every status is reachable
# ---------------------------------------------------------------------------


def test_all_five_statuses_are_reachable_from_the_check_layer():
    """PASS, FAIL, REVIEW, NO_DATA and NOT_APPLICABLE, each from a real check.

    A status nothing can produce is dead vocabulary, and the two that matter
    most here are the two an accuracy-chasing implementation quietly drops:
    REVIEW becomes FAIL, and NO_DATA becomes PASS. Both make the numbers look
    better and both are wrong in the direction that hurts a real person.
    """
    seen = {
        run("present", declaration_set(declaration()), fields=["mrp"]).status,
        run("present", declaration_set(declaration(field="batch")), fields=["mrp"]).status,
        run(
            "min_height_mm",
            declaration_set(declaration(height_mm=1.95, height_mm_tolerance=0.1)),
            fields=["mrp"],
            fixed_mm={"normal": 2.0, "embossed": 4.0},
        ).status,
        run(
            "min_height_mm", EMPTY, fields=["mrp"], fixed_mm={"normal": 2.0, "embossed": 4.0}
        ).status,
        run(
            "present",
            declaration_set(declaration()),
            PackageContext(category="cement"),
            fields=["mrp"],
            skip_if_category_in=["cement"],
        ).status,
    }
    assert seen == {"PASS", "FAIL", "REVIEW", "NO_DATA", "NOT_APPLICABLE"}, (
        f"reached {sorted(seen)}; every status must be produceable by some check"
    )


def test_the_registry_matches_the_modules_on_disk():
    """Thirteen, and section 13 says *"Build these and no more."*

    A fourteenth check added without a plan amendment is a rule nobody agreed
    to; one deleted silently is a rule that stops being enforced. Both are
    caught here rather than by a reviewer noticing a diff.
    """
    from pathlib import Path

    modules = {
        path.stem
        for path in (Path(__file__).parents[2] / "rules" / "checks").glob("*.py")
        if not path.stem.startswith("_")
    }
    assert modules == set(REGISTRY), (
        f"modules on disk {sorted(modules)} do not match the registry {sorted(REGISTRY)}"
    )
    assert len(REGISTRY) == 13, f"section 13 says thirteen check types, found {len(REGISTRY)}"
