"""The FastAPI application. AKSHAR.md sections 12 and 15b.

    "API: FastAPI 0.115 + Pydantic v2, async, `uvloop`. Pydantic v2 is
     Rust-backed; v1 validation would show at bulk-upload volume." -- section 15b

Run it:

    uvicorn api.main:app --reload

**It starts with no database, no Redis and no MinIO.** The stores are
Protocol-typed dependencies backed by in-memory implementations until a real
backend is wired in, which means `/healthz`, `/api/v1/rules` and the whole
`listing_text` channel work from a clean clone. That is not a toy mode: it is
the same substitutability that lets the API be tested in CI without a stack, and
it mirrors how `vision/` already takes its lookups from the caller.

**Two headers are set on every response**, and they are not decoration.
Section 15b: multithreaded WASM only runs when the page is cross-origin
isolated, and without `COOP`/`COEP` ONNX Runtime pins `numThreads` to 1 and *"the
WASM fallback path roughly doubles in latency"*. That is a server config line
that decides a headline number, so it lives in code with a comment rather than
in a deployment note somebody forgets.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import get_settings
from api.routers import auth, dashboard, ops, rules, scans, skus

DESCRIPTION = """
Compliance checking for packaged commodities under the **Legal Metrology
(Packaged Commodities) Rules, 2011**.

Three inputs, one rules engine: a photograph, a bulk image set, or an
e-commerce listing with no image at all. Verdicts come from a versioned YAML
rulepack citing gazette clauses — never from a model.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Fails loudly at boot rather than quietly issuing forgeable tokens. Only
    # bites outside development, so a clone still runs with no configuration.
    settings.require_production_ready()

    # The same argument, applied to storage. `AKSHAR_STORAGE=auto` falls back to
    # the in-memory stores when no database driver is importable, which is right
    # for a laptop and catastrophic for a department: every inspection would be
    # lost on the next restart, silently and with a perfectly healthy-looking
    # API in front of it. Refuse instead.
    from api.sql.engine import backend

    if settings.is_production and backend() == "memory":
        raise RuntimeError(
            f"refusing to start in {settings.environment}: no database is "
            f"configured, so scans would be held in memory and lost on restart. "
            f"Set AKSHAR_DATABASE_URL and install the `api` extra."
        )

    # Load the rulepack once. It is ~40 KB and parsing it per request would show
    # against section 4's 10 ms budget for the whole engine.
    from rules.loader import load_rulepack

    load_rulepack()

    # Two separate things, deliberately.
    #
    # ACCOUNTS are unconditional on the memory backend, because that backend has
    # no migration and no registration route: without the three rows in
    # `api/demo.py` there is no way to sign in, and the empty instance the
    # launcher advertises would be an instance nobody can open. Production never
    # reaches this line — it refuses to boot on the memory backend above.
    #
    # The SHELF is opt-in, and gated on the setting AND the backend. `api/demo.py`
    # says why the second condition is not paranoia: a department's dashboard
    # counting invented packets as inspections is a worse failure than the demo
    # not starting.
    if backend() == "memory":
        from api import demo
        from api.deps import get_user_store

        app.state.demo = {"users": len(demo.seed_accounts(get_user_store()))}

    if settings.demo_seed:
        if settings.is_production:
            raise RuntimeError(
                "refusing to start: AKSHAR_DEMO_SEED is set in "
                f"{settings.environment}. Demonstration rows must never enter a "
                f"real evidence store."
            )
        if backend() == "memory":
            from api import demo
            from api.deps import get_scan_store, get_sku_store, get_user_store

            # `seed` re-adds the same three accounts under the same UUIDs, which
            # the store treats as an upsert. Calling it after `seed_accounts` is
            # therefore idempotent rather than a duplicate-key error.
            app.state.demo = demo.seed(
                users=get_user_store(),
                skus=get_sku_store(),
                scans=get_scan_store(),
            )
        else:
            raise RuntimeError(
                "refusing to seed: AKSHAR_DEMO_SEED is set but the storage "
                "backend is SQL. Set AKSHAR_STORAGE=memory for a demo."
            )

    yield


app = FastAPI(
    title="AKSHAR",
    description=DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_isolation_and_timing_headers(request: Request, call_next):
    """Cross-origin isolation, plus the latency figure section 11 puts on screen.

    `X-Response-Time-Ms` exists because we make a speed claim and section 11
    requires the number to be visible on every scan: *"we make a speed claim,
    and showing it makes the claim verifiable."* A claim nobody can check is
    marketing.
    """
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    # Without these two, in-browser WASM runs single-threaded and roughly halves
    # our offline speed. See section 15b, "Deployment requirement".
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    return response


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """A bad value is a 400, not a 500.

    Notably `CanonicalisationError` — a scan carrying a non-finite measurement
    is a malformed submission, and telling the client that is more useful than
    a stack trace.
    """
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(auth.router)
app.include_router(scans.router)
app.include_router(skus.router)
app.include_router(ops.router)
app.include_router(dashboard.router)
app.include_router(rules.router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    return {
        "name": "AKSHAR",
        "docs": "/docs",
        "health": "/healthz",
        "rules": "/api/v1/rules",
    }
