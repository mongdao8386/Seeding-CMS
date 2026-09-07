"""Doc cookie tu chuoi cua nguoi ban acc.

Cookie la thu dang gia nhat trong mot dong acc mua san: co no thi khong phai dang nhap
tay, tuc la bo qua buoc cham nhat khi dua vai tram tai khoan vao he thong.

Cung vi vay, doc sai cookie la kieu hong dat nhat: profile duoc tao, khong co loi nao,
va tai khoan chi don gian hien ra nhu chua dang nhap - luc do nguoi van hanh se di tim
loi o proxy, o fingerprint, o moi cho tru cho that.
"""

import json

import pytest

from seeding.core import cookies
from seeding.models import Platform

FB = "c_user=100012345; xs=41%3AabcDEF==; fr=0aXyZ; datr=abc123"


# ------------------------------------------------------------ chuoi cham phay


def test_reads_a_semicolon_string():
    r = cookies.parse(FB, Platform.FACEBOOK)
    assert r.count == 4
    assert r.names == ["c_user", "xs", "fr", "datr"]


def test_the_value_keeps_its_equals_signs():
    """Gia tri cookie phien thuong la base64 va CO dau `=` ben trong. Tach o moi dau
    `=` thi dung cai cookie quan trong nhat bi cat cut."""
    r = cookies.parse(FB, Platform.FACEBOOK)
    xs = next(c for c in r.storage_state["cookies"] if c["name"] == "xs")
    assert xs["value"] == "41%3AabcDEF=="


def test_the_domain_comes_from_the_platform():
    """Chuoi cham phay khong noi ten mien. Doan sai thi trinh duyet nhan cookie nhung
    khong bao gio gui di, va tai khoan hien ra nhu chua dang nhap ma khong co loi nao."""
    r = cookies.parse(FB, Platform.FACEBOOK)
    assert all(c["domain"] == ".facebook.com" for c in r.storage_state["cookies"])


def test_a_leading_dot_is_kept_so_subdomains_are_covered():
    assert cookies.DOMAINS[Platform.FACEBOOK].startswith(".")


def test_extra_whitespace_and_quotes_are_trimmed():
    r = cookies.parse('  c_user = "100012345" ;  xs=abc  ', Platform.FACEBOOK)
    assert r.storage_state["cookies"][0]["value"] == "100012345"


def test_an_empty_string_is_refused():
    with pytest.raises(cookies.CookieError, match="empty"):
        cookies.parse("   ", Platform.FACEBOOK)


def test_a_string_with_no_pairs_is_refused():
    with pytest.raises(cookies.CookieError, match="no cookies"):
        cookies.parse("khong-phai-cookie", Platform.FACEBOOK)


# ----------------------------------------------------------------- JSON


def test_reads_a_json_array_from_a_cookie_extension():
    raw = json.dumps(
        [
            {"name": "sessionid", "value": "abc", "domain": ".instagram.com", "path": "/"},
            {"name": "ds_user_id", "value": "42", "expirationDate": 1799999999.5},
        ]
    )
    r = cookies.parse(raw, Platform.INSTAGRAM)
    assert r.names == ["sessionid", "ds_user_id"]
    assert r.storage_state["cookies"][1]["expires"] == 1799999999.5


def test_reads_a_full_storage_state_and_keeps_its_origins():
    """Mot so nen tang giu token dang nhap trong localStorage chu khong o cookie. Vut
    `origins` di thi phien mat mot nua ma khong co dau hieu gi."""
    raw = json.dumps(
        {
            "cookies": [{"name": "sessionid", "value": "abc"}],
            "origins": [{"origin": "https://www.instagram.com", "localStorage": []}],
        }
    )
    r = cookies.parse(raw, Platform.INSTAGRAM)
    assert r.storage_state["origins"][0]["origin"] == "https://www.instagram.com"


def test_broken_json_says_it_is_broken_json():
    with pytest.raises(cookies.CookieError, match="will not parse"):
        cookies.parse('[{"name": "a", ', Platform.FACEBOOK)


def test_an_odd_samesite_value_is_normalised():
    """Playwright chi nhan Strict/Lax/None. Truyen thang gia tri la thi `new_context`
    tu choi CA danh sach, va loi do khong noi cookie nao gay ra."""
    raw = json.dumps([{"name": "a", "value": "b", "sameSite": "unspecified"}])
    assert cookies.parse(raw, Platform.FACEBOOK).storage_state["cookies"][0]["sameSite"] == "Lax"


def test_keys_playwright_does_not_know_are_dropped():
    raw = json.dumps([{"name": "a", "value": "b", "hostOnly": True, "storeId": "0"}])
    cookie = cookies.parse(raw, Platform.FACEBOOK).storage_state["cookies"][0]
    assert set(cookie) <= {"name", "value", "domain", "path", "httpOnly", "secure", "sameSite"}


# ------------------------------------------------------------- canh bao that


def test_a_string_with_no_session_cookie_is_flagged():
    """Day la truong hop dat nhat: cookie dung cu phap, profile tao xong, va tai khoan
    hien ra nhu chua dang nhap."""
    r = cookies.parse("datr=abc; sb=xyz", Platform.FACEBOOK)
    assert not r.looks_logged_in
    assert any("c_user" in w for w in r.warnings)


def test_device_only_cookies_are_called_out_for_what_they_are():
    r = cookies.parse("datr=abc; sb=xyz", Platform.FACEBOOK)
    assert any("device cookies" in w for w in r.warnings)


def test_a_complete_facebook_cookie_raises_no_alarm():
    assert cookies.parse(FB, Platform.FACEBOOK).looks_logged_in


def test_platforms_without_a_known_session_cookie_are_not_guessed_at():
    """Doan bua o day te hon la khong doan: mot canh bao sai lam nguoi ta vut di nhung
    cookie hoan toan tot."""
    r = cookies.parse("SID=abc; HSID=def", Platform.YOUTUBE)
    assert r.warnings == []


def test_an_unknown_platform_domain_is_refused_rather_than_guessed():
    saved = cookies.DOMAINS.pop(Platform.YOUTUBE)
    try:
        with pytest.raises(cookies.CookieError, match="no cookie domain"):
            cookies.parse(FB, Platform.YOUTUBE)
    finally:
        cookies.DOMAINS[Platform.YOUTUBE] = saved
