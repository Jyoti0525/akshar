"""RTMDet-Ins decoding: score filtering, mask assembly, polygon extraction.

Numpy only, deliberately. Pulling torch in here to reuse `torchvision.ops.nms`
would put a 2 GB dependency into the inference container for one function, and
section 15b's whole argument is that we chose the small variant on purpose.

**The panel mask is not decoration.** Rule 9(1) requires the declarations to
appear on the principal display panel, and Rule 8(1) measures clear space
around the quantity. Both need the PDP outline as a polygon, which is why the
detector is an instance-segmentation model rather than a plain box model, and
why M3's criterion is *"PDP mask IoU >= 0.85"* rather than box mAP alone.

**Why this file is much smaller than the YOLO version it replaces.** Section
15b switched B2 from YOLO11n-seg to RTMDet-Ins-tiny on licence grounds — AGPL-3.0
against Apache-2.0 — and the two models present their outputs very differently.
YOLO11-seg emits one fused `(1, 4+nc+32, 8400)` tensor of raw anchors plus a
prototype bank, so the client has to transpose it, split it, run the mask
protos through a matrix multiply and then do its own non-maximum suppression.
RTMDet-Ins exported through mmdeploy's
`instance-seg_rtmdet-ins_onnxruntime_static-640x640.py` config is **end-to-end**:
the graph already contains the anchor decoding, the class-aware NMS and the
mask head, so it hands back finished detections.

That deleted about seventy lines of hand-written tensor surgery, and with them
our own `nms()` — which is a real reduction in risk, because a bug in
hand-rolled NMS is invisible until it silently drops the panel inside a package.

**So the contract is checked, not assumed.** `decode` validates the shapes it
was given and raises rather than guessing, because the failure it is guarding
against is a *different* export of the same model quietly producing plausible
nonsense. Section 18b U4 explicitly contemplates taking a pre-exported ONNX if
mmdeploy fights us for more than a day, and a pre-export from elsewhere may not
be end-to-end. Better to fail at integration with a message naming the shapes
than to ship a detector that boxes the wrong thing.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.detect.preprocess import IMG_SIZE, Letterbox
from vision.types import XYWH, DetectClass, DetectedObject, Point

CLASS_NAMES: tuple[DetectClass, ...] = ("package", "panel")
"""Two classes, in the order the training config declares them. Changing this
order silently relabels every detection, so it is defined once, here."""

MASK_THRESHOLD = 0.5
"""RTMDet-Ins mask logits come through the exported graph already activated, so
this is a probability cut rather than a sigmoid boundary. Instance masks are
per-detection and already cropped to their own box, which is why there is no
equivalent of the YOLO decoder's proto-bleed guard."""


