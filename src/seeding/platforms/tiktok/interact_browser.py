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
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from playwright.async_api import Error as PlaywrightError
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser import actions, humanize
from seeding.browser.checkpoints import Checkpoint, CheckpointKind, detect
from seeding.browser.session import open_profile
from seeding.config import get_settings
from seeding.content.comments import warm_comment
from seeding.domain.models import (
    Account,
    ActivityJob,
    ActivityKind,
    JobStatus,
    Platform,
    Profile,
)
from seeding.ops import proxy_stats
from seeding.platforms.base import InteractResult, register_interact
from seeding.platforms.outreach import direct_ok, ensure_proxy_loaded, watch_seconds
from seeding.platforms.tiktok import sitting as sitting_mod
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
# Mot cu bam: nut da hien va on dinh, chi con lop phu (captcha) co the chan. 30s mac dinh
# cua Playwright chi keo dai viec nhan ra dieu do.
CLICK_MS = 10_000


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
        return InteractResult(False, "chưa có proxy (no proxy) - không mở TikTok bằng IP máy chủ")
    if not profile.cookies_enc:
        return InteractResult(False, "profile chưa từng đăng nhập")
    # Phien chet thi trang van hien nut tim va nut van chuyen sang "da thich" khi bam -
    # TikTok chi khong luu (P03, 08/09/2026). Hoi TikTok 2 giay truoc khi ton 8 phut
    # trinh duyet; chet thi giao cho nguoi dang nhap lai.
    if reason := await session_dead(profile):
        return InteractResult(
            False, reason, checkpoint=Checkpoint(CheckpointKind.LOGGED_OUT, reason)
        )

    if job.kind is ActivityKind.BROWSE_FEED:
        return await _run_sitting(
            session, profile, job, open=open, rng=rng, sleep=sleep, recipe=recipe
        )

    handle, item_id = parse_target(job.target_url)
    if job.kind is ActivityKind.FOLLOW and job.target_account_id is not None:
        target = await session.get(Account, job.target_account_id)
        handle = target.handle if target else handle
    if job.kind is ActivityKind.FOLLOW:
        if not handle:
            return InteractResult(False, "job follow không có tên người cần follow")
        url = profile_url(handle)
    else:
        if not item_id:
            return InteractResult(False, f"job {job.kind.value} không có link video")
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
            opened = time.monotonic()
            shown = await _wait_with_nudge(page, needed, GOTO_TIMEOUT_MS, rng, sleep)
            await _note_render(profile, shown is not None, time.monotonic() - opened)
            if shown is None:
                if blocked := await detect(page, Platform.TIKTOK):
                    return InteractResult(False, blocked.evidence, checkpoint=blocked)
                return InteractResult(
                    False,
                    f"trang không hiện thanh hành động trong {GOTO_TIMEOUT_MS // 1000}s "
                    "(proxy chậm hoặc trang trống, page never rendered) - sẽ thử lại",
                    retryable=True,
                )

            # XEM. Trang video tu phat; day la 30-45 giay TikTok that su thay.
            await sleep(watch_seconds(job))

            try:
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
            except PlaywrightError as exc:
                # Bam khong toi: 08/09/2026 tren P05, hop captcha cua TikTok hien DE LEN
                # nut tim dung luc bam ("subtree intercepts pointer events"). Do la
                # checkpoint cho nguoi, khong phai loi tam de thu lai.
                if blocked := await detect(page, Platform.TIKTOK):
                    return InteractResult(False, blocked.evidence, checkpoint=blocked)
                return InteractResult(False, f"cú bấm bị chặn: {_short(exc)}", retryable=True)

            if not result.ok and result.checkpoint is None:
                if blocked := await detect(page, Platform.TIKTOK):
                    return InteractResult(False, blocked.evidence, checkpoint=blocked)
            return result
    except Exception as exc:
        log.warning("tiktok_browser.failed", job=str(job.id), error=_short(exc))
        return InteractResult(False, _short(exc), retryable=True)


