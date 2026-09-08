"""Co trang thai dung chung giua worker va API, tren Redis.

Worker la noi biet thu vien X con chay hay da lech query id; API la noi nguoi van hanh
nhin. Hai tien trinh khac nhau, nen co phai nam o mot cho ca hai cung toi duoc. Redis
da co san (ARQ dung), va mot co mat di khi Redis khoi dong lai thi cung khong sao -
vong quet sau dat lai.
"""

from __future__ import annotations

import json

import structlog
from redis import asyncio as aioredis

from seeding.config import get_settings

log = structlog.get_logger(__name__)

PREFIX = "seeding:flag:"


def _client() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def set_flag(key: str, value: dict, *, ttl_seconds: int | None = None) -> bool:
    """Ghi mot co. Redis chet thi ghi log va tra ve False - khong bao gio lam do job."""
    try:
        r = _client()
        try:
            await r.set(PREFIX + key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
        finally:
            await r.aclose()
        return True
    except Exception as exc:
        log.warning("flags.set_failed", key=key, error=f"{type(exc).__name__}: {exc}")
        return False


async def get_flag(key: str) -> dict | None:
    try:
        r = _client()
        try:
            raw = await r.get(PREFIX + key)
        finally:
            await r.aclose()
    except Exception as exc:
        log.warning("flags.get_failed", key=key, error=f"{type(exc).__name__}: {exc}")
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
