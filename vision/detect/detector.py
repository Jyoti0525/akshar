"""M3 Detect — RTMDet-Ins-tiny, two classes, 640 px, INT8 ONNX.

    "**RTMDet-Ins-tiny. Not YOLO11n-seg.** The two are close on accuracy and
     speed; the licence is not close at all. [...] A Legal Metrology
     department deploying this behind an API for officers across a state would
     be distributing under AGPL — obliging them to publish their entire stack,
     or buy a commercial licence for a tool we are pitching as free. That is a
     procurement blocker. [...] RTMDet is Apache-2.0 through MMDetection."
                                                          -- section 15b

    "Done when: mAP >= 0.85, PDP IoU >= 0.85, zero false positives on
     negatives, under 120 ms."                            -- section 17, M3

**The model was chosen on licence, not on mAP**, and that is worth knowing
before anyone "upgrades" it back. Ultralytics hold that AGPL-3.0 covers the
weights a custom training run produces, and that hosting the model behind an
API counts as distribution. Swapping this line for a YOLO checkpoint would
therefore hand a procurement problem to whichever department deploys us.

**The negatives criterion is the one that shapes this file.** "Zero false
packages across the 60 negative photos" is a much harder bar than mAP, and it
is the bar that matters, because a detector that boxes a shelf edge sends the
whole pipeline off to measure a price rail and produces a violation notice for
a piece of furniture. Two things here serve it: a package confidence threshold
deliberately higher than the panel one, and a minimum area — a "package"
occupying 2% of the frame is something the officer is not photographing.

The 60 negative photos are part of the corpus that has to come from the user;
until they exist this threshold is a reasoned default, not a measured one, and
`RESULTS.md` says so rather than implying otherwise.
"""

from __future__ import annotations

import time

from vision import runtime
from vision.detect.postprocess import decode
from vision.detect.preprocess import letterbox
from vision.types import DetectedObject, DetectionResult, Image

MODEL_FILENAME = "detector_rtmdet_ins_tiny_int8.onnx"

PACKAGE_CONF = 0.45
"""Higher than the usual 0.25. Section 17 grades this model on *zero* false
packages across 60 negatives, and precision on the package class is worth more
to us than recall: a missed pack means the officer retakes the photo, while a
false pack means a measurement of a shelf."""

PANEL_CONF = 0.30
"""Lower, because the panel is only looked for *inside* an accepted package.
The package detection has already established there is something to segment."""

MIN_PACKAGE_AREA_FRAC = 0.02
"""A package smaller than this is background clutter — a packet on a shelf two
metres behind the one being inspected."""


def _filter(objects: list[DetectedObject], frame_area: float) -> list[DetectedObject]:
    kept: list[DetectedObject] = []
    packages = [
        o
        for o in objects
        if o.cls == "package"
        and o.score >= PACKAGE_CONF
        and (o.box[2] * o.box[3]) >= frame_area * MIN_PACKAGE_AREA_FRAC
    ]
    kept.extend(packages)

    if packages:
        # A panel is only meaningful within a package. One floating in the
        # background is a mis-detection, and it would give `clear_space` a
        # polygon unrelated to the pack being judged.
        for panel in (o for o in objects if o.cls == "panel" and o.score >= PANEL_CONF):
            px, py, pw, ph = panel.box
            centre = (px + pw / 2.0, py + ph / 2.0)
            if any(
                bx <= centre[0] <= bx + bw and by <= centre[1] <= by + bh
                for bx, by, bw, bh in (p.box for p in packages)
            ):
                kept.append(panel)

    return kept


def detect(image: Image, *, model_name: str = MODEL_FILENAME) -> DetectionResult:
    """Find the package and its principal display panel.

    Raises `runtime.ModelUnavailableError` when weights are absent; the pipeline
    catches that and degrades rather than failing the scan.
    """
    model = runtime.load(model_name)

    started = time.perf_counter()
    tensor, box_transform = letterbox(image)
    raw = model.session.run(None, {model.input_name: tensor})
    objects = decode(raw, box_transform)
    elapsed = (time.perf_counter() - started) * 1000.0

    frame_area = float(image.shape[0] * image.shape[1])
    return DetectionResult(
        objects=_filter(objects, frame_area),
        inference_ms=elapsed,
        model_version=model.version,
    )


def is_available(model_name: str = MODEL_FILENAME) -> bool:
    return runtime.available(model_name)


__all__ = [
    "MIN_PACKAGE_AREA_FRAC",
    "MODEL_FILENAME",
    "PACKAGE_CONF",
    "PANEL_CONF",
    "detect",
    "is_available",
]
