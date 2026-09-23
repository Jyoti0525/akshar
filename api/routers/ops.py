"""`/healthz`, `/metrics`, `/api/v1/rules`, and chain status. AKSHAR.md sections 12, 18.

`/healthz` reports **degraded** rather than failing when models are absent,
which is the honest answer: without weights the geometry path, the rules engine
and the whole `listing_text` channel still work, and the pipeline reports a
degradation tier per scan. A health check that returned 503 because a 12 MB file
was missing would take down a service that is, in fact, serving.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from api.config import get_settings
from api.deps import ScanStoreDep, require_role
from api.schemas import ChainStatusResponse, HealthResponse
from evidence.anchor import default_path as anchor_path
from evidence.anchor import verify_anchors
from evidence.verify import head_digest, verify_chain
from retrieval.citations import DOCUMENTS as RULEBOOK_DOCUMENTS
from retrieval.citations import load_index
from rules.loader import load_rulepack

router = APIRouter(tags=["ops"])


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    from vision import runtime

    detail: list[str] = []

    try:
        pack = load_rulepack()
        rules_loaded = len(pack.all_rules())
        rulepack_version = pack.version_string
        if not pack.claims_currency():
            detail.append(
                "rulepack does not claim currency: an amendment in the source "
                "register is unverified (section 13a)"
            )
    except Exception as exc:  # pragma: no cover - a broken pack is a hard failure
        return HealthResponse(
            status="degraded",
            rulepack_version="unloadable",
            rules_loaded=0,
            models_present=0,
            models_expected=0,
            detail=[f"rulepack failed to load: {exc}"],
        )

    # `scripts/` is a directory of entry points, not one of the nine packages in
    # `[tool.setuptools]`, so it is absent from any image built from the wheel
    # alone — a Hugging Face Space, for one. A health endpoint that returns 500
    # because a helper module is missing is the worst possible failure: it is
    # the endpoint whose whole job is to answer "is this alive", and the
    # container orchestrator believes it.
    #
    # So the manifest is optional and its absence is reported rather than
    # raised. The count is the only thing lost, and the count is advisory.
    try:
        from scripts.fetch_models import ARTIFACTS
    except ModuleNotFoundError:
        expected = 0
        present = 0
        detail.append(
            "model manifest unavailable (scripts/ is not in this image), so the "
            "count below is not a check; the pipeline still reports a tier per scan"
        )
    else:
        expected = len(ARTIFACTS)
        present = sum(1 for artifact in ARTIFACTS if (runtime.MODELS_DIR / artifact.name).exists())
        if present < expected:
            detail.append(
                f"{expected - present} model artifact(s) absent; scans will "
                f"degrade and report a tier rather than fail"
            )

    from reports.render import pdf_available

    can_pdf, why = pdf_available()
    if not can_pdf:
        # Degraded, not broken. DOCX is the format the problem statement names,
        # and it has no native dependencies — so this is worth reporting and is
        # not worth refusing to serve over.
        detail.append(f"PDF rendering unavailable: {why}")

    from api.sql.engine import backend

    storage = backend()
    if storage == "memory":
        # Not an error — it is how a clean clone and the offline demo run — but
        # it must be visible. An operator looking at a healthy green page has no
        # other way to discover that nothing is being persisted.
        detail.append(
            "storage backend is in-memory: scans are held in this process and "
            "lost on restart (set AKSHAR_DATABASE_URL for Postgres)"
        )
        # The memory backend has no migration and no registration route, so
        # `api/main.py` creates three fixed accounts at boot or nobody could sign
        # in at all. Their password is published in `api/demo.py`. That is safe
        # only because production refuses to boot on this backend, and saying so
        # on the health page is how anyone who got here another way finds out.
        detail.append(
            "DEMONSTRATION ACCOUNTS: three fixed sign-ins exist with a published "
            "password, because the in-memory backend has no other way to create a "
            "user. Never reachable in production."
        )

    if get_settings().demo_seed:
        # The loudest place this can be said. Anyone reading a green health page
        # against a stack holding invented packets needs to be told so before
        # they quote a number off the dashboard.
        detail.append(
            "DEMONSTRATION DATA: AKSHAR_DEMO_SEED is set, so this instance was "
            "seeded with synthetic packages at boot. Verdicts are real rulepack "
            "output; the labels they were computed from are not real packets."
        )

    return HealthResponse(
        status="ok" if not detail else "degraded",
        rulepack_version=rulepack_version,
        rules_loaded=rules_loaded,
        models_present=present,
        models_expected=expected,
        storage=storage,
        detail=detail,
    )


@router.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/v1/rules", tags=["rules"])
async def active_rulepack() -> dict:
    """The rulepack, readable. Section 12, and `/rules` in the web app.

    Deliberately unauthenticated. Section 5 calls the whole legal logic "40 KB
    of text, small enough to email", and the argument for rules-as-data is
    weakened by hiding them. There is nothing here that is not already in a
    gazette.
    """
    pack = load_rulepack()
    index = load_index()
    return {
        "version": pack.version_string,
        "authority": pack.meta.get("authority"),
        "claims_currency": pack.claims_currency(),
        "sources": pack.meta.get("sources", []),
        "amendments_checked": pack.meta.get("amendments_checked", []),
        "amendments_unverified": pack.meta.get("amendments_unverified", []),
        "rules": [
            {
                "id": rule.id,
                "rule_ref": rule.rule_ref,
                "severity": rule.severity,
                "check": rule.check,
                "fields": list(rule.target_fields()),
                "message": rule.message,
                "enabled": rule.enabled,
                # Whether tier 1 can show the clause behind this citation.
                # Reported per rule rather than left to the client to discover:
                # five of the pack's rules cite the National Standards and
                # Numeration Rules, whose text this deployment does not carry,
                # and a "why" button that silently does nothing looks broken.
                # `GET /api/v1/rules/citation?ref=...` names the gazette instead.
                "text_held": index.resolve(rule.rule_ref).held,
            }
            for rule in pack.all_rules()
        ],
        "documents_held": sorted(RULEBOOK_DOCUMENTS.values()),
    }


@router.get(
    "/api/v1/chain/status",
    response_model=ChainStatusResponse,
    dependencies=[Depends(require_role("supervisor"))],
    tags=["evidence"],
)
async def chain_status(scans: ScanStoreDep) -> ChainStatusResponse:
    """Verify the evidence chain on demand. Section 6, section 17 M7.

    Exposed because a chain nobody ever verifies is a column rather than a
    control. Supervisor and above: the result names which record failed, which
    is information about a live case.
    """
    records = scans.all_records()
    report = verify_chain(records)

    # The anchor log answers the question `verify_chain` cannot. A wholesale
    # rewrite is internally consistent and reports ok=True above; what it cannot
    # do is match digests published before the rewrite.
    #
    # A log that cannot be read is reported as a failure, not swallowed. The one
    # circumstance in which this file is unreadable and it does not matter is
    # indistinguishable, from here, from the one in which someone has removed
    # it.
    try:
        anchors = verify_anchors(anchor_path(), records)
        anchor_failures = list(anchors.failures)
        held, compared = anchors.anchors, anchors.checked
        # "Nothing disagreed" and "nothing was asked" are different answers.
        status = "ok" if anchors.ok else "failed"
        if held == 0:
            status = "unanchored"
    except (OSError, ValueError) as exc:
        anchor_failures = [f"the anchor log could not be read: {exc}"]
        status, held, compared = "unreadable", 0, 0

    return ChainStatusResponse(
        checked=report.checked,
        ok=report.ok,
        head_sha256=head_digest(records),
        failures=[str(failure) for failure in report.failures],
        anchor_status=status,
        anchors=held,
        anchors_checked=compared,
        anchor_failures=anchor_failures,
    )
