"""Queue weighting — the middleware that keeps an overnight job off the morning.

    "Two queues, one worker pool: `scan` high (interactive scans, report
     requests), `bulk` low (ingestion, retraining exports, dashboard rebuilds),
     weighted. Without this, one overnight bulk job makes the tool unusable the
     next morning."                                              -- section 8c

**Two queues alone do not do this, and it is worth being precise about why.**
Dramatiq runs one consumer thread per queue but a *shared* pool of worker
threads. Each consumer prefetches `worker_threads * 2` messages into that shared
work queue. So a `bulk` ingestion of 5,000 images fills the in-memory work queue
with bulk messages, and an officer's interactive scan — correctly enqueued on
the high-priority `scan` queue — waits behind sixteen image ingestions because
it arrives at a pool with nothing free. The priority was real and made no
difference.

**So the weighting has to be on execution, not on ordering.** `BulkFairShare`
caps how many `bulk` messages may be *in flight* at once, at a fraction of the
pool. Some threads are therefore always free for `scan`, whatever the bulk
backlog looks like. A bulk message that arrives when the cap is full is put back
on the queue with a short delay and skipped, which returns its worker thread
immediately — the rejection costs microseconds where processing it would cost
seconds.

**The re-enqueue backs off.** Without that, a full cap turns into a spin: the
pool grabs bulk messages, bounces them, grabs them again, and burns Redis
round-trips doing no work. Each deferral raises the delay, so a queue that
cannot make progress goes quiet instead of hot.

The deferral count is kept here, keyed by message id, and *not* on the message —
because it cannot be. Every broker's delayed enqueue rewrites `options` to
`{"eta": ...}` wholesale, so any counter written there is discarded by the very
operation whose repetition it exists to count. The message id does survive, so a
process-local table keyed on it works. It resets if the message comes back to a
different process, which costs one extra bounce and no correctness.

**Fairness is per-process.** Two worker processes each get their own cap, which
is the right unit: the guarantee we want is "this pool always has a thread for
an interactive scan", and a pool is a process.
"""

from __future__ import annotations

import random
import threading
from collections import OrderedDict

from dramatiq.middleware import Middleware, SkipMessage

BULK_QUEUE = "bulk"
SCAN_QUEUE = "scan"

DEFAULT_BULK_SHARE = 0.5
"""Half the pool, at most, on bulk work.

Not a smaller number: bulk ingestion is the thing this system is *for* on the
day a department uploads a season's photographs, and starving it to protect a
queue that is empty most nights would be its own kind of failure. Half leaves an
interactive scan a free thread at every moment while still finishing a large
import in roughly the time a dedicated pool would.
"""

DEFERRAL_BASE_MS = 250
DEFERRAL_MAX_MS = 30_000
DEFERRAL_TABLE_MAX = 4096
"""Cap on the deferral table. Beyond this the oldest entries are dropped, which
loses a backoff level for a message that has been bouncing for a very long time
— a cheap, self-correcting failure, and far better than an unbounded dict in a
worker that runs for weeks."""


class BulkFairShare(Middleware):
    """Reserve worker threads for the `scan` queue. Section 8c.

    Constructed with an explicit `worker_threads` only in tests; in a real
    worker the pool size is not known until boot, so `after_worker_boot` reads
    it off the worker. That matters because the cap is a *fraction of the pool*
    — hard-coding it would silently mean "all of it" on a two-thread worker and
    "a tenth of it" on a twenty-thread one.
    """

    def __init__(
        self,
        *,
        bulk_share: float = DEFAULT_BULK_SHARE,
        worker_threads: int | None = None,
        bulk_queue: str = BULK_QUEUE,
    ) -> None:
        if not 0 < bulk_share <= 1:
            raise ValueError("bulk_share must be in (0, 1]")
        self.bulk_share = bulk_share
        self.bulk_queue = bulk_queue
        self._lock = threading.Lock()
        self._in_flight = 0
        self._limit = self._limit_for(worker_threads) if worker_threads else 1
        self._local = threading.local()
        self._deferrals: OrderedDict[str, int] = OrderedDict()

    def _limit_for(self, worker_threads: int) -> int:
        # `int(...)` floors, then a floor of 1 keeps a single-threaded worker
        # able to make progress at all. A cap of 0 would mean bulk work never
        # runs, which is a deadlock dressed as a policy.
        return max(1, int(worker_threads * self.bulk_share))

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_flight(self) -> int:
        with self._lock:
            return self._in_flight

    def after_worker_boot(self, broker, worker) -> None:
        self._limit = self._limit_for(getattr(worker, "worker_threads", 1))

    def _try_acquire(self) -> bool:
        with self._lock:
            if self._in_flight >= self._limit:
                return False
            self._in_flight += 1
            return True

    def _release(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)

    def before_process_message(self, broker, message) -> None:
        self._local.held = False
        if message.queue_name != self.bulk_queue:
            return
        if self._try_acquire():
            self._local.held = True
            return

        delay = self._next_delay(message.message_id)
        broker.enqueue(message.copy(), delay=delay)
        raise SkipMessage(
            f"bulk fair-share cap reached ({self._limit} in flight); requeued in {delay} ms"
        )

    def _next_delay(self, message_id: str) -> int:
        with self._lock:
            deferrals = self._deferrals.get(message_id, 0) + 1
            self._deferrals[message_id] = deferrals
            self._deferrals.move_to_end(message_id)
            while len(self._deferrals) > DEFERRAL_TABLE_MAX:
                self._deferrals.popitem(last=False)
        delay = min(DEFERRAL_MAX_MS, DEFERRAL_BASE_MS * (2 ** (deferrals - 1)))
        # Jitter so a burst of deferred messages does not come back as a burst.
        return int(delay * random.uniform(0.5, 1.5))

    def after_process_message(self, broker, message, *, result=None, exception=None) -> None:
        if getattr(self._local, "held", False):
            self._local.held = False
            self._release()
        with self._lock:
            self._deferrals.pop(message.message_id, None)

    def after_skip_message(self, broker, message) -> None:
        # A message we deferred was never acquired, so there is nothing to give
        # back. A message skipped by *other* middleware after we acquired must
        # release, or the cap leaks a slot per skip and eventually pins bulk
        # throughput at zero.
        if getattr(self._local, "held", False):
            self._local.held = False
            self._release()


__all__ = [
    "BULK_QUEUE",
    "DEFAULT_BULK_SHARE",
    "DEFERRAL_BASE_MS",
    "DEFERRAL_MAX_MS",
    "SCAN_QUEUE",
    "BulkFairShare",
]
