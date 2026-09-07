"""Mo trinh duyet Camoufox voi dung danh tinh cua mot profile.

Ba thu luon di cung nhau va khong bao gio tach roi:
    fingerprint da ghim  +  proxy co dinh  +  cookie jar da luu

`geoip=True` de Camoufox tu suy timezone va ngon ngu tu IP that cua proxy. Tu doan
timezone la cach de tao mau thuan nhat: mot may khai Windows/My ma dong ho Ha Noi
thi tu no lo ra.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

import structlog
from camoufox.async_api import AsyncCamoufox

from seeding.config import get_settings
from seeding.models import Platform, Profile

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SessionProbe:
    """Cach kiem tra mot phien con song hay khong.

    Dung chuyen huong lam tin hieu thay vi do selector: trang nao cung day nguoi
    chua dang nhap ve trang dang nhap, con selector thi doi theo moi lan nen tang
    doi giao dien.
    """

    url: str
    logged_out_markers: tuple[str, ...]
    login_url: str
    # Noi de "song" ma khong dang gi - dung cho job hoat dong nen.
    feed_url: str

    # Endpoint NHE tra ve JSON noi ro dang la ai. Uu tien dung no thay vi tai ca trang.
    #
    # Ly do do bang so: trang chu TikTok nang ~400KB. Do tren proxy dan cu Viet Nam
    # that: trang chu mat 23 GIAY hoac timeout han, con endpoint nay tra loi trong
    # ~1 giay. Dung trang chu de kiem suc khoe nghia la vong quet moi tieng se bao
    # phien chet vi PROXY CHAM, roi day ca doi tai khoan vao hang doi cho nguoi - voi
    # mot ly do khong dung.
    #
    # De trong thi quay ve cach cu: tai trang va xem co bi day ve trang dang nhap khong.
    info_url: str | None = None
    # Chuoi phai CO trong phan hoi thi moi tinh la con dang nhap.
    info_signed_in: tuple[str, ...] = ()
    # Chuoi bao la da het phien.
    info_signed_out: tuple[str, ...] = ()


PROBES: dict[Platform, SessionProbe] = {
    Platform.REDDIT: SessionProbe(
        url="https://www.reddit.com/settings/",
        logged_out_markers=("/login", "/account/login"),
        login_url="https://www.reddit.com/login/",
        feed_url="https://www.reddit.com/",
    ),
    Platform.THREADS: SessionProbe(
        url="https://www.threads.net/",
        logged_out_markers=("/login",),
        login_url="https://www.threads.net/login/",
        feed_url="https://www.threads.net/",
    ),
    Platform.X: SessionProbe(
        url="https://x.com/home",
        logged_out_markers=("/i/flow/login", "/login", "x.com/?"),
        login_url="https://x.com/i/flow/login",
        feed_url="https://x.com/home",
    ),
    Platform.FACEBOOK: SessionProbe(
        url="https://www.facebook.com/me",
        logged_out_markers=("/login", "checkpoint"),
        login_url="https://www.facebook.com/login/",
        feed_url="https://www.facebook.com/",
    ),
    Platform.INSTAGRAM: SessionProbe(
        url="https://www.instagram.com/accounts/edit/",
        logged_out_markers=("/accounts/login", "challenge"),
        login_url="https://www.instagram.com/accounts/login/",
        feed_url="https://www.instagram.com/",
        info_url="https://www.instagram.com/api/v1/accounts/edit/web_form_data/",
        info_signed_in=('"username"',),
        info_signed_out=("login_required", "Please wait a few minutes"),
    ),
    Platform.TIKTOK: SessionProbe(
        url="https://www.tiktok.com/tiktokstudio/upload",
        logged_out_markers=("/login", "/signup"),
        login_url="https://www.tiktok.com/login/",
        feed_url="https://www.tiktok.com/foryou",
        # Do tren proxy dan cu Viet Nam that: trang chu TikTok nang ~400KB va mat 23
        # GIAY hoac timeout han, con endpoint nay tra loi trong ~1 giay va noi thang
        # dang la ai. Dung trang chu de kiem suc khoe nghia la vong quet moi tieng se
        # bao phien chet vi PROXY CHAM, roi day ca doi vao hang doi cho nguoi.
        info_url="https://www.tiktok.com/passport/web/account/info/",
        info_signed_in=('"user_id"',),
        info_signed_out=("session_expired", "session expired"),
    ),
    Platform.YOUTUBE: SessionProbe(
        url="https://www.youtube.com/account",
        logged_out_markers=("accounts.google.com", "/signin"),
        login_url="https://accounts.google.com/ServiceLogin?service=youtube",
        feed_url="https://www.youtube.com/",
    ),
}


def launch_options(profile: Profile, *, headless: bool, humanize: bool) -> dict:
    """Tham so mo trinh duyet cho mot profile.

    Tach khoi `open_profile` de kiem duoc ma khong phai mo trinh duyet that: day la
    noi quyet dinh fingerprint nao duoc ghim, proxy nao duoc dung, va ngon ngu lay tu
    dau - ba thu ma sai mot cai la ca profile vo nghia, nhung khong cai nao bao loi.
    """
    options: dict = {
        "headless": headless,
        "humanize": humanize,
    }

    # "auto" = de Camoufox suy ngon ngu tu IP THAT cua proxy, giong nhu no lam voi mui
    # gio. Truyen mot locale co dinh se ghi de len do, va sinh ra hai van de:
    #
    #   - Lech: proxy dan cu Viet Nam ma trinh duyet khai en-US. Nguoi Viet dung trinh
    #     duyet tieng Anh la chuyen co that, nen mot minh no khong chet nguoi.
    #   - Dong deu: ca doi tai khoan dung DUNG MOT locale trong khi proxy nam o nhieu
    #     noi khac nhau. Cai nay moi la dau vet - no la thu chi xay ra khi co mot cau
    #     hinh chung sinh ra tat ca.
    if profile.locale and profile.locale != "auto":
        options["locale"] = profile.locale

    if profile.fingerprint:
        # `config` la co che ghim cua chinh Camoufox. Khong dung `fingerprint=`:
        # Camoufox bo qua fingerprint ngoai va canh bao, vi user agent phai khop
        # voi phien ban Firefox that cua binary.
        options["config"] = profile.fingerprint
        # Camoufox canh bao khi thay screen.* trong config vi gia tri tu dat co the
        # mau thuan. O day chung den tu chinh preset cua Camoufox nen da nhat quan,
        # va ghim nguyen ven ca preset moi la muc dich cua profile store.
        options["i_know_what_im_doing"] = True
    else:
        options["os"] = profile.os_family

    if profile.proxy is not None:
        options["proxy"] = profile.proxy.as_playwright_proxy()
        # Chi suy dia ly tu IP khi that su co proxy.
        options["geoip"] = True

    return options


@asynccontextmanager
async def open_profile(profile: Profile, *, headless: bool = True, humanize: bool = True):
    """Mo trinh duyet voi danh tinh cua profile. Tra ve (browser, context).

    Khong tu dong luu cookie khi thoat - viec do phai la mot hanh dong co chu y,
    goi profiles.save_cookies() sau khi da xac nhan phien dung.
    """
    options = launch_options(profile, headless=headless, humanize=humanize)

    async with AsyncCamoufox(**options) as browser:
        context = await browser.new_context(storage_state=profile.get_cookies())
        try:
            yield browser, context
        finally:
            await context.close()


async def check_session(profile: Profile, platform: Platform) -> tuple[bool, str]:
    """Phien con dang nhap khong? Tra ve (con song, mo ta).

    KHONG tu dang nhap lai khi phat hien phien chet. Do la viec cua nguoi van hanh.
    """
    probe = PROBES.get(platform)
    if probe is None:
        return False, f"no session probe defined for {platform.value}"

    if not profile.cookies_enc:
        return False, "profile has never signed in"

    settings = get_settings()
    try:
        async with open_profile(
            profile, headless=settings.headless_health_check, humanize=False
        ) as (_browser, context):
            page = await context.new_page()

            # Duong nhe: hoi mot endpoint JSON thay vi tai ca trang. Nhanh hon mot bac
            # do lon tren proxy dan cu, va cau tra loi thi ro rang hon - no noi thang
            # dang la ai, thay vi de ta doan tu dia chi cuoi cung.
            if probe.info_url:
                await page.goto(probe.info_url, wait_until="domcontentloaded", timeout=45_000)
                body = await page.evaluate("() => document.body.innerText.slice(0, 2000)")

                if any(m in body for m in probe.info_signed_out):
                    return False, "the platform says the session has expired"
                if any(m in body for m in probe.info_signed_in):
                    return True, "still signed in"
                # Khong khop dau hieu nao thi roi xuong cach cu, khong doan bua.

            await page.goto(probe.url, wait_until="domcontentloaded", timeout=45_000)
            final_url = page.url

            for marker in probe.logged_out_markers:
                if marker in final_url:
                    return False, f"bounced to {final_url}"

            return True, f"still signed in ({final_url})"

    except Exception as exc:
        # Loi mang hay proxy chet cung lam khong ket luan duoc - ghi nguyen van de
        # phan biet voi truong hop phien that su chet.
        return False, f"check inconclusive: {type(exc).__name__}: {exc}"


async def capture_storage_state(context) -> dict:
    return await context.storage_state()
