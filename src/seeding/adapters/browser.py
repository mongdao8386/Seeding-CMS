"""Adapter dang bai bang trinh duyet that.

Cai dat cung giao dien voi RedditAdapter, nen planner, scheduler va rate governor
khong phai biet su khac nhau.

CANH BAO VE SELECTOR: cac chuoi selector duoi day la diem xuat phat, KHONG phai da
kiem chung. Threads va X doi DOM lien tuc, va khong the xac minh chung neu khong co
tai khoan that. Chung duoc gom thanh bang khai bao o mot cho de sua nhanh, va adapter
that bai on ao voi danh sach nhung gi da thu - khong bao gio "im lang khong dang gi"
roi bao thanh cong.

Cach kiem chung khi ban co tai khoan that:
    python scripts/try_post.py threads <handle> "noi dung thu"
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

import structlog

from seeding.adapters.base import PublishResult, register
from seeding.browser import humanize
from seeding.browser.checkpoints import detect
from seeding.browser.session import open_profile
from seeding.config import get_settings
from seeding.models import Account, Platform, Profile, Variant

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PostRecipe:
    """Cac buoc dang bai tren mot nen tang.

    Moi buoc la mot danh sach selector ung vien, thu lan luot. Nhieu ung vien vi
    giao dien doi theo A/B test va theo ngon ngu.
    """

    compose_url: str
    # Nut mo o soan. De trong neu vao trang la o soan da san.
    open_composer: tuple[str, ...]
    editor: tuple[str, ...]
    submit: tuple[str, ...]
    # Dau hieu bai da len. Thay no moi tinh la thanh cong.
    posted_signal: tuple[str, ...]
    # O chon file. De trong neu nen tang khong nhan media.
    media_input: tuple[str, ...] = ()
    # True voi nhung nen tang khong dang duoc bai chi co chu.
    media_required: bool = False

    # Doan URL cho biet bai da len. DOC LAP NGON NGU, nen no la dau hieu dang tin nhat.
    #
    # `posted_signal` o tren la chuoi chu, va chu thi doi theo ngon ngu giao dien. Do
    # that tren tai khoan that: profile chay qua proxy Viet Nam nen TikTok Studio ra
    # `lang=vi-VN`, nut la "Dang" chu khong phai "Post", va KHONG mot chuoi tieng Anh
    # nao trong posted_signal xuat hien. Hau qua khong phai la job that bai - la job
    # bao that bai TRONG KHI bai da len, roi retry va dang lan hai.
    posted_url_contains: tuple[str, ...] = ()

    # Trang nang qua proxy dan cu thi 45 giay khong du. Do that: trang upload cua
    # TikTok Studio mat 55 GIAY moi domcontentloaded.
    goto_timeout_ms: int = 45_000

    # Cho o caption hien ra sau khi dinh file - tuc la cho video upload xong. Do that:
    # 40 giay voi mot video ngan. Truoc day cho 2-5 giay roi bo cuoc.
    editor_timeout_ms: int = 15_000

    # Nen tang tu dien san chu vao o caption (TikTok dien TEN FILE). Khong xoa thi
    # caption thanh "Snaptik.app_7238655423920753925-97b98e7cTrua nay doi hoai..." -
    # vua xau vua la dau vet ro rang la file tai ve tu cho khac.
    editor_prefilled: bool = False


@dataclass(frozen=True, slots=True)
class CommentRecipe:
    """Cac buoc de lai mot binh luan duoi mot bai co san.

    Khac dang bai o mot cho quan trong: khong co compose_url co dinh. URL den tu
    `target` cua nhom, vi moi binh luan nham mot bai khac nhau.
    """

    # Nut mo o tra loi. De trong neu o nhap da san duoi bai.
    open_reply: tuple[str, ...]
    editor: tuple[str, ...]
    submit: tuple[str, ...]


COMMENT_RECIPES: dict[Platform, CommentRecipe] = {
    Platform.THREADS: CommentRecipe(
        open_reply=("div[role='button']:has-text('Reply')", "svg[aria-label='Reply']"),
        editor=("div[contenteditable='true'][role='textbox']",),
        submit=("div[role='button']:has-text('Post')", "button:has-text('Post')"),
    ),
    Platform.X: CommentRecipe(
        open_reply=("div[data-testid='reply']",),
        editor=(
            "div[data-testid='tweetTextarea_0']",
            "div[contenteditable='true'][role='textbox']",
        ),
        submit=("button[data-testid='tweetButton']", "button[data-testid='tweetButtonInline']"),
    ),
    Platform.FACEBOOK: CommentRecipe(
        open_reply=(),  # o nhap binh luan nam san duoi bai
        editor=(
            "div[contenteditable='true'][aria-label*='comment']",
            "div[contenteditable='true'][aria-label*='binh luan']",
            "div[contenteditable='true'][role='textbox']",
        ),
        submit=(),  # Facebook gui bang Enter
    ),
    Platform.INSTAGRAM: CommentRecipe(
        open_reply=(),
        editor=("textarea[aria-label*='comment']", "textarea[placeholder*='comment']"),
        submit=("div[role='button']:has-text('Post')", "button:has-text('Post')"),
    ),
    Platform.TIKTOK: CommentRecipe(
        open_reply=("[data-e2e='comment-icon']",),
        editor=(
            "div[contenteditable='true'][data-e2e='comment-input']",
            "div[contenteditable='true']",
        ),
        submit=("div[data-e2e='comment-post']", "button:has-text('Post')"),
    ),
}


RECIPES: dict[Platform, PostRecipe] = {
    Platform.THREADS: PostRecipe(
        compose_url="https://www.threads.net/",
        open_composer=(
            "[role='button']:has-text('Start a thread')",
            "svg[aria-label='Create']",
            "[aria-label='Create']",
        ),
        editor=(
            "div[contenteditable='true'][role='textbox']",
            "div[contenteditable='true']",
        ),
        submit=(
            "div[role='button']:has-text('Post')",
            "button:has-text('Post')",
        ),
        posted_signal=(
            "text=Posted",
            "text=Your thread was posted",
        ),
    ),
    Platform.X: PostRecipe(
        compose_url="https://x.com/compose/post",
        open_composer=(),  # vao thang trang soan
        editor=(
            "div[data-testid='tweetTextarea_0']",
            "div[contenteditable='true'][role='textbox']",
        ),
        submit=(
            "button[data-testid='tweetButton']",
            "button[data-testid='tweetButtonInline']",
        ),
        posted_signal=(
            "text=Your post was sent",
            "text=Your Tweet was sent",
        ),
        media_input=("input[data-testid='fileInput']", "input[type='file']"),
    ),
    Platform.FACEBOOK: PostRecipe(
        compose_url="https://www.facebook.com/",
        open_composer=(
            "div[role='button']:has-text(\"What's on your mind\")",
            "div[role='button']:has-text('Bạn đang nghĩ gì')",
        ),
        editor=(
            "div[contenteditable='true'][role='textbox']",
            "div[aria-label*='mind']",
        ),
        submit=(
            "div[aria-label='Post']",
            "div[aria-label='Đăng']",
            "button:has-text('Post')",
        ),
        posted_signal=("text=Your post is now live", "text=Bài viết của bạn"),
        media_input=("input[type='file'][accept*='image']", "input[type='file']"),
    ),
    Platform.INSTAGRAM: PostRecipe(
        compose_url="https://www.instagram.com/",
        open_composer=(
            "svg[aria-label='New post']",
            "a[href='#'][role='link']:has(svg[aria-label='New post'])",
        ),
        editor=("div[contenteditable='true'][role='textbox']",),
        submit=("div[role='button']:has-text('Share')", "button:has-text('Share')"),
        posted_signal=("text=Your post has been shared", "text=Post shared"),
        media_input=("input[type='file'][accept*='image']", "input[type='file']"),
        media_required=True,
    ),
    # Cong thuc nay da duoc do tren trang that (tai khoan that, proxy Viet Nam that).
    # Xem ghi chu tung dong - moi gia tri o day deu sua mot thu da quan sat duoc.
    Platform.TIKTOK: PostRecipe(
        compose_url="https://www.tiktok.com/tiktokstudio/upload",
        open_composer=(),
        # O caption la Draft.js. Selector rieng dat truoc de khong bat nham mot
        # contenteditable khac tren trang.
        editor=(
            "div.public-DraftEditor-content[contenteditable='true']",
            "div[contenteditable='true']",
        ),
        # `data-e2e` truoc chu KHONG phai text: giao dien ra tieng Viet, nut ten la
        # "Dang". Selector theo chu chi la luoi do phong khi TikTok bo data-e2e.
        submit=(
            "button[data-e2e='post_video_button']",
            "button:has-text('Đăng')",
            "button:has-text('Post')",
        ),
        posted_url_contains=("/tiktokstudio/content",),
        posted_signal=(
            "text=Video của bạn đang được tải lên",
            "text=Your video is being uploaded",
            "text=Quản lý bài đăng",
            "text=Manage your posts",
        ),
        # `accept*='video'` KHONG ton tai tren trang do - o chon file khong khai accept.
        # De no dung dau chi ton them 15 giay timeout roi van phai roi xuong cai sau.
        media_input=("input[type='file']",),
        media_required=True,
        # 300 giay khong phai la du phong - la con so do duoc. Trang upload cua TikTok
        # keo 38 file JS/CSS tu CDN, va qua proxy dan cu moi file mat trung binh 101
        # GIAY. Do that cung mot trang, cung mot proxy: 17s khong proxy, 90-250s qua
        # proxy. He nay khong can nhanh - moi tai khoan dang 3 bai mot ngay, giai deu -
        # nen cho 4 phut la chap nhan duoc, con bo cuoc o giay thu 120 thi khong bao
        # gio dang duoc bai nao.
        goto_timeout_ms=300_000,
        editor_timeout_ms=180_000,
        editor_prefilled=True,
    ),
}


class BrowserAdapter:
    """Mot instance cho moi nen tang."""

    def __init__(
        self,
        platform: Platform,
        recipe: PostRecipe,
        comment_recipe: CommentRecipe | None = None,
    ) -> None:
        self.platform = platform
        self.recipe = recipe
        self.comment_recipe = comment_recipe

    async def publish(
        self,
        account: Account,
        variant: Variant,
        target: dict,
        *,
        profile: Profile | None = None,
    ) -> PublishResult:
        if profile is None:
            return PublishResult(
                ok=False,
                error=f"{account.handle}: no profile yet. Create one on the Accounts screen.",
            )
        if not profile.cookies_enc:
            return PublishResult(
                ok=False,
                needs_human=True,
                error=(
                    f"{account.handle} has never signed in. Run: "
                    f"python scripts/login_profile.py {self.platform.value} {account.handle}"
                ),
            )

        kind = (target.get("kind") or "post").lower()
        if kind == "comment":
            problem = self._comment_precheck(variant, target)
            if problem is not None:
                return problem

        rng = random.Random()
        try:
            headless = get_settings().headless_jobs
            async with open_profile(profile, headless=headless, humanize=True) as (_b, context):
                page = await context.new_page()
                if kind == "comment":
                    return await self._comment(page, variant, target["url"], rng)
                return await self._post(page, variant, rng)
        except Exception as exc:
            # Loi mo trinh duyet hoac proxy chet - thu lai co ich.
            log.warning("browser.publish.failed", handle=account.handle, error=str(exc))
            return PublishResult(ok=False, retryable=True, error=f"{type(exc).__name__}: {exc}")

    async def _post(self, page, variant: Variant, rng: random.Random) -> PublishResult:
        r = self.recipe

        if r.media_required and not variant.media_variant_ref:
            return PublishResult(
                ok=False,
                retryable=False,
                error=(
                    f"{self.platform.value} cannot post text alone. "
                    "Attach a media file to the content first."
                ),
            )

        await page.goto(r.compose_url, wait_until="domcontentloaded", timeout=r.goto_timeout_ms)

        if blocked := await detect(page, self.platform):
            return _from_checkpoint(blocked)

        # Xem feed truoc da. Vao trang la dang ngay roi thoat la mau hinh bot ro nhat.
        await humanize.warm_up(page, rng=rng)

        if r.open_composer:
            opener = await _first_visible(page, r.open_composer)
            if opener is None:
                return _selector_miss("the composer button", r.open_composer)
            await opener.click()
            await humanize.dwell(low=0.8, high=2.0, rng=rng)

        # Dinh media truoc khi go chu: nen tang nao cung phai xu ly file xong moi bat
        # o nhap mo ta, va nhieu trang con doi hoan toan giao dien sau buoc nay.
        if variant.media_variant_ref and r.media_input:
            attached = await _attach_media(page, r.media_input, variant.media_variant_ref)
            if attached is not None:
                return attached

        # Cho o soan hien ra. Voi nen tang co media day la cho VIDEO UPLOAD XONG, va do
        # that qua proxy dan cu la ~40 giay - khong phai vai giay nhu truoc kia cho.
        editor = await _wait_visible(page, r.editor, r.editor_timeout_ms)
        if editor is None:
            return _selector_miss("the text editor", r.editor)

        # Xoa chu co san truoc khi go, neu khong chu moi se noi duoi chu cu.
        if r.editor_prefilled:
            await _clear(editor)

        text = f"{variant.title}\n\n{variant.body}".strip() if variant.body else variant.title
        await humanize.type_like_person(editor, text, rng=rng)
        await humanize.dwell(low=1.0, high=3.0, rng=rng)  # doc lai truoc khi bam dang

        submit = await _first_visible(page, r.submit)
        if submit is None:
            return _selector_miss("the post button", r.submit)
        await submit.click()

        return await self._confirm(page, rng)

    def _comment_precheck(self, variant: Variant, target: dict) -> PublishResult | None:
        """Chan nhung viec chac chan hong TRUOC khi mo trinh duyet.

        Mo mot phien Camoufox ton ~400MB va vai chuc giay. Bao loi cau hinh sau khi da
        mo la lang phi ca hai, va no con lam ban nhat ky vong doi phien.
        """
        if self.comment_recipe is None:
            return PublishResult(
                ok=False,
                error=f"No comment recipe for {self.platform.value} yet.",
            )
        if not target.get("url"):
            return PublishResult(ok=False, error="target is missing 'url' to comment on")
        if not (variant.body or "").strip():
            return PublishResult(
                ok=False,
                error=(
                    "A comment needs body text - a title alone has nowhere to go in a comment. "
                    "Put the text in the body template."
                ),
            )
        return None

    async def _comment(self, page, variant: Variant, url: str, rng: random.Random) -> PublishResult:
        r = self.comment_recipe
        assert r is not None  # _comment_precheck da chan truong hop None

        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)

        if blocked := await detect(page, self.platform):
            return _from_checkpoint(blocked)

        # Doc bai truoc khi tra loi. Vao thang roi go ngay la nhip khong nguoi that nao co.
        await humanize.dwell(low=4.0, high=12.0, rng=rng)

        if r.open_reply:
            opener = await _first_visible(page, r.open_reply)
            if opener is None:
                return _selector_miss("the reply button", r.open_reply)
            await opener.click()
            await humanize.dwell(low=0.8, high=2.0, rng=rng)

        editor = await _first_visible(page, r.editor)
        if editor is None:
            return _selector_miss("the comment box", r.editor)

        text = variant.body.strip()
        await humanize.type_like_person(editor, text, rng=rng)
        await humanize.dwell(low=1.0, high=3.0, rng=rng)

        if r.submit:
            submit = await _first_visible(page, r.submit)
            if submit is None:
                return _selector_miss("the comment submit button", r.submit)
            await submit.click()
        else:
            # Khong co nut rieng thi nen tang gui bang Enter (Facebook lam vay).
            await editor.press("Enter")

        return await self._confirm_comment(page, text)

    async def _confirm_comment(self, page, text: str) -> PublishResult:
        """Binh luan len roi thi chinh no hien ra trong trang.

        Khong dung posted_signal nhu dang bai: phan lon nen tang khong bao gi ca khi
        binh luan thanh cong. Doi thay chinh doan chu vua go moi la dau hieu that, va
        no khong phu thuoc vao ngon ngu giao dien.
        """
        # Du dai de khong trung thu khac tren trang, du ngan de khong dinh phai cho
        # nen tang cat bot bang "... See more".
        needle = text[:60].strip()
        try:
            await page.wait_for_selector(f"text={needle}", timeout=15_000)
            return PublishResult(ok=True, remote_url=page.url)
        except Exception:
            pass

        if blocked := await detect(page, self.platform):
            return _from_checkpoint(blocked)

        # Nhu _confirm: da gui roi thi khong duoc tu dong thu lai, se thanh hai binh luan.
        return PublishResult(
            ok=False,
            needs_human=True,
            error=(
                "Submitted the comment but it never appeared on the page. It MAY already be "
                "there - open the post and look before commenting again."
            ),
        )

    async def _confirm(self, page, rng: random.Random) -> PublishResult:
        """Khong tin la da dang cho toi khi thay dau hieu that.

        Bao thanh cong nham nguy hiem hon bao that bai nham: job se khong duoc thu lai,
        va ban tuong bai da len trong khi no chua bao gio len.
        """
        r = self.recipe

        # URL truoc chu. Chuyen trang la dau hieu khong phu thuoc ngon ngu giao dien,
        # ma giao dien thi ra theo ngon ngu cua proxy chu khong phai tieng Anh.
        if r.posted_url_contains:
            try:
                await page.wait_for_url(
                    lambda url: any(frag in url for frag in r.posted_url_contains),
                    timeout=90_000,
                )
                return PublishResult(ok=True, remote_url=page.url)
            except Exception:
                pass

        for signal in r.posted_signal:
            try:
                await page.wait_for_selector(signal, timeout=12_000)
                return PublishResult(ok=True, remote_url=page.url)
            except Exception:
                continue

        if blocked := await detect(page, self.platform):
            return _from_checkpoint(blocked)

        # Da BAM dang roi ma khong biet ket qua ra sao. Day KHONG duoc retry tu dong:
        # neu bai da len that thi lan thu hai dang them mot bai nua len tai khoan that,
        # va khong go lai duoc. Day sang hang doi cho nguoi mo ra nhin.
        return PublishResult(
            ok=False,
            needs_human=True,
            error=(
                "Clicked post but could not confirm it went up (looked for "
                f"{list(r.posted_url_contains) + list(r.posted_signal)}). The post MAY "
                "already be live - open the account and look before posting again."
            ),
        )


async def _attach_media(page, selectors: tuple[str, ...], path: str) -> PublishResult | None:
    """Dinh file vao o chon file. Tra ve None neu xong xuoi, PublishResult neu hong.

    O chon file cua cac nen tang thuong bi an di sau mot nut tu ve, nen khong dung
    _first_visible o day - set_input_files chay duoc voi ca input dang an.
    """
    if not Path(path).exists():
        return PublishResult(
            ok=False, retryable=False, error=f"rendered media file is missing: {path}"
        )

    for selector in selectors:
        try:
            await page.locator(selector).first.set_input_files(path, timeout=15_000)
            return None
        except Exception:
            continue

    return _selector_miss("the file input", selectors)


async def _first_visible(page, selectors: tuple[str, ...], timeout_ms: int = 4_000):
    """Selector dau tien thuc su hien tren trang. None neu khong cai nao khop."""
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=timeout_ms):
                return locator
        except Exception:
            continue
    return None


async def _wait_visible(page, selectors: tuple[str, ...], timeout_ms: int):
    """Cho den khi mot trong cac selector hien ra. None neu het gio.

    Khac `_first_visible` o cho no QUAY VONG qua ca danh sach nhieu lan thay vi cho
    that lau o cai dau tien. Quan trong khi cai dau la selector rieng cua nen tang va
    cai sau la luoi do chung: cho 3 phut o cai rieng roi moi thu cai chung la hong,
    con quay vong thi cai nao hien ra truoc lay cai do.
    """
    import time

    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        # Chia deu cho cac selector, nhung moi lan thu khong duoi 1 giay va khong qua 3.
        per = max(1.0, min(3.0, remaining / max(len(selectors), 1)))
        found = await _first_visible(page, selectors, timeout_ms=int(per * 1000))
        if found is not None:
            return found


async def _clear(locator) -> None:
    """Xoa sach o soan. Chay duoc voi ca <textarea> lan contenteditable.

    Khong dung `fill("")`: Draft.js - thu ma TikTok dung cho o caption - bo qua viec
    dat value truc tiep. Chon het roi xoa la duong duy nhat di qua ban phim, va do
    cung la duong ma nguoi that di.
    """
    await locator.click()
    await locator.press("ControlOrMeta+a")
    await locator.press("Delete")


def _selector_miss(what: str, tried: tuple[str, ...]) -> PublishResult:
    """Khong khop selector la LOI CODE, khong phai loi tai khoan.

    Khong danh needs_human: nguoi van hanh mo trinh duyet ra cung khong sua duoc gi,
    thu can sua la bang RECIPES.
    """
    return PublishResult(
        ok=False,
        retryable=False,
        error=(
            f"Could not find {what}. Tried: {list(tried)}. "
            "The platform changed its interface - update RECIPES in adapters/browser.py."
        ),
    )


def _from_checkpoint(blocked) -> PublishResult:
    if blocked.is_terminal:
        # Bi khoa han thi nguoi cung khong cuu duoc - dung lam ban hang doi.
        return PublishResult(
            ok=False, retryable=False, error=f"account suspended: {blocked.evidence}"
        )
    return PublishResult(
        ok=False, needs_human=True, error=f"{blocked.kind.value}: {blocked.evidence}"
    )


for _platform, _recipe in RECIPES.items():
    register(BrowserAdapter(_platform, _recipe, COMMENT_RECIPES.get(_platform)))
