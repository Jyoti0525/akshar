"""The pipeline — three exits, cheapest first. AKSHAR.md sections 4 and 8.

    photo         ->  pHash -> cache? --hit-------->  replay verdicts    60 ms
    listing image ->  detect -> rectify -> scale
    listing text  ->  ROI OCR -> classify -> measure -> rules engine    561 ms

    "Exit zero — the cache. [...] Exit one — no product. [...] Exit two — the
     full path, only for a SKU we've genuinely never seen."   -- section 4

**This module orchestrates and decides nothing.** It returns a `DeclarationSet`
and the provenance around it; the verdicts come from `rules.engine`, which never
sees an image. Keeping that separation visible here is the point of the whole
design, and the reason the `listing_text` channel is four lines rather than a
second pipeline.

**Nothing in here raises on a missing model.** Weights absent, OCR head absent,
no marker, no readable text — each degrades and is reported. Section 5:

    "L4 is the one people forget. Even in the worst case the officer walks away
     with a timestamped evidence record. A tool that returns nothing when it
     can't read is worse than a notebook."

So the only way to get an exception out of `scan()` is to hand it something
that is not an image.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal, Protocol

from contracts import CaptureQuality, DeclarationSet, Framing, SourceChannel
from vision import degradation, runtime
from vision.classify import assemble
from vision.degradation import Degradation
from vision.detect import detector
from vision.identify import identify
from vision.ocr import roi, second_pass
from vision.quality import assess as assess_quality
from vision.quality import assess_framing
from vision.rectify.rectify import rectify
from vision.scale import coherence, tier_a, tier_b, tier_c
from vision.scale.resolve import resolve_scale
from vision.types import (
    XYWH,
    DetectionResult,
    Identity,
    Image,
    OcrResult,
    Point,
    RectifyMethod,
    RectifyResult,
    ScaleEstimate,
    TextRegion,
    Transform,
)

ExitPath = Literal["unusable", "cache_hit", "no_package", "full"]
"""`unusable` is B1's exit and it is listed first because it happens first.

