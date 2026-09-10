"""Alembic environment — AKSHAR.md section 10.

The database URL comes from `AKSHAR_DATABASE_URL`, never from `alembic.ini`. A
connection string in the repository is a credential in the repository, and this
one reaches a store of enforcement evidence.

There is deliberately **no SQLAlchemy model metadata and no autogenerate.** The
schema is hand-written SQL (`db/schema.sql`) because it carries constraints and
partial indexes that autogenerate round-trips badly — the `pack_size` unique
constraint and the `WHERE status = 'REVIEW'` partial index are both load-bearing
and both the kind of thing a generator quietly drops. Migrations here are
written by hand for the same reason the rulepack is: someone has to be able to
read them and say whether they are right.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _database_url() -> str:
    url = os.environ.get("AKSHAR_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "AKSHAR_DATABASE_URL is not set. Copy .env.example to .env, or export "
            "it — alembic.ini deliberately carries no connection string."
        )
    return url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting.

    Useful in a government deployment where a DBA applies changes by hand and
    wants to read them first.
    """
    context.configure(
        url=_database_url(),
        target_metadata=None,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()

    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
