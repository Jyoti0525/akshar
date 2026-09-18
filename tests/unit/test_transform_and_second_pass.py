"""B3's way back to the photograph, and B7's second reading. AKSHAR.md section 8b.

Both are about the same fact: a `Box` lives in rectified space, and the
photograph an officer took does not. B3 keeps the matrix that relates them; B7
uses it to fetch pixels the first pass had already interpolated three times.

The assertions below are mostly negative. A second pass that can make a reading
*worse*, or that quietly moves a measurement into a different pixel scale, would
be a net loss however often it helped — so most of what is tested is what these
two are forbidden to do.
"""

from __future__ import annotations

import numpy as np
import pytest

from contracts import Box
from vision.ocr import second_pass
from vision.types import OcrLine, Transform


def scaling_transform(factor: float = 2.0, dx: float = 10.0, dy: float = 20.0) -> Transform:
    """A benign affine warp: raw -> rectified is scale then translate."""
    homography = np.array([[factor, 0.0, dx], [0.0, factor, dy], [0.0, 0.0, 1.0]], dtype=np.float64)
    return Transform(
        homography=homography,
        method="quad",
        original_size=(600, 800),
        rectified_size=(1200, 1600),
    )


def perspective_transform() -> Transform:
    """A real perspective warp, of the kind a tilted pack produces."""
    import cv2

    source = np.array([[40, 30], [560, 70], [540, 420], [60, 380]], dtype=np.float32)
    destination = np.array([[0, 0], [499, 0], [499, 349], [0, 349]], dtype=np.float32)
    return Transform(
        homography=cv2.getPerspectiveTransform(source, destination).astype(np.float64),
        method="quad",
        original_size=(480, 640),
        rectified_size=(350, 500),
    )


def line(text: str = "MRP Rs 45", confidence: float = 0.5, **box) -> OcrLine:
    geometry = {"x": 100.0, "y": 80.0, "w": 120.0, "h": 24.0}
    geometry.update(box)
    return OcrLine(
        text=text,
        box=Box(**geometry),
        confidence=confidence,
        script="latin",
        cap_height_px=17.5,
        numeral_box=Box(x=150.0, y=82.0, w=60.0, h=20.0),
        char_boxes=[Box(x=100.0 + i * 12, y=80.0, w=10.0, h=24.0) for i in range(9)],
        engine="ppocr",
    )


# ---------------------------------------------------------------------------
# B3 — the transform
# ---------------------------------------------------------------------------


def test_a_point_survives_the_round_trip():
    transform = perspective_transform()
    for point in ((0.0, 0.0), (250.0, 175.0), (499.0, 349.0)):
        back = transform.point_to_original(point)
        assert back is not None
        again = transform.point_to_rectified(back)
        assert again == pytest.approx(point, abs=1e-6)


def test_a_box_maps_back_to_a_quadrilateral_not_a_rectangle():
    """The trap the type exists to prevent.

    Under a perspective warp the four corners of a rectified box are not the
    corners of an axis-aligned rectangle on the photograph. Drawing their
    bounding box on an exhibit would mark a region larger than the one actually
    measured — on a document whose whole purpose is to show what was measured.
    """
    transform = perspective_transform()
    quad = transform.box_to_original(Box(x=60.0, y=40.0, w=300.0, h=90.0))
    assert quad is not None

    top_left, top_right, _bottom_right, bottom_left = quad
    # If this were still a rectangle, the two top corners would share a y and
    # the two left corners an x.
    assert top_left[1] != pytest.approx(top_right[1], abs=1e-3)
    assert top_left[0] != pytest.approx(bottom_left[0], abs=1e-3)

    # And the bounding box of the quad is strictly larger than the quad, which
    # is exactly why no method here returns one.
    xs = [x for x, _ in quad]
    ys = [y for _, y in quad]
    bounding_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    shoelace = abs(
        sum(quad[i][0] * quad[(i + 1) % 4][1] - quad[(i + 1) % 4][0] * quad[i][1] for i in range(4))
        / 2
    )
    assert bounding_area > shoelace


