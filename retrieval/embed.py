"""`bge-small-en-v1.5` in ONNX — the dense half of tier 2. AKSHAR.md §15.

    "**Dense:** `bge-small-en-v1.5` — 33M parameters, 384 dimensions, ~130 MB,
     Apache-2.0, exports cleanly to ONNX so the identical model runs
     server-side and in the browser. Chosen over `bge-base` because at 1,700
     chunks the accuracy difference is invisible and the size difference is 4x"

**A missing model is a state, not a crash.** `vision/runtime.py` already
establishes this: weights are not in git, so every component that wants one has
to run without it and say so. Here the consequence is mild and worth stating
precisely — with no model, tier 2 degrades to lexical-only search, which is
still useful, while tier 1 is untouched because it never needed a model at all.
That is the whole reason §15 puts the citation lookup in a different tier.

**Queries and passages are encoded differently.** BGE is trained with an
instruction prefix on the query side only. Omitting it is the single most
common way to lose retrieval quality with this family of models, and it fails
silently: the vectors are still 384-dimensional, still normalised, still
plausible, just worse. `encode_query` applies it; `encode_passages` must not.

**CLS pooling, not mean pooling.** BGE pools the first token. Mean pooling over
the same model produces a different and worse space, again with no error.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODELS_DIR = Path(__file__).resolve().parent.parent / "data" / "models"
MODEL_FILE = MODELS_DIR / "bge-small-en-v1.5.onnx"
TOKENIZER_FILE = MODELS_DIR / "bge-small-en-v1.5.tokenizer.json"

DIMENSIONS = 384
MAX_TOKENS = 512

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
"""BGE's retrieval instruction, applied to queries only. See the module
docstring — leaving it off degrades results without any visible symptom."""


class EmbedderUnavailableError(RuntimeError):
    """The weights, the tokenizer or onnxruntime are not present."""


@dataclass(frozen=True, slots=True)
class Availability:
    ready: bool
    detail: str


def availability() -> Availability:
    """Why tier 2's dense half can or cannot run, in one line a human can act on."""
    missing = [p.name for p in (MODEL_FILE, TOKENIZER_FILE) if not p.exists()]
    if missing:
        return Availability(False, f"missing from data/models/: {', '.join(missing)}")
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401
    except ImportError as exc:
        return Availability(False, f"{exc.name} is not installed")
    return Availability(True, "bge-small-en-v1.5")


class Embedder:
    """Lazily loaded, thread-safe, and reusable across requests.

    The session is built on first use rather than at import so that importing
    `retrieval` in a test, a worker or a machine with no weights costs nothing
    and raises nothing.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            state = availability()
            if not state.ready:
                raise EmbedderUnavailableError(state.detail)

            import onnxruntime as ort
            from tokenizers import Tokenizer

            tokenizer = Tokenizer.from_file(str(TOKENIZER_FILE))
            tokenizer.enable_truncation(max_length=MAX_TOKENS)
            tokenizer.enable_padding()
            options = ort.SessionOptions()
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(
                str(MODEL_FILE), options, providers=["CPUExecutionProvider"]
            )
            self._tokenizer = tokenizer

    @property
    def input_names(self) -> list[str]:
        self._load()
        return [i.name for i in self._session.get_inputs()]

    def _encode(self, texts: list[str]):
        import numpy as np

        self._load()
        encoded = self._tokenizer.encode_batch(texts)
        ids = np.array([e.ids for e in encoded], dtype=np.int64)
        mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed: dict[str, Any] = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(ids)

        hidden = self._session.run(None, feed)[0]
        # CLS pooling — the first token, not the mean. See the module docstring.
        pooled = hidden[:, 0]
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        # A zero vector cannot be normalised; it also cannot be produced by this
        # model for non-empty input, so guarding costs nothing and removes a
        # division that would return NaN into a database column.
        norms[norms == 0] = 1.0
        return (pooled / norms).astype(np.float32)

    def encode_passages(self, texts: list[str]):
        """Encode corpus text. **No instruction prefix.**"""
        return self._encode(list(texts))

    def encode_query(self, query: str):
        """Encode one question, with BGE's retrieval instruction applied."""
        return self._encode([QUERY_PREFIX + query])[0]


_shared = Embedder()


def shared() -> Embedder:
    """The process-wide embedder. One ONNX session is enough and 127 MB is not
    something to hold several copies of."""
    return _shared


__all__ = [
    "DIMENSIONS",
    "MAX_TOKENS",
    "MODEL_FILE",
    "QUERY_PREFIX",
    "TOKENIZER_FILE",
    "Availability",
    "Embedder",
    "EmbedderUnavailableError",
    "availability",
    "shared",
]
