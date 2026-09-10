"""Build the tier-1 citation file, and check it against the rulepack.

    python -m scripts.build_rulebook          # write and report
    python -m scripts.build_rulebook --check  # report only, non-zero on a gap

**The JSON is for the browser, not for the server.** `retrieval/citations.py`
chunks the extracted text directly, so the API has one source of truth and
cannot serve a stale artefact. §15 wants tier 1 available offline — *"the whole
corpus fits in browser memory, so the explainer can work offline at tier L1"* —
and a static file the PWA can precache is how that happens.

**The check is the useful half.** Every rule in the pack carries a `rule_ref`,
and every `rule_ref` is a promise that an officer tapping "why" will be shown
something. This script resolves all of them and reports which are exact, which
point at a gazette we do not hold, and which resolve only to an enclosing
provision. That report has already caught defects in both directions: a parser
that dropped Rule 12(6) because the gazette prints it with an amendment
asterisk, and a Seventh Schedule item silently overwriting Rule 7.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from retrieval.chunker import chunk_document
from retrieval.citations import DOCUMENTS, RULEBOOK_DIR, CitationIndex
from retrieval.normalise import repair_spacing, vocabulary

OUTPUT = RULEBOOK_DIR.parent / "citations.json"


def build(directory: Path = RULEBOOK_DIR) -> tuple[list[dict], dict[str, int]]:
    records: list[dict] = []
    stats: dict[str, int] = {}
    for path in sorted(directory.glob("*.txt")):
        raw = path.read_text(encoding="utf-8")
        _, repairs = repair_spacing(raw, vocabulary(raw))
        chunks = chunk_document(raw, doc_id=path.stem)
        stats[f"{path.stem}: chunks"] = len(chunks)
        stats[f"{path.stem}: spacing repairs"] = repairs
        records.extend(asdict(chunk) for chunk in chunks)
    return records, stats


def check(index: CitationIndex) -> int:
    """Resolve every citation the rulepack makes. Returns the number unanswered."""
    from rules.loader import load_rulepack

    refs = sorted({rule.rule_ref for rule in load_rulepack().all_rules()})
    exact = external = parent = missing = 0

    for ref in refs:
        answer = index.resolve(ref)
        if answer.held:
            exact += 1
        elif "is a provision of" in answer.note:
            external += 1
            print(f"  other gazette  {ref}")
        elif answer.related:
            parent += 1
            print(f"  enclosing only {ref}  ->  {answer.related[-1].ref}")
        else:
            missing += 1
            print(f"  UNANSWERED     {ref}")

    print(
        f"\n{len(refs)} citations: {exact} exact, {external} in a gazette not held, "
        f"{parent} answered by the enclosing provision, {missing} unanswered."
    )
    if external:
        print(
            "\nThe unheld gazettes are named in the answer rather than left blank, "
            "so an officer is told which document to consult. Adding their text to "
            "data/rulebook/extracted/ is all that is needed to close them."
        )
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report only, write nothing")
    args = parser.parse_args(argv)

    records, stats = build()
    if not records:
        print(f"No gazette text found in {RULEBOOK_DIR}.", file=sys.stderr)
        return 1

    for label, value in stats.items():
        print(f"  {label}: {value}")

    index = CitationIndex.from_directory()
    # From the index, not from `DOCUMENTS`. That constant is the set of gazettes
    # this code can *name*; only the index knows which ones there is text for.
    print(f"  documents held: {len(index.held)} of {len(DOCUMENTS)} known")
    for title in index.held_titles():
        print(f"    - {title}")
    print()
    missing = check(index)

    if not args.check:
        OUTPUT.write_text(
            json.dumps({"documents": DOCUMENTS, "chunks": records}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nWrote {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KB).")

    return 1 if missing else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
