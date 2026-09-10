"""Architectural boundaries — AKSHAR.md sections 3 and 9.

    "rules/engine.py must not import OpenCV, PaddleOCR or the database.
     If it does, the boundary has leaked and the text channel breaks later."

That is not a style preference. The problem statement names three inputs and
one of them is pure text from an e-commerce listing with no image at all. If
extraction is wired into decision, that third channel stops being an
afternoon's work and becomes a rewrite.

These tests read the source rather than importing it, so they fail even when
the forbidden package happens not to be installed on the machine running CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_IN_PURE_LAYERS = {
    "cv2": "OpenCV — extraction only",
    "numpy": "array maths belongs in vision/",
    "paddleocr": "OCR — extraction only",
    "paddle": "OCR — extraction only",
    "onnxruntime": "model runtime — extraction only",
    "torch": "model runtime — training only",
    "ultralytics": "detector — extraction only",
    "sqlalchemy": "persistence — the engine never sees a database",
    "psycopg": "persistence — the engine never sees a database",
    "alembic": "persistence",
    "minio": "object storage",
    "redis": "queue",
    "fastapi": "transport — the engine is not a web handler",
    "dramatiq": "queue",
    "PIL": "imaging — extraction only",
    "requests": "the engine makes no network calls",
    "httpx": "the engine makes no network calls",
}

PURE_PACKAGES = ["contracts", "rules"]


def _module_files(package: str) -> list[Path]:
    return sorted((ROOT / package).rglob("*.py"))


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("package", PURE_PACKAGES)
def test_pure_layers_import_nothing_forbidden(package: str) -> None:
    violations: list[str] = []
    for path in _module_files(package):
        for root in _imported_roots(path):
            if root in FORBIDDEN_IN_PURE_LAYERS:
                rel = path.relative_to(ROOT)
                violations.append(f"{rel} imports {root} ({FORBIDDEN_IN_PURE_LAYERS[root]})")
    assert not violations, "boundary leak:\n  " + "\n  ".join(violations)


def test_engine_performs_no_file_io() -> None:
    """The engine receives a loaded rulepack; reading files is the loader's job."""
    source = (ROOT / "rules" / "engine.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    # `get` and `post` are deliberately NOT listed: `dict.get` and the check
    # registry's `get` are legitimate, and network access is already blocked by
    # the import guard above, which is the stronger test.
    for forbidden in ("open", "read_text", "read_bytes", "write_text", "connect", "urlopen"):
        assert forbidden not in called, f"rules/engine.py calls {forbidden}()"


def test_contracts_do_not_depend_on_rules() -> None:
    """Contracts are the shared vocabulary; they must not know about decisions."""
    for path in _module_files("contracts"):
        assert "rules" not in _imported_roots(path), f"{path} imports rules"


def test_every_permitted_check_type_has_a_module() -> None:
    """Thirteen check types, thirteen modules — and no fourteenth."""
    from rules.checks import REGISTRY
    from rules.models import ALLOWED_CHECKS

    assert set(REGISTRY) == set(ALLOWED_CHECKS)
    assert len(REGISTRY) == 13

    for name in ALLOWED_CHECKS:
        assert (ROOT / "rules" / "checks" / f"{name}.py").exists(), f"missing {name}.py"


def test_rulepack_is_small_enough_to_email() -> None:
    """Section 5: the entire legal logic of the system is ~40 KB of text.

    That claim is on a slide, so it is worth a test.
    """
    size = (ROOT / "rules" / "packs" / "lmpc_2011.yaml").stat().st_size
    assert size < 100_000, f"rulepack has grown to {size} bytes"


def test_every_model_a_loader_wants_is_in_the_fetch_script() -> None:
    """A rename in one place must not silently break the other.

    `vision/*/` declares the filename it loads; `scripts/fetch_models.py`
    declares the filename it downloads. Nothing connects them at runtime, so a
    rename on one side produces a bundle that fetches cleanly and a pipeline
    that finds nothing — and the pipeline's response to a missing model is to
    *degrade quietly*, which is exactly right in the field and exactly wrong as
    a way of discovering a typo.

    This is the same class of bug as train/serve skew: two places agreeing by
    convention rather than by construction.
    """
    from scripts.fetch_models import ARTIFACTS
    from vision.classify import model_tier
    from vision.detect import detector
    from vision.identify import embed
    from vision.ocr import detect_text, recognise

    fetchable = {artifact.name for artifact in ARTIFACTS}
    wanted = {
        detector.MODEL_FILENAME,
        detect_text.MODEL_FILENAME,
        embed.MODEL_FILENAME,
        model_tier.MODEL_FILENAME,
        *recognise.MODEL_FILENAMES.values(),
    }

    missing = wanted - fetchable
    assert not missing, (
        f"loaders ask for models the fetch script cannot supply: {sorted(missing)}"
    )


def test_the_pack_does_not_claim_a_currency_it_cannot_evidence() -> None:
    """Section 13a — the version string never outruns the source register.

    One amendment is still unverified: a "23 October 2025, medical devices"
    notification claimed by a secondary source and never confirmed against a
    gazette. Until someone produces it, the pack must not present itself as
    current.

    This test exists because the predicate broke silently. It used to read
    `amendments_known_missing`, a meta key the 2026-09-07 register rewrite
    removed — and `dict.get` on a missing key returns `None`, so the function
    flipped to answering "yes, current" with nothing behind it. Nothing failed;
    it had no test and no caller. A claim of legal currency is exactly the kind
    of thing that must fail loudly rather than default to true.
    """
    from rules.loader import load_rulepack

    pack = load_rulepack()
    assert pack.meta.get("amendments_unverified"), (
        "the unverified list is empty — if the medical-devices notification has "
        "genuinely been obtained, add it to the register with its gazette "
        "reference rather than deleting the row"
    )
    assert not pack.claims_currency()

    checked = pack.meta.get("amendments_checked") or []
    assert checked, "amendments_checked is empty; 13a confirms four"
    # A *checked* amendment has a confirmed effect and must not block currency.
    # Only *unverified* ones do.
    assert all("effect" in entry for entry in checked), (
        "every checked amendment must record its effect, including 'NONE'"
    )


def test_no_package_level_country_of_origin_rule() -> None:
    """AKSHAR.md section 13b — the wrong-law rule must not come back.

    An earlier pack carried `LMPC.ORIGIN.IMPORTED`, which required a country of
    origin *on the package* and cited Rule 6(10A) for it. 6(10A), inserted by
    GSR 128(E) of 13 February 2026 and already substituted by GSR 312(E) of 27
    April 2026, obliges an **e-commerce entity** to provide a searchable and
    sortable country-of-origin filter on its listings. It says nothing about
    what is printed on a package.

    Nothing in the 2011 principal rules requires country of origin on the pack.
    A rule demanding a declaration the law does not require is a
    false-violation generator pointed at compliant manufacturers, and it is the
    single most damaging thing this rulepack can contain — so its absence is
    asserted rather than assumed.

    The field is still *extracted*: it triggers `LMPC.IMPORTER.PRESENT` and
    appears in the report. It is simply never *required*.
    """
    from rules.loader import load_rulepack

    pack = load_rulepack()
    rule_ids = {rule.id for rule in pack.all_rules()}

    assert "LMPC.ORIGIN.IMPORTED" not in rule_ids, (
        "the country-of-origin rule is back; it cites Rule 6(10A), which is a "
        "platform obligation and not a labelling requirement"
    )
    assert "LMPC.IMPORTER.PRESENT" in rule_ids, "Rule 6(1)(a) importer check is missing"

    for rule in pack.all_rules():
        if "country_of_origin" in rule.target_fields():
            raise AssertionError(
                f"{rule.id} requires country_of_origin as a declaration; no "
                f"provision of the 2011 rules makes it mandatory on a package"
            )


def test_rules_never_import_vision() -> None:
    """The wall, in the direction that actually matters.

    `vision/` may import `rules/` — the regex classifier deliberately reuses the
    rulepack's locate patterns so extraction and decision cannot disagree about
    what an MRP looks like. The reverse is forbidden: a rule that reached into
    `vision/` would drag OpenCV into the decision layer and break the
    listing_text channel, which has no pixels at all.
    """
    for path in _module_files("rules"):
        assert "vision" not in _imported_roots(path), f"{path.relative_to(ROOT)} imports vision"


def test_vision_does_not_import_transport_or_persistence() -> None:
    """Extraction owns no connections.

    Scale tier B reads stored SKU dimensions and the pipeline reads the SKU
    cache, but both take a callable from the caller rather than opening a
    database. That keeps the whole pipeline runnable in a unit test, and it is
    what lets the identical code run in a browser where there is no Postgres.
    """
    forbidden = {"sqlalchemy", "psycopg", "alembic", "fastapi", "dramatiq", "redis", "minio"}
    violations: list[str] = []
    for path in _module_files("vision"):
        for root in _imported_roots(path):
            if root in forbidden:
                violations.append(f"{path.relative_to(ROOT)} imports {root}")
    assert not violations, "vision/ opened a connection:\n  " + "\n  ".join(violations)


def test_only_one_opencv_distribution_is_installed() -> None:
    """`opencv-python` and `opencv-python-headless` both install `cv2`.

    They unpack into the same directory, so having both means `import cv2`
    resolves to whichever landed last. Installing the corpus ingestion tools
    pulled in opencv-python 5.x beside this project's pinned headless 4.x, and
    the symptom was nine failures in the vision geometry and annotation tests —
    `putText` metrics changed between the majors, so a cap height measured 33 px
    where the test drew 44. Nothing in the failing code had been touched.

    This is a boundary in the same sense as the others in this file: the
    measurement stack owns which OpenCV it runs against, and a build-time tool
    does not get to change it. See the `corpus` extra in pyproject.toml.
    """
    from importlib.metadata import distributions

    installed = {dist.metadata["Name"] for dist in distributions()}
    both = installed & {"opencv-python", "opencv-python-headless"}
    assert both != {"opencv-python", "opencv-python-headless"}, (
        "opencv-python and opencv-python-headless are both installed; "
        "`import cv2` is now ambiguous. Uninstall opencv-python, then "
        "`pip install --force-reinstall --no-deps 'opencv-python-headless>=4.10,<5'` "
        "to restore the shared cv2 directory."
    )
