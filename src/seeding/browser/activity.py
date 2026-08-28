"""Chay mot lan hoat dong nen: mo feed, cuon, doc, roi thoat.

Khong dang gi ca. Muc dich duy nhat la tai khoan trong giong mot nguoi dung that,
chu khong phai mot cai loa chi phat ra roi im.

Job loai nay chiem phan lon tai cua he thong (nhieu gap 5-10 lan job dang bai), nen
no phai re: mo trinh duyet, lam trong dung ngan sach thoi gian, dong ngay.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import structlog

from seeding.browser import humanize
from seeding.browser.checkpoints import Checkpoint, detect
from seeding.browser.session import PROBES, open_profile
from seeding.models import ActivityKind, Platform, Profile

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class ActivityResult:
    ok: bool
    detail: str
    checkpoint: Checkpoint | None = None
    retryable: bool = False


async def run(
    profile: Profile,
    platform: Platform,
    kind: ActivityKind,
    duration_seconds: int,
    *,
    rng: random.Random | None = None,
) -> ActivityResult:
    rng = rng or random.Random()

    probe = PROBES.get(platform)
    if probe is None:
        return ActivityResult(False, f"no feed defined for {platform.value}")
    if not profile.cookies_enc:
        return ActivityResult(False, "profile has never signed in")

    try:
        async with open_profile(profile, headless=True, humanize=True) as (_b, context):
            page = await context.new_page()
            await page.goto(probe.feed_url, wait_until="domcontentloaded", timeout=45_000)

            if blocked := await detect(page, platform):
                return ActivityResult(False, blocked.evidence, checkpoint=blocked)

            detail = await _do(page, kind, duration_seconds, rng)

            # Kiem lai sau khi hoat dong: checkpoint hay xuat hien giua chung.
            if blocked := await detect(page, platform):
                return ActivityResult(False, blocked.evidence, checkpoint=blocked)

            return ActivityResult(True, detail)

    except Exception as exc:
        log.warning("activity.failed", profile=str(profile.id), error=str(exc))
        return ActivityResult(False, f"{type(exc).__name__}: {exc}", retryable=True)


async def _do(page, kind: ActivityKind, budget: int, rng: random.Random) -> str:
    """Lam viec trong dung ngan sach thoi gian, roi ve."""
    if kind is ActivityKind.BROWSE_FEED:
        rounds = max(2, budget // 25)
        done = await humanize.scroll_feed(page, rounds=rounds, rng=rng)
        return f"scrolled {done} times"

    if kind is ActivityKind.READ_POST:
        await humanize.scroll_feed(page, rounds=rng.randint(1, 3), rng=rng)
        seconds = await humanize.dwell(low=budget * 0.4, high=budget * 0.9, rng=rng)
        return f"read for {seconds:.0f}s"

    if kind is ActivityKind.WATCH_VIDEO:
        await humanize.scroll_feed(page, rounds=rng.randint(1, 4), rng=rng)
        seconds = await humanize.dwell(low=budget * 0.5, high=budget, rng=rng)
        return f"watched for {seconds:.0f}s"

    if kind is ActivityKind.REACT:
        # Co y KHONG bam that o giai doan nay. Tha cam xuc la hanh dong ghi lai duoc
        # tren nen tang, va selector chua duoc kiem chung tren tai khoan that - bam
        # nham vao thu khac con te hon la khong bam.
        await humanize.scroll_feed(page, rounds=rng.randint(2, 4), rng=rng)
        await humanize.dwell(low=1.0, high=3.0, rng=rng)
        return "browsed only, no reaction clicked (selectors unverified)"

    return "did nothing"