def _mask_polygon(
    mask: np.ndarray,
    letterbox: Letterbox,
    *,
    threshold: float = MASK_THRESHOLD,
    max_points: int = 40,
) -> list[Point] | None:
    """Reduce one instance mask to an outline in source-image pixels.

    A polygon rather than a bitmap: the rules only ever ask whether a point is
    inside the panel, the report needs to draw the outline, and a polygon
    survives JSON serialisation into the evidence record where a mask would
    bloat it beyond usefulness.
    """
    if mask.ndim != 2 or mask.size == 0:
        return None

    binary = (mask > threshold).astype(np.uint8) * 255
    if binary.shape != (IMG_SIZE, IMG_SIZE):
        binary = cv2.resize(binary, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_NEAREST)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < 4.0:
        return None

    epsilon = 0.004 * cv2.arcLength(largest, closed=True)
    simplified = cv2.approxPolyDP(largest, epsilon, closed=True).reshape(-1, 2)
    if len(simplified) > max_points:
        step = max(1, len(simplified) // max_points)
        simplified = simplified[::step]

    return [
        (
            (float(px) - letterbox.pad_x) / letterbox.scale,
            (float(py) - letterbox.pad_y) / letterbox.scale,
        )
        for px, py in simplified
    ]


def _squeeze_batch(array: np.ndarray, name: str, expected_ndim: int) -> np.ndarray:
    """Drop a leading batch axis of one, and insist on the documented rank."""
    out = array
    if out.ndim == expected_ndim + 1:
        if out.shape[0] != 1:
            raise ValueError(
                f"detector output {name!r} has batch size {out.shape[0]}; "
                f"this pipeline scans one image at a time"
            )
        out = out[0]
    if out.ndim != expected_ndim:
        raise ValueError(
            f"detector output {name!r} has shape {array.shape}, which is not the "
            f"rank-{expected_ndim} tensor the RTMDet-Ins end-to-end export produces. "
            f"If these weights came from somewhere other than mmdeploy's "
            f"instance-seg_rtmdet-ins config (see section 18b U4), the graph is "
            f"probably raw-head and needs its own decoder rather than this one."
        )
    return out


def decode(
    outputs: list[np.ndarray],
    letterbox: Letterbox,
    *,
    conf_threshold: float = 0.25,
    max_detections: int = 30,
) -> list[DetectedObject]:
    """Turn RTMDet-Ins outputs into objects in source-image coordinates.

    Expects mmdeploy's end-to-end triple:

        dets    (1, N, 5)      x1, y1, x2, y2, score — already NMS'd
        labels  (1, N)         class index into CLASS_NAMES
        masks   (1, N, H, W)   one activated mask per detection (optional)

    `masks` is optional so the same decoder serves a plain bounding-box RTMDet.
    That is not a hypothetical: section 18b U4's deeper fallback is exactly
    *"bounding-box detection plus classical quad recovery"* if instance-seg
    export proves painful. The polygons simply come back as None, and
    `clear_space` degrades to the box.

    Detections arrive sorted by score, because the NMS inside the graph sorts
    them; that order is preserved rather than re-derived.
    """
    if not outputs:
        return []

    dets = _squeeze_batch(np.asarray(outputs[0]), "dets", 2)
    if dets.shape[-1] != 5:
        raise ValueError(
            f"detector output 'dets' has {dets.shape[-1]} columns, expected 5 "
            f"(x1, y1, x2, y2, score). A wide second axis like this is the "
            f"signature of a raw-head export whose anchors have not been decoded "
            f"in-graph — see section 18b U4. This decoder handles mmdeploy's "
            f"end-to-end RTMDet-Ins output only, and guessing at a raw layout "
            f"would produce plausible-looking boxes in the wrong places."
        )
    if len(outputs) < 2:
        raise ValueError(
            "detector returned boxes with no labels; RTMDet-Ins exports "
            "'dets' and 'labels' together, and without labels every detection "
            "would have to be assumed to be a package"
        )

    labels = _squeeze_batch(np.asarray(outputs[1]), "labels", 1)
    if labels.shape[0] != dets.shape[0]:
        raise ValueError(
            f"detector returned {dets.shape[0]} boxes but {labels.shape[0]} labels"
        )

    masks = None
    if len(outputs) > 2 and np.asarray(outputs[2]).size:
        masks = _squeeze_batch(np.asarray(outputs[2]), "masks", 3)
        if masks.shape[0] != dets.shape[0]:
            raise ValueError(
                f"detector returned {dets.shape[0]} boxes but {masks.shape[0]} masks"
            )

    n_classes = len(CLASS_NAMES)
    objects: list[DetectedObject] = []

    for index in range(dets.shape[0]):
        score = float(dets[index, 4])
        # mmdeploy pads the output to a fixed length with zero-score rows.
        if score < conf_threshold:
            continue

        class_index = int(labels[index])
        if not 0 <= class_index < n_classes:
            # A class the rulepack has no meaning for. Skipping is safer than
            # guessing: mislabelling a shelf edge as a package sends the whole
            # pipeline off to measure furniture.
            continue

        x1, y1, x2, y2 = (float(v) for v in dets[index, :4])
        width, height = x2 - x1, y2 - y1
        if width <= 0.0 or height <= 0.0:
            continue
        box_640: XYWH = (x1, y1, width, height)

        polygon = _mask_polygon(masks[index], letterbox) if masks is not None else None

        objects.append(
            DetectedObject(
                box=letterbox.clip(letterbox.to_original(box_640)),
                cls=CLASS_NAMES[class_index],
                score=score,
                polygon=polygon,
            )
        )
        if len(objects) >= max_detections:
            break

    return objects


__all__ = ["CLASS_NAMES", "MASK_THRESHOLD", "decode"]
