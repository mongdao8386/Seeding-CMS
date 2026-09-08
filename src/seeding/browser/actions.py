"""Thao tac trinh duyet dung chung cho cac duong di bang Camoufox (Facebook).

Selector la diem xuat phat, khong phai da kiem chung: giao dien doi theo A/B test va
theo ngon ngu. Vi the moi buoc la MOT DANH SACH ung vien, thu lan luot, va khi khong
cai nao khop thi bao ro da thu gi - khong bao gio im lang roi bao thanh cong.
"""

from __future__ import annotations

import time
from pathlib import Path


async def first_visible(page, selectors: tuple[str, ...], timeout_ms: int = 4_000):
    """Selector dau tien thuc su hien tren trang. None neu khong cai nao khop."""
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=timeout_ms):
                return locator
        except Exception:
            continue
    return None


async def present(page, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        try:
            if await page.locator(selector).first.count():
                return True
        except Exception:
            continue
    return False


async def wait_visible(page, selectors: tuple[str, ...], timeout_ms: int):
    """Cho den khi mot trong cac selector hien ra, QUAY VONG qua ca danh sach thay vi
    cho that lau o cai dau tien. None neu het gio."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        per = max(1.0, min(3.0, remaining / max(len(selectors), 1)))
        found = await first_visible(page, selectors, timeout_ms=int(per * 1000))
        if found is not None:
            return found


async def attach_media(page, selectors: tuple[str, ...], path: str) -> str | None:
    """Dinh file vao o chon file. None neu xong, chuoi loi neu hong. O chon file thuong
    bi an sau mot nut tu ve nen khong doi no hien ra - set_input_files chay voi input an."""
    if not Path(path).exists():
        return f"rendered media file is missing: {path}"
    for selector in selectors:
        try:
            await page.locator(selector).first.set_input_files(path, timeout=15_000)
            return None
        except Exception:
            continue
    return selector_miss("the file input", selectors)


async def clear(locator) -> None:
    """Xoa sach o soan, qua ban phim - `fill("")` bi cac editor kieu Draft.js bo qua."""
    await locator.click()
    await locator.press("ControlOrMeta+a")
    await locator.press("Delete")


def selector_miss(what: str, tried: tuple[str, ...]) -> str:
    """Khong khop selector la LOI CODE, khong phai loi tai khoan: nguoi van hanh mo trinh
    duyet cung khong sua duoc gi, thu can sua la bang recipe."""
    return (
        f"Could not find {what}. Tried: {list(tried)}. "
        "The platform changed its interface - update the recipe."
    )
