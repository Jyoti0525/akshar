"""Train the four-way address head. AKSHAR.md §14, §15b, §17 M5.

    python -m training.classifier.train export.json
    python -m training.classifier.train export.json --epochs 30 --no-export

The only trained classifier in this system, and it decides between four things:

    manufacturer · packer · importer · consumer_care

Nothing else. Section 14: *"Regex handles MRP, dates, net quantity, batch and
country of origin in both scripts — these have strong lexical shape, and a
pattern is more explainable than a model. A trained head handles what regex
genuinely cannot: manufacturer versus packer versus importer versus consumer
care. All four are just addresses. The distinguishing signal is position and
context, not vocabulary."*

---------------------------------------------------------------------------
THE FEATURE VECTOR IS NOT DEFINED HERE
---------------------------------------------------------------------------
It is defined in `vision/classify/features.py` and imported. That module's own
docstring says why: *"the training code and the inference code must build this
vector identically, down to the ordering of the one-hot slots. Feature skew
between train and serve is silent."*

So this script has no opinion about feature order, no local copy of the panel
list, and no way to disagree with the pipeline. If `FEATURE_DIM` changes, this
file changes with it because it reads the constant rather than restating it.

The same applies to `CLASSES`, imported from `vision/classify/model_tier.py`.
Reordering that tuple relabels every prediction without touching a weight, so
there is exactly one place it is written down.

---------------------------------------------------------------------------
2M PARAMETERS, AND WHY THAT IS THE ARGUMENT
---------------------------------------------------------------------------
Section 15b: *"About 2M parameters — LayoutLMv3's 125M would overfit 400 photos
badly. Being able to say 'we chose 2M over 125M because our corpus is 400
images' is a better answer than the bigger number."*

The 384-d sentence embedding is **frozen**, and it is where nearly all the
representational capacity lives. What trains here is a two-layer encoder over
that plus fourteen geometry and one-hot features — small enough that four
hundred photographs is a reasonable number of examples for it.

The embedding is `bge-small-en-v1.5`, not the MiniLM-L6 §15b names, and the
reason is recorded in `embed()` below: the pipeline serves with bge, MiniLM
ships no weights, and the two disagreeing silently was a live defect rather
than a preference.

---------------------------------------------------------------------------
WHAT IS REPORTED, AND WHAT IS NOT
---------------------------------------------------------------------------
Per-class F1, never averaged. Section 14: *"Report per class, never averaged."*
A macro F1 of 0.87 over four classes routinely hides `importer` at 0.4, and
`importer` is the class that decides whether Rule 6(1)(f) applies at all.

Early stopping is on validation **macro** F1 rather than accuracy, because the
classes are heavily imbalanced -- most packets have a manufacturer and no
importer -- and accuracy would select the checkpoint that learned to say
`manufacturer`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(ROOT))

from vision.classify.features import FEATURE_DIM  # noqa: E402
from vision.classify.model_tier import CLASSES, MODEL_FILENAME  # noqa: E402

HIDDEN = 512
"""Two layers of this over a 398-d input is roughly 0.34M trainable parameters,
against the frozen 33M in bge-small-en-v1.5 that produces 384 of those inputs.
Section 15b's "about 2M" is the whole head including the embedding it
consumes."""

FOCAL_GAMMA = 2.0
"""Section 14: focal loss, gamma 2. The imbalance here is not the violation
imbalance the plan discusses elsewhere -- it is that `manufacturer` appears on
nearly every packet and `importer` on a handful. Cross-entropy would spend its
gradient on the easy majority."""

LEARNING_RATE = 3e-4
EPOCHS = 30
PATIENCE = 6
BATCH = 32
SEED = 26034


# ---------------------------------------------------------------------------
# Reading the labels
# ---------------------------------------------------------------------------


def rows_from_export(export: Path) -> list[dict[str, Any]]:
    """Address-labelled declaration boxes from a Label Studio export.

    Only the four classes, and only from `annotations`. A prediction is not a
    label -- `training/detector/convert.py` carries the same rule and the same
    reason.
    """
    tasks = json.loads(export.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for task in tasks:
        image = task.get("data", {}).get("image", "")
        for annotation in task.get("annotations") or []:
            if annotation.get("was_cancelled"):
                continue
            # Script choices are `perRegion`, so they arrive as separate result
            # entries keyed by the region id they belong to. Collected first so
            # a declaration can find its own script rather than assuming latin.
            scripts = {
                result.get("id"): (result.get("value", {}).get("choices") or ["latin"])[0]
                for result in annotation.get("result", [])
                if result.get("from_name") == "script"
            }
            for result in annotation.get("result", []):
                if result.get("from_name") != "declarations":
                    continue
                labels = result.get("value", {}).get("rectanglelabels") or []
                if not labels or labels[0] not in CLASSES:
                    continue
                rows.append(
                    {
                        "image": image,
                        "label": CLASSES.index(labels[0]),
                        "value": result["value"],
                        "width": result.get("original_width", 0),
                        "height": result.get("original_height", 0),
                        "script": scripts.get(result.get("id"), "latin"),
                        "text": result.get("meta", {}).get("text", [""])[0],
                    }
                )
    return rows


def rows_from_weak(path: Path) -> list[dict[str, Any]]:
    """Rows from `training/classifier/harvest.py`.

    Distant supervision from the regex tier, not from a model — the harvest's
    docstring makes that case at length and `rows_from_export`'s
    annotations-only rule is untouched above.

    The geometry arrives already in rectified pixels against the rectified
    frame, because the harvest took it from the same `scan()` the pipeline
    runs, so it is normalised here exactly as `geometry_features` normalises it
    at inference rather than through Label Studio's percentages.
    """
    rows = json.loads(path.read_text(encoding="utf-8"))
    for row in rows:
        row["label"] = int(row["label"])
    return list(rows)


def build_matrix_weak(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """(features, labels, image per row), built by the inference code itself.

    `build_features` is imported and called rather than reimplemented, so there
    is no second opinion about feature order to drift from the first. The
    Label Studio path above cannot do this — it has percentages and no
    `OcrLine` — which is precisely why it carries its own copy and this one
    does not.
    """
    from vision.classify.features import build_features
    from vision.types import Box, OcrLine

    embeddings = embed([row["text"] for row in rows])
    heights = [row["cap_height_px"] for row in rows if row.get("cap_height_px")]
    median = float(np.median(heights)) if heights else None

    features = []
    for row, embedding in zip(rows, embeddings, strict=True):
        x, y, w, h = row["box"]
        line = OcrLine(
            text=row["text"],
            box=Box(x=x, y=y, w=w, h=h),
            confidence=float(row.get("confidence", 1.0)),
            script=row.get("script", "latin"),
            cap_height_px=row.get("cap_height_px"),
            panel_id=row.get("panel_id") or None,
        )
        features.append(
            build_features(
                line,
                embedding,
                label_w=float(row["label_w"]),
                label_h=float(row["label_h"]),
                median_cap_height_px=median,
            )
        )

    matrix = np.stack(features)
    assert matrix.shape[1] == FEATURE_DIM, (
        f"built {matrix.shape[1]} features against {FEATURE_DIM}"
    )
    return (
        matrix,
        np.array([row["label"] for row in rows], dtype=np.int64),
        [row["image"] for row in rows],
    )


def embed(texts: list[str]) -> np.ndarray:
    """Frozen 384-d sentence embeddings, from the embedder that serves.

    **This used to load `all-MiniLM-L6-v2` and that was a live train/serve
    skew.** Section 15b names MiniLM-L6, and the constant in `features.py` is
    still called a 384-d sentence embedding because that is what it is — but
    `vision/pipeline.py::_layout_head`, which is the only code that ever calls
    the head, embeds with `bge-small-en-v1.5` through `retrieval.embed`. Two
    different models, both 384-dimensional, so `FEATURE_DIM` agreed and nothing
    raised. The head would have been trained in one vector space and queried in
    another, and the only symptom would have been a model that scored well here
    and predicted noise in production. That is exactly the silent failure
    `features.py`'s docstring exists to warn about.

    `bge-small-en-v1.5` is the one that ships: 133 MB of it is already in
    `data/models/` for retrieval, it is already an ONNX asset the server loads,
    and it needs no torch at inference. MiniLM ships nothing. So the serving
    side is the fixed point and training moves to meet it.

    Passages, not queries — BGE's instruction prefix belongs to the query side
    only, and a declaration on a package is neither a question nor being
    searched for.
    """
    from retrieval import embed as embedder

    ready = embedder.availability()
    if not ready.ready:
        raise SystemExit(
            f"the sentence embedder is not available: {ready.detail}\n"
            "It is the same one the pipeline serves with, so training cannot\n"
            "substitute another model without skewing the head."
        )
    return np.asarray(embedder.shared().encode_passages(texts), dtype=np.float32)


def build_matrix(rows: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """(features, labels, image per row), in the frozen order `features.py` defines."""
    from vision.classify.features import PANELS, SCRIPTS, _one_hot

    embeddings = embed([row["text"] for row in rows])
    features = []
    for row, embedding in zip(rows, embeddings, strict=True):
        value, height = row["value"], row["height"] or 1
        # Label Studio percentages are already normalised against the image,
        # which for these crops is the label. That is the same normalisation
        # `geometry_features` applies at inference time.
        x, y = value["x"] / 100.0, value["y"] / 100.0
        w, h = value["width"] / 100.0, value["height"] / 100.0
        cap = value["height"] * height / 100.0
        median = np.median([r["value"]["height"] * (r["height"] or 1) / 100.0 for r in rows]) or 1.0
        geometry = np.array([x, y, w, h, cap / median], dtype=np.float32)
        features.append(
            np.concatenate(
                [
                    embedding,
                    geometry,
                    # The panel is not exported per declaration by the current
                    # label config -- panels are polygons, declarations are
                    # boxes, and Label Studio does not join them. Until a
                    # point-in-polygon join is added to the export, every row
                    # trains as `unknown`, which is what inference also passes
                    # when the PDP polygon is absent. Honest, and it is why
                    # `panel` is not in the reported feature ablation.
                    _one_hot("unknown", PANELS),
                    _one_hot(row["script"], SCRIPTS),
                ]
            ).astype(np.float32)
        )
    matrix = np.stack(features)
    assert matrix.shape[1] == FEATURE_DIM, (
        f"built {matrix.shape[1]} features against vision/classify/features.py's {FEATURE_DIM}; "
        f"they must agree exactly or the trained head is wrong at inference in a way "
        f"nothing will report"
    )
    return matrix, np.array([row["label"] for row in rows], dtype=np.int64), [
        row["image"] for row in rows
    ]


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def build_model(torch):
    return torch.nn.Sequential(
        torch.nn.Linear(FEATURE_DIM, HIDDEN),
        torch.nn.LayerNorm(HIDDEN),
        torch.nn.GELU(),
        torch.nn.Dropout(0.2),
        torch.nn.Linear(HIDDEN, HIDDEN // 2),
        torch.nn.LayerNorm(HIDDEN // 2),
        torch.nn.GELU(),
        torch.nn.Dropout(0.2),
        torch.nn.Linear(HIDDEN // 2, len(CLASSES)),
    )


def focal_loss(torch, logits, targets, gamma: float = FOCAL_GAMMA):
    log_probabilities = torch.nn.functional.log_softmax(logits, dim=-1)
    picked = log_probabilities.gather(1, targets[:, None]).squeeze(1)
    return (-((1 - picked.exp()) ** gamma) * picked).mean()


def per_class_f1(predicted: np.ndarray, actual: np.ndarray) -> dict[str, float | None]:
    """F1 per class. `None` where the class does not appear in this split.

    Returning 0.0 for an absent class would drag the macro average down and make
    a checkpoint look worse than it is; returning 1.0 would flatter it. Neither
    is true, so the honest value is "not measured here" -- and a class that is
    `None` on validation is itself a finding about the corpus.
    """
    scores: dict[str, float | None] = {}
    for index, name in enumerate(CLASSES):
        true_positive = int(((predicted == index) & (actual == index)).sum())
        false_positive = int(((predicted == index) & (actual != index)).sum())
        false_negative = int(((predicted != index) & (actual == index)).sum())
        if true_positive + false_negative == 0:
            scores[name] = None
            continue
        precision = true_positive / (true_positive + false_positive) if true_positive else 0.0
        recall = true_positive / (true_positive + false_negative)
        scores[name] = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    return scores


def macro_f1(scores: dict[str, float | None]) -> float:
    measured = [value for value in scores.values() if value is not None]
    return float(np.mean(measured)) if measured else 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "export", type=Path, nargs="?", help="Label Studio JSON export (hand annotations)"
    )
    parser.add_argument(
        "--weak",
        type=Path,
        help="weak labels from training/classifier/harvest.py (distant supervision)",
    )
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--out", type=Path, default=ROOT / "data" / "models" / MODEL_FILENAME)
    parser.add_argument("--no-export", action="store_true", help="train and report, write nothing")
    args = parser.parse_args(argv)

    try:
        import torch
    except ImportError:  # pragma: no cover
        raise SystemExit('torch is not installed: pip install -e ".[training]"') from None

    if bool(args.export) == bool(args.weak):
        raise SystemExit("pass either a Label Studio export or --weak, and not both")

    weak = args.weak is not None
    rows = rows_from_weak(args.weak) if weak else rows_from_export(args.export)
    if weak:
        print("** weak supervision: labels from the regex tier, not hand annotation **")
        print("   A head trained this way inherits the patterns' blind spots. It can")
        print("   generalise to addresses printed with no caption, which is the whole")
        print("   point, but it cannot know anything the patterns never got right.\n")
    counts = Counter(CLASSES[row["label"]] for row in rows)
    print(f"{len(rows)} labelled address declarations")
    for name in CLASSES:
        print(f"  {name:16} {counts.get(name, 0):5}")

    if len(rows) < 4 * len(CLASSES):
        print(
            "\nToo few examples to train. This is not a bug -- it is section 16's "
            "annotation work not yet done. See docs/annotation-guide.md, rule 7."
        )
        return 1
    absent = [name for name in CLASSES if not counts.get(name)]
    if absent:
        print(f"\n  ** {', '.join(absent)} has no examples. The head cannot learn a class")
        print("     it has never seen, and will confidently never predict it. **")

    features, labels, images = (build_matrix_weak if weak else build_matrix)(rows)

    # Split by photograph, not by row. Two addresses from one packet share a
    # layout, a font and a lighting condition; splitting rows at random puts
    # both sides of that pair across the line and the validation F1 measures
    # memorisation.
    torch.manual_seed(SEED)
    rng = np.random.default_rng(SEED)
    unique_images = sorted(set(images))
    rng.shuffle(unique_images)
    validation_images = set(unique_images[: max(1, len(unique_images) // 5)])
    is_validation = np.array([image in validation_images for image in images])

    x_train = torch.from_numpy(features[~is_validation])
    y_train = torch.from_numpy(labels[~is_validation])
    x_val = torch.from_numpy(features[is_validation])
    y_val = torch.from_numpy(labels[is_validation])
    print(f"\ntrain {len(x_train)} rows / val {len(x_val)} rows, split by photograph")

    model = build_model(torch)
    parameters = sum(p.numel() for p in model.parameters())
    print(f"trainable parameters: {parameters:,} (plus 33M frozen in bge-small-en-v1.5)")

    optimiser = torch.optim.AdamW(model.parameters(), lr=LEARNING_RATE, weight_decay=0.01)
    schedule = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=args.epochs)

    best_score, best_state, waited = -1.0, None, 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        order = torch.randperm(len(x_train))
        for start in range(0, len(order), BATCH):
            batch = order[start : start + BATCH]
            optimiser.zero_grad()
            loss = focal_loss(torch, model(x_train[batch]), y_train[batch])
            loss.backward()
            optimiser.step()
        schedule.step()

        model.eval()
        with torch.no_grad():
            predicted = model(x_val).argmax(dim=-1).numpy()
        scores = per_class_f1(predicted, y_val.numpy())
        score = macro_f1(scores)
        flag = ""
        if score > best_score:
            best_score, best_state, waited, flag = score, model.state_dict(), 0, "  <- best"
        else:
            waited += 1
        print(f"  epoch {epoch:3}  macro F1 {score:.3f}{flag}")
        if waited >= PATIENCE:
            print(f"  early stop: {PATIENCE} epochs without improvement")
            break

    assert best_state is not None
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        predicted = model(x_val).argmax(dim=-1).numpy()
    scores = per_class_f1(predicted, y_val.numpy())

    print("\nPer class F1 on validation -- section 14: never averaged into one number")
    for name in CLASSES:
        value = scores[name]
        print(f"  {name:16} {'not present in val' if value is None else f'{value:.3f}'}")
    print(f"  {'macro (measured)':16} {best_score:.3f}")
    print(f"\nSection 17 M5 asks for per-field F1 >= 0.85. Met: {best_score >= 0.85}")

    if args.no_export:
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Exported float32 under the INT8 filename the pipeline loads, because
    # `vision/runtime.py` keys on the name and section 14's INT8 step belongs to
    # the same mmdeploy pass as the detector's. The accuracy delta is recorded
    # in RESULTS.md at that point; shipping FP32 under the INT8 name before that
    # comparison exists would make the recorded delta meaningless.
    torch.onnx.export(
        model,
        torch.zeros(1, FEATURE_DIM),
        str(args.out),
        input_names=["features"],
        output_names=["logits"],
        dynamic_axes={"features": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
    )

    # ONE FILE, weights inside it.
    #
    # torch's current exporter writes tensors to a sidecar `<name>.onnx.data`
    # and leaves the `.onnx` holding only a graph -- 3 KB of it, for a model
    # with 338,180 parameters. It loads correctly here because onnxruntime
    # finds the sidecar next to it, and that is exactly what makes it
    # dangerous: `vision/runtime.py` resolves models by filename, the bundle
    # ships them as single files, and anyone who copies the `.onnx` alone gets
    # a model with no weights. Whether that fails loudly or quietly is the
    # runtime's choice, not ours, and one of those two outcomes is a silent
    # wrong answer on an enforcement tool.
    _inline_weights(args.out)

    print(f"\nwrote {args.out} ({args.out.stat().st_size / 1e6:.2f} MB, self-contained)")
    print("NOTE: exported FP32 under the INT8 filename. Quantise with mmdeploy and")
    print("record the accuracy delta in RESULTS.md before claiming INT8.")
    return 0


def _inline_weights(path: Path) -> None:
    """Fold any external tensor data back into the model file, and prove it."""
    import onnx

    model = onnx.load(str(path))  # follows the sidecar
    onnx.save(model, str(path), save_as_external_data=False)

    sidecar = path.with_suffix(path.suffix + ".data")
    if sidecar.exists():
        sidecar.unlink()

    reloaded = onnx.load(str(path), load_external_data=False)
    external = [
        tensor.name
        for tensor in reloaded.graph.initializer
        if tensor.data_location == onnx.TensorProto.EXTERNAL
    ]
    if external:
        raise SystemExit(
            f"{path.name} still references external tensors {external[:4]}; refusing to "
            f"ship a model whose weights live in another file."
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