def test_corner_order_is_preserved_so_a_drawn_polygon_never_self_intersects():
    transform = perspective_transform()
    quad = transform.box_to_original(Box(x=10.0, y=10.0, w=200.0, h=120.0))
    assert quad is not None

    # A simple (non-self-intersecting) quadrilateral has a non-zero signed area
    # whose sign matches a consistent winding. A transposed pair would produce a
    # bow-tie, whose shoelace area collapses towards zero.
    signed = (
        sum(quad[i][0] * quad[(i + 1) % 4][1] - quad[(i + 1) % 4][0] * quad[i][1] for i in range(4))
        / 2
    )
    assert abs(signed) > 100.0


def test_an_affine_transform_maps_exactly():
    transform = scaling_transform(factor=2.0, dx=10.0, dy=20.0)
    quad = transform.box_to_original(Box(x=10.0, y=20.0, w=40.0, h=8.0))
    assert quad == ((0.0, 0.0), (20.0, 0.0), (20.0, 4.0), (0.0, 4.0))


def test_the_identity_transform_knows_it_is_one():
    identity = Transform(
        homography=np.eye(3),
        method="identity",
        original_size=(100, 100),
        rectified_size=(100, 100),
    )
    assert identity.is_identity
    assert not scaling_transform().is_identity


def test_a_singular_matrix_returns_none_rather_than_raising():
    """A degenerate homography is a bad photograph, not a bug. The cost is one
    missing annotation on an exhibit, never a failed scan."""
    singular = Transform(
        homography=np.zeros((3, 3)),
        method="quad",
        original_size=(10, 10),
        rectified_size=(10, 10),
    )
    assert singular.inverse() is None
    assert singular.point_to_original((1.0, 1.0)) is None
    assert singular.box_to_original(Box(x=0.0, y=0.0, w=1.0, h=1.0)) is None


# ---------------------------------------------------------------------------
# B7 — the second pass, and what it may not do
# ---------------------------------------------------------------------------


class _Stub:
    """A recogniser that answers however the test needs it to."""

    def __init__(self, text: str, confidence: float, available: bool = True):
        self.text, self.confidence, self.available = text, confidence, available
        self.calls = 0

    def is_available(self, script="latin") -> bool:
        return self.available

    def recognise(self, crop, script="latin"):
        from vision.ocr.recognise import Recognised

        self.calls += 1
        return Recognised(self.text, self.confidence, ())


@pytest.fixture
def photograph():
    rng = np.random.default_rng(0)
    return rng.integers(0, 255, size=(480, 640, 3), dtype=np.uint8)


def _install(monkeypatch, stub: _Stub) -> None:
    from vision.ocr import recognise as real

    monkeypatch.setattr(real, "is_available", stub.is_available)
    monkeypatch.setattr(real, "recognise", stub.recognise)


def test_a_worse_second_reading_is_discarded(monkeypatch, photograph):
    """The safety property that makes this pass safe to leave switched on.

    If it could lower a reading's confidence it would have to be justified frame
    by frame; one that cannot is simply free.
    """
    stub = _Stub("MRP Rs 4S", 0.30)
    _install(monkeypatch, stub)

    first = [line("MRP Rs 45", confidence=0.50)]
    out, report = second_pass.reread(photograph, perspective_transform(), first)

    assert stub.calls == 1, "it did look"
    assert out[0].text == "MRP Rs 45"
    assert out[0].confidence == 0.50
    assert report.improved == 0


