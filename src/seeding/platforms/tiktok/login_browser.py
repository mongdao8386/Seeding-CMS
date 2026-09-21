"""Dang nhap TikTok trong trinh duyet cua profile bang thong tin da luu - co nguoi ho tro captcha.

21/09/2026: nguoi ban giao 80/100 acc KHONG kem cookie. He thong da co san ten dang nhap, mat
khau va khoa OAuth2 cua hom thu (lay duoc ma xac minh), nen bat nguoi van hanh go tay 80 lan la
vo ly. Luong nay lam phan may lam duoc:

  1. mo trinh duyet CO CUA SO cua profile (dung fingerprint, dung proxy neu co) tai trang dang nhap;
  2. go ten dang nhap + mat khau nhu nguoi go;
  3. TikTok doi ma gui ve email -> doc ma tu hom thu (ops/mailbox.py) va dien vao;
  4. dang nhap xong -> luu cookie, hoi TikTok xem phien song khong, ghi vao dong thoi gian.

Phan may KHONG lam: captcha. Thay captcha thi luong dung yen, de nguyen cua so cho nguoi giai
(toi da HUMAN_WAIT_S), roi tu chay tiep. Khong ai giai thi job hen lai lan sau.

Moi lan chi MOT cua so dang nhap mo (worker khoa "lock:login-window") va cac luot cach nhau
vai phut: mot loat dang nhap don dap tu mot may la dau vet ro nhat co the tao ra.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser import actions, humanize
from seeding.browser.session import open_profile
from seeding.domain import profiles as profiles_mod
from seeding.domain.models import (
    Account,
    ActivityJob,
    Platform,
    Profile,
    SessionEventKind,
)
from seeding.ops import mailbox
from seeding.platforms.base import InteractResult, mark_browser, register_login
from seeding.platforms.outreach import direct_ok, ensure_proxy_loaded
from seeding.platforms.tiktok.health import account_state
from seeding.platforms.tiktok.web import ORIGIN

log = structlog.get_logger(__name__)

LOGIN_URL = f"{ORIGIN}/login/phone-or-email/email"
# Cho trang dang nhap hien o nhap (qua proxy dan cu co the mat vai phut).
FORM_TIMEOUT_MS = 300_000
# Sau khi bam Dang nhap: cho toi da tung nay giay cho ca qua trinh (ma email, nguoi giai captcha).
HUMAN_WAIT_S = 360
# Thu lay ma tu hom thu toi da tung nay giay ke tu luc o nhap ma hien ra.
CODE_WAIT_S = 150
POLL_S = 2.5


@dataclass(frozen=True, slots=True)
class LoginRecipe:
    username: tuple[str, ...] = ("input[name='username']",)
    password: tuple[str, ...] = ("input[type='password']",)
    submit: tuple[str, ...] = ("button[data-e2e='login-button']", "button[type='submit']")
    # Buoc ma xac minh gui ve email.
    code_input: tuple[str, ...] = (
        "input[autocomplete='one-time-code']",
        "input[placeholder*='6-digit' i]",
        "input[placeholder*='digit' i]",
        "input[placeholder*='code' i]",
        "input[placeholder*='mã' i]",
        "input[maxlength='6']",
    )
    send_code: tuple[str, ...] = (
        "button[data-e2e='send-code-button']",
        "button:has-text('Send code')",
        "button:has-text('Gửi mã')",
    )
    code_submit: tuple[str, ...] = (
        "button[data-e2e='login-button']",
        "button[type='submit']",
        "button:has-text('Next')",
        "button:has-text('Tiếp')",
        "button:has-text('Submit')",
    )
    logged_in: tuple[str, ...] = (
        "[data-e2e='profile-icon']",
        "[data-e2e='nav-profile']",
    )
    # Tu do 08/09 (id "-main-page" thay tan mat) + bo chon cua cac du an ma nguon mo con duoc
    # bao tri (04/2025): TikTok co CA lop gach ngang lan gach duoi, nen so theo tien to.
    captcha: tuple[str, ...] = (
        "#captcha-verify-container-main-page",
        "[id^='captcha-verify-container']",
        "[class*='captcha-verify']",
        "[class*='captcha_verify']",
        ".captcha-disable-scroll",
        "#captcha-verify-image",
        ".secsdk-captcha-drag-icon",
        "#tiktok-verify-ele",
        "#captcha_container",
        "iframe[src*='captcha']",
    )
    # Dong bao loi ngay duoi form (thuoc tinh type="error" la cua rieng TikTok).
    error_box: tuple[str, ...] = ("div[type='error']", "span[type='error']", "[role='alert']")


RECIPE = LoginRecipe()

# Chu tren trang (chu thuong) -> (ly do, co thu lai duoc khong).
ERRORS: tuple[tuple[str, str, bool], ...] = (
    # Ma email bi tu choi KHONG phai sai mat khau: dung truoc cac dong "incorrect" ben duoi.
    ("code is incorrect", "TikTok không nhận mã email - sẽ thử lại", True),
    ("code has expired", "mã email đã hết hạn - sẽ thử lại", True),
    ("mã xác minh không", "TikTok không nhận mã email - sẽ thử lại", True),
    ("match our records", "sai tên đăng nhập hoặc mật khẩu", False),
    ("account or password is incorrect", "sai tên đăng nhập hoặc mật khẩu", False),
    ("mật khẩu không chính xác", "sai tên đăng nhập hoặc mật khẩu", False),
    ("số lần thử tối đa", "TikTok báo thử quá nhiều lần - thử lại sau", True),
    ("login expired", "TikTok báo phiên đăng nhập hết hạn - sẽ thử lại", True),
    ("password is incorrect", "sai mật khẩu", False),
    ("incorrect account or password", "sai tên đăng nhập hoặc mật khẩu", False),
    ("không khớp", "sai tên đăng nhập hoặc mật khẩu", False),
    ("mật khẩu không đúng", "sai mật khẩu", False),
    ("account doesn't exist", "tài khoản không tồn tại", False),
    ("maximum number of attempts", "TikTok báo thử quá nhiều lần - thử lại sau", True),
    ("too many attempts", "TikTok báo thử quá nhiều lần - thử lại sau", True),
    ("quá nhiều lần", "TikTok báo thử quá nhiều lần - thử lại sau", True),
    ("try again later", "TikTok bảo thử lại sau", True),
    ("was banned", "tài khoản đã bị khoá", False),
    ("permanently banned", "tài khoản đã bị khoá", False),
    ("account was suspended", "tài khoản đã bị khoá", False),
    ("đã bị cấm", "tài khoản đã bị khoá", False),
)


def page_error(text: str) -> tuple[str, bool] | None:
    low = (text or "").lower()
    for needle, reason, retryable in ERRORS:
        if needle in low:
            return reason, retryable
    return None


async def _logged_in(page, context, recipe: LoginRecipe) -> bool:
    # Con o trang /login (form, captcha, o nhap ma) thi chua vao - du trang co ve gi di nua.
    url = str(getattr(page, "url", "") or "")
    if "/login" in url:
        return False
    if await actions.present(page, recipe.logged_in):
        return True
    try:
        cookies = await context.cookies(ORIGIN)
    except Exception:
        return False
    return any(c.get("name") == "sessionid" and c.get("value") for c in cookies)


async def _body_text(page, recipe: LoginRecipe = RECIPE) -> str:
    """Chu cua dong bao loi neu co (it nham), khong thi ca trang."""
    box = await actions.first_visible(page, recipe.error_box, timeout_ms=300)
    if box is not None:
        try:
            text = (await box.inner_text())[:600]
            if text.strip():
                return text
        except Exception:
            pass
    try:
        return (await page.inner_text("body"))[:6000]
    except Exception:
        return ""


async def run(
    session: AsyncSession,
    profile: Profile,
    job: ActivityJob,
    *,
    open=open_profile,
    rng: random.Random | None = None,
    sleep=asyncio.sleep,
    recipe: LoginRecipe = RECIPE,
    fetch_code=None,
    human_wait_s: int = HUMAN_WAIT_S,
) -> InteractResult:
    rng = rng or random.Random()
    fetch_code = fetch_code or mailbox.fetch_code
    account: Account = job.account
    await ensure_proxy_loaded(session, profile)
    if profile is None:
        return InteractResult(False, "acc chưa có profile")
    if profile.proxy is None and not direct_ok(job):
        return InteractResult(False, "chưa có proxy (no proxy) - không đăng nhập bằng IP máy chủ")

    secrets = account.get_secrets() or {}
    identifier = (secrets.get("username") or secrets.get("recovery_email") or "").strip()
    password = (secrets.get("password") or "").strip()
    if not identifier or not password:
        return InteractResult(
            False, "chưa lưu tên đăng nhập / mật khẩu cho acc này (thẻ Thông tin đăng nhập)"
        )

    saw_captcha = False
    try:
        # Luon CO CUA SO: gap captcha thi nguoi van hanh giai ngay trong cua so nay.
        async with open(profile, headless=False, humanize=True) as (_b, context):
            page = await context.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=FORM_TIMEOUT_MS)

            if await _logged_in(page, context, recipe):
                return await _finish(session, profile, context, "đã đăng nhập sẵn, lưu lại cookie")

            user_box = await actions.wait_visible(page, recipe.username, timeout_ms=FORM_TIMEOUT_MS)
            if user_box is None:
                if await _logged_in(page, context, recipe):
                    return await _finish(session, profile, context, "đã đăng nhập sẵn")
                return InteractResult(
                    False, "trang đăng nhập không hiện ô nhập (proxy chậm?) - sẽ thử lại", True
                )
            await humanize.dwell(low=1.0, high=2.5, rng=rng, sleep=sleep)
            await humanize.type_like_person(user_box, identifier, rng=rng, sleep=sleep)
            pass_box = await actions.first_visible(page, recipe.password)
            if pass_box is None:
                return InteractResult(False, actions.selector_miss("ô mật khẩu", recipe.password))
            await humanize.dwell(low=0.4, high=1.2, rng=rng, sleep=sleep)
            await humanize.type_like_person(pass_box, password, rng=rng, sleep=sleep)
            await humanize.dwell(low=0.6, high=1.6, rng=rng, sleep=sleep)
            button = await actions.first_visible(page, recipe.submit)
            if button is None:
                return InteractResult(False, actions.selector_miss("nút đăng nhập", recipe.submit))
            await button.click(timeout=10_000)

            started = time.monotonic()
            code_seen_at: float | None = None
            code_typed = False
            last_code_try = 0.0
            while time.monotonic() - started < human_wait_s:
                await sleep(POLL_S)
                if await _logged_in(page, context, recipe):
                    note = "đăng nhập bằng mật khẩu đã lưu"
                    if code_typed:
                        note += ", mã lấy từ email"
                    if saw_captcha:
                        note += ", captcha do người giải"
                    return await _finish(session, profile, context, note)

                if await actions.present(page, recipe.captcha):
                    if not saw_captcha:
                        log.info("tiktok_login.captcha_waiting_for_human", handle=account.handle)
                    saw_captcha = True
                    continue  # may khong giai captcha: de nguyen cho nguoi

                found = page_error(await _body_text(page, recipe))
                if found is not None:
                    reason, retryable = found
                    return InteractResult(False, reason, retryable=retryable)

                code_box = await actions.first_visible(page, recipe.code_input, timeout_ms=500)
                if code_box is None or code_typed:
                    continue
                now = time.monotonic()
                if code_seen_at is None:
                    code_seen_at = now
                    sender = await actions.first_visible(page, recipe.send_code, timeout_ms=500)
                    if sender is not None:
                        await sender.click(timeout=10_000)
                if now - code_seen_at > CODE_WAIT_S or now - last_code_try < 10:
                    continue
                last_code_try = now
                try:
                    found_code = await fetch_code(secrets, platform="tiktok", since_minutes=10)
                except mailbox.MailboxError as exc:
                    await _keep_token(session, account, getattr(exc, "new_refresh_token", None))
                    continue  # thu chua toi: thu lai sau 10 giay
                await _keep_token(session, account, found_code.new_refresh_token)
                secrets = account.get_secrets() or secrets
                await humanize.type_like_person(code_box, found_code.code, rng=rng, sleep=sleep)
                code_typed = True
                await humanize.dwell(low=0.5, high=1.2, rng=rng, sleep=sleep)
                go = await actions.first_visible(page, recipe.code_submit, timeout_ms=1_500)
                if go is not None:
                    await go.click(timeout=10_000)

            if saw_captcha:
                return InteractResult(
                    False,
                    f"captcha hiện ra, không ai giải trong {human_wait_s // 60} phút - sẽ thử lại; "
                    "hãy ngồi cạnh máy khi các lượt đăng nhập chạy",
                    retryable=True,
                )
            if code_seen_at is not None and not code_typed:
                return InteractResult(
                    False,
                    "TikTok đòi mã email nhưng không đọc được mã từ hộp thư - sẽ thử lại",
                    retryable=True,
                )
            return InteractResult(
                False, "bấm đăng nhập xong nhưng trang không vào được - sẽ thử lại", retryable=True
            )
    except Exception as exc:
        text = " ".join(str(exc).split())[:200].encode("ascii", "backslashreplace").decode()
        log.warning("tiktok_login.failed", handle=account.handle, error=type(exc).__name__)
        return InteractResult(False, f"{type(exc).__name__}: {text}", retryable=True)


async def _keep_token(session: AsyncSession, account: Account, new_token: str | None) -> None:
    """Microsoft xoay refresh token moi lan dung: ghi cai moi vao ket ngay."""
    if not new_token:
        return
    data = account.get_secrets() or {}
    data["mail_refresh_token"] = new_token
    account.set_secrets(data)
    await session.commit()


async def _finish(session: AsyncSession, profile: Profile, context, note: str) -> InteractResult:
    """Luu cookie, hoi TikTok xem phien vua tao co song khong, ghi su kien dang nhap."""
    await asyncio.sleep(3)  # de trang ghi not cookie phien
    state = await context.storage_state()
    await profiles_mod.save_cookies(session, profile, state)
    profile.last_login_at = datetime.now(UTC)
    await profiles_mod.record_event(session, profile, SessionEventKind.LOGIN, note, commit=False)
    await session.commit()
    try:
        alive, detail = await account_state(profile)
    except Exception as exc:
        alive, detail = True, f"chưa kiểm được phiên ({type(exc).__name__})"
    await profiles_mod.mark_health(session, profile, alive, detail=detail)
    if not alive:
        return InteractResult(False, f"đăng nhập xong nhưng TikTok báo {detail}", retryable=True)
    return InteractResult(True, f"{note}; {detail}")


register_login(Platform.TIKTOK, run)
mark_browser(Platform.TIKTOK)
