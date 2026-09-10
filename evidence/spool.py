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

    `GETDEL` is used rather than `GET` then `DEL` because two workers must not
    both receive the same payload — the object store is versioned and
    write-once, and a duplicate PUT would create a second version of an object
    that is supposed to have exactly one, which reads to an auditor as an
    overwrite of evidence.
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
        try:
            getdel = getattr(self.client, "getdel", None)
            if getdel is not None:
                return getdel(self._key(key))
            payload = self.client.get(self._key(key))
            if payload is not None:
                self.client.delete(self._key(key))
            return payload
        except Exception:
            return None

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
