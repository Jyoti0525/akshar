#!/usr/bin/env python3
"""Fetch the model bundle into `data/models/`. AKSHAR.md sections 5 and 15b.

    | Detector, INT8 ONNX               | ~12 MB |
    | OCR detection + recognition, INT8 | ~28 MB |
    | Field classifier                  |  ~4 MB |
    | SKU embedding                     |  ~4 MB |
    | **Total**                         | **~50 MB** |

Weights are not in git. Fifty megabytes of binary in a repository makes every
clone slow and every diff useless, and it is exactly what release artifacts and
object storage are for. `vision/runtime.py` therefore treats a missing model as
a first-class state — `ModelUnavailableError`, caught by the pipeline, reported
as a degradation tier — so the system runs, and degrades honestly, before this
script has ever been executed.

Run it with no arguments to fetch everything the pipeline can use:

    python scripts/fetch_models.py
    python scripts/fetch_models.py --only ocr        # just the OCR pair
    python scripts/fetch_models.py --check           # report, download nothing

---

### Why this verifies digests, and why several are blank

Every entry carries a `sha256`. Where it is `None`, the file is downloaded and
**its digest is printed rather than checked** — because pinning a hash we have
not personally verified would be security theatre: it would look like
provenance while actually meaning "whatever we happened to download first".

The honest workflow is: run once, read the digests it prints, confirm the files
are what you expect, then paste them in. After that a changed upstream artifact
fails loudly instead of silently altering every measurement the system makes —
which matters here more than in most projects, because `scans.model_versions`
records the digest into a legal record.

### One entry is a build step, not a download

The **PCA matrix** that reduces MobileNetV3's 576-d penultimate layer to the
512-d vector in `skus.embedding` is fitted from our own corpus and shipped as an
artifact. It is listed here so its absence is visible, but it cannot be fetched
from anywhere — `training/` produces it. The alternative, refitting at runtime,
would silently move every stored vector into a different space and quietly break
every near-duplicate lookup made before the change.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vision.runtime import MODELS_DIR  # noqa: E402


@dataclass(frozen=True)
class Artifact:
    name: str
    """Filename under `data/models/`. Must match the `MODEL_FILENAME` constant
    in the module that loads it, or the loader will not find it."""

    group: str
    approx_mb: float
    purpose: str
    url: str | None
    sha256: str | None = None
    licence: str = ""
    note: str = ""

    produces: tuple[str, ...] = ()
    """Files derived from this one after download, by `derive`.

    The recogniser's CTC table is the case this exists for. PaddlePaddle ships
    it inside `inference.yml` rather than as a text file, and the table must
    match the head exactly -- a mismatched dictionary of the right length does
    not raise, it returns confident wrong text. Extracting it here keeps the
    table and the weights arriving from **one pinned artifact with one digest**,
    instead of a second download that could drift against the first."""

    @property
    def path(self) -> Path:
        return MODELS_DIR / self.name


# ---------------------------------------------------------------------------
# The bundle. Names here are the single source of truth shared with
# `vision/*/`, so a rename must happen in both places or the loader misses.
# ---------------------------------------------------------------------------

ARTIFACTS: tuple[Artifact, ...] = (
    Artifact(
        name="detector_rtmdet_ins_tiny_int8.onnx",
        group="detector",
        approx_mb=12.0,
        purpose="B2 — package and PDP instance segmentation",
        url=None,
        licence="Apache-2.0 (OpenMMLab)",
        note=(
            "Exported from mmdeploy's instance-seg_rtmdet-ins_onnxruntime_static-640x640 "
            "config, or taken pre-exported under section 18b U4's one-day rule. "
            "NOT YOLO11n-seg: section 15b rejects it on licence (AGPL-3.0), not on mAP. "
            "See training/detector/."
        ),
    ),
    Artifact(
        name="ppocrv6_small_det.onnx",
        group="ocr",
        approx_mb=9.9,
        purpose="B6 — text region proposal, script-agnostic",
        url="https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx/resolve/main/inference.onnx",
        sha256="d73e0058b7a8086bbd57f3d10b8bcd4ff95363f67e06e2762b5e814fe9c9410e",
        licence="Apache-2.0 (PaddlePaddle)",
        note="PP-OCRv6 small_det, 2.48M params, LCNetV4 + RepLKFPN. `small` over "
        "`tiny` because our declarations are the smallest print on the pack. "
        "PaddlePaddle's own ONNX export, fp32 — section 15b's INT8 is a U3 "
        "latency decision to be benchmarked, not assumed.",
    ),
    Artifact(
        name="ppocrv5_rec_devanagari.onnx",
        group="ocr",
        approx_mb=7.9,
        purpose="B7 — Devanagari + Latin recognition",
        url="https://huggingface.co/PaddlePaddle/devanagari_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx",
        sha256="cb789212ce96c69d3e74728ae4309d179281d68cb3945d0616b67cafab41c986",
        licence="Apache-2.0 (PaddlePaddle)",
        note=(
            "PP-OCRv5, NOT v6. v6's 50 languages are Chinese, Japanese and 46 "
            "Latin-script — Devanagari is not among them, and taking v6 wholesale "
            "would silently drop Hindi. This head reads both scripts."
        ),
    ),
    Artifact(
        name="ppocrv5_rec_devanagari.yml",
        group="ocr",
        approx_mb=0.01,
        purpose="Source of the CTC output alphabet for the recognition head",
        url="https://huggingface.co/PaddlePaddle/devanagari_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml",
        sha256="9bd172dd26440c8ce94d1cde5d5baea6aefdc7cf3c5c8492e0beedef656d4e54",
        licence="Apache-2.0 (PaddlePaddle)",
        produces=("devanagari_dict.txt",),
        note=(
            "PaddlePaddle ships the character table inside this config, not as a "
            "text file. `derive` writes `devanagari_dict.txt` from it: 568 "
            "entries, which with PaddleOCR's blank at index 0 and space at the "
            "end makes the 570 the model's logits are actually that wide. "
            "94 of the 568 are ASCII, which is why there is no separate English "
            "head — see vision/ocr/recognise.MODEL_FILENAMES."
        ),
    ),
    # -- not shipped: the two heads section 15b's benchmark had to compare ----
    #
    # Section 15b left one question open -- *"benchmark whether a second
    # English-only head earns its bundle size; do not assume it"* -- and
    # `bench/head_compare.py` answers it. The answer is **no**, and these entries
    # exist so that anyone can re-run the comparison and check that for
    # themselves rather than taking the recorded number on trust.
    #
    # They are in their own group so `fetch_models.py` with no arguments does
    # not pull 16 MB nobody serves: `--only bench` fetches them.
    Artifact(
        name="ppocrv5_rec_en.onnx",
        group="bench",
        approx_mb=7.8,
        purpose="Section 15b benchmark only — English-only recognition head",
        url="https://huggingface.co/PaddlePaddle/en_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx",
        sha256="b5f833dfc5d0eb71da397b4efa06ebeee9b431b690a47d6af40d77d8eabc557f",
        licence="Apache-2.0 (PaddlePaddle)",
        note=(
            "NOT SHIPPED. Same v5 mobile architecture as the Devanagari head and "
            "within 64 KB of its size, so the comparison is between character "
            "tables and training sets rather than model families. Measured over "
            "1290 crops from the 38 hand-labelled panels, one head on every crop "
            "with no script routing: weighted CER 0.3060 against the Devanagari "
            "head's 0.2645 — and 0.3128 against 0.2708 on **Latin print alone**, "
            "which is the comparison the second head existed to win."
        ),
    ),
    Artifact(
        name="ppocrv5_rec_en.yml",
        group="bench",
        approx_mb=0.004,
        purpose="Character table for the English benchmark head",
        url="https://huggingface.co/PaddlePaddle/en_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml",
        sha256="27e91d0582f40168aa218303c76e184bc78fa7a5d105aad0cfbad8458b441067",
        licence="Apache-2.0 (PaddlePaddle)",
        produces=("en_dict.txt",),
        note="436 entries, 94 of them ASCII — the same 94 the Devanagari head "
        "carries. No Devanagari at all, which is why this head reads Hindi "
        "print at CER 0.89 rather than failing loudly.",
    ),
    Artifact(
        name="ppocrv5_rec_latin.onnx",
        group="bench",
        approx_mb=8.0,
        purpose="Section 15b benchmark only — Latin-family recognition head",
        url="https://huggingface.co/PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.onnx",
        sha256="7888113072263cb471b93f66dd5e2ad70548dc526fa1ace760d0d973dd121498",
        licence="Apache-2.0 (PaddlePaddle)",
        note=(
            "NOT SHIPPED. The other way of reading 'a dedicated Latin head': the "
            "whole Latin-script family rather than English alone. Weighted CER "
            "0.3044, Latin-only 0.3114 — indistinguishable from the English head "
            "and behind the shipped one on both."
        ),
    ),
    Artifact(
        name="ppocrv5_rec_latin.yml",
        group="bench",
        approx_mb=0.007,
        purpose="Character table for the Latin benchmark head",
        url="https://huggingface.co/PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx/resolve/main/inference.yml",
        sha256="0bbe984570f597af3638e50bdf2e8276f3ab26a61966096538b3b0d1849f5c84",
        licence="Apache-2.0 (PaddlePaddle)",
        produces=("latin_dict.txt",),
        note="836 entries covering Latin-script diacritics. Also no Devanagari.",
    ),
    Artifact(
        name="mobilenetv3_small_embed.onnx",
        group="identity",
        approx_mb=4.0,
        purpose="B4 — SKU near-duplicate embedding, 576-d penultimate layer",
        url=None,
        licence="Apache-2.0 (torchvision weights)",
        note="Reuses a model already in the bundle. A dedicated label-matching "
        "embedder is not worth 90 MB.",
    ),
    Artifact(
        name="sku_pca_512.npz",
        group="identity",
        approx_mb=1.2,
        purpose="B4 — 576-d to 512-d projection for skus.embedding",
        url=None,
        licence="ours",
        note=(
            "NOT DOWNLOADABLE — fitted from our corpus by training/. Shipped as an "
            "artifact and never refitted at runtime: refitting would move every "
            "stored vector into a different space and break every lookup made "
            "before the change."
        ),
    ),
    Artifact(
        name="field_classifier_int8.onnx",
        group="classifier",
        approx_mb=4.0,
        purpose="B8 tier 2 — manufacturer vs packer vs importer vs consumer_care",
        url=None,
        licence="ours",
        note=(
            "OPTIONAL, and possibly never needed. Section 15b: 'measure before "
            "building the model. If patterns separate the fields adequately on the "
            "corpus, ship without a classifier.' The regex tier already handles "
            "every other field and all six hard negatives."
        ),
    ),
    Artifact(
        name="bge-small-en-v1.5.onnx",
        group="retrieval",
        approx_mb=33.0,
        purpose="Tier 2 retrieval — 384-d dense embedding over 1,700 rule chunks",
        url=None,
        licence="MIT (BAAI)",
        note=(
            "Only needed for the free-text rule search. Tier 1 — the citation "
            "lookup officers actually use — is a dict keyed on rule_ref and needs "
            "no model at all."
        ),
    ),
)

GROUPS = tuple(dict.fromkeys(artifact.group for artifact in ARTIFACTS))

OPTIONAL_GROUPS = frozenset({"bench"})
"""Groups the bare `fetch_models.py` skips, and `--check` does not call missing.

