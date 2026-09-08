"""Tham so mo trinh duyet: fingerprint, proxy, va ngon ngu lay tu dau.

Ba thu nay ma sai mot cai thi ca profile vo nghia - nhung khong cai nao bao loi. Trinh
duyet van mo, trang van vao duoc, chi la danh tinh khong con la cai ban tuong.

Cho de sai nhat: proxy duoc gan trong database ma khong duoc truyen xuong trinh duyet.
Moi thu van chay, chi la chay bang IP nha ban.
"""

import uuid

from seeding.browser.session import launch_options
from seeding.domain.models import Profile, Proxy


def _profile(**kw) -> Profile:
    fields = {"fingerprint": {"navigator.userAgent": "x"}, "os_family": "windows", "locale": "auto"}
    fields.update(kw)
    return Profile(**fields)


def _proxy() -> Proxy:
    return Proxy(label="P01", scheme="http", host="1.2.3.4", port=8080)


# --------------------------------------------------------------- ngon ngu


def test_auto_locale_is_not_passed_so_geoip_can_decide():
    """Truyen locale co dinh se GHI DE len thu Camoufox suy tu IP. Ca doi tai khoan
    dung mot locale trong khi proxy nam o nhieu nuoc la mot dau vet: no chi xay ra khi
    co mot cau hinh chung sinh ra tat ca."""
    assert "locale" not in launch_options(_profile(), headless=True, humanize=True)


def test_an_explicit_locale_is_still_honoured():
    options = launch_options(_profile(locale="vi-VN"), headless=True, humanize=True)
    assert options["locale"] == "vi-VN"


def test_an_empty_locale_behaves_like_auto():
    assert "locale" not in launch_options(_profile(locale=""), headless=True, humanize=True)


# ------------------------------------------------------------- fingerprint


def test_a_pinned_fingerprint_goes_in_as_config_not_as_fingerprint():
    """Camoufox bo qua fingerprint ngoai va canh bao: user agent phai khop voi phien
    ban Firefox that cua binary. `config=` moi la co che ghim cua chinh no."""
    options = launch_options(_profile(), headless=True, humanize=True)
    assert "config" in options
    assert "fingerprint" not in options


def test_a_profile_with_no_fingerprint_falls_back_to_the_os():
    options = launch_options(_profile(fingerprint=None), headless=True, humanize=True)
    assert options["os"] == "windows"
    assert "config" not in options


# -------------------------------------------------------------------- proxy


def test_a_proxy_is_actually_passed_to_the_browser():
    """Gan proxy trong database ma khong truyen xuong thi moi thu van chay - chi la
    chay bang IP nha ban, va khong co gi bao ca."""
    options = launch_options(_profile(proxy=_proxy()), headless=True, humanize=True)
    assert options["proxy"]["server"] == "http://1.2.3.4:8080"


def test_geoip_is_on_when_there_is_a_proxy():
    """Do la thu lam mui gio va ngon ngu khop voi IP thoat."""
    assert launch_options(_profile(proxy=_proxy()), headless=True, humanize=True)["geoip"] is True


def test_geoip_is_off_without_a_proxy():
    """Khong co proxy thi suy dia ly tu IP nha ban - vo nghia, va ton mot lan tra cuu."""
    assert "geoip" not in launch_options(_profile(), headless=True, humanize=True)


def test_headless_and_humanize_are_passed_through():
    options = launch_options(_profile(), headless=False, humanize=False)
    assert options["headless"] is False
    assert options["humanize"] is False


# ------------------------------------------- kiem phien bang endpoint nhe


def test_every_platform_has_a_session_probe():
    """Thieu probe thi `check_session` tra ve "no session probe defined" va vong quet
    suc khoe danh dau MOI tai khoan cua nen tang do la hong - roi day ca doi vao hang
    doi cho nguoi, vi mot ly do khong dung.

    TikTok tung thieu dung nhu vay.
    """
    from seeding.browser.session import PROBES
    from seeding.domain.models import Platform

    assert sorted(p.value for p in Platform if p not in PROBES) == []


def test_tiktok_checks_a_light_endpoint_not_the_home_page():
    """Do that tren proxy dan cu Viet Nam: trang chu TikTok ~400KB, mat 23 GIAY hoac
    timeout han. Endpoint nay tra loi trong ~1 giay."""
    from seeding.browser.session import PROBES
    from seeding.domain.models import Platform

    probe = PROBES[Platform.TIKTOK]
    assert probe.info_url
    assert "passport" in probe.info_url


def test_a_probe_with_a_light_endpoint_knows_both_answers():
    """Chi biet dau hieu 'con song' thi khong phan biet duoc 'da het phien' voi 'proxy
    hong' - hai thu can xu ly khac han nhau."""
    from seeding.browser.session import PROBES

    for platform, probe in PROBES.items():
        if probe.info_url:
            assert probe.info_signed_in, platform
            assert probe.info_signed_out, platform


def test_probes_without_a_light_endpoint_still_have_the_old_path():
    from seeding.browser.session import PROBES

    for platform, probe in PROBES.items():
        assert probe.url, platform
        assert probe.logged_out_markers, platform


def test_static_bypass_goes_into_the_proxy_block_only_when_configured(monkeypatch):
    """Host tinh di thang chi khi co proxy VA co cau hinh; khong bao gio them khi khong proxy."""
    from seeding.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "browser_static_bypass", "*.ttwstatic.com,*.tiktokcdn.com")
    proxy = Proxy(host="proxy.example.com", port=8080, scheme="http")
    p = Profile(id=uuid.uuid4(), proxy_id=uuid.uuid4(), fingerprint={}, os_family="windows")
    p.proxy = proxy
    opts = launch_options(p, headless=True, humanize=False)
    assert opts["proxy"]["bypass"] == "*.ttwstatic.com,*.tiktokcdn.com"
    monkeypatch.setattr(settings, "browser_static_bypass", "")
    assert "bypass" not in launch_options(p, headless=True, humanize=False)["proxy"]
    p.proxy = None
    p.proxy_id = None
    assert "proxy" not in launch_options(p, headless=True, humanize=False)
