"""Thu mot proxy that: di ra Internet qua no va hoi xem ra bang IP nao.

Mot proxy chua bao gio duoc thu la mot an so, va an so thi khong nen gan vao tai
khoan. Ket qua ghi len chinh doi tuong proxy; nguoi goi commit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from seeding.domain.models import Proxy, ProxyStatus

TIMEOUT = 15.0
PROBE_URL = "https://api.ipify.org?format=json"


@dataclass(slots=True)
class ProxyTest:
    ok: bool
    exit_ip: str | None
    latency_ms: int | None
    error: str | None


def explain_failure(exc: Exception, proxy: Proxy) -> str:
    """Doi loi mang thanh mot cau noi ro phai lam gi.

    `ProxyError: 407 Proxy Authentication Required` la chinh xac ve ky thuat va vo dung
    ve thuc hanh: no khong noi rang o Username dang de trong.
    """
    raw = f"{type(exc).__name__}: {exc}"
    text = str(exc).lower()

    if "407" in text or "proxy authentication" in text:
        if not proxy.username:
            return (
                "Proxy này cần username và mật khẩu mà chưa có. Nhà cung cấp đưa chúng kèm "
                f"{proxy.host}. ({raw})"
            )
        return (
            f"Proxy từ chối username '{proxy.username}'. Sai mật khẩu, hoặc nhà cung cấp "
            f"muốn định dạng username khác. ({raw})"
        )
    if "getaddrinfo" in text or "name or service" in text or "nodename" in text:
        return f"Tên miền {proxy.host} không phân giải được — kiểm tra lỗi gõ. ({raw})"
    if "timed out" in text or "timeout" in text:
        return (
            f"{proxy.host}:{proxy.port} không trả lời trong {TIMEOUT:.0f}s. Proxy chết, sai "
            f"cổng, hoặc IP máy này chưa được nhà cung cấp cho phép. ({raw})"
        )
    if "connection refused" in text or "actively refused" in text:
        return (
            f"{proxy.host} từ chối kết nối ở cổng {proxy.port}. Thường là sai cổng hoặc sai "
            f"scheme — đang đặt {proxy.scheme}. ({raw})"
        )
    if "403" in text:
        return f"Proxy nhận đăng nhập nhưng từ chối request — hết gói hoặc bị chặn đích. ({raw})"
    return raw


def proxy_url(proxy: Proxy) -> str:
    auth = f"{proxy.username}:{proxy.get_password() or ''}@" if proxy.username else ""
    return f"{(proxy.scheme or 'http').lower()}://{auth}{proxy.host}:{proxy.port}"


async def run(proxy: Proxy) -> ProxyTest:
    started = time.perf_counter()
    result = ProxyTest(ok=False, exit_ip=None, latency_ms=None, error=None)
    try:
        async with httpx.AsyncClient(proxy=proxy_url(proxy), timeout=TIMEOUT) as client:
            response = await client.get(PROBE_URL)
            response.raise_for_status()
            result.exit_ip = response.json().get("ip")
            result.ok = True
    except Exception as exc:
        result.error = explain_failure(exc, proxy)
    result.latency_ms = int((time.perf_counter() - started) * 1000)

    proxy.status = ProxyStatus.OK if result.ok else ProxyStatus.FAILING
    proxy.last_checked_at = datetime.now(UTC)
    proxy.last_exit_ip = result.exit_ip
    proxy.last_error = result.error
    return result