It is not a failure: section 5's L4 record — the photograph, its time and its
place — is still produced, and the officer is told what to change. What does not
happen is a measurement, because a measurement taken from a blurred or
glare-blown frame is confidently wrong, which section 8 names as the worst
failure available to this project."""


class CacheLookup(Protocol):
    """Supplied by the API or the browser's IndexedDB store.

    `vision/` never opens a database or an HTTP connection; the caller owns
    both. Returns an opaque scan identifier whose verdicts are replayed.
    """

    def __call__(self, identity: Identity) -> str | None: ...


def _label_reader(
    lines: list[Any],
    rectified: Image | None,
    versions: dict[str, str],
) -> Any | None:
    """The vision model's read of the label, or `None` for every reason there
    is not one.

    Returns `None` — meaning "the OCR path's own classification stands" — when
    no reader is installed, when OpenCV cannot encode the crop, when the call
    fails or times out, when the reply does not parse, and when nothing the
    model said could be placed on a detected text region. Every one of those is
    an ordinary outcome and none of them is allowed to fail a scan.

    The reader's name is recorded in `model_versions` only once it has actually
    contributed, so a scan row never claims a model that did not touch it.
    """
    from vision import vlm

    if rectified is None or not lines:
        return None
    ready = vlm.availability()
    if not ready.ready:
        return None

    started = time.perf_counter()
    encoded = vlm.encode(rectified)
    if encoded is None:  # pragma: no cover - OpenCV is a hard dependency
        return None
    reply = vlm.provider.read(encoded, prompt=vlm.build())
    if reply is None:
        return None

    readings = vlm.parse(reply)
    if not readings:
        return None

    height, width = rectified.shape[:2]
    applied = vlm.apply(lines, readings, width=width, height=height)
    if not applied.fields:
        return None

    versions["label_reader"] = ready.name
    return replace(applied, elapsed_ms=(time.perf_counter() - started) * 1000.0)


@dataclass(frozen=True, slots=True)
class ScanOutcome:
    """Everything a scan produced, including how far it had to degrade."""

    exit_path: ExitPath
    identity: Identity
    degradation: Degradation
    timings_ms: dict[str, float] = field(default_factory=dict)
    model_versions: dict[str, str] = field(default_factory=dict)

    quality: CaptureQuality | None = None
    """B1's measurement of the frame itself. Present on every photograph — a
    frame that passed the gate carries its scores too, because "we checked and
    it was fine" is a different statement from "we did not check" and the scan
    record has to be able to tell them apart six months later.

    None for the `listing_text` channel, which has no pixels."""

    declarations: DeclarationSet | None = None
    """None on the three early exits. On `cache_hit` the caller replays the
    stored verdicts; on `no_package` there is nothing to judge; on `unusable`
    there is nothing that could be judged honestly."""

    framing: Framing | None = None
    """Whether the declaration panel was in shot at all — the other half of B1.

    `quality` above says the photograph is good; this says whether it is a
    photograph of the right side of the pack. Present only on the full path,
    because it is answered by looking for declarations and the earlier exits
    never look. It carries no status and suppresses nothing: `rules/` does not
    import it, and the inference from silence is withdrawn independently by
    `reading_supports_an_absence`. It is here so the officer's screen can say
    which way to turn the pack instead of showing an empty result."""

    cached_scan_id: str | None = None

    rectified: Image | None = None
    """The flattened label, kept so the caller can draw on it. Section 13.

    Handed back rather than re-derived later, because `Declaration.box` is in
    *this* image's coordinates. Rectifying the same photograph a second time
    finds its own label quad, and a quad that differs by a few pixels moves every
    box — so the annotated exhibit in the report would show rectangles that were
    never where the measurement was taken. `evidence/annotate.py` draws it.

    None on both early exits and whenever OpenCV never ran. It is an in-process
    reference, not part of the record: nothing is serialised from it.
    """

    scale: ScaleEstimate | None = None
    rectify_method: RectifyMethod | None = None

    transform: Transform | None = None
    """B3's way back to the photograph — the homography, and its inverse.

    `rectified` above is what the boxes were measured in; this is what turns one
    of those boxes into the quadrilateral it occupies on the officer's original
    photograph. Section 6 asks for an annotated exhibit, and an exhibit has to
    be the photograph that was taken rather than a warped rectangle nobody has
    seen.

    Kept beside `rectified` rather than folded into it because it outlives the
    pixels: three numbers per corner serialise, and a 12-megapixel array does
    not. None on both early exits and wherever OpenCV never ran."""
    detection: DetectionResult | None = None
    ocr: OcrResult | None = None
    message: str = ""
    """What to show the officer, in their words rather than ours."""

    @property
    def total_ms(self) -> float:
        return sum(self.timings_ms.values())


def _layout_head(
    lines: list[TextRegion] | list[Any],
    rectified: Image | None,
    versions: dict[str, str],
) -> dict[int, Any] | None:
    """Tier two's opinion on the address-shaped lines regex left as `other`.

    Returns `None` — meaning "regex tier only" — for every reason it cannot run,
    and never raises. Four things have to be present: address-shaped candidates,
    a rectified image to measure position against, the sentence embedder, and
    the trained head. Any of them missing is an ordinary outcome, not an error,
    and the scan proceeds on the patterns alone.

    The embedder is `bge-small-en-v1.5`, already in `data/models/` for retrieval
    and 384-dimensional, which is what `vision.classify.features.FEATURE_DIM`
    was sized for.
    """
    from vision.classify import model_tier

    if rectified is None or not lines:
        return None
    if not model_tier.is_available():
        return None

    try:
        rows = list(lines)
        candidates = assemble.address_candidates(rows, assemble.classify_lines(rows))
        if not candidates:
            return None

        from retrieval import embed

        if not embed.availability().ready:
            return None
        embedder = embed.shared()
        vectors = embedder.encode_passages([rows[i].text for i in candidates])
        embeddings = {index: vectors[n] for n, index in enumerate(candidates)}

        height, width = rectified.shape[:2]
        predictions = model_tier.classify_addresses(
            rows,
            embeddings,
            candidates=candidates,
            label_w=float(width),
            label_h=float(height),
        )
    except Exception:  # pragma: no cover - the tier is optional by design
        return None

    if predictions:
        versions.setdefault("field_classifier", model_tier.MODEL_FILENAME)
    return predictions or None


def _geometric_package_box(image: Image) -> XYWH | None:
    """Where the pack is, without the detector.

    Used when the detector weights are absent. It is the same quad search
    rectification already performs, so it costs nothing extra, and it is
    honestly weaker than the model: it finds *a* rectangle, not *a package*.
    The scan is degraded accordingly and says so, rather than silently
    pretending a detector ran.
    """
    from vision.rectify.rectify import find_label_quad

    quad = find_label_quad(image)
    if quad is None:
        return None
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


ESCALATION_FIELDS = ("mrp", "net_quantity")
"""What the cheap pass must find before we accept its answer.

