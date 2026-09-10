"""ONNX Runtime session management, shared by every model in the bundle.

    "Browser execution: `onnxruntime-web` 1.20, WebGPU EP first, WASM SIMD +
     threads as fallback. Detect support at load, record which path ran in
     `scans.model_versions` so latency figures are attributable."
                                                        -- section 15b

This module is the server-side half of that. The browser half lives in `web/`
and speaks the same vocabulary, so a latency figure from either says which
execution provider produced it.

**Weights are not in the repository, and their absence is a first-class state.**
Models are ~50 MB of binary; they belong in object storage and a release
artifact, not in git. So every loader here raises `ModelUnavailableError`, which the
pipeline catches and turns into a degradation tier rather than a stack trace.
That is not a development convenience — it is the same code path that runs when
a browser has evicted the model cache mid-inspection, and it must be exercised.

**Every session records its file digest.** Section 14: *"every scan stores
detector hash, OCR version, classifier version and rulepack version. A finding
you cannot reproduce is a finding you cannot defend."* The hash is computed once
per process at load, not per scan.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODELS_DIR = Path(os.environ.get("AKSHAR_MODELS_DIR", "data/models"))

_PREFERRED_PROVIDERS = (
    "CUDAExecutionProvider",
    "CPUExecutionProvider",
)
"""Server-side order. The browser's WebGPU-then-WASM ladder is the same idea
expressed in `onnxruntime-web`; neither list belongs in the other."""


class ModelUnavailableError(RuntimeError):
    """A model file is missing, unreadable, or onnxruntime is not installed.

    Caught by `vision.pipeline`, which degrades the scan and reports the tier.
    Never allowed to escape as a 500: an officer standing in a shop needs a
    timestamped evidence record far more than they need an error page.
    """


@dataclass(frozen=True, slots=True)
class LoadedModel:
    """An ONNX session plus everything reproducibility needs to know about it."""

    session: Any
    path: Path
    sha256: str
    provider: str
    input_name: str
    output_names: tuple[str, ...]

    @property
    def version(self) -> str:
        """Short digest, which is what goes in `scans.model_versions`."""
        return f"{self.path.stem}@{self.sha256[:12]}"


_CACHE: dict[Path, LoadedModel] = {}
_LOCK = threading.Lock()


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


def resolve(name: str) -> Path:
    """Locate a model by filename under the models directory."""
    return (MODELS_DIR / name).resolve()


def available(name: str) -> bool:
    """Is this model present? Lets a caller choose a path without exceptions."""
    return resolve(name).is_file()


def load(name: str, *, providers: tuple[str, ...] | None = None) -> LoadedModel:
    """Load and cache an ONNX model. Raises `ModelUnavailableError` if it cannot.

    Sessions are process-cached: building one costs tens of milliseconds and
    the bulk worker would otherwise pay that per image, which alone would miss
    section 4's ">8 img/s/worker" budget.
    """
    path = resolve(name)

    with _LOCK:
        cached = _CACHE.get(path)
        if cached is not None:
            return cached

        if not path.is_file():
            raise ModelUnavailableError(
                f"model {name!r} not found at {path}. "
                f"Fetch the bundle with `python scripts/fetch_models.py`, or set "
                f"AKSHAR_MODELS_DIR. The pipeline will degrade without it."
            )

        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - depends on install extra
            raise ModelUnavailableError(
                "onnxruntime is not installed; install the 'vision' extra"
            ) from exc

        # The CUDA and cuDNN runtimes arrive as pip packages under
        # site-packages/nvidia/, which Windows does not search when loading a
        # DLL's dependencies. Without this, `onnxruntime_providers_cuda.dll`
        # fails to load on a missing `cublasLt64_13.dll`, onnxruntime reports
        # CUDA among its *available* providers anyway, and the session falls
        # back to CPU **without raising** -- a thirty-times slowdown that looks
        # exactly like a machine with no GPU. Cheap, idempotent, and a no-op
        # where the libraries are absent.
        if hasattr(ort, "preload_dlls"):
            with contextlib.suppress(Exception):  # best effort by design
                ort.preload_dlls()

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # One thread per session: the bulk worker gets its parallelism from
        # running several images at once, and oversubscribing here makes
        # throughput worse, not better.
        options.intra_op_num_threads = int(os.environ.get("AKSHAR_ORT_THREADS", "2"))

        wanted = providers or _PREFERRED_PROVIDERS
        usable = [p for p in wanted if p in ort.get_available_providers()]
        if not usable:  # pragma: no cover - CPU EP is always present
            usable = ["CPUExecutionProvider"]

        try:
            session = ort.InferenceSession(str(path), options, providers=usable)
        except Exception as exc:  # pragma: no cover - corrupt file
            raise ModelUnavailableError(f"could not open {path}: {exc}") from exc

        model = LoadedModel(
            session=session,
            path=path,
            sha256=_digest(path),
            provider=session.get_providers()[0],
            input_name=session.get_inputs()[0].name,
            output_names=tuple(o.name for o in session.get_outputs()),
        )
        _CACHE[path] = model
        return model


def clear_cache() -> None:
    """Drop cached sessions. Used by tests and by model hot-swap in the worker."""
    with _LOCK:
        _CACHE.clear()


__all__ = [
    "MODELS_DIR",
    "LoadedModel",
    "ModelUnavailableError",
    "available",
    "clear_cache",
    "load",
    "resolve",
]
