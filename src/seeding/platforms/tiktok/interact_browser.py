"""Tha tim / theo doi / binh luan / dang lai tren TikTok BANG TRINH DUYET (Camoufox).

Vi sao co duong nay du da co duong HTTP: do that 08/09/2026 tren tai khoan that -
DOC (feed, tim kiem, chi tiet video) qua HTTP chay 1-3 giay va tot; nhung GHI
(/api/commit/item/digg/) bi cong TikTok tra 200 rong trong moi bien the (tt-csrf,
x-secsdk-csrf-token that, X-Bogus/X-Gnarly trong header, body form, msToken moi
TikTok vua cap). Cong ghi cua web TikTok doi mot thu ma phien SDK cua signer khong co.

Nen: doc va lap lich van HTTP (nhanh), con bam thi mo dung trang video trong trinh duyet
cua profile - trang tu phat video, tuc la TikTok THAT SU thay 30-45 giay xem, roi moi
bam tim. Cham (trang qua proxy dan cu 90-300 giay) nhung dung nhip nguoi that, va day
la cach duy nhat da chung minh duoc la len.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser import actions, humanize
from seeding.browser.checkpoints import Checkpoint, CheckpointKind, detect
from seeding.browser.session import open_profile
from seeding.config import get_settings
from seeding.content.comments import warm_comment
from seeding.domain.models import Account, ActivityJob, ActivityKind, Platform, Profile
from seeding.platforms.base import InteractResult, register_interact
from seeding.platforms.outreach import direct_ok, ensure_proxy_loaded, watch_seconds
from seeding.platforms.tiktok.health import session_dead
from seeding.platforms.tiktok.interact import parse_target
from seeding.platforms.tiktok.web import ORIGIN

log = structlog.get_logger(__name__)

# Trang video qua proxy dan cu: do that 08/09/2026 tren P03 - thanh hanh dong ve sau 109s,
# 222s, va co lan qua 300s; lan tha tim len duoc mat 211s tong. 8 phut la con so do duoc,
# khong phai du phong. Worker: job_timeout phai lon hon con so nay.
GOTO_TIMEOUT_MS = 480_000
# Sau khi bam, trang gui request like/follow QUA PROXY roi moi doi trang thai nut. Qua
# proxy dan cu cham, 1-3 giay la khong du (17:23 08/09/2026: bam xong, nhin mot lan, chua
# thay "da thich", job bao 'MAY have worked'). Cho toi 20 giay, thay ngay thi tra ngay.
CONFIRM_MS = 20_000


@dataclass(frozen=True, slots=True)
class Recipe:
    """Do that 08/09/2026 tren trang video (giao dien moi): nut tim la
    div[role=button][data-e2e=like-icon] co aria-pressed va aria-label "Thich video ...",
    follow ngay tren video la button[data-e2e=feed-follow]; thanh hanh dong chi ve sau khi
    co di chuot / cuon."""

    like: tuple[str, ...] = (
        "[role='button'][data-e2e='like-icon']",
        "[data-e2e='like-icon']",
        "[data-e2e='browse-like-icon']",
    )
    liked: tuple[str, ...] = (
        "[data-e2e='like-icon'][aria-pressed='true']",
        "[data-e2e='browse-like-icon'][aria-pressed='true']",
    )
    follow: tuple[str, ...] = ("button[data-e2e='follow-button']", "button[data-e2e='feed-follow']")
    following: tuple[str, ...] = (
        "button[data-e2e='follow-button']:has-text('Following')",
        "button[data-e2e='follow-button']:has-text('Đang')",
        "button[data-e2e='feed-follow']:has-text('Đang')",
    )
    comment_open: tuple[str, ...] = (
        "[data-e2e='comment-icon']",
        "[data-e2e='browse-comment-icon']",
    )
    comment_editor: tuple[str, ...] = (
        "div[contenteditable='true'][data-e2e='comment-input']",
        "[data-e2e='comment-input'] div[contenteditable='true']",
        "div[contenteditable='true']",
    )
    comment_submit: tuple[str, ...] = ("[data-e2e='comment-post']", "button:has-text('Đăng')")
    share_open: tuple[str, ...] = ("[data-e2e='share-icon']", "[data-e2e='browse-share-icon']")
    repost: tuple[str, ...] = ("text=Đăng lại", "text=Repost")
    reposted: tuple[str, ...] = ("text=Đã đăng lại", "text=Reposted", "text=Remove repost")


RECIPE = Recipe()


def profile_url(handle: str) -> str:
    return f"{ORIGIN}/@{handle.lstrip('@')}"


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    open=open_profile,
    rng: random.Random | None = None,
    sleep=asyncio.sleep,
    recipe: Recipe = RECIPE,
) -> InteractResult:
    rng = rng or random.Random()
    await ensure_proxy_loaded(session, profile)
    if profile is None or (profile.proxy is None and not direct_ok(job)):
        return InteractResult(
            False, "profile has no proxy - refusing to touch TikTok from the host IP"
        )
    if not profile.cookies_enc:
        return InteractResult(False, "profile has never signed in")
    # Phien chet thi trang van hien nut tim va nut van chuyen sang "da thich" khi bam -
    # TikTok chi khong luu (P03, 08/09/2026). Hoi TikTok 2 giay truoc khi ton 8 phut
    # trinh duyet; chet thi giao cho nguoi dang nhap lai.
    if reason := await session_dead(profile):
        return InteractResult(
            False, reason, checkpoint=Checkpoint(CheckpointKind.LOGGED_OUT, reason)
        )

    handle, item_id = parse_target(job.target_url)
    if job.kind is ActivityKind.FOLLOW and job.target_account_id is not None:
        target = await session.get(Account, job.target_account_id)
        handle = target.handle if target else handle
    if job.kind is ActivityKind.FOLLOW:
        if not handle:
            return InteractResult(False, "follow job has no target handle")
        url = profile_url(handle)
    else:
        if not item_id:
            return InteractResult(False, f"{job.kind.value} job has no video url")
        url = job.target_url

    try:
        headless = get_settings().headless_jobs
        async with open(profile, headless=headless, humanize=True) as (_b, context):
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS)
            if blocked := await detect(page, Platform.TIKTOK):
                return InteractResult(False, blocked.evidence, checkpoint=blocked)

            # domcontentloaded chi la cai vo: qua proxy dan cu, JS cua TikTok con tai them
            # vai phut nua roi moi ve nut. Cho nut can dung xuat hien truoc, roi moi XEM.
            if job.kind is ActivityKind.FOLLOW:
                needed = recipe.follow + recipe.following
            elif job.kind is ActivityKind.COMMENT:
                needed = recipe.comment_open + recipe.comment_editor + recipe.like
            elif job.kind is ActivityKind.REPOST:
                needed = recipe.share_open + recipe.like + recipe.reposted
            else:
                needed = recipe.like + recipe.liked
            if await _wait_with_nudge(page, needed, GOTO_TIMEOUT_MS, rng, sleep) is None:
                if blocked := await detect(page, Platform.TIKTOK):
                    return InteractResult(False, blocked.evidence, checkpoint=blocked)
                return InteractResult(
                    False,
                    f"page never rendered its action bar in {GOTO_TIMEOUT_MS // 1000}s "
                    "(slow proxy or a blank shell) - it will be retried",
                    retryable=True,
                )

            # XEM. Trang video tu phat; day la 30-45 giay TikTok that su thay.
            await sleep(watch_seconds(job))

            if job.kind is ActivityKind.ENGAGE:
                result = await _like(page, recipe, rng, sleep)
            elif job.kind is ActivityKind.FOLLOW:
                result = await _follow(page, recipe, rng, sleep)
            elif job.kind is ActivityKind.COMMENT:
                result = await _comment(
                    page, recipe, warm_comment(job.id, "tiktok", rng), rng, sleep
                )
            else:
                result = await _repost(page, recipe, rng, sleep)

            if not result.ok and result.checkpoint is None:
                if blocked := await detect(page, Platform.TIKTOK):
                    return InteractResult(False, blocked.evidence, checkpoint=blocked)
            return result
    except Exception as exc:
        log.warning("tiktok_browser.failed", job=str(job.id), error=f"{type(exc).__name__}: {exc}")
        return InteractResult(False, f"{type(exc).__name__}: {exc}", retryable=True)


async def _wait_with_nudge(page, selectors, timeout_ms: int, rng, sleep):
    """Cho nut hien, moi ~15 giay lai di chuot / cuon nhe: do that, thanh hanh dong cua
    TikTok chi render sau khi trang thay co tuong tac."""
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        found = await actions.first_visible(page, selectors, timeout_ms=3_000)
        if found is not None:
            return found
        try:
            await page.mouse.move(rng.randint(500, 800), rng.randint(300, 500))
            await page.mouse.wheel(0, rng.randint(80, 160))
            await sleep(rng.uniform(0.6, 1.4))
            await page.mouse.wheel(0, -rng.randint(80, 160))
        except Exception:
            pass
        await sleep(rng.uniform(8, 14))
    return None


async def _like(page, r: Recipe, rng, sleep) -> InteractResult:
    if await actions.present(page, r.liked):
        return InteractResult(True, "already liked")
    button = await actions.first_visible(page, r.like)
    if button is None:
        return InteractResult(False, actions.selector_miss("the like button", r.like))
    await button.click()
    await humanize.dwell(low=1.0, high=3.0, rng=rng, sleep=sleep)
    if await actions.wait_visible(page, r.liked, timeout_ms=CONFIRM_MS):
        return InteractResult(True, "liked")
    return InteractResult(
        False,
        "clicked like but the button never showed as pressed - it MAY have worked",
        retryable=True,
    )


async def _follow(page, r: Recipe, rng, sleep) -> InteractResult:
    if await actions.present(page, r.following):
        return InteractResult(True, "already following")
    button = await actions.first_visible(page, r.follow)
    if button is None:
        return InteractResult(False, actions.selector_miss("the follow button", r.follow))
    await button.click()
    await humanize.dwell(low=1.5, high=4.0, rng=rng, sleep=sleep)
    if await actions.present(page, r.following):
        return InteractResult(True, "followed")
    return InteractResult(False, "clicked follow but saw no confirmation", retryable=True)


async def _comment(page, r: Recipe, text: str, rng, sleep) -> InteractResult:
    opener = await actions.first_visible(page, r.comment_open)
    if opener is not None:
        await opener.click()
        await humanize.dwell(low=0.8, high=2.0, rng=rng, sleep=sleep)
    editor = await actions.wait_visible(page, r.comment_editor, 15_000)
    if editor is None:
        return InteractResult(False, actions.selector_miss("the comment box", r.comment_editor))
    await humanize.type_like_person(editor, text, rng=rng, sleep=sleep)
    await humanize.dwell(low=0.8, high=2.0, rng=rng, sleep=sleep)
    submit = await actions.first_visible(page, r.comment_submit)
    if submit is None:
        return InteractResult(
            False, actions.selector_miss("the comment post button", r.comment_submit)
        )
    await submit.click()
    await humanize.dwell(low=2.0, high=4.0, rng=rng, sleep=sleep)
    # Sticker hien thanh anh, khong tim duoc bang chu: o soan trong lai la dau hieu da gui.
    try:
        left = (await editor.inner_text()).strip()
    except Exception:
        left = ""
    if not left:
        return InteractResult(True, f"comment: {text}")
    return InteractResult(
        False,
        "submitted the comment but the box did not clear - it MAY be there, look first",
        checkpoint=Checkpoint(CheckpointKind.VERIFY, "comment unconfirmed"),
    )


async def _repost(page, r: Recipe, rng, sleep) -> InteractResult:
    if await actions.present(page, r.reposted):
        return InteractResult(True, "already reposted")
    opener = await actions.first_visible(page, r.share_open)
    if opener is None:
        return InteractResult(False, actions.selector_miss("the share button", r.share_open))
    await opener.hover()
    await humanize.dwell(low=0.8, high=1.6, rng=rng, sleep=sleep)
    button = await actions.first_visible(page, r.repost)
    if button is None:
        return InteractResult(False, actions.selector_miss("the repost item", r.repost))
    await button.click()
    await humanize.dwell(low=1.5, high=3.0, rng=rng, sleep=sleep)
    if await actions.present(page, r.reposted):
        return InteractResult(True, "reposted")
    return InteractResult(False, "clicked repost but saw no confirmation", retryable=True)


if get_settings().tiktok_actions == "browser":
    register_interact(Platform.TIKTOK, run)
