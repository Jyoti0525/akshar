"""The hand-off buffer between the request and the upload worker. Section 8c.

    "Nothing delays the verdict. Report render, dashboard counters, `scan_count`
     and evidence upload all come off the critical path."      -- section 8c

Which raises an awkward question: if the evidence upload happens in a worker,
where do the bytes live between the response and the worker picking them up?

**Not in the Dramatiq message.** A 300 KB JPEG base64-encoded into a queue
message is 400 KB of broker payload per scan, and a bulk upload of 200 images
turns the broker into an image store — one it will happily accept and then run
out of memory holding. Dramatiq's own guidance is that messages carry
identifiers, not data.

**Not in MinIO.** Writing to MinIO to avoid writing to MinIO is not a plan.

So: a short-lived keyed buffer, Redis in a deployment and a dict in a test. The
bytes sit there for a minute or two while a worker collects them, redacted and
already hashed. The scan row is complete before anything is spooled — it holds
the digest and the object key, both computed synchronously — so the spool never
carries anything the database needs. It carries only the bytes themselves.

**What happens when the spool loses an entry.** Redis is evicted, the worker
dies, the TTL expires. The scan record survives with an `image_key` pointing at
an object that was never written, which sounds bad and is in fact the *only*
acceptable failure: it is loudly detectable. `evidence.verify.verify_object`
already re-downloads and re-hashes every referenced object, so a missing
evidence file surfaces as a failed verification rather than as a silently
compliant record. A design that instead dropped the scan row would lose the
inspection entirely, which section 5 forbids in the strongest terms it uses.

`put` therefore reports whether it succeeded, and the caller falls back to
uploading inline. A slow response is a much smaller problem than absent
evidence.
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_TTL_SECONDS = 900
"""Fifteen minutes. Long enough that a worker restart, a redeploy or a backed-up
`bulk` queue does not lose evidence; short enough that a broker outage cannot
turn Redis into a photo album. The `bulk` queue is the sizing constraint here,
not the `scan` queue — an interactive scan's bytes are collected in
milliseconds."""

DEFAULT_MAX_BYTES = 256 * 1024 * 1024
"""Ceiling for the in-memory spool only. A quarter of a gigabyte is roughly 800
scans in flight, far beyond anything a single-process dev stack will reach — and
having a number here means the failure is a refused `put` with an inline-upload
fallback, rather than an API process growing until the kernel kills it."""


class EvidenceSpool(Protocol):
    """Somewhere to leave bytes for a worker. Deliberately tiny.

    Not a cache: an entry is taken exactly once and gone. Two workers racing on
    the same scan id must not both upload, and `take` returning `None` for the
    loser is how that is settled without a lock.
    """

    def put(self, key: str, payload: bytes, *, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        """Store bytes. Returns False if it could not — the caller then uploads
        inline rather than losing the evidence."""
        ...

    def take(self, key: str) -> bytes | None:
        """Remove and return the bytes, or None if they are not there."""
        ...

    def discard(self, key: str) -> None:
        """Drop an entry the caller no longer needs. Never raises."""
        ...


@dataclass
class InMemorySpool:
    """Process-local spool. Correct when the API and the worker are one process.

    That is not only the test configuration — it is also `--processes 1` on a
    laptop during a demo, where there is no Redis and the whole stack has to
    keep working. It is *not* correct across processes, and the deployed system
    uses `RedisSpool`; `api.deps` picks between them by whether a broker is
    configured, so nothing here has to be remembered by a person.
    """

    max_bytes: int = DEFAULT_MAX_BYTES
    _entries: OrderedDict[str, bytes] = field(default_factory=OrderedDict)
    _size: int = 0

    def put(self, key: str, payload: bytes, *, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        # TTL is accepted and ignored: this spool's lifetime is the process's,
        # and a sweeper thread to expire entries in a dev stack would be
        # machinery in exchange for nothing. The signature matches so a caller
        # never has to know which implementation it holds.
        if len(payload) > self.max_bytes:
            return False
        self.discard(key)
        while self._size + len(payload) > self.max_bytes and self._entries:
            # Evict oldest. The evicted scan's upload then fails to find its
            # bytes and is reported, rather than the process dying and taking
            # every in-flight scan with it.
            _, evicted = self._entries.popitem(last=False)
            self._size -= len(evicted)
        self._entries[key] = payload
        self._size += len(payload)
        return True

    def take(self, key: str) -> bytes | None:
        payload = self._entries.pop(key, None)
        if payload is not None:
            self._size -= len(payload)
        return payload

    def discard(self, key: str) -> None:
        self.take(key)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def bytes_held(self) -> int:
        return self._size


@dataclass
class RedisSpool:
    """The deployed spool. Takes its client from the caller.

    Same rule as `evidence/storage.py` and every lookup in `vision/`: this
    module opens no connection of its own, so the redaction-to-upload hand-off
    is testable with `fakeredis`, with a stub, or with nothing at all.

    The payload must reach exactly one worker — the object store is versioned
    and write-once, and a duplicate PUT would create a second version of an
    object that is supposed to have exactly one, which reads to an auditor as
    an overwrite of evidence. A `MULTI/EXEC` of `GET` then `DEL` gives that:
    Redis runs a transaction to completion without interleaving, so of two
    workers racing on one slot, one gets the bytes and the other gets `None`.

    ---------------------------------------------------------------------------
    WHY NOT `GETDEL`, WHICH IS THE OBVIOUS ANSWER
    ---------------------------------------------------------------------------
    It was `GETDEL`, guarded by `getattr(client, "getdel", None)`. That checks
    the **client library**, and `redis-py` has had the method since 4.0. The
    command is a **server** feature, added in Redis 6.2.

    The dev stack here runs Redis 3.0.504. So the guard passed, the server
    answered `unknown command 'GETDEL'`, the `except Exception: return None`
    below turned that into "the entry is not there", and the worker logged a
    reassuring warning and returned. **Every photograph of every scan taken on
    that stack was discarded**, while its scan row went on recording an
    `image_key` for an object that had never been written. `akshar-evidence`
    held zero objects; the bytes were still sitting in Redis, unread, until
    their TTL expired. Found 2026-09-19, by going to look for the photograph
    behind a defect report and finding the bucket empty.

    A capability test that asks the wrong side of the wire is worse than no
    test. `MULTI/EXEC` needs nothing newer than Redis 1.2, so there is no
    capability to test any more.
    """

    client: Any
    prefix: str = "akshar:spool:"

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    def put(self, key: str, payload: bytes, *, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
        try:
            self.client.set(self._key(key), payload, ex=ttl)
        except Exception:
            # Redis down. Reported, not raised: the caller uploads inline and
            # the officer's scan completes. An evidence path that fails when
            # the queue fails is not an evidence path.
            return False
        return True

    def take(self, key: str) -> bytes | None:
        """The bytes, removed. Raises if Redis could not answer.

        **A transport failure is not an empty slot** and must never be reported
        as one: the caller's whole contract is "no bytes here, so there is
        nothing to upload", and answering that to a broken connection is how
        evidence goes missing quietly. A raise lets Dramatiq retry, and the
        bytes are still in the spool to retry against precisely because the
        delete did not happen.
        """
        name = self._key(key)
        pipe = getattr(self.client, "pipeline", None)
        if pipe is None:  # a stub that is a plain mapping-like client
            payload = self.client.get(name)
            if payload is not None:
                self.client.delete(name)
            return payload

        with pipe(transaction=True) as tx:
            tx.get(name)
            tx.delete(name)
            payload, _ = tx.execute()
        return payload

    def discard(self, key: str) -> None:
        # Best effort by contract: the entry has a TTL, so a Redis that is down
        # when we try to tidy up will expire it anyway.
        with contextlib.suppress(Exception):
            self.client.delete(self._key(key))


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TTL_SECONDS",
    "EvidenceSpool",
    "InMemorySpool",
    "RedisSpool",
]
