"""Authentication and the three roles. AKSHAR.md section 12.

    "Roles: `officer` · `supervisor` · `admin`."

**Two token types, and the distinction is load-bearing.** An access token lives
30 minutes and authorises requests; a refresh token lives 14 days and can only
mint access tokens. If they were interchangeable, a token leaked from a browser
would be usable for a fortnight against a store of enforcement evidence. The
`typ` claim is checked on every decode, so a refresh token presented as a bearer
credential is rejected rather than quietly accepted.

**Roles nest.** An admin can do anything a supervisor can, and a supervisor
anything an officer can. That is expressed once, in `ROLE_RANK`, rather than as
a set membership test repeated in every route — set membership is how a route
ends up accidentally excluding admins from a supervisor endpoint.

**Passwords are bcrypt, called directly rather than through passlib.** Not
SHA-256, not SHA-256 with a salt we invented. bcrypt is slow on purpose, and a
government deployment will be a target for credential stuffing long before it is
a target for anything sophisticated.

*Why not passlib, which section 15b names.* passlib 1.7.4 is the current release
and dates from 2020; its bcrypt backend probes the library with a 73-byte string
during initialisation, and bcrypt 4.1+ raises on that instead of truncating. The
result is an immediate `ValueError` on the first hash, not a subtle
incompatibility. Rather than pin an old bcrypt to satisfy an unmaintained
wrapper, this calls `bcrypt` directly — which is three lines and removes a
dependency. Recorded in `docs/spec-deltas.md`.

*And the 72-byte problem is handled rather than inherited.* bcrypt silently
ignores everything past the 72nd byte of a password, so `passphrase-A` and
`passphrase-B` are the same credential if they share their first 72 bytes. Since
a Devanagari passphrase reaches 72 bytes in about 24 characters, this is not
hypothetical here. Pre-hashing with SHA-256 gives bcrypt a fixed 44-byte input
in which every byte of the original participates.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import bcrypt
from jose import JWTError, jwt

from api.config import Settings, get_settings

Role = Literal["officer", "supervisor", "admin"]
TokenType = Literal["access", "refresh"]

ROLE_RANK: dict[Role, int] = {"officer": 1, "supervisor": 2, "admin": 3}
"""Roles nest rather than partition.

A supervisor reading a scan is not an exception to be listed on the scan route;
it is the ordinary consequence of outranking an officer. Expressing that as a
rank means a new route cannot forget it.
"""

BCRYPT_ROUNDS = 12
"""Cost factor. 12 is roughly 250 ms per hash on current hardware — slow enough
to make offline cracking expensive, fast enough that a login is not noticeable.
Raise it as hardware improves; stored hashes carry their own cost, so old
hashes keep verifying after a change."""


class AuthError(Exception):
    """Credential rejected. Mapped to 401 by the router, never to 500."""


def _prehash(password: str) -> bytes:
    """SHA-256 then base64, so bcrypt sees every byte of the password.

    bcrypt truncates at 72 bytes without complaint. A 44-byte base64 digest is
    comfortably inside that and depends on the whole input, so two passphrases
    sharing a long prefix stay distinct. base64 rather than raw digest bytes
    because a raw digest can contain a NUL, and bcrypt truncates at the first
    one — which would quietly reduce the effective key space.
    """
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Compare in constant time. Never raises on a malformed stored hash.

    A bad hash — from a botched migration, say — must read as "wrong password",
    not as a 500 that confirms to an attacker that the account exists.
    """
    try:
        return bcrypt.checkpw(_prehash(password), hashed.encode())
    except (ValueError, TypeError):
        return False


def create_token(
    *,
    subject: str | UUID,
    role: Role,
    token_type: TokenType = "access",
    settings: Settings | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    config = settings or get_settings()
    now = datetime.now(UTC)
    lifetime = (
        timedelta(minutes=config.access_token_minutes)
        if token_type == "access"
        else timedelta(days=config.refresh_token_days)
    )
    claims: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + lifetime).timestamp()),
    }
    if extra:
        claims.update(extra)
    return jwt.encode(claims, config.jwt_secret, algorithm=config.jwt_algorithm)


def decode_token(
    token: str,
    *,
    expect: TokenType = "access",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Decode and validate. Raises `AuthError` for anything wrong.

    `expect` is not optional-by-omission on purpose. Every call site states
    which kind of token it will accept, so the refresh endpoint cannot be
    reached with an access token and — far more importantly — a protected route
    cannot be reached with a 14-day refresh token.
    """
    config = settings or get_settings()
    try:
        claims = jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])
    except JWTError as exc:
        raise AuthError(f"token rejected: {exc}") from exc

    if claims.get("typ") != expect:
        raise AuthError(
            f"expected a {expect} token, got {claims.get('typ')!r}"
        )
    if not claims.get("sub"):
        raise AuthError("token carries no subject")
    if claims.get("role") not in ROLE_RANK:
        raise AuthError(f"unknown role {claims.get('role')!r}")
    return claims


def outranks(role: Role, minimum: Role) -> bool:
    """Does `role` meet or exceed `minimum`?"""
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


__all__ = [
    "ROLE_RANK",
    "AuthError",
    "Role",
    "TokenType",
    "create_token",
    "decode_token",
    "hash_password",
    "outranks",
    "verify_password",
]
