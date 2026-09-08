"""Dang bai / binh luan Facebook bang trinh duyet - chuyen tu nhanh legacy.

Hai luat giu nguyen:
  1. Xem feed truoc khi dang (humanize.warm_up). Vao trang la dang ngay la mau bot ro nhat.
  2. Khong bao gio bao thanh cong khi chua thay dau hieu that. Da bam Dang ma khong
     xac nhan duoc -> cho nguoi, KHONG thu lai: bai co the da len.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import structlog

from seeding.browser import actions, humanize
from seeding.browser.checkpoints import detect
from seeding.browser.session import open_profile
from seeding.config import get_settings
from seeding.domain.models import Account, Platform, Profile, Variant
from seeding.platforms.base import PublishResult, register

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PostRecipe:
    compose_url: str
    open_composer: tuple[str, ...]
    editor: tuple[str, ...]
    submit: tuple[str, ...]
    posted_signal: tuple[str, ...]
    media_input: tuple[str, ...] = ()
    goto_timeout_ms: int = 120_000
    editor_timeout_ms: int = 30_000


@dataclass(frozen=True, slots=True)
class CommentRecipe:
    editor: tuple[str, ...]
    # Rong = gui bang Enter (Facebook lam vay).
    submit: tuple[str, ...] = ()


POST = PostRecipe(
    compose_url="https://www.facebook.com/",
    open_composer=(
        "div[role='button']:has-text(\"What's on your mind\")",
        "div[role='button']:has-text('Bạn đang nghĩ gì')",
    ),
    editor=(
        "div[contenteditable='true'][role='textbox']",
        "div[aria-label*='mind']",
        "div[aria-label*='nghĩ gì']",
    ),
    submit=("div[aria-label='Post']", "div[aria-label='Đăng']", "button:has-text('Post')"),
    posted_signal=("text=Your post is now live", "text=Bài viết của bạn"),
    media_input=("input[type='file'][accept*='image']", "input[type='file']"),
)

COMMENT = CommentRecipe(
    editor=(
        "div[contenteditable='true'][aria-label*='comment']",
        "div[contenteditable='true'][aria-label*='bình luận']",
        "div[contenteditable='true'][role='textbox']",
    ),
)


def caption_for(variant: Variant) -> str:
    return f"{variant.title}\n\n{variant.body}".strip() if variant.body else variant.title


def precheck(account: Account, variant: Variant, target: dict, profile: Profile | None):
    """Chan nhung viec chac chan hong TRUOC khi mo trinh duyet (~400MB, vai chuc giay)."""
    if profile is None:
        return PublishResult(ok=False, error=f"{account.handle}: no profile yet")
    if not profile.cookies_enc:
        return PublishResult(
            ok=False, needs_human=True, error=f"{account.handle} has never signed in"
        )
    if profile.proxy is None:
        return PublishResult(ok=False, error=f"{account.handle}: profile has no proxy")
    kind = (target.get("kind") or "post").lower()
    if kind == "comment":
        if not target.get("url"):
            return PublishResult(ok=False, error="target is missing 'url' to comment on")
        if not (variant.body or "").strip():
            return PublishResult(ok=False, error="Bình luận cần thân bài.")
    elif not caption_for(variant) and not variant.media_variant_ref:
        return PublishResult(ok=False, error="nothing to post: empty text and no media")
    return None


class FacebookBrowserAdapter:
    platform = Platform.FACEBOOK

    def __init__(
        self, *, open=open_profile, post: PostRecipe = POST, comment: CommentRecipe = COMMENT
    ):
        self._open = open
        self.post_recipe = post
        self.comment_recipe = comment

    async def publish(
        self,
        account: Account,
        variant: Variant,
        target: dict,
        *,
        profile: Profile | None = None,
    ) -> PublishResult:
        problem = precheck(account, variant, target, profile)
        if problem is not None:
            return problem
        kind = (target.get("kind") or "post").lower()
        rng = random.Random()
        try:
            headless = get_settings().headless_jobs
            async with self._open(profile, headless=headless, humanize=True) as (_b, context):
                page = await context.new_page()
                if kind == "comment":
                    return await self._comment(page, variant, target["url"], rng)
                return await self._post(page, variant, rng)
        except Exception as exc:
            log.warning("facebook.publish_failed", handle=account.handle, error=str(exc))
            return PublishResult(ok=False, retryable=True, error=f"{type(exc).__name__}: {exc}")

    async def _post(self, page, variant: Variant, rng: random.Random) -> PublishResult:
        r = self.post_recipe
        await page.goto(r.compose_url, wait_until="domcontentloaded", timeout=r.goto_timeout_ms)
        if blocked := await detect(page, Platform.FACEBOOK):
            return _from_checkpoint(blocked)
        await humanize.warm_up(page, rng=rng)

        opener = await actions.first_visible(page, r.open_composer)
        if opener is None:
            return _miss("the composer button", r.open_composer)
        await opener.click()
        await humanize.dwell(low=0.8, high=2.0, rng=rng)

        if variant.media_variant_ref:
            err = await actions.attach_media(page, r.media_input, variant.media_variant_ref)
            if err:
                return PublishResult(ok=False, error=err)

        editor = await actions.wait_visible(page, r.editor, r.editor_timeout_ms)
        if editor is None:
            return _miss("the text editor", r.editor)
        text = caption_for(variant)
        if text:
            await humanize.type_like_person(editor, text, rng=rng)
        await humanize.dwell(low=1.0, high=3.0, rng=rng)

        submit = await actions.first_visible(page, r.submit)
        if submit is None:
            return _miss("the post button", r.submit)
        await submit.click()

        for signal in r.posted_signal:
            try:
                await page.wait_for_selector(signal, timeout=12_000)
                return PublishResult(ok=True, remote_url=page.url)
            except Exception:
                continue
        if blocked := await detect(page, Platform.FACEBOOK):
            return _from_checkpoint(blocked)
        return PublishResult(
            ok=False,
            needs_human=True,
            error=(
                "Clicked post but could not confirm it went up. The post MAY already be "
                "live - open the account and look before posting again."
            ),
        )

    async def _comment(self, page, variant: Variant, url: str, rng: random.Random) -> PublishResult:
        r = self.comment_recipe
        await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        if blocked := await detect(page, Platform.FACEBOOK):
            return _from_checkpoint(blocked)
        await humanize.dwell(low=4.0, high=12.0, rng=rng)

        editor = await actions.first_visible(page, r.editor)
        if editor is None:
            return _miss("the comment box", r.editor)
        text = variant.body.strip()
        await humanize.type_like_person(editor, text, rng=rng)
        await humanize.dwell(low=1.0, high=3.0, rng=rng)
        if r.submit:
            submit = await actions.first_visible(page, r.submit)
            if submit is None:
                return _miss("the comment submit button", r.submit)
            await submit.click()
        else:
            await editor.press("Enter")

        needle = text[:60].strip()
        try:
            await page.wait_for_selector(f"text={needle}", timeout=15_000)
            return PublishResult(ok=True, remote_url=page.url)
        except Exception:
            pass
        if blocked := await detect(page, Platform.FACEBOOK):
            return _from_checkpoint(blocked)
        return PublishResult(
            ok=False,
            needs_human=True,
            error="Submitted the comment but it never appeared. It MAY be there - look first.",
        )


def _miss(what: str, tried: tuple[str, ...]) -> PublishResult:
    return PublishResult(ok=False, error=actions.selector_miss(what, tried))


def _from_checkpoint(blocked) -> PublishResult:
    if blocked.is_terminal:
        return PublishResult(ok=False, error=f"account suspended: {blocked.evidence}")
    return PublishResult(
        ok=False, needs_human=True, error=f"{blocked.kind.value}: {blocked.evidence}"
    )


if get_settings().facebook_enabled:
    register(FacebookBrowserAdapter())
