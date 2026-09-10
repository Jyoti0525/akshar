# Legal decisions — what we found, traced, and did not ship

Three clauses in the source documents look like checkable rules and are not.
Each was read, tested against real label text, and deliberately left out.

A team that can explain why it declined to ship a finding reads better than one
that ships it. These three together are a better answer to *"how do you know
your rules are right?"* than any accuracy number.

---

## 1. The comma separator — traced, and not built

**What the gazettes say.** Two instruments prohibit comma grouping, and the
second points straight at us.

*Numeration Rules 2011, rule 4* — writing a number exceeding three digits, the
decimal point is the starting point; under Indian terminology the first three
digits group together and subsequent digits divide into groups of two, under
English terminology into groups of three, and in both cases **neither dots nor
commas shall be inserted in the intervening spaces**. The gazette's own
examples are `23 14 345.732 23 50` and `123 345.732 456`.

*National Standards Rules, Third Schedule, item 11* — expressly about numbers
used **in connection with units of weights and measures**: the dot separates
integral from decimal part, numbers divide into groups of three from the
decimal point, and neither dots nor commas go in the gaps. Its illustration is
explicit: write `3211 468.022 82`, **not** `3,211,468.022.82`.

On its face, `Net Wt. 1,500 g` is unlawful and `Net Wt. 1 500 g` is correct.

**Why we did not build it.** Three reasons; the third settles it.

1. **It does not reach the MRP.** Item 11 governs numbers used with units of
   weight or measure. A retail sale price is a monetary amount, not a
   measurement. `MRP Rs. 1,250.00` is outside the clause entirely — and the MRP
   is where the commas actually appear on real labels.

2. **The magnitude rule makes it nearly unreachable on net quantity.** Third
   Schedule item 10 requires the multiple to be chosen so the value falls in
   [0.1, 1000). A compliant net quantity is therefore `1.5 kg`, never `1500 g`
   — so a four-digit quantity needing grouping is *already* a violation of item
   10, which is a cleaner and better-founded finding. Flagging the comma would
   be flagging a symptom.

3. **A rule that fires on every product in India is a rule being read wrong.**
   Enforcement has never treated the comma as an offence. Shipping it would
   generate mass false violations and destroy the tool's credibility with the
   one user who matters.

**What we built instead.** `LMPC.QTY.UNIT_MAGNITUDE` cites Third Schedule item
10 alongside LMPC r.13(2)-(3), and carries the upper bound the original rule
was missing. Commas are accepted everywhere in extraction, via the `amount`
pattern.

> *"We found a clause that would make every label in India non-compliant,
> traced why it does not apply, and built the rule underneath it instead."*

---

## 2. The litre symbol — shipped, but disabled

**What the gazette says.** National Standards Rules, Fourth Schedule item 3
gives the litre symbol as lower-case **`l`**, equal to one thousandth of a
cubic metre.

**The problem.** International practice and BIPM both accept `L`, and virtually
every Indian beverage label uses `L` or `Ltr`.

**What we did.** `LMPC.UNIT.LITRE_SYMBOL` exists in the rulepack at severity
`low`, marked `advisory: true`, and **`enabled: false`**. Turning it on is a
one-line data edit for a deployment that wants it; the report says it is
disputed.

`Ltr` and `LTR` are separately caught by `LMPC.UNIT.SYMBOL_PLURAL` and
`LMPC.UNIT.SYMBOL_CASE`, which rest on firmer ground.

---

## 3. National Standards Rule 18 — a promising lead that was nothing

**What it says.** Units in the **Seventh and Eighth Schedules** shall not be
used in any field except scientific and technological research.

That sounded like it would catch imperial units on a label — `1 lb`, `16 oz`,
`5 inches`.

**It does not.** The Seventh Schedule is CGS units with special names: erg,
dyne, poise, stokes, gauss, oersted, maxwell, stilb, phot. The Eighth is fermi,
torr, kilogram-force, calorie, micron, X unit, gamma, lambda. Obscure
scientific units; no imperial anywhere.

Imperial on a label is already caught by `LMPC.NETQTY.SI_UNITS` under LMPC
r.13(5), not by rule 18.

**The trap inside it.** The **calorie** sits in the Eighth Schedule. A naive
reading makes every nutrition panel printing `kcal` a violation.

It is not. Nutrition labelling is FSSAI's domain and mandates kcal, and LMPC
does not govern nutritional declarations at all. **Do not encode it.**

---

## The discipline behind all three

From §13a of the plan:

> Every value in the rulepack must trace to a document in the source register.
> No blog summaries, no recalled figures, no "this is probably right."

One earlier draft carried Rule 7 height thresholds taken from a vendor blog.
They were wrong, and they would have made every verdict incorrect while looking
confident. A dropped rule — `ratio_min`, for a "Unit Sale Price must be half
the MRP height" requirement that is **not in the 2011 Rules** — came from the
same source.

Two consequences visible in the code:

- Values that cannot yet be traced are marked `verification: pending_gazette`
  in the rulepack, and a mismatch against them yields **REVIEW**, never FAIL.
- `meta.amendments_known_missing` lists the three notifications we do not hold,
  and `Rulepack.claims_currency()` returns `False` while it is non-empty. The
  version string must never claim an amendment the register cannot evidence.
