"""M3 Detect — letterbox arithmetic and RTMDet-Ins output decoding.

**Why this file exists.** `IMPLEMENTATION.md` claimed the detector decoder was
"verified against synthetic tensors". It was not — there was no test for it at
all, and the claim survived a plan switch unchallenged. It is easy to see how:
the decoder has no weights, so nothing fails when it is wrong, and the pipeline
catches `ModelUnavailableError` and degrades quietly. A decoder that transposes
the wrong axis would sail through every other test in this suite.

So these tests feed the decoder tensors shaped exactly as mmdeploy's
`instance-seg_rtmdet-ins_onnxruntime_static-640x640.py` export produces them,
with boxes at known coordinates, and assert the objects come back where they
were put. That is all a decoder test can do before the weights land — but it is
the half that catches sign errors, axis swaps and the letterbox inverse, which
are precisely the bugs that would otherwise be found by a wrong millimetre
number on stage.

What they cannot prove is accuracy. M3's real criteria — mAP >= 0.85, PDP IoU
>= 0.85, **zero false packages across 60 negatives** — need the corpus.
"""

from __future__ import annotations

import numpy as np
import pytest

from vision.detect.postprocess import CLASS_NAMES, decode
from vision.detect.preprocess import IMG_SIZE, letterbox

PACKAGE, PANEL = 0, 1


def _photo(width: int = 1200, height: int = 900) -> np.ndarray:
    return np.full((height, width, 3), 200, dtype=np.uint8)


def _end2end(
    boxes: list[tuple[float, float, float, float, float]],
    labels: list[int],
    masks: np.ndarray | None = None,
) -> list[np.ndarray]:
    """Tensors shaped as the mmdeploy end-to-end graph emits them."""
    dets = np.asarray([boxes], dtype=np.float32)  # (1, N, 5)
    lab = np.asarray([labels], dtype=np.int64)  # (1, N)
    return [dets, lab] if masks is None else [dets, lab, masks[np.newaxis, ...]]


# ---------------------------------------------------------------------------
# Letterbox — the inverse must actually be an inverse
# ---------------------------------------------------------------------------


def test_letterbox_produces_the_tensor_the_model_expects():
    tensor, box = letterbox(_photo())
    assert tensor.shape == (1, 3, IMG_SIZE, IMG_SIZE)
    assert tensor.dtype == np.float32
    assert tensor.min() >= 0.0 and tensor.max() <= 1.0
    assert box.original_w == 1200 and box.original_h == 900


@pytest.mark.parametrize(
    ("width", "height"),
    [(1200, 900), (900, 1200), (640, 640), (4000, 1000), (300, 2400)],
)
def test_letterbox_roundtrip_returns_the_original_box(width, height):
    """A box mapped into 640-space and back must land where it started.

    Run across wildly different aspect ratios because the padding axis flips
    between them, and a sign error in `pad_x` versus `pad_y` is invisible on a
    square test image — which is the one everybody writes.
    """
    _tensor, box = letterbox(_photo(width, height))

    original = (0.2 * width, 0.3 * height, 0.25 * width, 0.15 * height)
    forward = (
        original[0] * box.scale + box.pad_x,
        original[1] * box.scale + box.pad_y,
        original[2] * box.scale,
        original[3] * box.scale,
    )
    assert box.to_original(forward) == pytest.approx(original, rel=1e-6)


def test_clip_keeps_a_half_cropped_pack_but_refuses_a_negative_box():
    """An officer's hand cropping the pack is normal; a negative width is not."""
    _tensor, box = letterbox(_photo(1200, 900))

    x, y, w, h = box.clip((-50.0, -30.0, 400.0, 300.0))
    assert (x, y) == (0.0, 0.0)
    assert w > 0 and h > 0

    _x, _y, w2, h2 = box.clip((5000.0, 5000.0, 100.0, 100.0))
    assert w2 >= 1.0 and h2 >= 1.0


# ---------------------------------------------------------------------------
# decode — the RTMDet-Ins end-to-end contract
# ---------------------------------------------------------------------------


def test_decode_places_a_box_where_the_model_put_it():
    """The whole point: 640-space in, source-photo pixels out."""
    _tensor, box = letterbox(_photo(1280, 640))

    # A box covering the middle of the letterboxed square.
    outputs = _end2end([(160.0, 200.0, 480.0, 440.0, 0.91)], [PACKAGE])
    objects = decode(outputs, box)

    assert len(objects) == 1
    found = objects[0]
    assert found.cls == "package"
    assert found.score == pytest.approx(0.91)

    expected = box.clip(box.to_original((160.0, 200.0, 320.0, 240.0)))
    assert found.box == pytest.approx(expected, rel=1e-6)


def test_decode_respects_the_label_tensor():
    """Class comes from `labels`, never from position or score order.

    Getting this wrong relabels every detection, and the symptom is a panel
    polygon used as the package box — which measures the wrong thing without
    ever looking broken.
    """
    outputs = _end2end(
        [(100.0, 100.0, 300.0, 300.0, 0.9), (120.0, 120.0, 200.0, 200.0, 0.8)],
        [PANEL, PACKAGE],
    )
    _tensor, box = letterbox(_photo())
    objects = decode(outputs, box)

    assert [o.cls for o in objects] == ["panel", "package"]


