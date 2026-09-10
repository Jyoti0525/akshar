"""FastAPI dependencies — auth, stores, and the audit trail.

Every store reaches a router through a dependency rather than a module-level
singleton, so `app.dependency_overrides` can swap the whole persistence layer in
a test. That is also what lets the API run against the in-memory stores for an
offline demo with no Docker stack up.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.config import Settings, get_settings
from api.deps.resources import get_bulk_jobs, get_enqueuer, get_object_store, get_spool
from api.repository import (
    AuditLog,
    BulkJobStore,
    InMemoryAuditLog,
    InMemoryReviewStore,
    InMemoryScanStore,
    InMemorySkuStore,
    InMemoryUserStore,
    ReviewStore,
    ScanStore,
    SkuStore,
    UserStore,
)
from api.schemas import CurrentUser
from api.security import AuthError, Role, decode_token, outranks

# `auto_error=False` so a missing header produces our own 401 with a useful
# message rather than FastAPI's bare 403, which is both the wrong code and
# unhelpful to a client trying to work out whether to refresh.
_bearer = HTTPBearer(auto_error=False)

# Process-wide stores, built once. `api.sql.engine` decides whether that means
# Postgres or a dict — see its module docstring for the `auto` rule — and
# `app.dependency_overrides` replaces the lot in a test.
#
# The in-memory objects are constructed unconditionally and cheaply, so the SQL
# and memory paths are never half-initialised: a deployment that loses its
# database at boot does not end up with three real stores and one None.
_memory_skus = InMemorySkuStore()
_memory_scans = InMemoryScanStore(skus=_memory_skus)
_memory_users = InMemoryUserStore()
_memory_audit = InMemoryAuditLog()
_memory_reviews = InMemoryReviewStore()


@lru_cache(maxsize=1)
def _sql_stores() -> dict[str, object] | None:
    """The five SQL-backed stores, or None when this process has no database."""
    from api.sql.engine import get_engine

    engine = get_engine()
    if engine is None:
        return None
    from api.sql.stores import (
        SqlAuditLog,
        SqlReviewStore,
        SqlScanStore,
        SqlSkuStore,
        SqlUserStore,
    )

    return {
        "scans": SqlScanStore(engine),
        "users": SqlUserStore(engine),
        "skus": SqlSkuStore(engine),
        "audit": SqlAuditLog(engine),
        "reviews": SqlReviewStore(engine),
    }


def _store(name: str, fallback: object) -> object:
    stores = _sql_stores()
    return fallback if stores is None else stores[name]


def get_scan_store() -> ScanStore:
    return _store("scans", _memory_scans)  # type: ignore[return-value]


def get_user_store() -> UserStore:
    return _store("users", _memory_users)  # type: ignore[return-value]


def get_sku_store() -> SkuStore:
    return _store("skus", _memory_skus)  # type: ignore[return-value]


def get_audit_log() -> AuditLog:
    return _store("audit", _memory_audit)  # type: ignore[return-value]


def get_review_store() -> ReviewStore:
    return _store("reviews", _memory_reviews)  # type: ignore[return-value]


SettingsDep = Annotated[Settings, Depends(get_settings)]
# The three resources that may legitimately be absent — see `resources.py`. They
# are dependencies rather than module globals for the same reason the stores are:
# a test overrides them, and an offline demo runs without any of them.
BulkJobStoreDep = Annotated[BulkJobStore, Depends(get_bulk_jobs)]
SpoolDep = Annotated[object, Depends(get_spool)]
ObjectStoreDep = Annotated[object, Depends(get_object_store)]
EnqueueDep = Annotated[object, Depends(get_enqueuer)]
ScanStoreDep = Annotated[ScanStore, Depends(get_scan_store)]
UserStoreDep = Annotated[UserStore, Depends(get_user_store)]
SkuStoreDep = Annotated[SkuStore, Depends(get_sku_store)]
AuditDep = Annotated[AuditLog, Depends(get_audit_log)]
ReviewStoreDep = Annotated[ReviewStore, Depends(get_review_store)]


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    users: UserStoreDep,
    settings: SettingsDep,
) -> CurrentUser:
    """Resolve the bearer token to a user, or 401.

    The token is decoded with `expect="access"`, so a 14-day refresh token
    presented as a bearer credential is rejected here rather than accepted as a
    fortnight-long session against enforcement evidence.

    The user is then re-read from the store: a token issued before an account
    was deactivated must stop working immediately, and a claim inside a signed
    token cannot know that.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing. Send `Bearer <access token>`.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_token(credentials.credentials, expect="access", settings=settings)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    record = users.by_id(UUID(claims["sub"]))
    if record is None or not record.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account no longer active.",
        )
    return CurrentUser(
        id=record.id,
        email=record.email,
        full_name=record.full_name,
        role=record.role,  # type: ignore[arg-type]
        district=record.district,
    )


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]


def require_role(minimum: Role):
    """Dependency factory gating a route on a minimum role.

    Uses `outranks`, so an admin reaching a supervisor route is the ordinary
    consequence of the hierarchy rather than something each route has to
    remember to allow. Listing permitted roles per route is how an admin ends up
    locked out of a dashboard.
    """

    async def _guard(user: CurrentUserDep) -> CurrentUser:
        if not outranks(user.role, minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This endpoint requires the {minimum} role or above.",
            )
        return user

    return _guard


def client_ip(request: Request) -> str | None:
    """Best-effort client address for `access_log`.

    `X-Forwarded-For` is trusted only for its first hop and only because this
    sits behind the department's own reverse proxy. It is written to an audit
    row, never used for an authorisation decision, so a spoofed value misleads
    a reader rather than granting access.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


__all__ = [
    "AuditDep",
    "BulkJobStoreDep",
    "CurrentUserDep",
    "EnqueueDep",
    "ObjectStoreDep",
    "ReviewStoreDep",
    "ScanStoreDep",
    "SettingsDep",
    "SkuStoreDep",
    "SpoolDep",
    "UserStoreDep",
    "client_ip",
    "current_user",
    "get_audit_log",
    "get_bulk_jobs",
    "get_enqueuer",
    "get_object_store",
    "get_scan_store",
    "get_sku_store",
    "get_spool",
    "get_user_store",
    "require_role",
]
