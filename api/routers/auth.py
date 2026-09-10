"""`/api/v1/auth` — login and refresh. AKSHAR.md section 12."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from api.deps import AuditDep, CurrentUserDep, SettingsDep, UserStoreDep, client_ip
from api.schemas import CurrentUser, LoginRequest, RefreshRequest, TokenPair
from api.security import AuthError, create_token, decode_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_DUMMY_HASH = hash_password("a password nobody has")
"""Verified against when the email is unknown, so the bcrypt cost is paid on
every login path. Without it, a missing user returns measurably faster and the
timing difference re-creates the account-enumeration oracle that the identical
error message exists to close."""


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest,
    request: Request,
    users: UserStoreDep,
    settings: SettingsDep,
    audit: AuditDep,
) -> TokenPair:
    """Exchange credentials for a token pair.

    **The failure message is identical for an unknown email and a wrong
    password, and the password is verified either way.** Two reasons, and the
    second is the one people forget: a distinct "no such user" reply turns the
    login form into an account-enumeration oracle, and an early return on a
    missing user makes the response measurably faster, which leaks the same fact
    through timing.
    """
    record = users.by_email(body.email)

    # Verify against a dummy hash when the user is absent, so the bcrypt cost is
    # paid on every path.
    stored = record.password_hash if record else _DUMMY_HASH
    ok = verify_password(body.password, stored)

    if record is None or not ok or not record.is_active:
        audit.record(
            user_id=record.id if record else None,
            action="login_failed",
            entity="user",
            entity_id=body.email,
            ip=client_ip(request),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    audit.record(
        user_id=record.id,
        action="login",
        entity="user",
        entity_id=str(record.id),
        ip=client_ip(request),
    )
    return TokenPair(
        access_token=create_token(
            subject=record.id, role=record.role, token_type="access", settings=settings
        ),
        refresh_token=create_token(
            subject=record.id, role=record.role, token_type="refresh", settings=settings
        ),
        expires_in=settings.access_token_minutes * 60,
        role=record.role,  # type: ignore[arg-type]
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(
    body: RefreshRequest,
    users: UserStoreDep,
    settings: SettingsDep,
) -> TokenPair:
    """Mint a new access token from a refresh token.

    The role is re-read from the store rather than copied from the token. A
    supervisor demoted to officer must lose supervisor access at the next
    refresh, and a claim signed a fortnight ago cannot know that.
    """
    try:
        claims = decode_token(body.refresh_token, expect="refresh", settings=settings)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    from uuid import UUID

    record = users.by_id(UUID(claims["sub"]))
    if record is None or not record.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Account no longer active."
        )

    return TokenPair(
        access_token=create_token(
            subject=record.id, role=record.role, token_type="access", settings=settings
        ),
        refresh_token=create_token(
            subject=record.id, role=record.role, token_type="refresh", settings=settings
        ),
        expires_in=settings.access_token_minutes * 60,
        role=record.role,  # type: ignore[arg-type]
    )


@router.get("/me", response_model=CurrentUser)
async def me(user: CurrentUserDep) -> CurrentUser:
    return user
