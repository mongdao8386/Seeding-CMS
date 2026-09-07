"""Ba hanh dong nham vao mot dich: theo doi, tha cam xuc, chia se lai.

Khac han hoat dong nen. Hoat dong nen chi can "trong giong nguoi that" va sai mot chut
cung khong sao. Ba hanh dong o day GHI LAI MOT CANH tren nen tang: no cong khai, no o
lai, va no khong rut ve duoc mot cach sach se.

Nen o day co hai luat khac han phan con lai cua he thong:

  1. Khong bao gio bao thanh cong khi chua thay bang chung. Bam xong phai thay nut doi
     trang thai ("Follow" -> "Following"). Khong thay thi bao that bai, ke ca khi cu
     bam co the da an. Bao thanh cong nham o day nghia la `core/graph.py` tuong mot
     canh da ton tai, va moi phep tinh mat do sau do deu sai.

  2. Selector khong tim thay thi DUNG, khong doan tiep. Tren mot trang ca nhan, nut
     nam canh "Follow" thuong la "Block" hoac "Report". Bam nham vao do khong phai la
     mot loi nho.

Nhu RECIPES trong adapters/browser.py, cac selector duoi day CHUA DUOC KIEM CHUNG tren
tai khoan that. Chung la diem xuat phat de sua, khong phai su that.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import structlog

from seeding.browser import humanize
from seeding.browser.checkpoints import Checkpoint, detect
from seeding.browser.session import open_profile
from seeding.config import get_settings
from seeding.models import ActivityKind, Platform, Profile

log = structlog.get_logger(__name__)


@dataclass(slots=True)
class InteractResult:
    ok: bool
    detail: str
    checkpoint: Checkpoint | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class GraphRecipe:
    """Cach lam ba hanh dong tren mot nen tang.

    `profile_url` la mau de dung dia chi trang ca nhan tu handle. `{handle}` duoc thay.
    """

    profile_url: str
    follow: tuple[str, ...]
    # Dau hieu DA theo doi. Thay no moi tinh la xong - va cung dung no de biet minh
    # da theo doi tu truoc, khoi bam lan hai (bam lan hai la BO theo doi).
    following_marker: tuple[str, ...]
    like: tuple[str, ...] = ()
    liked_marker: tuple[str, ...] = ()
    repost: tuple[str, ...] = ()
    reposted_marker: tuple[str, ...] = ()


RECIPES: dict[Platform, GraphRecipe] = {
    Platform.THREADS: GraphRecipe(
        profile_url="https://www.threads.net/@{handle}",
        follow=("div[role='button']:has-text('Follow')", "button:has-text('Follow')"),
        following_marker=("div[role='button']:has-text('Following')", "text=Following"),
        like=("svg[aria-label='Like']", "div[role='button'][aria-label='Like']"),
        liked_marker=("svg[aria-label='Unlike']",),
        repost=("svg[aria-label='Repost']", "div[role='button']:has-text('Repost')"),
        reposted_marker=("text=Reposted", "svg[aria-label='Remove']"),
    ),
    Platform.X: GraphRecipe(
        profile_url="https://x.com/{handle}",
        follow=("button[data-testid$='-follow']", "div[role='button']:has-text('Follow')"),
        following_marker=("button[data-testid$='-unfollow']", "text=Following"),
        like=("button[data-testid='like']",),
        liked_marker=("button[data-testid='unlike']",),
        repost=("button[data-testid='retweet']",),
        reposted_marker=("button[data-testid='unretweet']",),
    ),
    Platform.INSTAGRAM: GraphRecipe(
        profile_url="https://www.instagram.com/{handle}/",
        follow=("button:has-text('Follow')", "div[role='button']:has-text('Follow')"),
        following_marker=("button:has-text('Following')", "text=Following"),
        like=("svg[aria-label='Like']",),
        liked_marker=("svg[aria-label='Unlike']",),
    ),
    Platform.TIKTOK: GraphRecipe(
        profile_url="https://www.tiktok.com/@{handle}",
        follow=("button[data-e2e='follow-button']", "button:has-text('Follow')"),
        following_marker=("button[data-e2e='follow-button']:has-text('Following')",),
        like=("span[data-e2e='like-icon']",),
        liked_marker=("span[data-e2e='undefined-count']",),
        repost=("span[data-e2e='undefined-icon']",),
    ),
    Platform.FACEBOOK: GraphRecipe(
        profile_url="https://www.facebook.com/{handle}",
        follow=("div[aria-label='Follow']", "div[role='button']:has-text('Follow')"),
        following_marker=("div[aria-label='Following']", "text=Following"),
        like=("div[aria-label='Like']",),
        liked_marker=("div[aria-label='Remove Like']",),
        repost=("div[aria-label='Send this to friends or post it on your profile.']",),
    ),
}


def profile_url(platform: Platform, handle: str) -> str | None:
    recipe = RECIPES.get(platform)
    if recipe is None:
        return None
    return recipe.profile_url.format(handle=handle.lstrip("@"))


async def _first_visible(page, selectors: tuple[str, ...]):
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if await locator.count() and await locator.is_visible():
                return locator
        except Exception:
            continue
    return None


async def _present(page, selectors: tuple[str, ...]) -> bool:
    for selector in selectors:
        try:
            if await page.locator(selector).first.count():
                return True
        except Exception:
            continue
    return False


async def run(
    profile: Profile,
    platform: Platform,
    kind: ActivityKind,
    *,
    target_url: str | None = None,
    target_handle: str | None = None,
    budget_seconds: int = 60,
    rng: random.Random | None = None,
) -> InteractResult:
    """Thuc hien mot hanh dong nham dich."""
    rng = rng or random.Random()

    recipe = RECIPES.get(platform)
    if recipe is None:
        return InteractResult(False, f"no interaction recipe for {platform.value} yet")
    if not profile.cookies_enc:
        return InteractResult(False, "profile has never signed in")

    if kind is ActivityKind.FOLLOW:
        if not target_handle:
            return InteractResult(False, "follow job has no target handle")
        url = profile_url(platform, target_handle)
    else:
        if not target_url:
            return InteractResult(False, f"{kind.value} job has no target url")
        url = target_url

    if url is None:
        return InteractResult(False, f"cannot build a profile url for {platform.value}")

    try:
        headless = get_settings().headless_jobs
        async with open_profile(profile, headless=headless, humanize=True) as (_b, context):
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)

            if blocked := await detect(page, platform):
                return InteractResult(False, blocked.evidence, checkpoint=blocked)

            # Doc truoc khi hanh dong. Mo trang roi bam ngay trong mot giay la nhip cua
            # mot cai nut - va day chinh la cho nhip do bi soi ky nhat.
            await humanize.dwell(low=budget_seconds * 0.2, high=budget_seconds * 0.5, rng=rng)

            if kind is ActivityKind.FOLLOW:
                result = await _follow(page, recipe, rng)
            elif kind is ActivityKind.REPOST:
                result = await _act(page, recipe.repost, recipe.reposted_marker, "repost", rng)
            else:
                result = await _act(page, recipe.like, recipe.liked_marker, "like", rng)

            if not result.ok:
                if blocked := await detect(page, platform):
                    return InteractResult(False, blocked.evidence, checkpoint=blocked)
            return result

    except Exception as exc:
        log.warning("interact.failed", profile=str(profile.id), error=str(exc))
        return InteractResult(False, f"{type(exc).__name__}: {exc}", retryable=True)


async def _follow(page, recipe: GraphRecipe, rng: random.Random) -> InteractResult:
    # Da theo doi tu truoc thi DUNG LAI. Nut "Following" bam vao la BO theo doi - mot
    # canh bi xoa mat ma khong ai co y xoa, va lan sau lai bam theo doi lai.
    if await _present(page, recipe.following_marker):
        return InteractResult(True, "already following")

    button = await _first_visible(page, recipe.follow)
    if button is None:
        return InteractResult(
            False,
            "could not find the follow button. On a profile page the button next to Follow is "
            "usually Block or Report, so this stops instead of guessing — update RECIPES in "
            "browser/interact.py.",
        )

    await button.click()
    await humanize.dwell(low=1.5, high=4.0, rng=rng)

    if await _present(page, recipe.following_marker):
        return InteractResult(True, "followed")

    return InteractResult(
        False,
        "clicked follow but the button never changed to Following. It MAY have worked — "
        "check by hand before letting it retry.",
        retryable=True,
    )


async def _act(
    page,
    selectors: tuple[str, ...],
    marker: tuple[str, ...],
    name: str,
    rng: random.Random,
) -> InteractResult:
    if not selectors:
        return InteractResult(False, f"no {name} selectors for this platform yet")

    if marker and await _present(page, marker):
        return InteractResult(True, f"already {name}d")

    button = await _first_visible(page, selectors)
    if button is None:
        return InteractResult(False, f"could not find the {name} button")

    await button.click()
    await humanize.dwell(low=1.0, high=3.0, rng=rng)

    if not marker:
        # Khong co dau hieu de kiem thi khong khang dinh duoc. Bao that bai co chu y:
        # mot canh "co le da tao" lam moi phep tinh mat do sau do thanh vo nghia.
        return InteractResult(
            False,
            f"clicked {name} but this platform has no confirmation marker defined, so the "
            "result cannot be verified — add one to RECIPES in browser/interact.py.",
        )

    if await _present(page, marker):
        return InteractResult(True, f"{name}d")

    return InteractResult(
        False,
        f"clicked {name} but saw no confirmation. It MAY have worked — check by hand.",
        retryable=True,
    )
