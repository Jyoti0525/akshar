"""The Dramatiq broker. AKSHAR.md sections 12 and 8c.

    "Dramatiq 1.17 over Celery: heavier, worse defaults."      -- section 15b

**The broker is chosen at import, and it can be a stub.** `workers/tasks.py`
declares its actors against whatever this returns, so a test importing the
actors gets an in-process `StubBroker` and a deployed worker gets Redis. Without
that, importing the task module in CI would open a socket to a Redis that is not
there — and every test of the upload path would need a container.

**Two queues, declared here so both sides agree on the names.** A typo'd queue
name is a message that is enqueued successfully, acknowledged by the broker, and
never consumed by anyone: the worst possible failure shape, because nothing
errors. `QUEUE_SCAN` and `QUEUE_BULK` are the only two, and `workers/tasks.py`
takes them from this module rather than spelling them again.

**`BulkFairShare` is attached here, not in the worker command line.** The
weighting is a correctness property of the system — section 8c's whole point —
and a property that only holds when somebody remembers a flag does not hold.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import dramatiq

from workers.middleware import BULK_QUEUE, SCAN_QUEUE, BulkFairShare

QUEUE_SCAN = SCAN_QUEUE
"""Interactive work: the evidence upload behind a scan an officer is watching,
and a report they asked for. Latency-sensitive; almost always short."""

QUEUE_BULK = BULK_QUEUE
"""Everything nobody is waiting on: bulk ingestion, `scan_count` bumps,
retraining exports, dashboard rebuilds. Throughput-sensitive; often long."""

_STUB_ENV = "AKSHAR_BROKER"


def _want_stub() -> bool:
    """Should this process talk to a real Redis?

    An explicit `AKSHAR_BROKER` always wins, so a developer can point a local
    worker at a real broker or force the stub in either direction. Otherwise the
    stub is used when pytest is in the process, because a unit test that needs a
    container is not a unit test — and, importantly, `pytest` in `sys.modules`
    is true at *collection* time, whereas `PYTEST_CURRENT_TEST` is only set once
    a test is running and would be absent at the moment `workers.tasks` imports.
    """
    configured = os.environ.get(_STUB_ENV, "").strip().lower()
    if configured in {"stub", "memory", "none"}:
        return True
    if configured in {"redis"}:
        return False
    return "pytest" in sys.modules


def build_broker(*, url: str | None = None, stub: bool | None = None) -> Any:
    """Construct a broker with our middleware attached. Does not connect.

    `RedisBroker` builds its client lazily, so calling this on a machine with no
    Redis is fine until something is actually enqueued. That is deliberate: the
    API must import cleanly and serve `/healthz` with the queue down, and report
    the queue as degraded rather than refusing to start.
    """
    use_stub = _want_stub() if stub is None else stub
    if use_stub:
        from dramatiq.brokers.stub import StubBroker

        broker: Any = StubBroker()
        broker.emit_after("process_boot")
    else:
        from dramatiq.brokers.redis import RedisBroker

        from api.config import get_settings

        broker = RedisBroker(url=url or get_settings().redis_url)

    broker.add_middleware(BulkFairShare())
    # Declared eagerly so `dramatiq workers.tasks` consumes both from the first
    # second. A queue Dramatiq has not seen is not consumed, and an actor whose
    # queue is only declared on first enqueue leaves a window where messages
    # sent by the API pile up unread.
    for queue in (QUEUE_SCAN, QUEUE_BULK):
        broker.declare_queue(queue)
    return broker


_broker = build_broker()
dramatiq.set_broker(_broker)


def get_broker() -> Any:
    """The process-wide broker. `api.deps` uses this to enqueue."""
    return dramatiq.get_broker()


def is_stub() -> bool:
    return type(get_broker()).__name__ == "StubBroker"


def drain(*queues: str, timeout_ms: int = 20_000, worker_threads: int = 2) -> None:
    """Run everything queued, then return. Stub broker only.

    The whole point of the upload path is that work happens *after* the
    response, which makes it invisible to a test that only looks at the
    response. This is how a test asserts the deferred half actually ran — and it
    raises rather than no-ops against a real broker, because "the test silently
    checked nothing" is the failure mode it exists to prevent.

    A real `dramatiq.Worker` is started rather than the actors being called
    directly, so the middleware runs too: `BulkFairShare` is exercised by the
    same path a deployment uses, and `fail_fast` re-raises whatever an actor
    threw instead of leaving it dead-lettered and silent.
    """
    broker = get_broker()
    if not is_stub():
        raise RuntimeError("drain() is for the stub broker; a real worker consumes its own queues")

    names = list(queues) or [QUEUE_SCAN, QUEUE_BULK]
    worker = dramatiq.Worker(broker, worker_timeout=100, worker_threads=worker_threads)
    worker.start()
    try:
        for name in names:
            broker.join(name, fail_fast=True, timeout=timeout_ms)
        worker.join()
    finally:
        worker.stop()


__all__ = [
    "QUEUE_BULK",
    "QUEUE_SCAN",
    "build_broker",
    "drain",
    "get_broker",
    "is_stub",
]
