"""tables.py e le migrazioni Alembic devono descrivere lo stesso schema.

L'autogenerate di Alembic non confronta i CHECK e non vede quelli dichiarati
dentro Column(...): questi test coprono quello che `make revision` non vede.
"""

import io
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from core.models.tables import metadata
from sqlalchemy import CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB

ALEMBIC_INI = Path(__file__).parents[1] / "packages" / "core" / "alembic.ini"

# Nell'SQL offline un CHECK è "CONSTRAINT ck_x CHECK (expr)," dentro CREATE TABLE
# oppure "ALTER TABLE t ADD CONSTRAINT ck_x CHECK (expr);", sempre su una riga.
_ADD_CHECK = re.compile(r"CONSTRAINT (\w+) CHECK \((.*)\)[,;]?\s*$")
_DROP_CONSTRAINT = re.compile(r"DROP CONSTRAINT (\w+)")


def _norm(sql: str) -> str:
    return " ".join(sql.split())


def _migrated_checks() -> dict[str, str]:
    """I CHECK dopo `alembic upgrade head`, letti dall'SQL offline: niente database."""
    sql = io.StringIO()
    command.upgrade(Config(str(ALEMBIC_INI), output_buffer=sql), "head", sql=True)
    checks: dict[str, str] = {}
    for line in sql.getvalue().splitlines():
        if m := _ADD_CHECK.search(line):
            checks[m[1]] = _norm(m[2])
        elif m := _DROP_CONSTRAINT.search(line):
            checks.pop(m[1], None)
    return checks


def test_migrations_create_the_checks_of_tables_py() -> None:
    expected = {
        str(c.name): _norm(str(c.sqltext))
        for t in metadata.tables.values()
        for c in t.constraints
        if isinstance(c, CheckConstraint)
    }
    migrated = _migrated_checks()
    assert {name: migrated.get(name) for name in expected} == expected, (
        "tables.py e le migrazioni non coincidono: se hai cambiato un enum serve "
        "una migrazione che rifà questi CHECK (drop + create) con i nuovi valori"
    )


def test_checks_are_table_level() -> None:
    inline = [
        f"{t.name}.{c.name}"
        for t in metadata.tables.values()
        for c in t.columns
        if any(isinstance(k, CheckConstraint) for k in c.constraints)
    ]
    assert inline == [], "CHECK dentro Column(...): l'autogenerate non li vede"


def test_jsonb_none_is_sql_null() -> None:
    json_null = [
        f"{t.name}.{c.name}"
        for t in metadata.tables.values()
        for c in t.columns
        if isinstance(c.type, JSONB) and not c.type.none_as_null
    ]
    assert json_null == [], "senza none_as_null un None diventa il JSON null, non NULL"
