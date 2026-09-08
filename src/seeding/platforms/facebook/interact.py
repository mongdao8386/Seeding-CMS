"""Tha tim / theo doi / binh luan tren Facebook bang trinh duyet - chuyen tu legacy.

Da theo doi tu truoc thi DUNG LAI: nut "Following" bam vao la BO theo doi.
Bam roi ma khong thay dau hieu xac nhan thi KHONG khang dinh thanh cong.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser import actions, humanize
from seeding.browser.checkpoints import detect
from seeding.browser.session import open_profile
from seeding.config import get_settings
from seeding.content.comments import comment_text
from seeding.domain.models import Account, ActivityJob, ActivityKind, Platform, Profile
from seeding.platforms.base import InteractResult, register_interact
from seeding.platforms.facebook.publish import COMMENT
from seeding.platforms.outreach import ensure_proxy_loaded

log = structlog.get_logger(__name__)

ORIGIN = "https://www.facebook.com"


@dataclass(frozen=True, slots=True)
class GraphRecipe:
    follow: tuple[str, ...]
    following_marker: tuple[str, ...]
    like: tuple[str, ...]
    liked_marker: tuple[str, ...]


RECIPE = GraphRecipe(
    follow=(
        "div[aria-label='Follow']",
        "div[aria-label='Theo dõi']",
        "div[role='button']:has-text('Follow')",
    ),
    following_marker=(
        "div[aria-label='Following']",
        "div[aria-label='Đang theo dõi']",
        "text=Following",
    ),
    like=("div[aria-label='Like']", "div[aria-label='Thích']"),
    liked_marker=("div[aria-label='Remove Like']", "div[aria-label='Bỏ thích']"),
)


def profile_url(handle: str) -> str:
    return f"{ORIGIN}/{handle.lstrip('@')}"


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    open=open_profile,
    rng: random.Random | None = None,
) -> InteractResult:
    rng = rng or random.Random()
    await ensure_proxy_loaded(session, profile)
    if profile is None or profile.proxy is None:
        return InteractResult(False, "profile has no proxy - refusing to touch Facebook")
    if not profile.cookies_enc:
        return InteractResult(False, "profile has never signed in")

    if job.kind is ActivityKind.FOLLOW:
        handle = None
        if job.target_account_id is not None:
            target = await session.get(Account, job.target_account_id)
            handle = target.handle if target else None
        url = job.target_url or (profile_url(handle) if handle else None)
    else:
        url = job.target_url
    if not url:
        return InteractResult(False, f"{job.kind.value} job has no target")
    if job.kind is ActivityKind.REPOST:
        return InteractResult(False, "repost on facebook is not implemented")

    try:
        headless = get_settings().headless_jobs
        async with open(profile, headless=headless, humanize=True) as (_b, context):
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            if blocked := await detect(page, Platform.FACEBOOK):
                return InteractResult(False, blocked.evidence, checkpoint=blocked)
            budget = max(job.duration_seconds or 60, 20)
            await humanize.dwell(low=budget * 0.2, high=budget * 0.5, rng=rng)

            if job.kind is ActivityKind.FOLLOW:
                result = await _follow(page, rng)
            elif job.kind is ActivityKind.COMMENT:
                result = await _comment(page, comment_text(job.id, rng), rng)
            else:
                result = await _like(page, rng)

            if not result.ok and (blocked := await detect(page, Platform.FACEBOOK)):
                return InteractResult(False, blocked.evidence, checkpoint=blocked)
            return result
    except Exception as exc:
        log.warning("facebook_interact.failed", job=str(job.id), error=str(exc))
        return InteractResult(False, f"{type(exc).__name__}: {exc}", retryable=True)


async def _follow(page, rng: random.Random) -> InteractResult:
    if await actions.present(page, RECIPE.following_marker):
        return InteractResult(True, "already following")
    button = await actions.first_visible(page, RECIPE.follow)
    if button is None:
        return InteractResult(False, actions.selector_miss("the follow button", RECIPE.follow))
    await button.click()
    await humanize.dwell(low=1.5, high=4.0, rng=rng)
    if await actions.present(page, RECIPE.following_marker):
        return InteractResult(True, "followed")
    return InteractResult(
        False, "clicked follow but saw no confirmation - it MAY have worked", retryable=True
    )


async def _like(page, rng: random.Random) -> InteractResult:
    if await actions.present(page, RECIPE.liked_marker):
        return InteractResult(True, "already liked")
    button = await actions.first_visible(page, RECIPE.like)
    if button is None:
        return InteractResult(False, actions.selector_miss("the like button", RECIPE.like))
    await button.click()
    await humanize.dwell(low=1.0, high=3.0, rng=rng)
    if await actions.present(page, RECIPE.liked_marker):
        return InteractResult(True, "liked")
    return InteractResult(False, "clicked like but saw no confirmation", retryable=True)


async def _comment(page, text: str, rng: random.Random) -> InteractResult:
    editor = await actions.first_visible(page, COMMENT.editor)
    if editor is None:
        return InteractResult(False, actions.selector_miss("the comment box", COMMENT.editor))
    await humanize.type_like_person(editor, text, rng=rng)
    await humanize.dwell(low=1.0, high=3.0, rng=rng)
    await editor.press("Enter")
    try:
        await page.wait_for_selector(f"text={text[:60].strip()}", timeout=15_000)
        return InteractResult(True, f"comment: {text}")
    except Exception:
        # Da gui roi: khong thu lai (se thanh hai binh luan) - cho nguoi nhin.
        from seeding.browser.checkpoints import Checkpoint, CheckpointKind

        return InteractResult(
            False,
            "submitted the comment but it never appeared - it MAY be there, look first",
            checkpoint=Checkpoint(CheckpointKind.VERIFY, "comment unconfirmed"),
        )


if get_settings().facebook_enabled:
    register_interact(Platform.FACEBOOK, run)