def test_decode_drops_the_zero_score_padding():
    """mmdeploy pads to a fixed length. Those rows are not detections."""
    outputs = _end2end(
        [
            (100.0, 100.0, 300.0, 300.0, 0.88),
            (0.0, 0.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0, 0.0, 0.0),
        ],
        [PACKAGE, PACKAGE, PACKAGE],
    )
    _tensor, box = letterbox(_photo())
    assert len(decode(outputs, box)) == 1


def test_decode_honours_the_confidence_threshold():
    outputs = _end2end(
        [(100.0, 100.0, 300.0, 300.0, 0.40), (100.0, 100.0, 300.0, 300.0, 0.10)],
        [PACKAGE, PANEL],
    )
    _tensor, box = letterbox(_photo())
    assert len(decode(outputs, box, conf_threshold=0.25)) == 1
    assert len(decode(outputs, box, conf_threshold=0.50)) == 0


def test_decode_ignores_a_class_the_rulepack_cannot_name():
    """A stray class index must be skipped, never coerced to `package`.

    Coercing would let a shelf edge become the thing we measure.
    """
    outputs = _end2end([(100.0, 100.0, 300.0, 300.0, 0.99)], [len(CLASS_NAMES) + 3])
    _tensor, box = letterbox(_photo())
    assert decode(outputs, box) == []


def test_decode_turns_a_mask_into_a_polygon_in_source_pixels():
    """The PDP outline is what Rule 8(1) and Rule 9(1) are checked against."""
    masks = np.zeros((1, IMG_SIZE, IMG_SIZE), dtype=np.float32)
    masks[0, 200:400, 150:450] = 1.0
    outputs = _end2end([(150.0, 200.0, 450.0, 400.0, 0.93)], [PANEL], masks)

    _tensor, box = letterbox(_photo(1280, 640))
    objects = decode(outputs, box)

    assert len(objects) == 1
    polygon = objects[0].polygon
    assert polygon is not None and len(polygon) >= 4

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    expected_x, expected_y, expected_w, expected_h = box.to_original((150.0, 200.0, 300.0, 200.0))
    assert min(xs) == pytest.approx(expected_x, abs=6.0)
    assert min(ys) == pytest.approx(expected_y, abs=6.0)
    assert max(xs) - min(xs) == pytest.approx(expected_w, abs=8.0)
    assert max(ys) - min(ys) == pytest.approx(expected_h, abs=8.0)


def test_decode_without_masks_is_the_u4_fallback():
    """Section 18b U4: bbox detection plus classical quad recovery.

    If instance-seg export fights us, we drop the mask head. The decoder must
    keep working and simply return no polygon, so `clear_space` degrades to the
    box instead of the pipeline breaking.
    """
    outputs = _end2end([(100.0, 100.0, 300.0, 300.0, 0.9)], [PACKAGE])
    _tensor, box = letterbox(_photo())
    objects = decode(outputs, box)
    assert len(objects) == 1
    assert objects[0].polygon is None


# ---------------------------------------------------------------------------
# The contract is checked, not assumed
# ---------------------------------------------------------------------------


def test_a_raw_head_export_fails_loudly_rather_than_guessing():
    """A YOLO-shaped tensor must not be silently decoded as RTMDet.

    This is the failure mode the switch actually creates: someone takes a
    pre-exported ONNX under U4's escape hatch, it happens to load, and the
    boxes it produces are plausible-looking nonsense. Better a message naming
    the shapes than a detector that boxes the wrong thing.
    """
    fused = np.zeros((1, 4 + len(CLASS_NAMES) + 32, 8400), dtype=np.float32)
    _tensor, box = letterbox(_photo())
    with pytest.raises(ValueError, match=r"raw-head|rank-2"):
        decode([fused], box)


def test_boxes_without_labels_are_refused():
    dets = np.zeros((1, 3, 5), dtype=np.float32)
    _tensor, box = letterbox(_photo())
    with pytest.raises(ValueError, match="labels"):
        decode([dets], box)


def test_a_mismatched_label_count_is_refused():
    dets = np.zeros((1, 3, 5), dtype=np.float32)
    labels = np.zeros((1, 2), dtype=np.int64)
    _tensor, box = letterbox(_photo())
    with pytest.raises(ValueError, match="boxes but"):
        decode([dets, labels], box)


def test_a_batched_export_is_refused():
    """We scan one image at a time; a batch axis of 4 means the wrong graph."""
    dets = np.zeros((4, 3, 5), dtype=np.float32)
    labels = np.zeros((4, 3), dtype=np.int64)
    _tensor, box = letterbox(_photo())
    with pytest.raises(ValueError, match="batch size"):
        decode([dets, labels], box)


def test_no_outputs_is_not_an_error():
    """A model that returns nothing means no package, not a broken scan."""
    _tensor, box = letterbox(_photo())
    assert decode([], box) == []