def _short(exc: BaseException) -> str:
    """Mot dong, ASCII: loi Playwright dai hang chuc dong va co ky tu trang khong ma hoa
    duoc tren console cp1252 - da lam sap chinh handler ghi log (08/09/2026)."""
    text = " ".join(str(exc).split())[:300]
    return f"{type(exc).__name__}: {text}".encode("ascii", "backslashreplace").decode()


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
        return InteractResult(True, "đã thả tim từ trước")
    button = await actions.first_visible(page, r.like)
    if button is None:
        return InteractResult(False, actions.selector_miss("the like button", r.like))
    await button.click(timeout=CLICK_MS)
    await humanize.dwell(low=1.0, high=3.0, rng=rng, sleep=sleep)
    if await actions.wait_visible(page, r.liked, timeout_ms=CONFIRM_MS):
        return InteractResult(True, "đã thả tim")
    return InteractResult(
        False,
        "đã bấm tim nhưng nút không chuyển sang đã thích - CÓ THỂ đã được, sẽ kiểm lại",
        retryable=True,
    )


async def _follow(page, r: Recipe, rng, sleep) -> InteractResult:
    if await actions.present(page, r.following):
        return InteractResult(True, "đã follow từ trước")
    button = await actions.first_visible(page, r.follow)
    if button is None:
        return InteractResult(False, actions.selector_miss("the follow button", r.follow))
    await button.click(timeout=CLICK_MS)
    await humanize.dwell(low=1.5, high=4.0, rng=rng, sleep=sleep)
    if await actions.present(page, r.following):
        return InteractResult(True, "đã follow")
    return InteractResult(False, "clicked follow but saw no confirmation", retryable=True)


async def _comment(page, r: Recipe, text: str, rng, sleep) -> InteractResult:
    opener = await actions.first_visible(page, r.comment_open)
    if opener is not None:
        await opener.click(timeout=CLICK_MS)
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
    await submit.click(timeout=CLICK_MS)
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
        return InteractResult(True, "đã đăng lại từ trước")
    opener = await actions.first_visible(page, r.share_open)
    if opener is None:
        return InteractResult(False, actions.selector_miss("the share button", r.share_open))
    await opener.hover()
    await humanize.dwell(low=0.8, high=1.6, rng=rng, sleep=sleep)
    button = await actions.first_visible(page, r.repost)
    if button is None:
        return InteractResult(False, actions.selector_miss("the repost item", r.repost))
    await button.click(timeout=CLICK_MS)
    await humanize.dwell(low=1.5, high=3.0, rng=rng, sleep=sleep)
    if await actions.present(page, r.reposted):
        return InteractResult(True, "đã đăng lại")
    return InteractResult(False, "clicked repost but saw no confirmation", retryable=True)


if get_settings().tiktok_actions == "browser":
    register_interact(Platform.TIKTOK, run)


# ------------------------------------------------------------------ phien luot xem

# Sang video ke tiep: TikTok web nhan phim mui ten xuong tren For You va trong trinh
# phat; trang ket qua tim kiem co nut mui ten phai. Khong duoc thi cuon.
NEXT_VIDEO = ("button[data-e2e='arrow-right']", "[data-e2e='arrow-right']")
SEARCH_ITEM = (
    "[data-e2e='search_video-item'] a",
    "[data-e2e='search_top-item'] a",
    "[data-e2e='search-card-video-link']",
)
# Doi URL sang video moi sau khi bam sang: toi da tung nay giay.
NEXT_WAIT_S = 20


