"""Move the development database from SQLite to PostgreSQL (data included).

Prerequisite (once, as the postgres superuser):
    psql -U postgres -h localhost -f scripts/setup_postgres.sql

Then:
    backend/.venv/Scripts/python scripts/migrate_to_postgres.py            # copies data + switches backend/.env
    backend/.venv/Scripts/python scripts/migrate_to_postgres.py --dry-run  # only reports row counts

Steps: run Alembic migrations on the target, copy every table in foreign-key order using the
application's own models (so UUID / JSON / timestamp types convert correctly), reset identity
sequences, verify row counts, and finally enable DATABASE_URL in backend/.env (a backup of the
previous file is kept as backend/.env.bak).
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
ENV = BACKEND / ".env"
sys.path.insert(0, str(BACKEND))


def target_url_from_env() -> str | None:
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    match = re.search(r"^#?\s*DATABASE_URL=(postgresql\S+)", text, re.M)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default=f"sqlite:///{(BACKEND / 'storage' / 'stegolab.db').as_posix()}")
    parser.add_argument("--target", default=None, help="defaults to the DATABASE_URL line in backend/.env")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-env-switch", action="store_true", help="do not edit backend/.env")
    args = parser.parse_args()

    target = args.target or target_url_from_env()
    if not target:
        print("No PostgreSQL URL found. Run scripts/init_env.py --postgres first.", file=sys.stderr)
        return 1

    from sqlalchemy import create_engine, func, select, text

    from app.db import models  # noqa: F401  (registers tables)
    from app.db.base import Base

    src = create_engine(args.source)
    dst = create_engine(target)
    with dst.connect() as conn:  # fail fast with a clear message if the role/database is missing
        conn.execute(text("SELECT 1"))

    tables = Base.metadata.sorted_tables  # parents before children
    counts = {}
    with src.connect() as s:
        for table in tables:
            counts[table.name] = s.execute(select(func.count()).select_from(table)).scalar_one()
    print("source rows:", counts)
    if args.dry_run:
        return 0

    print("running migrations on target …")
    env = {**os.environ, "DATABASE_URL": target}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True)

    with src.connect() as s, dst.begin() as d:
        for table in tables:
            existing = d.execute(select(func.count()).select_from(table)).scalar_one()
            if existing:
                print(f"  {table.name}: target already has {existing} rows - skipped")
                continue
            rows = [dict(r._mapping) for r in s.execute(select(table))]
            for start in range(0, len(rows), 500):
                d.execute(table.insert(), rows[start : start + 500])
            print(f"  {table.name}: copied {len(rows)}")
        if dst.dialect.name == "postgresql":
            for table in tables:
                for column in table.columns:
                    if column.primary_key and column.autoincrement is True or (column.primary_key and str(column.type) == "INTEGER"):
                        d.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{column.name}'), "
                            f"COALESCE((SELECT MAX({column.name}) FROM {table.name}), 0) + 1, false)"
                        ))  # fmt: skip

    with dst.connect() as d:
        mismatches = {t.name: (counts[t.name], d.execute(select(func.count()).select_from(t)).scalar_one()) for t in tables}
    bad = {k: v for k, v in mismatches.items() if v[0] > v[1]}
    if bad:
        print("row count mismatch:", bad, file=sys.stderr)
        return 1
    print("verified row counts on target")

    if not args.no_env_switch and ENV.exists() and target.startswith("postgresql"):
        shutil.copy(ENV, ENV.with_suffix(".env.bak"))
        content = ENV.read_text(encoding="utf-8")
        content = re.sub(r"^#\s*(DATABASE_URL=postgresql\S+)", r"\1", content, flags=re.M)
        ENV.write_text(content, encoding="utf-8")
        print("backend/.env now points at PostgreSQL (backup: backend/.env.bak). Restart the API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
