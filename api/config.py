"""Runtime configuration, read once from the environment. AKSHAR.md section 12.

Every value comes from an `AKSHAR_*` environment variable, and there are no
credentials in this repository. `.env.example` documents the shape;
`docker-compose.yml` supplies working values for a local stack; `.env` is
gitignored.

**One setting refuses its own default in production.** `jwt_secret` ships as
`dev-only-change-me` so a clone runs immediately, and `require_production_ready`
rejects exactly that string when `environment` is not `development`. A signing
key that everyone with the repository knows is not a signing key, and the thing
it protects here is access to enforcement evidence.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AKSHAR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = "development"

    # --- database -----------------------------------------------------------
    database_url: str = "postgresql+psycopg://akshar:akshar@localhost:5432/akshar"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    storage: Literal["auto", "memory", "sql"] = "auto"
    """Which store family to use. `auto` picks Postgres when a driver is
    importable and the in-memory stores when it is not, so a clean clone runs
    with no configuration and `docker compose up` uses the database. See
    `api/sql/engine.py`; production refuses to boot on `memory`."""

    # --- queue --------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- object storage -----------------------------------------------------
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "akshar"
    minio_secret_key: str = "akshar-secret"
    minio_secure: bool = False
    evidence_bucket: str = "akshar-evidence"
    derived_bucket: str = "akshar-derived"

    # --- auth ---------------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14

    # --- rules --------------------------------------------------------------
    rulepack_path: str = "rules/packs/lmpc_2011.yaml"

    # --- privacy (section 18) -----------------------------------------------
    geo_precision_dp: int = Field(
        default=3,
        ge=0,
        le=6,
        description=(
            "Decimal places kept on stored latitude/longitude. 3 dp is about "
            "110 m — 'enough to identify a market, not a doorway'. Officer "
            "location is personal data under the DPDP Act 2023."
        ),
    )
    blur_faces: bool = True

    # --- demo ---------------------------------------------------------------
    demo_seed: bool = False
    """Fill the in-memory stores with a demonstration shelf at boot.

    Off by default, ignored entirely on the SQL backend, and refused outright in
    production — see `api/demo.py`. It exists so `scripts/run_demo.py` can bring
    up a walkthrough with no Postgres, no Redis and no MinIO; the verdicts it
    produces come from the real rulepack over synthetic labels, and never from a
    stored answer."""

    # --- ops ----------------------------------------------------------------
    cors_origins: str = "http://localhost:3000"

    @field_validator("geo_precision_dp")
    @classmethod
    def _geo_precision_is_coarse_enough(cls, value: int) -> int:
        # 6 dp is ~11 cm. Nothing in this system needs to know which doorway an
        # officer stood in, and storing it would be a liability rather than a
        # feature.
        if value > 4:
            raise ValueError(
                f"geo_precision_dp={value} resolves to roughly "
                f"{111_000 / (10**value):.1f} m, which is finer than section 18 "
                f"permits; 3 (about 110 m) identifies a market without "
                f"identifying a doorway"
            )
        return value

    @property
    def is_production(self) -> bool:
        return self.environment != "development"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def require_production_ready(self) -> None:
        """Refuse to serve production traffic with development secrets.

        Called from the app lifespan rather than at import, so tests and a local
        `uvicorn` still start instantly while a real deployment fails loudly at
        boot instead of quietly issuing forgeable tokens.
        """
        if not self.is_production:
            return
        problems: list[str] = []
        if self.jwt_secret == DEV_JWT_SECRET:
            problems.append(
                "AKSHAR_JWT_SECRET is still the development default; anyone with "
                "the repository can mint an admin token"
            )
        # Only if object storage is actually configured. `get_minio()` returns
        # None on an empty endpoint and the evidence bucket is simply not used —
        # a deployment without object storage is a supported, degraded one, and
        # it was being refused for holding a development password to a service
        # it never contacts. That is not a security check, it is a spurious one,
        # and a spurious check on a startup path is how a correct deployment
        # gets blocked at the worst moment.
        #
        # The moment an endpoint IS set both conditions bite again, which is
        # when they mean something: evidence would really be moving, and really
        # be moving in the clear.
        if self.minio_endpoint:
            if self.minio_secret_key == "akshar-secret":
                problems.append("AKSHAR_MINIO_SECRET_KEY is still the development default")
            if not self.minio_secure:
                problems.append(
                    "AKSHAR_MINIO_SECURE is false; evidence would move over plain HTTP"
                )
        if problems:
            raise RuntimeError(
                "refusing to start in "
                f"{self.environment}:\n  - " + "\n  - ".join(problems)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Cached so the environment is read once.

    `lru_cache` also makes this overridable in tests via `cache_clear()`, which
    is why it is a function rather than a module-level instance.
    """
    return Settings()


__all__ = ["DEV_JWT_SECRET", "Settings", "get_settings"]