async def _run_sitting(
    session, profile: Profile, job: ActivityJob, *, open, rng, sleep, recipe: Recipe
) -> InteractResult:
    plan = sitting_mod.decode(job.target_url) or sitting_mod.Plan()
    try:
        headless = get_settings().headless_jobs
        async with open(profile, headless=headless, humanize=True) as (_b, context):
            page = await context.new_page()
            await page.goto(
                plan.url(ORIGIN), wait_until="domcontentloaded", timeout=GOTO_TIMEOUT_MS
            )
            if blocked := await detect(page, Platform.TIKTOK):
                return InteractResult(False, blocked.evidence, checkpoint=blocked)
            if plan.source == "search":
                item = await _wait_with_nudge(page, SEARCH_ITEM, GOTO_TIMEOUT_MS, rng, sleep)
                if item is None:
                    if blocked := await detect(page, Platform.TIKTOK):
                        return InteractResult(False, blocked.evidence, checkpoint=blocked)
                    return InteractResult(
                        False,
                        f"trang tìm kiếm không hiện kết quả trong {GOTO_TIMEOUT_MS // 1000}s "
                        "(page never rendered) - sẽ thử lại",
                        retryable=True,
                    )
                await humanize.dwell(low=2.0, high=5.0, rng=rng, sleep=sleep)
                await item.click(timeout=CLICK_MS)
            opened = time.monotonic()
            bar = await _wait_with_nudge(
                page, recipe.like + recipe.liked, GOTO_TIMEOUT_MS, rng, sleep
            )
            await _note_render(profile, bar is not None, time.monotonic() - opened)
            if bar is None:
                if blocked := await detect(page, Platform.TIKTOK):
                    return InteractResult(False, blocked.evidence, checkpoint=blocked)
                return InteractResult(
                    False,
                    f"trang không hiện thanh hành động trong {GOTO_TIMEOUT_MS // 1000}s "
                    "(proxy chậm hoặc trang trống, page never rendered) - sẽ thử lại",
                    retryable=True,
                )
            return await _browse(session, page, job, plan, recipe, rng, sleep)
    except Exception as exc:
        log.warning("tiktok_browser.failed", job=str(job.id), error=_short(exc))
        return InteractResult(False, _short(exc), retryable=True)


async def _note_render(profile: Profile, ok: bool, seconds: float) -> None:
    """Ghi cho proxy cua acc: trang TikTok hien hay khong, sau bao lau. Redis hong thi thoi."""
    try:
        await proxy_stats.note_render(getattr(profile, "proxy_id", None), ok, seconds)
    except Exception:
        pass


def _current_video(page) -> str | None:
    url = str(getattr(page, "url", "") or "")
    return url if "/video/" in url else None


def _child(job: ActivityJob, kind: ActivityKind, url: str | None, secs: int, res: InteractResult):
    """Mot hanh dong trong phien = mot job con da xong, de dong thoi gian va ngan sach
    ngay (count_outward_for_day) dem duoc nhu job mo thang link."""
    return ActivityJob(
        account_id=job.account_id,
        kind=kind,
        status=JobStatus.SUCCEEDED if res.ok else JobStatus.FAILED,
        scheduled_at=datetime.now(UTC),
        duration_seconds=secs,
        target_url=url or job.target_url,
        detail=res.detail,
        last_error=None if res.ok else res.detail,
    )


def _record(session, children: list) -> None:
    add_all = getattr(session, "add_all", None)
    if add_all is not None and children:
        add_all(children)


async def _watch(page, secs: int, rng, sleep) -> None:
    """Xem `secs` giay: ngu tung khuc 6-12 giay, giua cac khuc di chuot nhe - trang co
    nguoi ngoi truoc, khong phai mot tab bo quen."""
    elapsed = 0.0
    while elapsed < secs:
        chunk = min(rng.uniform(6.0, 12.0), secs - elapsed)
        await sleep(chunk)
        elapsed += chunk
        try:
            await page.mouse.move(rng.randint(400, 900), rng.randint(200, 600))
        except Exception:
            pass


async def _next_video(page, rng, sleep) -> bool:
    """Sang video ke tiep: phim xuong, roi nut mui ten, roi cuon. Thanh cong = URL doi."""
    before = str(getattr(page, "url", "") or "")
    for how in ("key", "arrow", "wheel"):
        try:
            if how == "key":
                await page.keyboard.press("ArrowDown")
            elif how == "arrow":
                button = await actions.first_visible(page, NEXT_VIDEO, timeout_ms=2_000)
                if button is None:
                    continue
                await button.click(timeout=CLICK_MS)
            else:
                await page.mouse.wheel(0, rng.randint(600, 900))
        except Exception:
            continue
        waited = 0.0
        while waited < NEXT_WAIT_S:
            step = rng.uniform(1.0, 2.5)
            await sleep(step)
            waited += step
            if str(getattr(page, "url", "") or "") != before:
                return True
    return False


