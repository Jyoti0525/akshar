"""The two directions a marker warp can be degenerate. AKSHAR.md section 8b, B3.

`warp_to_marker` maps a marker's corners to a square and applies that homography
to the whole frame. When the marker is read at a grazing angle the plane runs to
the horizon and the output is unbounded, which `_MAX_WARP_GROWTH` has always
refused.

**The opposite direction was unguarded until 2026-09-18**, and only an absolute
8 px floor stood in its way. That floor is far too low to catch the case that
actually happens.
"""

from __future__ import annotations

import numpy as np
import pytest

from vision.rectify.rectify import _MAX_WARP_GROWTH, rectify, warp_to_marker


@pytest.fixture
def frame():
    rng = np.random.default_rng(7)
    return rng.integers(0, 255, size=(4032, 3024, 3), dtype=np.uint8)


def test_a_tiny_false_marker_no_longer_collapses_the_whole_frame(frame):
    """The measured case, reproduced.

    On `IMG_0640.JPG` a false-positive ArUco hit on a 68x56 px patch of a Pepsi
    can -- 0.03% of the frame, and there is no marker card anywhere in that
    photograph -- warped a 3024x4032 image down to **31x168**. The text detector
    proposed nothing, the scan exited at tier L4, and the officer was told
    "nothing legible was recovered" about a sharp 12-megapixel photograph of a
    declaration panel. With the guard the frame falls back to identity and reads
    43 declarations.
    """
    # The real corners `cv2.aruco` returned on that photograph, to 0.1 px, so
    # this is the geometry that actually happened rather than one invented to
    # fail. The quad spans 68x56 px and is badly non-square -- edges of 66, 34,
    # 33 and 48 px -- which is what drives the collapse.
    marker = ((827.6, 3760.3), (863.0, 3704.0), (895.6, 3711.9), (875.2, 3738.1))
    assert warp_to_marker(frame, marker) is None

    result = rectify(frame, marker=marker)
    assert result.method != "marker"
    assert result.image.shape[:2] == frame.shape[:2], "the full frame survives"


def test_the_guard_is_the_growth_guard_read_backwards(frame):
    """Not a new constant. A plane that collapses by more than the factor we
    already refuse to let it grow by is degenerate for the same reason."""
    height, width = frame.shape[:2]
    # Sized so the frame maps to just inside, then just outside, the limit.
    edge = 400.0
    square = (
        (100.0, 100.0),
        (100.0 + edge, 100.0),
        (100.0 + edge, 100.0 + edge),
        (100.0, 100.0 + edge),
    )
    kept = warp_to_marker(frame, square)
    assert kept is not None, "a fronto-parallel marker is not degenerate"
    out = kept[0]
    assert out.shape[0] * _MAX_WARP_GROWTH >= height
    assert out.shape[1] * _MAX_WARP_GROWTH >= width


def test_a_grazing_marker_is_still_refused_the_old_way(frame):
    """The guard that already existed keeps working."""
    grazing = ((10.0, 10.0), (3000.0, 12.0), (2990.0, 30.0), (12.0, 28.0))
    assert warp_to_marker(frame, grazing) is None