def test_a_better_second_reading_replaces_the_text_and_nothing_else(monkeypatch, photograph):
    """The measurement stays in the space `mm_per_px` was calibrated against.

    The re-cropped image genuinely has more pixels, so a cap height measured on
    it would be more precise -- and in a different pixel scale. A more precise
    number in the wrong units is worse than a coarser one in the right units,
    and the cap height is what becomes a millimetre figure on a notice.
    """
    stub = _Stub("MRP Rs 45", 0.94)
    _install(monkeypatch, stub)

    before = line("MRP Rs 4S", confidence=0.42)
    out, report = second_pass.reread(photograph, perspective_transform(), [before])

    assert out[0].text == "MRP Rs 45"
    assert out[0].confidence == pytest.approx(0.94)
    assert report.improved == 1
    assert report.changed_text == 1

    # Everything geometric is untouched, identically.
    assert out[0].box == before.box
    assert out[0].cap_height_px == before.cap_height_px
    assert out[0].numeral_box == before.numeral_box
    assert out[0].char_boxes == before.char_boxes
    assert out[0].script == before.script
    assert "2pass" in out[0].engine, "the record says which reading this was"


def test_a_shorter_reading_is_refused_however_confident_it_is(monkeypatch, photograph):
    """The defect the corpus found, and the reason this guard exists.

    `ctc_decode` sets confidence to the **mean** of the kept per-step scores, so
    a decoder that drops the characters it finds hardest comes back with a
    *higher* score for a worse reading. Accepting on confidence alone turned a
    licence number `' c.N 1310010409'` into `'  No 130029'` — four digits gone —
    and recorded it as an improvement. Measured on 20 corpus frames: 17 text
    changes, of which one was right.
    """
    stub = _Stub("No 130029", 0.99)
    _install(monkeypatch, stub)

    before = line("c.N 1310010409", confidence=0.40)
    out, report = second_pass.reread(photograph, perspective_transform(), [before])

    assert stub.calls == 1
    assert out[0].text == "c.N 1310010409", "characters dropped are evidence dropped"
    assert report.improved == 0


def test_a_marginal_confidence_gain_is_not_believed(monkeypatch, photograph):
    """0.01 on a mean of a dozen softmax scores is noise, not a better reading.

    Equal length, so the length guard above does not catch it; the margin does.
    """
    stub = _Stub("MRP Rs 46", 0.51)
    _install(monkeypatch, stub)

    out, report = second_pass.reread(
        photograph, perspective_transform(), [line("MRP Rs 45", confidence=0.50)]
    )
    assert out[0].text == "MRP Rs 45"
    assert report.improved == 0


def test_a_longer_decisive_reading_is_believed(monkeypatch, photograph):
    """The case this whole module exists for: a bracket read as a digit.

    Measured on the corpus — `'[014814'` at 0.76 became `'1014814'` at 0.90 once
    the crop came from the photograph rather than from twice-interpolated
    rectified pixels.
    """
    stub = _Stub("1014814", 0.90)
    _install(monkeypatch, stub)

    out, report = second_pass.reread(
        photograph, perspective_transform(), [line("[014814", confidence=0.76)]
    )
    assert out[0].text == "1014814"
    assert report.improved == 1
    assert report.changed_text == 1


def test_a_confident_line_is_never_re_read(monkeypatch, photograph):
    stub = _Stub("something else", 0.99)
    _install(monkeypatch, stub)

    out, report = second_pass.reread(
        photograph, perspective_transform(), [line("Net 100 g", confidence=0.97)]
    )
    assert stub.calls == 0
    assert report.considered == 0
    assert out[0].text == "Net 100 g"


def test_the_budget_bounds_the_work(monkeypatch, photograph):
    """A label with sixty doubtful lines is one the scan will report as partly
    unread whatever happens. Spending sixty warps to confirm that costs an
    officer time they are standing in a shop to spend."""
    stub = _Stub("x", 0.99)
    _install(monkeypatch, stub)

    lines = [line(f"line {i}", confidence=0.10 + i * 0.001, y=40.0 + i) for i in range(60)]
    _, report = second_pass.reread(photograph, perspective_transform(), lines, budget=5)

    assert report.considered == 60
    assert stub.calls <= 5
    assert report.reread <= 5


