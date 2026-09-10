"""The three resources that are not a database: MinIO, the spool, the queue.

Kept apart from `api/deps/__init__.py` because they share one property the
stores do not: **each of them may legitimately be absent, and the API still
works.** No MinIO means evidence is not uploaded and says so; no Redis means the
evidence upload happens inline and the response is a little slower; no broker
means a bulk request is refused with an explanation rather than accepted and
lost. None of those is a 500, and none of them stops an officer recording an
inspection.

Every factory is `lru_cache`d, so one client per process. A `Minio` object holds
a connection pool and building one per request would open a socket per scan.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from api.config import Settings, get_settings
from api.repository import BulkJobStore, InMemoryBulkJobStore
from evidence.spool import EvidenceSpool, InMemorySpool, RedisSpool

_memory_bulk_jobs = InMemoryBulkJobStore()


@lru_cache(maxsize=1)
def get_bulk_jobs() -> BulkJobStore:
    """Bulk job receipts. SQL when there is a database, a dict when there is not.

    Worth noting that this one is written from Dramatiq worker threads rather
    than from request handlers, and both implementations increment atomically —
    the in-memory store under a lock, the SQL one with `completed = completed +
    1`. A read-modify-write here loses increments and produces a job that never
    reaches its total, which is a hang with no error.
    """
    from api.sql.engine import get_engine

    engine = get_engine()
    if engine is None:
        return _memory_bulk_jobs
    from api.sql.stores import SqlBulkJobStore

    return SqlBulkJobStore(engine)


@lru_cache(maxsize=1)
def get_rulebook() -> Any | None:
    """Tier-2 search over `rule_chunks`, or None when there is no database.

    Returning None rather than an empty stub is deliberate. Tier 2 is the only
    part of retrieval that needs Postgres; tier 1 is a dict lookup over files
    and must keep working without one. The endpoint therefore answers "search
    is unavailable here" instead of "no results", which are different facts and
    only one of them means the officer's question had no answer.
    """
    from api.sql.engine import get_engine

    engine = get_engine()
    if engine is None:
        return None
    from api.sql.rulebook import SqlRulebook

    return SqlRulebook(engine)


@lru_cache(maxsize=1)
def get_object_store() -> Any | None:
    """A MinIO client, or None if the library or the endpoint is absent.

    Constructing a `Minio` opens nothing — the first request does — so this is
    safe at import and cheap when the server is down. `ensure_buckets` is
    deliberately *not* called here: it is a network round trip, and a factory
    that blocks on an unreachable MinIO would turn a storage outage into a
    failure to serve `/healthz`, which is precisely the page you want during
    a storage outage.
    """
    settings = get_settings()
    try:
        from minio import Minio
    except ImportError:  # pragma: no cover - `pip install -e .[api]` supplies it
        return None
    if not settings.minio_endpoint:
        return None
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


@lru_cache(maxsize=1)
def get_redis() -> Any | None:
    """A Redis client, or None. Used for the spool, never for anything durable."""
    settings = get_settings()
    try:
        import redis
    except ImportError:  # pragma: no cover
        return None
    try:
        return redis.Redis.from_url(settings.redis_url)
    except Exception:  # pragma: no cover - a malformed URL should not stop boot
        return None


@lru_cache(maxsize=1)
def get_spool() -> EvidenceSpool:
    """Redis where there is one, a dict where there is not.

    The in-memory fallback is correct only when the API and the worker are the
    same process, which is exactly the case where Redis is absent — a laptop
    demo or a test. The two conditions travel together, so there is nothing for
    a person to remember and nothing to misconfigure.
    """
    from workers.broker import is_stub

    client = None if is_stub() else get_redis()
    return InMemorySpool() if client is None else RedisSpool(client=client)


def enqueue(task: str, *, queue: str, **kwargs: Any) -> None:
    """Send one message to a named actor in `workers.tasks`.

    `queue` is **checked, not applied.** A Dramatiq actor's queue is fixed at
    declaration, so passing one here could only ever disagree with the truth;
    asserting instead means a caller that thinks it is enqueueing on `bulk` and
    is actually on `scan` finds out at the call site. Section 8c's whole
    guarantee rests on which lane a message lands in, and the failure otherwise
    is invisible: the message runs, correctly, at the wrong priority.
    """
    from workers import tasks

    actor = getattr(tasks, task, None)
    if actor is None or not hasattr(actor, "send_with_options"):
        raise ValueError(f"no such task: {task}")
    if actor.queue_name != queue:
        raise ValueError(
            f"{task} is declared on the {actor.queue_name!r} queue, not {queue!r}"
        )
    actor.send_with_options(kwargs=kwargs)


def get_enqueuer() -> Any:
    return enqueue


def reset_caches() -> None:
    """Drop the cached clients. For tests that change `Settings`."""
    get_object_store.cache_clear()
    get_redis.cache_clear()
    get_spool.cache_clear()
    get_bulk_jobs.cache_clear()
    get_rulebook.cache_clear()


__all__ = [
    "Settings",
    "enqueue",
    "get_bulk_jobs",
    "get_enqueuer",
    "get_object_store",
    "get_redis",
    "get_rulebook",
    "get_spool",
    "reset_caches",
]
