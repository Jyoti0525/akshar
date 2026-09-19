"""The annotated exhibit — AKSHAR.md sections 13 and 6.

The picture in the report is the one part of it a reader believes without
reading. That makes two failures much worse than having no picture at all, and
most of this file is about them:

- **boxes drawn in the wrong coordinate frame.** `Declaration.box` is in
  rectified label space. Drawn onto the camera frame, every rectangle lands
  somewhere plausible and wrong, and a report exhibit that points at the wrong
  text is evidence of something that never happened.
- **an advisory painted as a contravention.** A `250 ML` colouring the net
  quantity box red says, faster than any table can, that a formatting note is an
  offence.

Plus the privacy rule, which the annotation has to keep independently: it is
warped from the *unredacted* frame, so the blur applied to the evidence copy
does not carry across.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import numpy as np
import pytest

from contracts.declarations import Box, Declaration
from evidence import annotate, storage

CAPTURED = datetime(2026, 9, 8, 11, 30, tzinfo=UTC)


def _label(width: int = 900, height: int = 600):
    """A plain light panel. Content does not matter; geometry does."""
    return np.full((height, width, 3), 220, dtype=np.uint8)


def _declaration(field: str = "mrp", **overrides) -> Declaration:
    payload = {
        "field": field,
        "text": "MRP Rs. 10.00",
        "script": "latin",
        "box": Box(x=100.0, y=200.0, w=240.0, h=40.0),
        "height_px": 26.0,
        "height_mm": 0.82,
        "height_mm_tolerance": 0.09,
        "ocr_confidence": 0.9,
        "field_confidence": 0.9,
    }
    payload.update(overrides)
    return Declaration(**payload)


# ---------------------------------------------------------------------------
# The pen
# ---------------------------------------------------------------------------


def test_every_declaration_is_marked():
    result = annotate.draw(_label(), [_declaration(), _declaration("net_quantity")])

    assert result.available
    assert result.boxes == 2


def test_the_drawing_lands_where_the_declaration_is():
    """The one test that would catch boxes drawn in the wrong frame.

    A rectangle at x=100..340, y=200..240 must change those pixels and leave a
    patch far away untouched. If somebody ever draws on the raw photograph
    instead of the rectified label, the coordinates stop meaning this.

    The far-away patch is below and to the *left* of the box on purpose. A
    leader line runs rightward from a box to its row in the key, so anything to
    the right of a declaration is legitimately drawable; only the space the pen
    has no business in proves the point.
    """
    blank = _label()
    result = annotate.draw(blank, [_declaration()])

    on_the_box = result.image[200:241, 100:341]
    far_away = result.image[500:560, 20:90]

    assert not np.array_equal(on_the_box, blank[200:241, 100:341])
    assert np.array_equal(far_away, blank[500:560, 20:90])


def test_the_photograph_is_not_painted_over_by_the_key():
    """The whole point of the 2026-09-19 restyle.

    The key is its own panel, so the exhibit is larger than the photograph and
    `label_box` says where the photograph ends. Before this, the captions were
    chips laid on the packaging, and the answer to "what does the artwork under
    that caption say" was "we covered it up".
    """
    result = annotate.draw(_label(), [_declaration(), _declaration("net_quantity")])

    assert result.label_box == (0, 0, 900, 600)
    assert result.image.shape[:2] != (600, 900), "no key panel was added"


def test_a_wide_label_gets_its_key_underneath_and_a_tall_one_beside():
    """Not a style choice; it is what keeps the exhibit from being mostly blank.

    A declaration panel is usually landscape. One tall column of eighteen rows
    beside it made an exhibit twice the height of the photograph with the lower
    half empty, and a PDF scales that down until the millimetre figures are
    unreadable.
    """
    rows = [_declaration(), _declaration("net_quantity"), _declaration("batch")]

    wide = annotate.draw(_label(900, 600), rows)
    tall = annotate.draw(_label(600, 900), rows)

    assert wide.image.shape[1] == 900, "a landscape label must not grow wider"
    assert wide.image.shape[0] > 600
    assert tall.image.shape[1] > 600, "a portrait label must not grow taller"
    assert tall.image.shape[0] == 900


def test_the_measured_glyphs_are_outlined_separately():
    """A height rule measures the numerals, not "MRP Rs. 10.00 (incl. of taxes)".

    The report says 0.82 mm; the exhibit has to show which characters that was.
    """
    with_numerals = _declaration(numeral_box=Box(x=160.0, y=205.0, w=90.0, h=30.0))

    drawn = annotate.draw(_label(), [with_numerals]).image
    plain = annotate.draw(_label(), [_declaration()]).image

    assert not np.array_equal(drawn, plain)


def test_the_caption_carries_the_tolerance():
    assert annotate.caption_for(_declaration()) == "MRP  0.82 +/- 0.09 mm"


def test_a_declaration_with_no_scale_is_captioned_without_a_number():
    """Tier C measured nothing. Printing a millimetre figure would invent one."""
    assert annotate.caption_for(_declaration(height_mm=None)) == "MRP"


def test_a_declaration_with_no_box_is_skipped_not_crashed_on():
    assert annotate.draw(_label(), [object()]).boxes == 0


def test_there_is_no_annotation_without_a_rectified_label():
    result = annotate.draw(None, [_declaration()])

    assert not result.available
    assert "nothing" in result.detail or "no rectified" in result.detail


# ---------------------------------------------------------------------------
# Which colour, and the three counting rules again
# ---------------------------------------------------------------------------


def test_an_advisory_verdict_never_colours_a_box():
    """Section 13c's separation, restated in pixels.

    `250 ML` is a formatting defect. A red box around the net quantity would
    assert a contravention of the Packaged Commodities Rules in the most
    immediate way a document can.
    """
    statuses = annotate.statuses_from(
        [{"field": "net_quantity", "status": "FAIL", "advisory": True}]
    )

    assert statuses == {}


def test_a_suppressed_verdict_never_colours_a_box():
    statuses = annotate.statuses_from(
        [
            {"field": "mrp", "status": "PASS"},
            {"field": "mrp", "status": "FAIL", "suppressed_by": "LMPC.MRP.NUMERAL_HEIGHT"},
        ]
    )

    assert statuses == {"mrp": "PASS"}


def test_the_worst_countable_status_wins():
    statuses = annotate.statuses_from(
        [
            {"field": "mrp", "status": "PASS"},
            {"field": "mrp", "status": "FAIL"},
            {"field": "mrp", "status": "REVIEW"},
        ]
    )

    assert statuses == {"mrp": "FAIL"}


def test_a_field_with_no_verdict_is_drawn_but_not_coloured():
    """Grey is the truthful appearance: we read it and concluded nothing."""
    coloured = annotate.draw(_label(), [_declaration()], statuses={"mrp": "FAIL"}).image
    uncoloured = annotate.draw(_label(), [_declaration()], statuses={}).image

    assert not np.array_equal(coloured, uncoloured)


def test_the_legend_is_derived_from_the_colours_that_draw():
    """A legend maintained beside the renderer drifts from the pen.

    Every entry's swatch must be a colour this module actually uses, so adjusting
    one cannot leave the report mislabelling an exhibit.
    """
    used = {
        annotate._hex(colour)
        for colour in (
            *annotate.BOX_COLOURS.values(),
            annotate.NUMERAL_COLOUR,
            annotate.CONTEXT_COLOUR,
            annotate.GROUP_COLOUR,
        )
    }

    assert {colour for _, _, colour in annotate.LEGEND} <= used


def test_the_legend_and_the_key_panel_use_one_set_of_words():
    """`STATUS_WORDS` feeds both, so the report's legend cannot come to describe
    a status the exhibit has stopped naming that way."""
    for status, word in annotate.STATUS_WORDS.items():
        assert any(label == word for label, _meaning, _colour in annotate.LEGEND), status


# ---------------------------------------------------------------------------
# One printed block, and the lines drawn to a finding
# ---------------------------------------------------------------------------


def _address(field: str, y: float):
    return _declaration(
        field, box=Box(x=60.0, y=y, w=300.0, h=26.0), height_mm=None, height_mm_tolerance=None
    )


def test_an_address_printed_as_one_paragraph_is_enclosed_once():
    """Four rectangles around four lines of one address read as four findings.

    The rules judge manufacturer, packer and consumer care separately and the
    key still lists them separately; the region only says what the label did.
    """
    result = annotate.draw(
        _label(),
        [_address("manufacturer", 100.0), _address("packer", 132.0), _address("consumer_care", 164.0)],
    )

    assert result.regions == 1
    assert result.boxes == 3, "grouping must not merge the boxes it encloses"


def test_declarations_scattered_across_the_panel_are_not_enclosed():
    """A region round two boxes at opposite corners is a rectangle round the
    whole label asserting a closeness the printing does not have."""
    result = annotate.draw(
        _label(),
        [_address("manufacturer", 20.0), _address("packer", 540.0)],
    )

    assert result.regions == 0


def test_one_address_line_alone_is_not_a_block():
    assert annotate.draw(_label(), [_address("manufacturer", 100.0)]).regions == 0


def test_the_region_carries_no_status_of_its_own():
    """The guard that keeps grouping from becoming an accusation.

    A failing manufacturer beside a passing packer must not paint the packer's
    address with the manufacturer's verdict, so the enclosing colour is fixed
    and is none of the status colours.
    """
    assert annotate.GROUP_COLOUR not in set(annotate.BOX_COLOURS.values())

    failing = annotate.draw(
        _label(),
        [_address("manufacturer", 100.0), _address("packer", 132.0)],
        statuses={"manufacturer": "FAIL"},
    )

    assert failing.regions == 1


def test_only_a_finding_gets_a_line_drawn_to_its_row():
    """A leader from every box to every row is twelve crossing lines, which is
    the clutter back in a new form. The numbered badge finds the rest."""
    blank = _label()
    declarations = [_declaration(), _declaration("net_quantity")]

    quiet = annotate.draw(blank, declarations, statuses={"mrp": "PASS", "net_quantity": "PASS"})
    accused = annotate.draw(blank, declarations, statuses={"mrp": "FAIL", "net_quantity": "PASS"})

    # Empty label below both boxes and clear of every badge. Only a leader on
    # its way to the key can put a mark here.
    lane = (slice(300, 560), slice(60, 500))
    assert np.array_equal(quiet.image[lane], blank[lane]), "a passing box drew a line"
    assert not np.array_equal(accused.image[lane], blank[lane])


def test_nothing_drawn_on_the_exhibit_is_outside_ascii():
    """`cv2.putText` renders one black lozenge per character it has no glyph
    for. On the line of an exhibit that says what was measured."""
    for text in (
        *annotate.FIELD_LABELS.values(),
        *annotate.STATUS_WORDS.values(),
        *(title for title, _fields in annotate.FAMILIES),
        annotate.caption_for(_declaration()),
        annotate.measurement_for(_declaration()),
    ):
        assert text.isascii(), text


# ---------------------------------------------------------------------------
# Size and storage
# ---------------------------------------------------------------------------


def test_a_large_label_is_scaled_down_and_the_boxes_scale_with_it():
    """Section 6 budgets the derived tier at roughly 40 KB.

    Scaling the canvas without scaling the coordinates is the obvious way to get
    this wrong, and it would put every box in the top-left corner.
    """
    big = np.full((2400, 3600, 3), 220, dtype=np.uint8)
    declaration = _declaration(box=Box(x=2000.0, y=1500.0, w=600.0, h=120.0))

    result = annotate.draw(big, [declaration])

    # MAX_EDGE_PX budgets the *photograph*. The key beside it is flat colour and
    # ASCII, which is the cheapest thing a JPEG can carry.
    _x, _y, label_w, label_h = result.label_box
    assert max(label_w, label_h) == annotate.MAX_EDGE_PX

    factor = label_w / 3600.0
    x, y = int(2000 * factor), int(1500 * factor)
    patch = result.image[y : y + 40, x : x + 40]
    assert not np.array_equal(patch, np.full_like(patch, 220))


def test_the_annotation_key_sits_beside_the_photograph_it_illustrates():
    scan_id = "abc-123"

    assert (
        storage.annotation_key(scan_id, captured_at=CAPTURED)
        == "2026/09/08/abc-123/annotated.jpg"
    )
    assert storage.object_key(scan_id, captured_at=CAPTURED).startswith("2026/09/08/")


def test_the_annotation_is_derived_and_never_lands_in_the_evidence_bucket():
    """Seven years and a governance lock are for the photograph, not for a
    drawing over it that can be reproduced from the stored declaration set."""
    puts: list[tuple[str, str]] = []

    class Store:
        def put_object(self, bucket, key, data, length, **kwargs):
            puts.append((bucket, key))

    stored = storage.put_annotation(
        Store(), b"\xff\xd8jpeg", scan_id="abc-123", captured_at=CAPTURED
    )

    assert puts == [(storage.DERIVED_BUCKET, "2026/09/08/abc-123/annotated.jpg")]
    assert stored.tier == "derived_crop"
    assert stored.retention_days == 365 * 2


# ---------------------------------------------------------------------------
# The scan path: privacy, and the storage plan's own gate
# ---------------------------------------------------------------------------


class _Outcome:
    def __init__(self, image, declarations, method="quad"):
        self.rectified = image
        self.declarations = declarations
        self.rectify_method = method


class _Declarations:
    def __init__(self, declarations):
        self.declarations = declarations


def _plan(*, crops: bool):
    return storage.StoragePlan(
        upload_original=crops, upload_crops=crops, tier="derived_crop", reason="because"
    )


def test_no_annotation_when_the_storage_plan_stores_nothing():
    """A repeat SKU uploads nothing at all. The annotation follows section 6's
    table rather than inventing a second policy."""
    from api.scanning import prepare_annotation

    payload, note = prepare_annotation(
        _Outcome(_label(), _Declarations([_declaration()])),
        [],
        plan=_plan(crops=False),
        blur_faces=True,
    )

    assert payload is None
    assert "because" in note


def test_no_annotation_when_nothing_was_extracted():
    from api.scanning import prepare_annotation

    payload, note = prepare_annotation(
        _Outcome(None, None), [], plan=_plan(crops=True), blur_faces=True
    )

    assert payload is None
    assert "nothing was extracted" in note


def test_the_annotation_is_a_jpeg_and_says_what_it_marked():
    from api.scanning import prepare_annotation

    payload, note = prepare_annotation(
        _Outcome(_label(), _Declarations([_declaration()])),
        [{"field": "mrp", "status": "FAIL"}],
        plan=_plan(crops=True),
        blur_faces=True,
    )

    assert payload is not None
    assert payload[:2] == b"\xff\xd8"  # JPEG SOI
    assert "1 declaration" in note


def test_a_rectified_label_treats_a_face_on_it_as_printed_artwork(monkeypatch):
    """The Amul girl is not a bystander.

    When rectification warped to the label, the frame *is* the package, so a
    detected face is printing and must survive — blurring it would delete label
    content from the exhibit that is supposed to show the label.
    """
    from api import scanning

    seen: list[object] = []

    def fake_redact(image, *, package_box=None):
        seen.append(package_box)
        return scanning.redact.Redaction(image=image, available=True)

    monkeypatch.setattr(scanning.redact, "redact_faces", fake_redact)
    scanning.prepare_annotation(
        _Outcome(_label(), _Declarations([_declaration()]), method="quad"),
        [],
        plan=_plan(crops=True),
        blur_faces=True,
    )

    assert seen == [(0, 0, 900, 600)]


def test_an_unrectified_frame_still_has_bystanders_in_it(monkeypatch):
    """`identity` means no warp happened: the frame is the whole photograph
    again, and whoever was standing behind the shelf is in it."""
    from api import scanning

    seen: list[object] = []

    def fake_redact(image, *, package_box=None):
        seen.append(package_box)
        return scanning.redact.Redaction(image=image, available=True)

    monkeypatch.setattr(scanning.redact, "redact_faces", fake_redact)
    scanning.prepare_annotation(
        _Outcome(_label(), _Declarations([_declaration()]), method="identity"),
        [],
        plan=_plan(crops=True),
        blur_faces=True,
    )

    assert seen == [None]


def test_the_annotation_fails_closed_when_redaction_cannot_run(monkeypatch):
    """Same rule as the evidence copy: no redaction, no stored image."""
    from api import scanning

    monkeypatch.setattr(
        scanning.redact,
        "redact_faces",
        lambda image, *, package_box=None: scanning.redact.Redaction(
            image=image, available=False, detail="cascade missing"
        ),
    )

    payload, note = scanning.prepare_annotation(
        _Outcome(_label(), _Declarations([_declaration()])),
        [],
        plan=_plan(crops=True),
        blur_faces=True,
    )

    assert payload is None
    assert "cascade missing" in note


# ---------------------------------------------------------------------------
# What the report does with it
# ---------------------------------------------------------------------------


def _jpeg() -> bytes:
    import cv2

    ok, buffer = cv2.imencode(".jpg", _label(160, 120))
    assert ok
    return buffer.tobytes()


def test_the_exhibit_is_embedded_not_linked():
    """WeasyPrint is given no base_url, and a filed report has no network."""
    from reports.model import Exhibit

    exhibit = Exhibit(jpeg=b"\xff\xd8abc")

    assert exhibit.data_uri.startswith("data:image/jpeg;base64,")
    assert len(exhibit.sha256) == 64


def test_the_report_prints_the_exhibit_and_its_legend():
    from reports import model, render

    report = model.build(
        scan={"id": uuid4(), "captured_at": CAPTURED},
        verdicts=[],
        exhibit=model.Exhibit(jpeg=_jpeg()),
    )
    html = render.to_html(report)

    assert "data:image/jpeg;base64," in html
    for label, _meaning, colour in annotate.LEGEND:
        assert label in html
        assert colour in html


def test_a_report_with_no_exhibit_says_why_rather_than_showing_a_gap():
    """Three quite different things end with no picture, and a reader is
    entitled to know which one applies."""
    from reports import model, render

    report = model.build(
        scan={"id": uuid4(), "captured_at": CAPTURED},
        verdicts=[],
        exhibit_note="no annotated image: repeat SKU",
    )
    html = render.to_html(report)

    assert "no annotated image: repeat SKU" in html
    assert "data:image/jpeg" not in html


def test_the_docx_embeds_the_exhibit_too():
    """The editable format is the one the problem statement names. An exhibit
    that only exists in the PDF is an exhibit half the readers never see."""
    pytest.importorskip("docx")
    import io
    import zipfile

    from reports import docx_writer, model

    report = model.build(
        scan={"id": uuid4(), "captured_at": CAPTURED},
        verdicts=[],
        exhibit=model.Exhibit(jpeg=_jpeg()),
    )
    with zipfile.ZipFile(io.BytesIO(docx_writer.to_docx(report))) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]

    assert media, "the annotated label was not embedded in the DOCX"


def test_the_assembler_reports_a_missing_annotation_rather_than_raising():
    from reports.assemble import NO_EXHIBIT_STORED, exhibit_for

    class Empty:
        def get_object(self, bucket, key):
            raise RuntimeError("NoSuchKey")

    exhibit, note = exhibit_for({"id": uuid4(), "captured_at": CAPTURED}, Empty())

    assert exhibit is None
    assert note == NO_EXHIBIT_STORED
