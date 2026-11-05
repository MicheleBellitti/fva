"""Alembic environment script.

Responsibilities:
- Resolve the DB URL: explicit sqlalchemy.url, else DATABASE_URL, else the local default
  (normalising postgres:// and postgresql:// → postgresql+psycopg://).
- Expose target_metadata so autogenerate can diff against the live DB.
- Exclude burr_state (schema.md §5.11 — owned by Burr's persister, not Alembic).
- Support both offline (--sql) and online migration modes.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from typing import Any

from alembic import context

# Import the shared MetaData from our Core table definitions.
# `prepend_sys_path` in alembic.ini adds packages/core/src to sys.path.
from core.models.tables import metadata as target_metadata
from sqlalchemy import engine_from_config, pool

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to values in alembic.ini
# ---------------------------------------------------------------------------

config = context.config

# Apply logging config from the ini file (if present)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_url() -> str:
    """Return the SQLAlchemy URL for the target database.

    An explicit sqlalchemy.url (alembic.ini leaves it unset, so only code sets it,
    e.g. a test fixture) wins over DATABASE_URL: a fixture must never migrate the
    dev DB by accident.  Falls back to the local default so `make migrate` works
    without a .env file.  Always ensures the psycopg 3 driver prefix is used.
    """
    url = (
        config.get_main_option("sqlalchemy.url")
        or os.getenv("DATABASE_URL")
        or "postgresql+psycopg://fva:fva@localhost:5432/fva"
    )
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            url = "postgresql+psycopg://" + url.removeprefix(scheme)
    return url


def _include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Exclude tables not owned by Alembic.

    schema.md §5.11: burr_state is created and managed by Burr's PostgreSQL
    persister (persister.initialize()).  We must never touch it.
    """
    return not (type_ == "table" and name == "burr_state")


# ---------------------------------------------------------------------------
# Offline mode — emits SQL to stdout (used by `alembic upgrade head --sql`)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online mode — connects to the live DB (used by `make migrate`)
# ---------------------------------------------------------------------------


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
