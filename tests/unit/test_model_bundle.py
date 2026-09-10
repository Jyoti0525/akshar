"""`scripts/fetch_models.py` must name the files the loaders actually open.

The bundle is not in git. Every module under `vision/` names the artifact it
needs as a string constant, and `fetch_models.py` names the artifact it
downloads as a different string, in a different file. **Nothing connects the
two but agreement**, and its own `Artifact` docstring says so:

    Filename under `data/models/`. Must match the `MODEL_FILENAME` constant
    in the module that loads it, or the loader will not find it.

When they disagree the failure is silent in the worst way. `fetch_models.py`
reports `fetched` for every file and exits zero; the download really happened.
Then `runtime.load` looks for a name nobody wrote, raises
`ModelUnavailableError`, and the pipeline **degrades exactly as it is designed
to** -- an honest tier, a lower confidence, a scan that still returns. Nothing
errors. The only symptom is that the system is quietly worse than the machine
it is running on could make it.

Four artifacts had drifted when this test was written: the two recognition
dictionaries (`ppocr_keys_en.txt` against `en_dict.txt`), the SKU embedding's
PCA basis (`embed_pca_512.npz` against `sku_pca_512.npz`), and the retrieval
embedder, which `fetch_models.py` called `bge_small_en_v15.onnx` while the file
sitting on disk and working was `bge-small-en-v1.5.onnx`. That last one settles
which side of the disagreement is right: **the loaders are, because they are
the code that runs.**
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.fetch_models import ARTIFACTS  # noqa: E402

ARTIFACT_SUFFIXES = {".onnx", ".txt", ".npz", ".json"}

CONSTANTS = ("MODEL_FILENAME", "MODEL_FILENAMES", "DICT_FILENAMES", "PCA_FILENAME", "MODEL_FILE")
"""The names a module uses to say which file it opens.

Listed rather than discovered, so that adding a fifth spelling is a deliberate
edit to this tuple and not a silent hole in the check.
"""


def _strings_in(node: ast.AST) -> set[str]:
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    }


def _requested_filenames() -> dict[str, set[Path]]:
    """Every artifact filename named by a loader constant, and where."""
    found: dict[str, set[Path]] = {}
    for path in [*sorted((ROOT / "vision").rglob("*.py")), ROOT / "retrieval" / "embed.py"]:
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            names = {t.id for t in targets if isinstance(t, ast.Name)}
            if not names & set(CONSTANTS) or node.value is None:
                continue
            for text in _strings_in(node.value):
                if Path(text).suffix in ARTIFACT_SUFFIXES:
                    found.setdefault(text, set()).add(path.relative_to(ROOT))
    return found


def test_every_file_a_loader_opens_is_in_the_bundle():
    """A loader asking for a file nobody fetches degrades silently, forever."""
    declared = {artifact.name for artifact in ARTIFACTS}
    declared |= {name for artifact in ARTIFACTS for name in artifact.produces}
    requested = _requested_filenames()

    missing = {name: sorted(map(str, where)) for name, where in requested.items() if name not in declared}

    assert not missing, (
        "these files are opened by a loader but never fetched, so the pipeline "
        f"will degrade with no error on a clean machine: {missing}"
    )


def test_every_file_the_bundle_fetches_is_opened_by_something():
    """The other direction: a fetched file nobody opens is dead weight.

    Worse than dead weight -- it reads as evidence that the capability is
    present. Somebody checks `data/models/`, sees the file, and concludes the
    feature works.
    """
    requested = set(_requested_filenames())
    orphans = sorted(
        a.name
        for a in ARTIFACTS
        if a.name not in requested and not set(a.produces) & requested
    )

    assert not orphans, (
        "these are downloaded but no loader names them; either wire them up or "
        f"drop them from the bundle: {orphans}"
    )


def test_the_check_can_actually_see_the_loaders():
    """Guards the test itself.

    Both assertions above pass trivially if `_requested_filenames` returns
    nothing -- a renamed constant or a moved package would turn this file into
    two tests that can never fail. So require that it found the artifacts we
    know are named, in the modules we know name them.
    """
    requested = _requested_filenames()

    assert len(requested) >= 6, f"only found {sorted(requested)}"
    assert "ppocrv6_small_det.onnx" in requested
    assert "bge-small-en-v1.5.onnx" in requested


@pytest.mark.parametrize("artifact", ARTIFACTS, ids=lambda a: a.name)
def test_an_artifact_carries_enough_to_be_fetched_and_trusted(artifact):
    """Section 18b's supply-chain line: a URL alone is not provenance.

    `url=None` is allowed -- several of these are exported by us, not
    downloaded -- but a *remote* file with no digest is a file that can change
    under us between two clean checkouts.
    """
    assert artifact.licence, f"{artifact.name} states no licence"
    assert artifact.purpose, f"{artifact.name} states no purpose"
    if artifact.url is not None:
        assert artifact.sha256, (
            f"{artifact.name} is downloaded from {artifact.url} with no sha256 to "
            f"check it against"
        )