async def _browse(session, page, job: ActivityJob, plan, r: Recipe, rng, sleep) -> InteractResult:
    """Luot `plan.videos` video, xem moi video 20-45 giay, tieu ngan sach cua phien.

    Video dau tien khong bam gi (nguoi that vao la luot vai cai da). Tha tim voi xac
    suat tim-con-lai / video-con-lai, nen het phien la vua het ngan sach ma khong dinh
    vao mot vi tri co dinh. Follow / binh luan / dang lai chi tren video vua tha tim.
    """
    started = time.monotonic()
    left = {
        "likes": plan.likes,
        "follows": plan.follows,
        "comments": plan.comments,
        "reposts": plan.reposts,
    }
    done = {"likes": 0, "follows": 0, "comments": 0, "reposts": 0}
    children: list = []
    watched = 0
    videos = 0
    stopped = None

    async def act(kind: ActivityKind, key: str, fn, url, secs):
        """Mot hanh dong; tra ve checkpoint neu gap, None neu khong."""
        try:
            res = await fn()
        except PlaywrightError as exc:
            if blocked := await detect(page, Platform.TIKTOK):
                return blocked
            res = InteractResult(False, f"cú bấm bị chặn: {_short(exc)}")
        left[key] -= 1
        children.append(_child(job, kind, url, secs, res))
        if res.ok:
            done[key] += 1
        elif res.checkpoint is not None:
            return res.checkpoint
        return None

    def halted(blocked):
        _record(session, children)
        return InteractResult(False, blocked.evidence, checkpoint=blocked)

    for i in range(plan.videos):
        if time.monotonic() - started > sitting_mod.SITTING_MAX_S:
            stopped = "hết giờ phiên"
            break
        if blocked := await detect(page, Platform.TIKTOK):
            return halted(blocked)
        secs = rng.randint(*sitting_mod.WATCH_RANGE)
        await _watch(page, secs, rng, sleep)
        watched += secs
        videos += 1
        url = _current_video(page)
        remaining = plan.videos - i
        liked = False
        if i > 0 and left["likes"] > 0 and rng.random() < left["likes"] / remaining:
            blocked = await act(
                ActivityKind.ENGAGE, "likes", lambda: _like(page, r, rng, sleep), url, secs
            )
            if blocked:
                return halted(blocked)
            liked = children[-1].status is JobStatus.SUCCEEDED
        if liked and left["follows"] > 0:
            await humanize.dwell(low=2.0, high=6.0, rng=rng, sleep=sleep)
            blocked = await act(
                ActivityKind.FOLLOW, "follows", lambda: _follow(page, r, rng, sleep), url, secs
            )
            if blocked:
                return halted(blocked)
        if liked and left["comments"] > 0:
            await humanize.dwell(low=3.0, high=8.0, rng=rng, sleep=sleep)
            text = warm_comment(job.id, "tiktok", rng)
            blocked = await act(
                ActivityKind.COMMENT,
                "comments",
                lambda text=text: _comment(page, r, text, rng, sleep),
                url,
                secs,
            )
            if blocked:
                return halted(blocked)
        if liked and left["reposts"] > 0:
            await humanize.dwell(low=2.0, high=6.0, rng=rng, sleep=sleep)
            blocked = await act(
                ActivityKind.REPOST, "reposts", lambda: _repost(page, r, rng, sleep), url, secs
            )
            if blocked:
                return halted(blocked)
        if i < plan.videos - 1 and not await _next_video(page, rng, sleep):
            stopped = "không sang được video kế tiếp"
            break

    _record(session, children)
    parts = [f"xem {videos} video ({watched}s)"]
    if done["likes"]:
        parts.append(f"thả tim {done['likes']}")
    if done["follows"]:
        parts.append(f"follow {done['follows']}")
    if done["comments"]:
        parts.append(f"bình luận {done['comments']}")
    if done["reposts"]:
        parts.append(f"đăng lại {done['reposts']}")
    if not any(done.values()) and plan.watch_only:
        parts.append("chỉ xem")
    if stopped:
        parts.append(stopped)
    return InteractResult(videos > 0, ", ".join(parts), retryable=videos == 0)
