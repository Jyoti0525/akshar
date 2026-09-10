# Submission checklist — walked, 2026-09-09

AKSHAR.md §20's checklist, item by item, with what is actually true rather than
what is intended. The plan's own warning is the reason this file exists:

> *"Teams lose marks on the boring items — the editable format, the search
> facility, the deployment document. Check these the night before, not the
> morning of."*

So this is the night-before list, walked early enough that the red rows can
still be turned green. **Re-walk it before submission** — a checklist is a
snapshot, and three of the rows below depend on work that is blocked on
photographs.

| | Item | State |
|---|---|---|
| 1 | GitHub public with a README that works | 🟡 |
| 2 | `docker compose up` from a clean clone | 🟡 |
| 3 | Architecture document, ≤2 pages | ✅ |
| 4 | Demo video, ≤2 minutes | ❌ |
| 5 | Presentation, ≤5 slides | ❌ |
| 6 | `RESULTS.md` with dated accuracy **and** latency | 🟡 |
| 7 | Reports export PDF **and editable** | ✅ |
| 8 | Search across all facets | ✅ |
| 9 | Role-based access demonstrable | ✅ |
| 10 | Deployment framework documented | ✅ |
| 11 | Offline demo rehearsed in aeroplane mode | ✅ |
| 12 | **Rule 7 tables + Second Schedule cross-checked by two people** | 🟡 |

---

## 1. GitHub public with a README that works 🟡

[`README.md`](../README.md) runs the whole stack in one command with no Docker
(`python scripts/run_demo.py`), names the three sign-ins, and states the three
gaps in the interface rather than hiding them.

**What is not done:** the repository has **no commits**. Everything is untracked
in a working tree. That is one `git init && git add && git commit` away, but
until it happens there is nothing to make public and "clean clone" has no
meaning. It also means the `.gitignore` written for the 900 MB of photographs
has never been exercised against a real `git add`.

## 2. `docker compose up` from a clean clone 🟡

[`docker-compose.yml`](../docker-compose.yml) and [`docker/`](../docker/) exist
and `db/schema.sql` initialises Postgres 17 + pgvector. Migration `0002` was
added today and has **not been run against a live database** — `db/schema.sql`
carries the same DDL and `tests/unit/test_schema.py` asserts the two agree, so
a fresh `compose up` is covered, but an *upgrade* from `0001` is untested.

**Do before submission:** `docker compose up -d db && alembic upgrade head` on a
database created at `0001`.

## 3. Architecture document, two pages ✅

[`docs/architecture.md`](architecture.md), including the section that names the
honest gaps. Also: [`docs/spec-deltas.md`](spec-deltas.md) for every departure
from the plan, [`docs/legal-decisions.md`](legal-decisions.md) for rules found
and deliberately not shipped, and [`docs/plan-migration.md`](plan-migration.md)
for the MAAPDAND→AKSHAR switch.

## 4. Demo video, two minutes ❌

Not made. §20 scripts it minute by minute and the script is the storyboard.

**Two of its eleven beats cannot currently be filmed as written:**

- *0:15 — "1.6 mm measured, 2.0 mm required"*. Needs a packet whose MRP is
  genuinely under-height and a scan that measures it. The ruler set has the
  packets; MRP coverage on it is below the 0.90 bar, so the beat depends on
  picking a frame that reads.
- *1:55 — "0.13 mm mean error"*. `RESULTS.md` records **0.499 mm** on 4 of 40
  frames. The number in the script is the target, not the measurement. **Do not
  say it.** Say what was measured, on how many frames, and that the rest did not
  yield a declaration — that is a stronger position than a number a judge can
  ask you to reproduce.

The other nine beats are all runnable today, including the aeroplane-mode one.

## 5. Presentation, five slides ❌

Not made.

## 6. `RESULTS.md` with dated accuracy and latency 🟡

Every number in it is dated and traceable to a script. Latency is thorough.
**Accuracy is the gap**: U1 is 0.499 mm on 4 of 40 frames against a ≤0.15 mm
target, and MRP coverage is below the 0.90 bar. Both are recorded honestly with
the decomposition of the misses, which is the right way to be short of a target.

## 7. Reports export PDF and editable ✅

[`reports/`](../reports/) renders one HTML template through WeasyPrint to PDF and
python-docx to `.docx`. §20 flags "the editable format" as an item teams lose
marks on; it is done and tested (`tests/unit/test_reports.py`).

## 8. Search across all facets ✅

`GET /search` — brand, barcode, date, district, officer, rule, status — and the
`/search` page in the PWA. Backed by the `ScanStore` Protocol, so the in-memory
and SQL paths cannot answer differently.

## 9. Role-based access demonstrable ✅

Three roles, three sign-ins, `require_role` on every guarded route against the
signed token. The navigation hides links an officer may not use, and
[`web/src/components/nav.tsx`](../web/src/components/nav.tsx) says in its own
docstring that hiding a link is courtesy and not a security control.

Demonstrable in about fifteen seconds: sign in as `officer@akshar.demo`, note
that `/dashboard` is absent from the masthead, then visit it directly and get a
403 from the API rather than a redirect.

## 10. Deployment framework documented ✅

[`docs/deployment.md`](deployment.md), and it leads with the failure that will
actually happen: a reverse proxy that drops the COOP and COEP headers halves the
WASM path silently, with nothing in the console to say so.

## 11. Offline demo rehearsed in aeroplane mode ✅

A Playwright test, not a memory: `web/e2e/` takes a photograph with the browser
context offline and asserts the L4 record survives a reload. 12 e2e tests in
total. **Rehearse it on the actual demo laptop anyway** — the test proves the
code path, not the venue's wifi captive portal.

## 12. Rule 7 tables + Second Schedule cross-checked by two people 🟡

**This is the highest-risk row on the list and the plan says so twice.** §20's
risk table: *"Rulepack drifts from the act — Values were wrong once already,
from a vendor blog."*

Done so far: the tables were re-derived from the gazette PDFs during the
rulebook build, `docs/legal-decisions.md` records what was declined and why, and
`tests/unit/test_engine.py::test_table_one_bands_and_boundaries` pins the bands.
`data/rulebook/` holds the extracted text with a manifest, so every value is
traceable to a page.

**Not done: the second person.** One reviewer has checked these; §20 asks for
two, and the whole point of the second is that the first cannot catch their own
misreading. This needs a human hour with the bare act PDF open beside
[`rules/packs/`](../rules/packs/), and it is the single cheapest way to protect
the claim the entire project rests on.

---

## The three blocked items, restated

Not §20 checklist rows, but they gate rows 4 and 6 and they cannot be produced
by writing code:

1. **Originals for the remaining 248 corpus frames** — 231 arrived 2026-09-09
   and cover 221 of 469. See [`docs/corpus.md`](corpus.md).
2. **The 40-photo ruler ground truth, re-measured.** The frames exist and are
   sealed; the recorded heights are whole and half millimetres, which reads like
   a rule read to 0.5 mm rather than the 0.1 mm §16 asks for. U1 cannot beat its
   own ground truth's resolution.
3. **20–30 deliberately non-compliant frames.** §17's M0 acceptance criterion is
   *"rejects the deliberately-bad subset at ≥90% recall"*, and there is no
   deliberately-bad subset. The pass-rate half of M0 can be measured today; the
   recall half cannot be claimed at all.
