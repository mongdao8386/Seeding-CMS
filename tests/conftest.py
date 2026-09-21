"""Test chay tren DATABASE RIENG, khong bao gio tren du lieu that.

Truoc 21/09/2026 bo test dung chung database voi he thong dang chay: no tao va xoa tai
khoan, va co test goi "xoa tat ca tai khoan". Luc DB con trong thi vo hai; khi da co 50 acc
that thi mot lan chay `pytest` la mat sach. Tu gio:

  - DATABASE_URL cua test = ten database that + "_test" (tu tao neu chua co, tu migrate).
  - REDIS_URL cua test = cung Redis, db so 1 (he thong that dung db 0).

File nay chay TRUOC khi bat ky module `seeding.*` nao duoc import, vi engine la singleton
tao luc import (seeding/db.py) va get_settings() co cache.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys

from sqlalchemy.engine import make_url

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DB = "postgresql+asyncpg://seeding:seeding@localhost:5433/seeding"
DEFAULT_REDIS = "redis://localhost:6380"


def _from_env_file(name: str) -> str | None:
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _configure() -> tuple[str, str]:
    real = os.environ.get("DATABASE_URL") or _from_env_file("DATABASE_URL") or DEFAULT_DB
    url = make_url(real)
    name = url.database or "seeding"
    if not name.endswith("_test"):
        url = url.set(database=f"{name}_test")
    test_db = url.render_as_string(hide_password=False)

    redis = os.environ.get("REDIS_URL") or _from_env_file("REDIS_URL") or DEFAULT_REDIS
    base = redis.rstrip("/")
    # bo so db neu co (redis://host:port/0) roi gan db 1
    head, _, tail = base.rpartition("/")
    if tail.isdigit() and "://" in head:
        base = head
    test_redis = f"{base}/1"

    os.environ["DATABASE_URL"] = test_db
    os.environ["REDIS_URL"] = test_redis
    return test_db, test_redis


TEST_DATABASE_URL, TEST_REDIS_URL = _configure()


async def _ensure_database() -> None:
    import asyncpg

    url = make_url(TEST_DATABASE_URL)
    admin = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    )
    try:
        exists = await admin.fetchval("select 1 from pg_database where datname = $1", url.database)
        if not exists:
            await admin.execute(f'create database "{url.database}"')
    finally:
        await admin.close()


def _migrate() -> None:
    env = dict(os.environ)
    env["DATABASE_URL"] = TEST_DATABASE_URL
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(ROOT),
        env=env,
        check=True,
        capture_output=True,
    )


assert make_url(TEST_DATABASE_URL).database.endswith("_test"), "test phai chay tren database _test"
asyncio.run(_ensure_database())
_migrate()


def pytest_report_header(config):
    url = make_url(TEST_DATABASE_URL)
    return f"seeding test database: {url.host}:{url.port}/{url.database} | redis: {TEST_REDIS_URL}"
