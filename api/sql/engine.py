"""Engine construction, and the decision of whether there is a database at all.

**`AKSHAR_STORAGE` has three values and the default is `auto`.** Explicit
`memory` or `sql` always win; `auto` uses Postgres when a driver is actually
importable and falls back to the in-memory stores when it is not. That is not
cleverness for its own sake — it is what makes the two documented ways of
running this system both work with no configuration:

    git clone && uvicorn api.main:app     ->  no psycopg installed  ->  memory
    docker compose up                     ->  .[api] installed      ->  sql

**The fallback is silent in development and fatal in production.** An in-memory
store loses every inspection on restart, which is fine for a demo on a laptop
and unacceptable for a department. `api.main`'s lifespan refuses to boot in
production on the memory backend, in the same place it refuses to boot with the
development JWT secret — a deployment that quietly discards evidence is worse
than one that will not start.

**No connection is opened here.** `create_engine` builds a pool lazily; the
first query connects. So a misconfigured or temporarily down database produces a
failing request with a real error, not an API that cannot start and therefore
cannot even serve `/healthz`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from api.config import get_settings

Backend = Literal["memory", "sql"]


@lru_cache(maxsize=1)
def get_engine() -> Any | None:
    """A SQLAlchemy `Engine`, or None when this process has no database.

    `pool_pre_ping` is on because the workers are long-lived and a Postgres
    restart, a failover or a connection idled out by a firewall otherwise
    surfaces as a dead connection on the next bulk job rather than as a
    reconnect. It costs one round trip per checkout.
    """
    settings = get_settings()
    if settings.storage == "memory":
        return None
    try:
        from sqlalchemy import create_engine
    except ImportError:  # pragma: no cover - sqlalchemy is a hard api dependency
        return None

    try:
        engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            future=True,
        )
    except Exception:
        # A missing driver (`psycopg` absent) or an unparseable URL. In `auto`
        # this is the ordinary "no database here" case; asked for `sql`
        # explicitly, it is a configuration error and must be loud.
        if settings.storage == "sql":
            raise
        return None
    return engine


def backend() -> Backend:
    """Which store family this process is actually using. Reported by `/healthz`."""
    return "sql" if get_engine() is not None else "memory"


def reset() -> None:
    """Drop the cached engine. For tests that change `Settings`."""
    get_engine.cache_clear()


__all__ = ["Backend", "backend", "get_engine", "reset"]
