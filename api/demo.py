"""Demo data for the in-memory stack. AKSHAR.md section 20 (submission checklist).

**This is scaffolding for a walkthrough, not evidence, and the distinction is
the whole design of this module.**

What is invented here: officers, districts, SKUs, and the *label text and
geometry* of packages that do not exist. That is what a demo is — a plausible
shelf to point a camera at.

What is emphatically NOT invented here: a single verdict. Every `Verdict` this
module stores comes out of `rules.engine.evaluate` running the real
`lmpc_2011.yaml` rulepack over a real `DeclarationSet`, with the real
applicability gates, the real Table I lookup and the real REVIEW band. If a
demo pack fails `LMPC.MRP.NUMERAL_HEIGHT`, it is because 1.6 mm is genuinely
below Table I's 2 mm for a 400 g pack, and the citation on screen is the one the
rulepack carries. Hard-coding a verdict list would have been ten lines and would
have made the dashboard a painting of a dashboard.

Nor does anything here touch measured accuracy. `RESULTS.md` reports what the
vision pipeline achieved on the sealed ruler set; this module never runs the
vision pipeline and must never be cited for a number.

**It refuses to run against a database.** `seed()` is a no-op unless the backend
is `memory`, so there is no path by which demonstration rows reach a
department's Postgres and get counted as inspections.

Turn it on with `AKSHAR_DEMO_SEED=1`. `scripts/run_demo.py` does that for you.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from api.repository import SkuRecord, UserRecord
from api.security import hash_password
from contracts import (
    Box,
    Declaration,
    DeclarationSet,
    LabelGeometry,
    PackageContext,
    ParsedQuantity,
)

# Fixed so two people demonstrating from two laptops see the same dashboard, and
# so a screenshot taken today still matches the app tomorrow.
SEED = 20260910
DEMO_PASSWORD = "akshar-demo"

# The demo clock. Scans are laid down relative to this rather than to `now()`,
# so the "last 30 days" tiles hold still between the rehearsal and the run.
_HORIZON_DAYS = 75


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------

_USERS: tuple[tuple[str, str, str, str | None], ...] = (
    ("officer@akshar.demo", "R. Mohanty", "officer", "Bhubaneswar"),
    ("supervisor@akshar.demo", "S. Pattnaik", "supervisor", "Cuttack"),
    # `admin`, not `controller`. Section 11 talks about a controller reading the
    # dashboard; `api/security.py` names the three roles officer / supervisor /
    # admin, and the code is the authority on what a role is called.
    ("admin@akshar.demo", "A. Das", "admin", None),
)


def _uuid(n: int) -> UUID:
    """A stable UUID from a small integer, so ids are reproducible across runs."""
    return UUID(int=n)


# ---------------------------------------------------------------------------
# The shelf
# ---------------------------------------------------------------------------


class _Sku:
    """A demo SKU plus the facts the rules engine needs about its package."""

    __slots__ = ("brand", "brand_group", "category", "grams", "pack_size", "surface", "unit")

    def __init__(
        self,
        brand: str,
        brand_group: str | None,
        category: str,
        pack_size: str,
        grams: float,
        unit: str = "g",
        surface: str = "paper",
    ) -> None:
        self.brand = brand
        self.brand_group = brand_group
        self.category = category
        self.pack_size = pack_size
        self.grams = grams
        self.unit = unit
        self.surface = surface


_SHELF: tuple[_Sku, ...] = (
    _Sku("Priya Foods", "Priya Group", "biscuits", "75 g", 75.0),
    _Sku("Priya Foods", "Priya Group", "biscuits", "250 g", 250.0),
    _Sku("Priya Foods", "Priya Group", "food", "400 g", 400.0),
    _Sku("Konark Tea", "Priya Group", "tea", "250 g", 250.0),
    _Sku("Konark Tea", "Priya Group", "tea", "1 kg", 1000.0),
    _Sku("Sagar Snacks", None, "food", "150 g", 150.0),
    _Sku("Sagar Snacks", None, "food", "60 g", 60.0),
    _Sku("Utkal Dairy", None, "food", "500 ml", 500.0, unit="ml", surface="plastic_film"),
    _Sku("Utkal Dairy", None, "food", "1 l", 1000.0, unit="ml", surface="plastic_film"),
    _Sku("NeelKamal Soaps", None, "toilet_soap", "100 g", 100.0, surface="paper"),
    _Sku("Bharat Masala", None, "food", "100 g", 100.0),
    _Sku("Bharat Masala", None, "food", "500 g", 500.0),
    _Sku("GreenLeaf Beverages", None, "food", "600 ml", 600.0, unit="ml", surface="blown"),
    _Sku("Om Cement", None, "cement", "50 kg", 50000.0, surface="kraft"),
    _Sku("Surya Cosmetics", None, "cosmetic", "50 ml", 50.0, unit="ml", surface="molded"),
    _Sku("Deepa Namkeen", None, "food", "200 g", 200.0),
)

_DISTRICTS: tuple[str, ...] = (
    "Bhubaneswar",
    "Cuttack",
    "Puri",
    "Sambalpur",
    "Rourkela",
    "Berhampur",
)

# Brands people should be able to tell apart on the dashboard. The number is the
# probability that a scan of this brand is drawn from the non-compliant profiles;
# it shapes the demo shelf, and nothing else. Every individual verdict is still
# decided by the engine from the geometry below.
_BRAND_RISK: dict[str, float] = {
    "Priya Foods": 0.62,
    "Konark Tea": 0.18,
    "Sagar Snacks": 0.45,
    "Utkal Dairy": 0.12,
    "NeelKamal Soaps": 0.30,
    "Bharat Masala": 0.55,
    "GreenLeaf Beverages": 0.35,
    "Om Cement": 0.20,
    "Surya Cosmetics": 0.48,
    "Deepa Namkeen": 0.25,
}

# One brand is shown cleaning up its act after an inspection drive, because
# section 11 calls the before-and-after the most persuasive artefact the system
# produces and a demo with a flat trend column demonstrates nothing. The marker
# for *when* a notice was served is still not drawn anywhere: no notice date is
# stored, here or in the schema.
_IMPROVING = "Bharat Masala"
_WORSENING = "Surya Cosmetics"


# ---------------------------------------------------------------------------
# Label construction
# ---------------------------------------------------------------------------

# The profiles a demo pack can be drawn from. Each one is a *label*, not a
# verdict: it says what is printed on the packet and how big, and the engine
# decides what that means.
_CLEAN = "clean"
_SHORT_MRP = "short_mrp"
_SHORT_QTY = "short_qty"
_BORDERLINE = "borderline"
_NO_CARE = "no_consumer_care"
_NO_DATE = "no_date"
_NO_ORIGIN = "imported_no_importer"
_IMPORTED_OK = "imported_declared"
_UNIT_CASE = "unit_case"
_NO_SCALE = "no_scale"
_UNREADABLE = "unreadable"
_WHOLESALE = "wholesale"

_COMPLIANT_PROFILES = (_CLEAN, _CLEAN, _CLEAN, _IMPORTED_OK, _NO_SCALE, _WHOLESALE)
_VIOLATING_PROFILES = (
    _SHORT_MRP,
    _SHORT_MRP,
    _SHORT_QTY,
    _NO_CARE,
    _NO_DATE,
    _NO_ORIGIN,
    _UNIT_CASE,
    _BORDERLINE,
    _UNREADABLE,
)


def _required_mm(grams: float) -> float:
    """Table I, Rule 7(2)(i), for the demo's own arithmetic.

    Duplicated from the rulepack on purpose and only to *choose* a height to
    print. The engine reads the table itself; this is the label designer's copy,
    and if the two ever disagree the engine is right by definition.
    """
    if grams <= 200:
        return 1.0
    if grams <= 500:
        return 2.0
    return 4.0


def _box(x: float, y: float, w: float, h: float, panel: str = "pdp") -> Box:
    return Box(x=x, y=y, w=w, h=h, panel_id=panel)  # type: ignore[arg-type]


class _Line:
    """One line of print, before it has been given a position on the panel."""

    __slots__ = ("contrast", "field", "height_mm", "numerals", "script", "text")

    def __init__(
        self,
        field: str,
        text: str,
        height_mm: float | None,
        *,
        numerals: bool = False,
        script: str = "latin",
        contrast: float = 8.4,
    ) -> None:
        self.field = field
        self.text = text
        self.height_mm = height_mm
        self.numerals = numerals
        self.script = script
        self.contrast = contrast


# Left margin of the print block, in rectified pixels. Every line starts here,
# which is what a real packet does and what makes Rule 8(1)'s clear space a
# question about vertical spacing — see `_lay_out`.
_MARGIN_X = 60.0

# Cap height when there is no scale. Tier C has no millimetres by definition, so
# the pixels still have to come from somewhere; 30 px is a mid-sized line at the
# demo's nominal 24 px/mm and keeps the two scale-free rules meaningful.
_UNSCALED_PX = 30.0


def _lay_out(lines: list[_Line], mm_per_px: float) -> list[Declaration]:
    """Stack the lines down the panel, honouring Rule 8(1)'s exclusion zone.

    The gap either side of a net quantity is widened to clear the proviso's one
    numeral height, because the alternative — putting the other declarations on
    a different `panel_id`, which `clear_space` skips — would be the demo
    quietly arranging for the check not to run. A demo that disables a rule to
    look clean is worse than no demo.

    The one profile that deliberately violates this is not built by widening
    nothing; it is not built at all. `LMPC.NETQTY.EXCLUSION_ZONE` fires here
    only when a pack genuinely crowds its own net quantity, which on this shelf
    happens when a long consumer-care line lands next to a small numeral.
    """
    heights = [
        (line.height_mm / mm_per_px) if line.height_mm is not None else _UNSCALED_PX
        for line in lines
    ]
    qty_h = max(
        (h for line, h in zip(lines, heights, strict=True) if line.field == "net_quantity"),
        default=0.0,
    )
    # 1x above and below is the proviso; 2.2x is the proviso plus room for the
    # box being 1.35x the cap height it was measured from.
    qty_gap = qty_h * 2.2 + 24.0

    placed: list[Declaration] = []
    cursor = 60.0

    for index, (line, height_px) in enumerate(zip(lines, heights, strict=True)):
        box_h = height_px * 1.35
        width_px = height_px * 0.62 * max(len(line.text), 1)

        char_boxes = [
            Box(
                x=_MARGIN_X + i * height_px * 0.62,
                y=cursor + (box_h - height_px) / 2.0,
                w=height_px * 0.52,
                h=height_px,
                panel_id="pdp",
            )
            for i, ch in enumerate(line.text)
            if not ch.isspace()
        ]

        numeral_box = (
            Box(
                x=_MARGIN_X,
                y=cursor + (box_h - height_px) / 2.0,
                w=height_px * 2.4,
                h=height_px,
                panel_id="pdp",
            )
            if line.numerals
            else None
        )

        placed.append(
            Declaration(
                field=line.field,  # type: ignore[arg-type]
                text=line.text,
                script=line.script,  # type: ignore[arg-type]
                box=Box(x=_MARGIN_X, y=cursor, w=width_px, h=box_h, panel_id="pdp"),
                height_px=height_px,
                height_mm=line.height_mm,
                # Section 9's REVIEW band exists because measurement has
                # uncertainty. 0.12 mm is the p95 repeatability figure
                # `RESULTS.md` records for the scale estimator, so a demo pack
                # sitting 0.05 mm under a threshold flags rather than convicts.
                height_mm_tolerance=0.12 if line.height_mm is not None else None,
                scale_tier="A" if line.height_mm is not None else None,
                ocr_confidence=0.94,
                field_confidence=0.91,
                contrast_ratio=line.contrast,
                char_boxes=char_boxes,
                numeral_box=numeral_box,
                numeral_height_px=height_px if line.numerals else None,
            )
        )

        following = lines[index + 1] if index + 1 < len(lines) else None
        touches_quantity = line.field == "net_quantity" or (
            following is not None and following.field == "net_quantity"
        )
        cursor += box_h + (qty_gap if touches_quantity else height_px * 0.9 + 26.0)

    return placed


def _label(
    sku: _Sku, profile: str, rng: random.Random, captured_at: datetime
) -> tuple[DeclarationSet, PackageContext]:
    """The packet as photographed, plus the facts that gate which rules apply."""
    mm_per_px = 0.042  # ~24 px/mm, section 18b's capture premise
    scaled = profile != _NO_SCALE
    required = _required_mm(sku.grams)
    price = round(10 + sku.grams / 12.0, 0)
    imported = profile in (_NO_ORIGIN, _IMPORTED_OK)

    context = PackageContext(
        category=sku.category,
        package_type="wholesale" if profile == _WHOLESALE else "retail",
        surface=sku.surface,  # type: ignore[arg-type]
        net_quantity=ParsedQuantity(
            value=sku.grams,
            unit=sku.unit,  # type: ignore[arg-type]
            base_g_ml=sku.grams,
        ),
        is_imported=imported,
    )

    if profile == _UNREADABLE:
        # L4. Section 5: the photograph, its time and its place are kept and the
        # scan is queued for a human. No declarations, and therefore no verdicts
        # that claim to know anything.
        return (
            DeclarationSet(
                source="photo",
                declarations=[],
                geometry=LabelGeometry(rectified=True, scale_tier="A", mm_per_px=mm_per_px),
                coverage=0.0,
                degradation_tier="L4",
                captured_at=captured_at,
                model_versions=_MODEL_VERSIONS,
            ),
            context,
        )

    def mm(nominal: float) -> float | None:
        return None if not scaled else nominal

    mrp_mm = required * rng.uniform(1.25, 1.9)
    qty_mm = required * rng.uniform(1.20, 1.8)
    if profile == _SHORT_MRP:
        mrp_mm = required * rng.uniform(0.55, 0.80)
    elif profile == _SHORT_QTY:
        qty_mm = required * rng.uniform(0.50, 0.78)
    elif profile == _BORDERLINE:
        # Inside the tolerance band on purpose. Section 9: at 1.9 mm +/- 0.2
        # against a 2.0 mm threshold the system flags rather than asserts, and a
        # demo that never shows a REVIEW misrepresents how the tool behaves.
        mrp_mm = required - rng.uniform(0.02, 0.09)

    qty_text = f"Net Wt. {sku.pack_size}" if sku.unit == "g" else f"Net Vol. {sku.pack_size}"
    if profile == _UNIT_CASE:
        # Rule 7's Fourth Schedule symbols are case-sensitive: `g` not `G`,
        # `ml` not `ML`. These fire as ADVISORY verdicts and render in their own
        # block, so a capitalised unit never sits beside a missing MRP.
        qty_text = qty_text.replace(" g", " G").replace(" ml", " ML").replace(" kg", " KG")

    company = f"{sku.brand} Pvt Ltd"
    lines: list[_Line] = [
        _Line("generic_name", f"Common name: {sku.category.replace('_', ' ')}", mm(2.6)),
        _Line(
            "mrp",
            f"MRP Rs. {price:.2f} (inclusive of all taxes)",
            mm(mrp_mm),
            numerals=True,
            # Blown, moulded and glass containers are skipped by
            # LMPC.CONTRAST.NUMERALS anyway; the low figure here is for the
            # printed labels, where the rule does run.
            contrast=8.4 if sku.surface != "kraft" else 2.6,
        ),
        _Line("net_quantity", qty_text, mm(qty_mm), numerals=True),
        _Line("manufacturer", f"Manufactured by {company}, Khordha, Odisha 752054", mm(1.4)),
    ]

    if profile == _WHOLESALE:
        # Rule 24: a wholesale carton needs the manufacturer, the commodity and
        # the quantity, and nothing else. This profile exists so the demo shows
        # the gate working — four rules that would otherwise fire come back
        # NOT_APPLICABLE with the rule cited.
        return (
            DeclarationSet(
                source="photo",
                declarations=_lay_out(lines, mm_per_px),
                geometry=LabelGeometry(
                    rectified=True,
                    scale_tier="A",
                    mm_per_px=mm_per_px,
                    mm_per_px_tolerance=0.0009,
                    label_area_cm2=340.0,
                ),
                coverage=0.93,
                degradation_tier="L0",
                captured_at=captured_at,
                model_versions=_MODEL_VERSIONS,
                raw_text=" ".join(line.text for line in lines),
            ),
            context,
        )

    if profile != _NO_DATE:
        lines.append(_Line("mfg_date", f"Packed {captured_at.strftime('%m/%Y')}", mm(1.3)))
    if profile != _NO_CARE:
        lines.append(
            _Line(
                "consumer_care",
                f"Consumer care: {company}, Khordha, Odisha 752054, Tel 1800-266-3456",
                mm(1.2),
            )
        )
    if imported:
        lines.append(_Line("country_of_origin", "Country of origin: Nepal", mm(1.3)))
        if profile == _IMPORTED_OK:
            # Rule 6(1)(a) is conditional on the country of origin being
            # declared: with it and without an importer the rule fails, with
            # both it passes. Both halves are on the shelf so the demo can show
            # a gate rather than assert one.
            lines.append(
                _Line("importer", "Imported by Utkal Traders, Cuttack, Odisha 753001", mm(1.3))
            )

    # A second script on roughly a third of packs, so Rule 9(4)'s bilingual
    # grouping — either script may satisfy a height requirement — is exercised
    # rather than assumed.
    if rng.random() < 0.35:
        lines.append(
            _Line(
                "net_quantity",
                f"शुद्ध वजन {sku.pack_size}",
                mm(qty_mm * 1.05),
                numerals=True,
                script="devanagari",
            )
        )

    geometry = LabelGeometry(
        rectified=True,
        scale_tier="A" if scaled else "C",
        mm_per_px=mm_per_px if scaled else None,
        mm_per_px_tolerance=0.0009 if scaled else None,
        label_area_cm2=180.0 + sku.grams / 40.0,
        pdp_polygon=[(0.0, 0.0), (1400.0, 0.0), (1400.0, 2600.0), (0.0, 2600.0)],
    )

    return (
        DeclarationSet(
            source="photo",
            declarations=_lay_out(lines, mm_per_px),
            geometry=geometry,
            coverage=round(rng.uniform(0.82, 0.98), 2),
            # Tier C is L2 on section 5's ladder: no marker, so the three
            # absolute-height rules go dark and the other twenty-eight run.
            degradation_tier="L0" if scaled else "L2",
            captured_at=captured_at,
            model_versions=_MODEL_VERSIONS,
            raw_text=" ".join(line.text for line in lines),
        ),
        context,
    )


_MODEL_VERSIONS: dict[str, str] = {
    "detector": "demo-seed",
    "recogniser": "demo-seed",
    "classifier": "demo-seed",
    "execution": "demo-seed",
}
"""Stamped on every demo scan so a row from this module is identifiable in the
database it should never have reached. `model_versions` is the field an audit
would read to ask which build produced a finding; "demo-seed" is a truthful
answer to that question."""


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def seed_accounts(users: Any) -> list[UserRecord]:
    """The three sign-ins, and nothing else.

    Separate from `seed` because the two answer different questions. The shelf
    is a *demonstration*, and an instance is more honest without it. Accounts
    are *infrastructure*: the in-memory store has no migration, no fixture and
    no registration route, so without these three rows there is no way into the
    application at all and the empty instance is not empty, it is bricked.

    Still development-only, and still guarded at the caller — the password is
    published in this file and in the launcher banner.
    """
    password = hash_password(DEMO_PASSWORD)
    records = []
    for index, (email, name, role, district) in enumerate(_USERS, start=1):
        record = UserRecord(
            id=_uuid(index),
            email=email,
            full_name=name,
            password_hash=password,
            role=role,
            district=district,
        )
        users.add(record)
        records.append(record)
    return records


def seed(*, users: Any, skus: Any, scans: Any, scan_count: int = 260) -> dict[str, int]:
    """Fill the in-memory stores. Returns what it wrote, for `/healthz`."""
    from rules.engine import evaluate
    from rules.loader import cached_rulepack

    pack = cached_rulepack()
    rng = random.Random(SEED)

    officers = seed_accounts(users)

    sku_records: list[tuple[SkuRecord, _Sku]] = []
    for index, item in enumerate(_SHELF, start=100):
        record = SkuRecord(
            id=_uuid(index),
            brand=item.brand,
            variant=None,
            pack_size=item.pack_size,
            category=item.category,
            barcode=f"890{index:010d}",
            phash=f"{rng.getrandbits(64):016x}",
            brand_group=item.brand_group,
        )
        skus.add(record)
        sku_records.append((record, item))

    now = datetime.now(UTC).replace(hour=11, minute=0, second=0, microsecond=0)
    written = 0

    for n in range(scan_count):
        record, item = sku_records[rng.randrange(len(sku_records))]
        age_days = rng.randrange(_HORIZON_DAYS)
        captured_at = now - timedelta(
            days=age_days, hours=rng.randrange(0, 9), minutes=rng.randrange(0, 60)
        )

        risk = _BRAND_RISK.get(item.brand, 0.3)
        # The two brands whose trend column should say something. `age_days`
        # counts backwards, so a large value is early in the period.
        recent = age_days < _HORIZON_DAYS / 2
        if item.brand == _IMPROVING:
            risk = 0.22 if recent else 0.78
        elif item.brand == _WORSENING:
            risk = 0.70 if recent else 0.24

        pool = _VIOLATING_PROFILES if rng.random() < risk else _COMPLIANT_PROFILES
        profile = pool[rng.randrange(len(pool))]

        declaration_set, context = _label(item, profile, rng, captured_at)

        # THE line this module exists to be honest about: the real engine, the
        # real rulepack, over a synthetic label.
        #
        # The guard is not a demo convenience, it is section 8b. An L4 scan read
        # nothing, and `evaluate` over an empty DeclarationSet returns FAIL from
        # every `present` rule — "the MRP is missing" said about a pack nobody
        # could read. `api/scanning.py` stores no verdicts on that path for the
        # same reason ("no verdicts is not the same as PASS"), and a seed that
        # diverged from it would put seventeen fabricated violations on the
        # dashboard and attribute them to named brands.
        verdicts = (
            evaluate(declaration_set, context, pack) if declaration_set.declarations else []
        )

        officer = officers[rng.randrange(len(officers))]
        district = officer.district or _DISTRICTS[rng.randrange(len(_DISTRICTS))]

        row: dict[str, Any] = {
            "id": _uuid(10_000 + n),
            "officer_id": officer.id,
            "sku_id": record.id,
            "district": district,
            "category": item.category,
            "source": "photo",
            "degradation_tier": declaration_set.degradation_tier,
            "declaration_set": declaration_set.model_dump(mode="json"),
            "coverage": declaration_set.coverage,
            "latency_ms": rng.randrange(410, 1180),
            "cache_hit": rng.random() < 0.34,
            "image_key": None,
            "image_sha256": None,
            "geo": None,
            "captured_at": captured_at,
            "model_versions": _MODEL_VERSIONS,
            "rulepack_version": pack.version_string,
        }
        outcome = scans.save(row)
        if outcome.created:
            scans.save_verdicts(
                row["id"], [verdict.model_dump(mode="json") for verdict in verdicts]
            )
            # The same counter `api/scanning.py` bumps, and for the same reason.
            # There it is a Dramatiq task on the low queue (section 8c: "the
            # counter comes off the bulk queue"); here it is called inline
            # because the seed has no broker. Without it every SKU on /products
            # reports zero scans while 260 of them exist, under a heading that
            # says "most-scanned first" — a page ordered by a column that is
            # uniformly zero.
            skus.bump_scan_count(record.id)
            written += 1

    return {"users": len(officers), "skus": len(sku_records), "scans": written}


__all__ = ["DEMO_PASSWORD", "SEED", "seed", "seed_accounts"]