Nothing in `vision/` loads these. They exist so a recorded benchmark result can
be reproduced rather than believed, and pulling 16 MB on every fresh checkout to
support a comparison that was already decided would be a poor trade. Fetch them
with `--only bench` when you want to re-run `bench/head_compare.py`."""


def digest_of(path: Path, *, chunk: int = 1 << 20) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _download(artifact: Artifact, destination: Path) -> None:
    assert artifact.url is not None
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        with urllib.request.urlopen(artifact.url, timeout=60) as response:
            temporary.write_bytes(response.read())
    except (urllib.error.URLError, TimeoutError) as exc:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"could not fetch {artifact.name}: {exc}") from exc
    # Rename only after a complete download, so an interrupted run never leaves
    # a truncated file that `runtime.load` would happily open and mis-infer with.
    temporary.replace(destination)


def derive(artifact: Artifact) -> list[str]:
    """Write the files `artifact.produces` names. Returns one status line each.

    Only the recogniser's character table today. It is extracted rather than
    downloaded separately because **the table and the weights must agree
    exactly**: decoding 570-wide logits against a table of 570 different
    characters does not raise, it returns fluent nonsense, and no test that
    asserts on shapes would catch it. One artifact, one digest, both files.
    """
    if not artifact.produces:
        return []

    import yaml

    lines: list[str] = []
    spec = yaml.safe_load(artifact.path.read_text(encoding="utf-8"))
    characters = [str(c) for c in spec["PostProcess"]["character_dict"]]

    for name in artifact.produces:
        target = MODELS_DIR / name
        target.write_text("\n".join(characters) + "\n", encoding="utf-8")
        lines.append(f"derived   {name}  {len(characters)} entries from {artifact.name}")
    return lines


def fetch(artifact: Artifact, *, force: bool = False) -> str:
    """Return a one-line status for this artifact."""
    path = artifact.path

    if path.exists() and not force:
        actual = digest_of(path)
        if artifact.sha256 and actual != artifact.sha256:
            return f"MISMATCH  {artifact.name}  expected {artifact.sha256[:12]}, got {actual[:12]}"
        return "\n".join([f"present   {artifact.name}  sha256={actual[:12]}...", *derive(artifact)])

    if artifact.url is None:
        return f"NO SOURCE {artifact.name}  {artifact.note.splitlines()[0][:60] if artifact.note else ''}"

    path.parent.mkdir(parents=True, exist_ok=True)
    _download(artifact, path)
    actual = digest_of(path)

    if artifact.sha256 is None:
        return f"fetched   {artifact.name}  sha256={actual}  <- PIN THIS"
    if actual != artifact.sha256:
        path.unlink(missing_ok=True)
        return f"MISMATCH  {artifact.name}  expected {artifact.sha256[:12]}, got {actual[:12]}"
    return "\n".join([f"fetched   {artifact.name}  verified", *derive(artifact)])


def report() -> int:
    """Print what is present, what is missing, and what still works regardless."""
    print(f"models dir: {MODELS_DIR.resolve()}\n")

    missing: list[Artifact] = []
    total_mb = 0.0
    for group in GROUPS:
        optional = group in OPTIONAL_GROUPS
        print(f"  [{group}]" + ("  (optional; --only bench)" if optional else ""))
        for artifact in (a for a in ARTIFACTS if a.group == group):
            if artifact.path.exists():
                size = artifact.path.stat().st_size / 1e6
                total_mb += size
                print(f"    present  {artifact.name:42s} {size:6.1f} MB")
            else:
                # An absent optional artifact is not a missing one: it is a
                # benchmark input, and `report` exits non-zero on missing so
                # that CI can gate on the models the product needs.
                if not optional:
                    missing.append(artifact)
                label = "absent  " if optional else "MISSING "
                print(f"    {label} {artifact.name:42s} {artifact.approx_mb:6.1f} MB (approx)")
            for produced in artifact.produces:
                state = "present " if (MODELS_DIR / produced).exists() else "MISSING "
                print(f"    {state} {produced:42s}        (derived)")
        print()

    print(f"  present: {total_mb:.1f} MB")
    if missing:
        print(f"  missing: {len(missing)} artifact(s)\n")
        print("  What still works with these missing:")
        print("    - capture quality, rectification, scale, measurement (no model)")
        print("    - the rules engine and all 13 check types")
        print("    - the listing_text channel end to end")
        print("    - every scan degrades and reports its tier; nothing raises")
    return 0 if not missing else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--only", choices=GROUPS, help="fetch one group only")
    parser.add_argument("--check", action="store_true", help="report status, download nothing")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args(argv)

    if args.check:
        return report()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    if args.only:
        selected = [a for a in ARTIFACTS if a.group == args.only]
    else:
        selected = [a for a in ARTIFACTS if a.group not in OPTIONAL_GROUPS]

    statuses = [fetch(artifact, force=args.force) for artifact in selected]
    for status in statuses:
        print(status)

    unresolved = [s for s in statuses if s.startswith(("NO SOURCE", "MISMATCH"))]
    if unresolved:
        print(
            f"\n{len(unresolved)} artifact(s) unresolved. Sources are not yet pinned — "
            f"see the module docstring on why a hash we have not verified is worse "
            f"than no hash. Run with --check to see what still works meanwhile."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
