"""Retrieval — AKSHAR.md section 15.

    "Retrieval exists to *show an officer the law behind a verdict*, nothing
     more."

**Never in the decision path.** `rules/` decides; this package explains. Nothing
here is imported by the rules engine, and a failure in this package can cost an
officer an explanation but can never change a verdict.

Tier 1 — `citations.py` — is a dictionary lookup keyed on the `rule_ref` every
verdict already carries. Tiers 2 and 3 are §15's week-7 work and the first thing
it says to cut.
"""

from retrieval.citations import Answer, Citation, CitationIndex, explain, load_index

__all__ = ["Answer", "Citation", "CitationIndex", "explain", "load_index"]