def test_the_worst_lines_go_first(monkeypatch, photograph):
    """With a budget smaller than the queue, the reading most likely to be wrong
    is the one that gets the second look."""
    seen: list[str] = []

    class Recording(_Stub):
        def recognise(self, crop, script="latin"):
            from vision.ocr.recognise import Recognised

            self.calls += 1
            seen.append(f"{crop.shape}")
            return Recognised("better", 0.99, ())

    stub = Recording("better", 0.99)
    _install(monkeypatch, stub)

    lines = [
        line("high", confidence=0.79, y=40.0),
        line("lowest", confidence=0.11, y=140.0),
        line("middle", confidence=0.45, y=240.0),
    ]
    out, _ = second_pass.reread(photograph, perspective_transform(), lines, budget=1)

    assert out[1].text == "better", "the 0.11 line was the one re-read"
    assert out[0].text == "high"
    assert out[2].text == "middle"


def test_an_identity_transform_skips_the_pass_entirely(monkeypatch, photograph):
    """The rectified image *is* the photograph, so the crop would come from the
    same pixels through the same interpolations. Nothing to gain, a budget to
    waste."""
    stub = _Stub("better", 0.99)
    _install(monkeypatch, stub)

    identity = Transform(
        homography=np.eye(3),
        method="identity",
        original_size=(480, 640),
        rectified_size=(480, 640),
    )
    out, report = second_pass.reread(photograph, identity, [line(confidence=0.2)])

    assert stub.calls == 0
    assert not report.ran
    assert out[0].text == "MRP Rs 45"


@pytest.mark.parametrize(
    ("original", "transform"),
    [(None, "perspective"), ("photo", None)],
)
def test_a_missing_input_is_an_ordinary_outcome(monkeypatch, photograph, original, transform):
    """Every reason it cannot run returns the lines unchanged. Nothing in the
    scan path may raise because a second pass was not possible."""
    stub = _Stub("better", 0.99)
    _install(monkeypatch, stub)

    lines = [line(confidence=0.2)]
    out, report = second_pass.reread(
        photograph if original == "photo" else None,
        perspective_transform() if transform == "perspective" else None,
        lines,
    )
    assert out == lines
    assert not report.ran
    assert stub.calls == 0


def test_a_missing_recognition_head_is_an_ordinary_outcome(monkeypatch, photograph):
    stub = _Stub("better", 0.99, available=False)
    _install(monkeypatch, stub)

    out, report = second_pass.reread(photograph, perspective_transform(), [line(confidence=0.2)])
    assert out[0].text == "MRP Rs 45"
    assert not report.ran


def test_a_recogniser_that_raises_never_breaks_the_scan(monkeypatch, photograph):
    """The Devanagari head may be absent while latin is present, and a crop can
    be degenerate. Either way the line keeps its first reading."""

    class Exploding(_Stub):
        def recognise(self, crop, script="latin"):
            self.calls += 1
            raise RuntimeError("no head for this script")

    stub = Exploding("", 0.0)
    _install(monkeypatch, stub)

    out, report = second_pass.reread(photograph, perspective_transform(), [line(confidence=0.2)])
    assert stub.calls == 1
    assert out[0].text == "MRP Rs 45"
    assert report.improved == 0


def test_an_empty_second_reading_is_not_an_improvement(monkeypatch, photograph):
    """A blank string at high confidence is the recogniser saying "no text
    here", and accepting it would erase a line the first pass did read."""
    stub = _Stub("   ", 0.99)
    _install(monkeypatch, stub)

    out, _ = second_pass.reread(photograph, perspective_transform(), [line(confidence=0.2)])
    assert out[0].text == "MRP Rs 45"


def test_a_line_from_outside_the_photograph_is_skipped(monkeypatch, photograph):
    """A homography can map rectified pixels to places the camera never saw.
    There are no original pixels to go back to, so there is nothing to read."""
    stub = _Stub("better", 0.99)
    _install(monkeypatch, stub)

    far_away = line(confidence=0.2, x=-99000.0, y=-99000.0)
    out, report = second_pass.reread(photograph, scaling_transform(), [far_away])
    assert stub.calls == 0
    assert out[0].text == "MRP Rs 45"
    assert report.reread == 0
