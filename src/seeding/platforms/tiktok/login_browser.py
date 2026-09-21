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
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.browser import actions, humanize, winfocus
from seeding.browser.session import open_profile
from seeding.config import get_settings
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
# Chua thay thu moi sau tung nay giay thi bam gui lai ma MOT lan.
RESEND_AFTER_S = 60
# Dong ho hop thu va may nay lech nhau chut it: ma den truoc moc nay moi bi coi la ma cu.
CODE_CLOCK_SKEW = timedelta(seconds=90)
POLL_S = 2.5


@dataclass(frozen=True, slots=True)
class LoginRecipe:
    """Bo chon lay tu: trang that (form, 21/09), anh chup cua nguoi van hanh (hop "Verify it's
    really you"), loi that trong lich su job (nut gui ma bi khoa), va tu dien + ma nguon cua chinh
    trang dang nhap TikTok (buoc nhap ma /login/2sv/email - CHUA thay tan mat)."""

    username: tuple[str, ...] = ("input[name='username']",)
    password: tuple[str, ...] = ("input[type='password']",)
    submit: tuple[str, ...] = (
        "button[data-e2e='login-button']",
        "button[data-e2e='continue-button']",
        "form button[type='submit']",
    )
    # "Verify it's really you": TikTok bat chon cach xac minh; dong Email ghi dia chi che kieu
    # a***b@hotmail.com (khong phu thuoc ngon ngu). Ba dong sau: trang 2SV mo san cach khac
    # (SMS, app) thi chuyen sang email.
    verify_email: tuple[str, ...] = (
        r"text=/^\S{0,6}\*{2,}\S{0,6}@\S+\.\S+$/",
        "[role='dialog'] >> text=/^Email$/",
        "button:has-text('Send code via email')",
        "button:has-text('Gửi mã qua email')",
        "a[href='/login/2sv/email']",
        "text=/^Email$/",
    )
    # O nhap ma: MOT o, khong phai sau o; khong co name/maxlength.
    code_input: tuple[str, ...] = (
        "input[placeholder='Enter 6-digit code']",
        "input[placeholder='Nhập mã gồm 6 chữ số']",
        "div.code-input input",
        "div[class*='DivCodeInputContainer'] input",
        "input[placeholder*='6-digit' i]",
        "input[placeholder*='chữ số' i]",
        "input[data-testid='tux-web-pin-item']",
        "input[autocomplete='one-time-code']",
        "input[placeholder*='digit' i]",
    )
    # TikTok TU gui ma khi vao buoc nay, nut nay bi khoa va dem nguoc ("Resend code: 59s").
    send_code: tuple[str, ...] = (
        "button[data-e2e='send-code-button']",
        "button:has-text('Send code')",
        "button:has-text('Resend code')",
        "button:has-text('Gửi mã')",
        "button:has-text('Gửi lại mã')",
    )
    # KHONG de "button[type='submit']" tran o day: nut Log in cua form phia sau hop thoai cung
    # khop, bam vao la dang nhap lai tu dau. Nut cua buoc ma duoc tim TRONG form cua o nhap ma
    # (_submit_code); day chi la du phong.
    code_submit: tuple[str, ...] = (
        "button[class*='StyledTwoStepButton']",
        "button:text-is('Next')",
        "button:text-is('Tiếp')",
        "button:text-is('Submit')",
    )
    logged_in: tuple[str, ...] = (
        "a[data-e2e='nav-profile'][href^='/@']",
        "[data-e2e='profile-icon']",
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
        "[data-testid='whirl-inner-img']",
        "#tiktok-verify-ele",
        "#captcha_container",
        "iframe[src*='captcha']",
    )
    # Dong bao loi ngay duoi form: <div type="error"><span role="status">...</span></div>.
    # No co the nam san trong trang voi chu RONG - doc chu, dung chi xem co mat.
    error_box: tuple[str, ...] = (
        "div[type='error'] span[role='status']",
        "div[type='error']",
        "span[role='status']",
        "[role='alert']",
    )


RECIPE = LoginRecipe()

SESSION_COOKIES = ("sessionid", "sessionid_ss", "sid_tt")

_TRY_LATER = "TikTok báo thử quá nhiều lần - thử lại sau"
_WRONG = "sai tên đăng nhập hoặc mật khẩu"
_LOCKED = "tài khoản đã bị khoá"
_BAD_CODE = "TikTok không nhận mã email - sẽ thử lại"
_DEVICE = "TikTok chặn THIẾT BỊ này (không phải khoá acc): đổi fingerprint hoặc proxy của profile"
_NEEDS_APP = "TikTok đòi xác minh bằng app / SMS - máy không làm được, cần người"

