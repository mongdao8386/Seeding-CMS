"""Nhip thao tac giong nguoi that, cho cac duong di bang trinh duyet (Facebook).

Khong phai de "qua mat" bo phat hien - de tranh nhung dau vet may moc ro rang nhat:
go ca doan van trong mot su kien duy nhat, dang bai ngay giay dau tien vao trang,
khong bao gio cuon, khong bao gio dung lai doc.

Moi ham nhan `sleep` va `rng` tu ngoai vao de test do duoc hanh vi ma khong phai
cho that. Trong san xuat cu de mac dinh.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

Sleep = Callable[[float], Awaitable[None]]

# Nghi lau hon sau dau cau - nguoi that dung lai o cuoi cau, khong go deu tam tap.
_PAUSE_AFTER = ".,!?;:\n"


async def type_like_person(
    locator,
    text: str,
    *,
    rng: random.Random | None = None,
    sleep: Sleep = asyncio.sleep,
    cps: float = 6.5,
) -> None:
    """Go tung ky tu voi do tre thay doi, nghi lau hon o dau cau. `cps` ~ 6-8 la nguoi go nhanh."""
    rng = rng or random.Random()
    base = 1.0 / max(cps, 0.5)

    await locator.click()
    await sleep(rng.uniform(0.3, 0.9))  # nhin vao o soan truoc khi go

    for ch in text:
        await locator.type(ch, delay=0)
        delay = rng.uniform(base * 0.45, base * 1.9)
        if ch in _PAUSE_AFTER:
            delay += rng.uniform(0.15, 0.55)
        elif ch == " " and rng.random() < 0.08:
            delay += rng.uniform(0.2, 0.8)  # thinh thoang khung lai nghi mot nhip
        await sleep(delay)


async def dwell(
    *,
    low: float = 1.0,
    high: float = 4.0,
    rng: random.Random | None = None,
    sleep: Sleep = asyncio.sleep,
) -> float:
    """Dung lai mot lat, nhu dang doc."""
    rng = rng or random.Random()
    seconds = rng.uniform(low, high)
    await sleep(seconds)
    return seconds


async def scroll_feed(
    page,
    *,
    rounds: int = 5,
    rng: random.Random | None = None,
    sleep: Sleep = asyncio.sleep,
) -> int:
    """Cuon feed vai nhip, thinh thoang cuon nguoc len - nguoi that hay luot qua roi
    quay lai xem lai."""
    rng = rng or random.Random()
    done = 0
    for _ in range(rounds):
        amount = rng.randint(250, 900)
        if rng.random() < 0.15:
            amount = -rng.randint(120, 400)
        await page.mouse.wheel(0, amount)
        done += 1
        await dwell(low=0.8, high=3.5, rng=rng, sleep=sleep)
    return done


async def warm_up(
    page,
    *,
    rng: random.Random | None = None,
    sleep: Sleep = asyncio.sleep,
) -> None:
    """Xem qua feed truoc khi lam gi do. Chay truoc MOI lan dang bai, khong phai tuy chon."""
    rng = rng or random.Random()
    await dwell(low=1.5, high=4.0, rng=rng, sleep=sleep)
    await scroll_feed(page, rounds=rng.randint(2, 5), rng=rng, sleep=sleep)
    await dwell(low=1.0, high=3.0, rng=rng, sleep=sleep)