Not "did we read anything" -- eight crops of ingredients list is a successful
read and a useless one. These two are the declarations every consumer package
must carry (Rules 6(1)(e) and 6(1)(b)), so a pack where neither appears is
either unreadable or was read in the wrong eight places, and both are worth a
second look.
"""


def _transform_of(rectified: RectifyResult, original: Image) -> Transform | None:
    """Pair M1's matrix with the two frame sizes, or `None` if there isn't one.

    The sizes are carried because the matrix alone cannot say whether a mapped
    point landed inside the photograph. A caller drawing an exhibit needs to
    know that; a caller measuring does not, which is why nothing in the
    measurement path reads this.
    """
    if rectified.homography is None:
        return None
    return Transform(
        homography=rectified.homography,
        method=rectified.method,
        original_size=original.shape[:2],
        rectified_size=rectified.image.shape[:2],
    )


def _read_and_escalate(
    rectified: Image,
    lines: list[TextRegion],
    *,
    pdp_polygon: list[Point] | None,
    mm_per_px: float | None,
    detect_ms: float,
    detect_version: str,
) -> OcrResult:
    """Read the crop budget; if no declaration surfaced, read further.

    **The cheap path is unchanged and costs nothing extra.** A pack whose MRP
    or net quantity appears in the first eight crops exits here exactly as
    before, which is most packs and every pack in a demo. The larger budget is
    spent only where the alternative is telling an officer the label could not
    be read -- and three seconds beats that answer every time.

    The decision uses `regex_tier`, which is the same rulepack pattern the
    engine itself uses to ask whether a declaration is present. Nothing here
    decides compliance; it decides only whether to look harder.
    """
    from vision.classify import regex_tier

    def read(limit: int) -> OcrResult:
        result = roi.read_regions(
            rectified, lines, pdp_polygon=pdp_polygon, limit=limit, mm_per_px=mm_per_px
        )
        return OcrResult(
            lines=result.lines,
            regions_proposed=result.regions_proposed,
            regions_read=result.regions_read,
            inference_ms=result.inference_ms + detect_ms,
            model_version=f"{detect_version}+{result.model_version}",
        )

    first = read(roi.MAX_REGIONS)
    if any(regex_tier.classify_line(line).field in ESCALATION_FIELDS for line in first.lines):
        return first
    if len(lines) <= roi.MAX_REGIONS:
        # Nothing left unread. Escalating would re-read the same crops.
        return first
    return read(roi.ESCALATED_REGIONS)


def scan(
    image: Image,
    *,
    source: SourceChannel = "photo",
    cache_lookup: CacheLookup | None = None,
    dimension_lookup: tier_b.DimensionLookup | None = None,
    operator_height_mm: float | None = None,
    online: bool = True,
    marker_edge_mm: float = tier_a.MARKER_EDGE_MM,
    marker_dictionary: str = tier_a.DEFAULT_DICTIONARY,
    is_embossed: bool = False,
    rulepack_version: str = "",
    quality_gate: bool = True,
) -> ScanOutcome:
    """Run extraction. Returns facts and provenance; never a verdict.

    The caller passes `outcome.declarations` to `rules.engine.evaluate` along
    with a `PackageContext`. That second step is deliberately not done here:
    the context carries facts about the package that no image contains
    (wholesale or retail, industrial or consumer, imported or not), and
    guessing them from pixels would put a compliance decision inside the
    extractor.
    """
    timings: dict[str, float] = {}
    versions: dict[str, str] = {"rulepack": rulepack_version} if rulepack_version else {}

    # -- B1: is this image usable at all? -----------------------------------
    #
    # Before the cache, before the detector, before anything. Section 8: the
    # measurement is what a bad frame corrupts, and it corrupts it *confidently*
    # — a motion-blurred `8` read as a `3` comes back with a high recogniser
    # score, because blur destroys the evidence before the confidence is
    # computed. Roughly 8 ms buys the ability to say "hold still" instead of
    # putting a wrong millimetre figure on an enforcement record.
    #
    # `quality_gate=False` measures without rejecting. It exists for the bench
    # harness, which has to be able to run the pipeline over the deliberately
    # bad frames in order to find out what the gate should reject.
    started = time.perf_counter()
    quality = assess_quality(image)
    timings["quality"] = (time.perf_counter() - started) * 1000.0

    # -- exit zero: identity, before any model runs -------------------------
    #
    # Computed even for a frame B1 is about to reject, and deliberately so. An
    # unusable frame still becomes an L4 record, and section 5 says that record
    # is the point — *"the officer walks away with a timestamped evidence
    # record"*. A record with no perceptual hash and no barcode cannot be
    # matched to a SKU afterwards, which is most of what makes it worth keeping.
    # The barcode in particular often survives the blur that ruined the printed
    # declaration, because it is designed to.
    #
    # This is a hash and a barcode read, not an analysis. Nothing expensive runs
    # before the gate, which is what B1 being "first" actually buys.
    started = time.perf_counter()
    from vision.identify.phash import normalise_for_hash

    normalised = normalise_for_hash(image)
    identity, _ = identify(normalised, image)
    timings["identity"] = (time.perf_counter() - started) * 1000.0

    if quality_gate and not quality.usable:
        return ScanOutcome(
            exit_path="unusable",
            identity=identity,
            quality=quality,
            degradation=degradation.assign(
                online=online, scale_tier=None, coverage=0.0, lines_read=0
            ),
            timings_ms=timings,
            model_versions=versions,
            message=quality.reason or "This photograph cannot be measured. Take another.",
        )

    if cache_lookup is not None:
        started = time.perf_counter()
        cached = cache_lookup(identity)
        timings["cache_lookup"] = (time.perf_counter() - started) * 1000.0
        if cached is not None:
            return ScanOutcome(
                exit_path="cache_hit",
                identity=identity,
                quality=quality,
                cached_scan_id=cached,
                degradation=degradation.assign(
                    online=online, scale_tier="A", coverage=1.0, lines_read=99
                ),
                timings_ms=timings,
                model_versions=versions,
                message="Already assessed. Replaying the stored verdicts for this SKU.",
            )

    # -- exit one: is there a product in frame at all? ----------------------
    started = time.perf_counter()
    detector_ran = True
    try:
        detection = detector.detect(image)
        versions["detector"] = detection.model_version
    except runtime.ModelUnavailableError:
        detector_ran = False
        detection = DetectionResult()
    timings["detect"] = (time.perf_counter() - started) * 1000.0

    if detector_ran and not detection.has_package():
        return ScanOutcome(
            exit_path="no_package",
            identity=identity,
            quality=quality,
            detection=detection,
            degradation=degradation.assign(
                online=online, scale_tier=None, coverage=0.0, lines_read=0
            ),
            timings_ms=timings,
            model_versions=versions,
            message="No packaged product found. Point the camera at a product.",
        )

    package = detection.best_package()
    package_box: XYWH | None = package.box if package else None
    if package_box is None:
        package_box = _geometric_package_box(image)

    # -- exit two: the full path -------------------------------------------
    #
    # The marker is detected ONCE, here, and its corners feed both stages:
    # rectification warps the plane against a shape known to be square, and
    # tier A measures that same shape for the scale. Section 8b's claim that
    # one detection yields "the scale *and* the homography" is only true if
    # they share a detection, which is why this does not live inside either.
    started = time.perf_counter()
    marker = tier_a.marker_quad(image, dictionary=marker_dictionary)
    rectified = rectify(image, marker=marker, package_box=package_box)
    timings["rectify"] = (time.perf_counter() - started) * 1000.0

    # The PDP polygon comes from the detector in raw space and must be carried
    # into rectified space, because every rule that uses it compares it against
    # boxes measured there.
    pdp_polygon = None
    panels = detection.panels()
    if panels and panels[0].polygon:
        from vision.rectify.rectify import map_point

        pdp_polygon = [map_point(rectified.homography, point) for point in panels[0].polygon]

    started = time.perf_counter()
    scale = resolve_scale(
        image,
        rectified.image,
        homography=rectified.homography,
        rectify_method=rectified.method,
        edge_mm=marker_edge_mm,
        dictionary=marker_dictionary,
        cache_key=identity.cache_key(),
        lookup=dimension_lookup,
        operator_height_mm=operator_height_mm,
        # A studio artwork render from an e-commerce listing cannot contain a
        # physical marker card, so tier A has nothing to find and is skipped
        # rather than run and rejected.
        allow_tier_a=source != "bulk_image",
    )
    timings["scale"] = (time.perf_counter() - started) * 1000.0

    started = time.perf_counter()
    try:
        # The scale is resolved above, and the ranking needs it: without a
        # millimetre the eight crops go to the largest print on the pack,
        # which is the brand name. See roi.DECLARATION_BAND_MM.
        #
        # Detection runs once here and its lines are reused if we escalate
        # below: it costs 705 ms on a 3000 px label, against 38 ms for a crop.
        lines, detect_ms, detect_version = roi.propose_lines(
            rectified.image, mm_per_px=scale.mm_per_px
        )
        ocr_result = _read_and_escalate(
            rectified.image,
            lines,
            pdp_polygon=pdp_polygon,
            mm_per_px=scale.mm_per_px,
            detect_ms=detect_ms,
            detect_version=detect_version,
        )
        versions["ocr"] = ocr_result.model_version

        # -- B7: the doubtful lines, read again from the photograph ---------
        #
        # After the escalation rather than inside it, and the order matters.
        # Escalation asks "did we read *enough of* the label"; this asks "did
        # we read *correctly* what we found". Running it first would spend the
        # budget re-reading lines the wider pass was about to supersede.
        #
        # It can only raise a line's confidence, and it touches no geometry —
        # see `vision/ocr/second_pass.py` for why the tempting second half of
        # that (re-measuring cap height on the sharper crop) is deliberately
        # not done.
        # `ENABLED` is False on the evidence of 2026-09-18 and that constant
        # carries the measurement: zero change to every accuracy figure on the
        # 38 labelled panels, against 336 ms whenever it fires. The call is left
        # here, wired and tested, so turning it on is one boolean rather than a
        # re-integration.
        if second_pass.ENABLED:
            transform = _transform_of(rectified, image)
            improved, second = second_pass.reread(image, transform, ocr_result.lines)
            if second.ran:
                ocr_result = replace(ocr_result, lines=improved)
                timings["ocr_second_pass"] = second.elapsed_ms
    except runtime.ModelUnavailableError:
        ocr_result = OcrResult()
    timings["ocr"] = (time.perf_counter() - started) * 1000.0

    tier = degradation.assign(
        online=online,
        scale_tier=scale.tier,
        coverage=ocr_result.coverage,
        lines_read=len(ocr_result.lines),
        detector_ran=detector_ran,
        legible=degradation.legible_fraction([line.text for line in ocr_result.lines]),
    )

    if not tier.is_usable:
        # L4. No verdicts, but the photograph, the timestamp and the location
        # are still stored by the caller. That record is the point.
        return ScanOutcome(
            exit_path="full",
            identity=identity,
            quality=quality,
            detection=detection,
            ocr=ocr_result,
            scale=scale,
            rectified=rectified.image,
            rectify_method=rectified.method,
            transform=_transform_of(rectified, image),
            degradation=tier,
            timings_ms=timings,
            model_versions=versions,
            message=(
                "Nothing legible was recovered. The photograph has been stored with "
                "its time and location and queued for review."
            ),
        )

    started = time.perf_counter()
    # -- M5 tier two: the layout head, for addresses regex cannot name --------
    #
    # Rule 6(1)(a)'s name-and-address, Rule 6(2)'s consumer care, the packer and
    # the importer are four declarations that look identical on the page: they
    # are all a company and a street. `regex_tier` can only find them by their
    # caption, so a pack printing `PARLE PRODUCTS PVT. LTD., VILE PARLE, MUMBAI
    # 400057` under somebody else's heading is invisible to it. That is exactly
    # what section 15b built this tier for.
    #
    # **This call did not exist until 2026-09-18.** `from_lines` has taken
    # `model_tier_predictions` since the tier was written and nothing ever
    # passed it, so the head was unreachable code: shipping the weights would
    # have changed nothing. Wired now, so the moment a trained head is dropped
    # into `data/models/` it is used.
    #
    # Absent weights, an absent embedder and a failure inside either are all the
    # same outcome — regex tier only — because section 15b is explicit that
    # shipping without this model is acceptable if the patterns separate the
    # fields well enough. It must never be able to fail a scan.
    predictions = _layout_head(ocr_result.lines, rectified.image, versions)

    # -- the label reader ---------------------------------------------------
    #
    # A vision model reads the photograph and says which declaration each piece
    # of text is. Everything below it is unchanged: the lines it rewrote are
    # measured, associated, grouped and de-duplicated by exactly the same code
    # as the lines it did not, so no millimetre in the record comes from the
    # model. `vision/vlm/` carries the measurement that justifies it and the
    # reason a reading with no detected text under it is dropped rather than
    # trusted.
    #
    # Absent is the default. With no reader installed this is one dictionary
    # lookup and the scan proceeds as it always did -- which is what keeps
    # section 5's L4 promise intact on a phone with no network.
    read_lines, reader_fields = ocr_result.lines, {}
    applied = _label_reader(ocr_result.lines, rectified.image, versions)
    if applied is not None:
        read_lines, reader_fields = applied.lines, applied.fields
        timings["label_reader"] = applied.elapsed_ms

    declarations = assemble.from_lines(
        read_lines,
        scale,
        reader_fields=reader_fields,
        source=source,
        coverage=ocr_result.coverage,
        degradation_tier=tier.tier,
        pdp_polygon=pdp_polygon,
        rectified=rectified.method == "quad",
        is_embossed=is_embossed,
        model_versions=versions,
        model_tier_predictions=predictions,
    )
    timings["classify"] = (time.perf_counter() - started) * 1000.0

    # -- does the scale survive contact with what it measured? --------------
    #
    # The last place a wrong pack height can be caught, and the only place the
    # one that got through can be. Every earlier guard asks whether the entered
    # number is believable; 20 mm is believable, and on a 150 mm jar it made
    # every letter measure seven and a half times too small and failed a
    # compliant pack on character height. The evidence that it was wrong exists
    # only here, in the result. See vision/scale/coherence.py.
    #
    # Demotion is to tier C and the declarations are re-assembled against it,
    # so what comes out is exactly what a scan with no scale at all would have
    # said -- not a scan with a scale quietly blanked out of it.
    incoherent = coherence.implausible(declarations.declarations)
    if incoherent is not None:
        scale = tier_c.estimate(incoherent)
        declarations = assemble.from_lines(
            read_lines,
            scale,
            reader_fields=reader_fields,
            source=source,
            coverage=ocr_result.coverage,
            degradation_tier=tier.tier,
            pdp_polygon=pdp_polygon,
            rectified=rectified.method == "quad",
            is_embossed=is_embossed,
            model_versions=versions,
            model_tier_predictions=predictions,
        )

    # -- B1, second half: was the declaration panel in shot? ----------------
    #
    # Only answerable here, after the read. Nothing in the raw pixels separates
    # a sharp photograph of a declaration panel from a sharp photograph of the
    # brand face, which is why this cannot live in the pre-gate above and why
    # 41 of the corpus's 122 frames sail through it. See vision/quality/framing.
    #
    # It replaces the message and nothing else. `declarations` goes to the
    # engine exactly as assembled, because a frame that showed no declaration
    # and a pack that carries none are different claims and only the engine,
    # holding the rulepack, is entitled to tell them apart.
    framing = assess_framing(declarations, line_count=len(ocr_result.lines))

    return ScanOutcome(
        exit_path="full",
        identity=identity,
        quality=quality,
        framing=framing,
        declarations=declarations,
        detection=detection,
        ocr=ocr_result,
        scale=scale,
        rectified=rectified.image,
        rectify_method=rectified.method,
        transform=_transform_of(rectified, image),
        degradation=tier,
        timings_ms=timings,
        model_versions=versions,
        message=framing.reason or tier.checks_available,
    )


def scan_listing_text(text: str, *, rulepack_version: str = "") -> ScanOutcome:
    """The third input channel — no image, no models, no geometry.

    Worth running live in a demo immediately after a photo scan: same rulepack,
    same engine, same verdict shapes, and the geometric rules honestly report
    NO_DATA instead of inventing measurements. Most teams read only "images".
    """
    started = time.perf_counter()
    declarations = assemble.from_listing_text(text)
    elapsed = (time.perf_counter() - started) * 1000.0

    tier = degradation.assign(
        online=True,
        scale_tier="C",
        coverage=1.0,
        lines_read=len(declarations.declarations),
        detector_ran=True,
    )
    return ScanOutcome(
        exit_path="full",
        identity=Identity(),
        declarations=declarations,
        degradation=tier,
        scale=tier_c.estimate("listing text has no pixels"),
        timings_ms={"classify": elapsed},
        model_versions=({"rulepack": rulepack_version} if rulepack_version else {}),
        message=(
            "Read from listing text. Presence, format, unit-symbol and schedule "
            "rules ran; every geometric rule returned NO_DATA."
        ),
    )


__all__ = ["CacheLookup", "ExitPath", "ScanOutcome", "scan", "scan_listing_text"]