# Chu tren trang (chu thuong) -> (ly do, co thu lai duoc khong). THU TU co nghia: ma email bi tu
# choi va "thiet bi bi cam" phai dung truoc cac dong "incorrect" / "was banned" chung chung.
ERRORS: tuple[tuple[str, str, bool], ...] = (
    ("incorrect code", _BAD_CODE, True),
    ("code is incorrect", _BAD_CODE, True),
    ("expired or incorrect", _BAD_CODE, True),
    ("code has expired", _BAD_CODE, True),
    ("verification failed", _BAD_CODE, True),
    ("mã không chính xác", _BAD_CODE, True),
    ("mã xác minh không", _BAD_CODE, True),
    ("xác minh không thành công", _BAD_CODE, True),
    ("device was banned", _DEVICE, False),
    ("thiết bị của bạn đã bị cấm", _DEVICE, False),
    ("incorrect account or password", _WRONG, False),
    ("account or password is incorrect", _WRONG, False),
    ("incorrect password", "sai mật khẩu", False),
    ("password is incorrect", "sai mật khẩu", False),
    ("match our records", _WRONG, False),
    ("mật khẩu không chính xác", _WRONG, False),
    ("mật khẩu không đúng", "sai mật khẩu", False),
    ("account doesn't exist", "tài khoản không tồn tại", False),
    ("tài khoản không tồn tại", "tài khoản không tồn tại", False),
    ("maximum number of attempts", _TRY_LATER, True),
    ("too many attempts", _TRY_LATER, True),
    ("too frequently", _TRY_LATER, True),
    ("quá nhiều lần", _TRY_LATER, True),
    ("số lần thử tối đa", _TRY_LATER, True),
    ("currently suspended", _LOCKED, False),
    ("account was suspended", _LOCKED, False),
    ("đã bị đình chỉ", _LOCKED, False),
    ("has been locked", _LOCKED, False),
    ("đã bị khóa", _LOCKED, False),
    ("was deactivated", _LOCKED, False),
    ("đã bị hủy kích hoạt", _LOCKED, False),
    ("permanently banned", _LOCKED, False),
    ("was banned", _LOCKED, False),
    ("đã bị cấm", _LOCKED, False),
    ("continue on the tiktok app", _NEEDS_APP, False),
    ("tiếp tục trên ứng dụng tiktok", _NEEDS_APP, False),
    ("use sms verification", _NEEDS_APP, False),
    ("xác minh sms", _NEEDS_APP, False),
    ("log in with the app", _NEEDS_APP, False),
    ("đăng nhập bằng ứng dụng", _NEEDS_APP, False),
    ("your password expired", "TikTok báo mật khẩu đã hết hạn - cần người đổi mật khẩu", False),
    ("mật khẩu của bạn đã hết hạn", "TikTok báo mật khẩu đã hết hạn - cần người đổi", False),
    ("login expired", "TikTok báo phiên đăng nhập hết hạn - sẽ thử lại", True),
    ("đăng nhập đã hết hạn", "TikTok báo phiên đăng nhập hết hạn - sẽ thử lại", True),
    ("try again later", "TikTok bảo thử lại sau", True),
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
    return any(c.get("name") in SESSION_COOKIES and c.get("value") for c in cookies)


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


async def _try_click(locator, *, timeout_ms: int = 5_000) -> bool:
    """Bam neu bam duoc. Nut bi khoa (dang dem nguoc) hay bi che thi thoi, khong de
    mot cu bam hong lam hong ca luot dang nhap."""
    try:
        if not await locator.is_enabled(timeout=1_000):
            return False
        await locator.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


async def _submit_code(page, code_box, recipe: LoginRecipe) -> None:
    """Gui ma: nut submit TRONG form cua chinh o nhap ma, roi bo chon du phong, cuoi cung Enter
    (buoc nay la mot <form onSubmit>). Khong bao gio dung toi nut Log in cua form phia sau."""
    try:
        inner = code_box.locator("xpath=ancestor::form[1]//button[@type='submit']").first
        if await inner.count() and await _try_click(inner):
            return
    except Exception:
        pass
    go = await actions.first_visible(page, recipe.code_submit, timeout_ms=1_500)
    if go is not None and await _try_click(go):
        return
    try:
        await code_box.press("Enter")
    except Exception:
        pass


def _fresh(found_code, not_before: datetime | None) -> bool:
    """Ma trong thu co phai cua LAN NAY khong. Lan thu truoc that bai de lai ma cu trong hop thu;
    go ma cu la TikTok bao sai ma va tinh them mot lan thu."""
    if not_before is None or found_code.received_at is None:
        return True
    return found_code.received_at >= not_before - CODE_CLOCK_SKEW


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
    minder=None,
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
    if minder is None:
        # Truoc khi mo trinh duyet: ghi nho cua so nguoi van hanh dang dung.
        minder = winfocus.WindowMinder(enabled=get_settings().login_background)
    # Canh cua so suot phien, khong chi giua cac buoc (xem WindowMinder.watch).
    watcher = asyncio.create_task(minder.watch())
    try:
        # Luon CO CUA SO (captcha la viec cua nguoi) nhung cua so nam PHIA SAU, khong lay focus:
        # nguoi van hanh lam viec khac tren cung may, Alt+Tab thoai mai. Xem browser/winfocus.py.
        async with open(profile, headless=False, humanize=True) as (_b, context):
            page = await context.new_page()
            minder.tuck()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=FORM_TIMEOUT_MS)
            minder.tuck()

            if await _logged_in(page, context, recipe):
                return await _finish(session, profile, context, "đã đăng nhập sẵn, lưu lại cookie")

            user_box = await actions.wait_visible(page, recipe.username, timeout_ms=FORM_TIMEOUT_MS)
            if user_box is None:
                if await _logged_in(page, context, recipe):
                    return await _finish(session, profile, context, "đã đăng nhập sẵn")
                return InteractResult(
                    False, "trang đăng nhập không hiện ô nhập (proxy chậm?) - sẽ thử lại", True
                )
            minder.keep_alive()
            await humanize.dwell(low=1.0, high=2.5, rng=rng, sleep=sleep)
            await humanize.type_like_person(user_box, identifier, rng=rng, sleep=sleep)
            pass_box = await actions.first_visible(page, recipe.password)
            if pass_box is None:
                return InteractResult(False, actions.selector_miss("ô mật khẩu", recipe.password))
            minder.keep_alive()
            await humanize.dwell(low=0.4, high=1.2, rng=rng, sleep=sleep)
            await humanize.type_like_person(pass_box, password, rng=rng, sleep=sleep)
            await humanize.dwell(low=0.6, high=1.6, rng=rng, sleep=sleep)
            button = await actions.first_visible(page, recipe.submit)
            if button is None:
                return InteractResult(False, actions.selector_miss("nút đăng nhập", recipe.submit))
            minder.keep_alive()
            await button.click(timeout=10_000)

            started = time.monotonic()
            code_seen_at: float | None = None
            code_requested_at: datetime | None = None
            code_typed = False
            last_code_try = 0.0
            resent = False
            method_clicks = 0
            last_method_click = 0.0
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
                    minder.surface()  # len tren cung + nhay + keu; may khong giai captcha
                    continue
                if minder.surfaced:
                    minder.tuck()  # nguoi giai xong: lui ve phia sau
                minder.keep_alive()

                found = page_error(await _body_text(page, recipe))
                if found is not None:
                    reason, retryable = found
                    return InteractResult(False, reason, retryable=retryable)

                url = str(getattr(page, "url", "") or "")
                wrong_method = "/login/2sv/" in url and "/2sv/email" not in url
                code_box = (
                    None
                    if wrong_method
                    else await actions.first_visible(page, recipe.code_input, timeout_ms=500)
                )
                if code_box is None:
                    # "Verify it's really you": TikTok bat chon cach xac minh truoc khi gui ma.
                    now = time.monotonic()
                    if method_clicks < 3 and now - last_method_click > 12:
                        method = await actions.first_visible(
                            page, recipe.verify_email, timeout_ms=500
                        )
                        if method is not None:
                            code_requested_at = code_requested_at or datetime.now(UTC)
                            last_method_click = now
                            method_clicks += 1
                            clicked = await _try_click(method)
                            log.info(
                                "tiktok_login.verify_by_email", handle=account.handle, ok=clicked
                            )
                    continue
                if code_typed:
                    continue
                now = time.monotonic()
                if code_seen_at is None:
                    code_seen_at = now
                    code_requested_at = code_requested_at or datetime.now(UTC)
                    sender = await actions.first_visible(page, recipe.send_code, timeout_ms=500)
                    if sender is not None:
                        # Nut bi khoa = TikTok da tu gui ma va dang dem nguoc: khong can bam.
                        await _try_click(sender)
                if not resent and now - code_seen_at > RESEND_AFTER_S:
                    sender = await actions.first_visible(page, recipe.send_code, timeout_ms=500)
                    resent = sender is not None and await _try_click(sender)
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
                if not _fresh(found_code, code_requested_at):
                    continue  # ma cua lan thu truoc: doi thu moi
                minder.keep_alive()
                try:
                    await humanize.type_like_person(code_box, found_code.code, rng=rng, sleep=sleep)
                except Exception:
                    # O nhap ma kieu 6 o roi / o an: go thang vao trang, focus da nam san o do.
                    await page.keyboard.type(found_code.code, delay=120)
                code_typed = True
                await humanize.dwell(low=0.5, high=1.2, rng=rng, sleep=sleep)
                await _submit_code(page, code_box, recipe)

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
        text = " ".join(str(exc).split())[:400].encode("ascii", "backslashreplace").decode()
        log.warning("tiktok_login.failed", handle=account.handle, error=type(exc).__name__)
        return InteractResult(False, f"{type(exc).__name__}: {text}", retryable=True)
    finally:
        watcher.cancel()


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
