"""Mo Camoufox that. Cham (moi test khoang 15-25 giay).

    pytest -m browser

Cac test nay khong dung toi mang xa hoi nao. Chung kiem chung dung mot dieu, la
danh tinh ghim trong DB dung la thu trang web nhin thay, va no on dinh qua cac phien.
Neu dieu do sai thi moi lan mo trinh duyet la mot may khac - dung thu bat thuong ma
ca he thong nay sinh ra de tranh.
"""

import pytest

from seeding.browser.session import open_profile
from seeding.domain import fingerprint as fpm
from seeding.domain.models import Profile

pytestmark = pytest.mark.browser

# Ve mot hinh nho roi lay data URL. Cung mot lenh ve, hai may khac nhau cho ra hai
# chuoi khac nhau - day chinh la canvas fingerprinting ma cac nen tang dung.
CANVAS_PROBE = """
() => {
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d');
  ctx.textBaseline = 'top';
  ctx.font = '14px Arial';
  ctx.fillStyle = '#f60';
  ctx.fillRect(0, 0, 100, 20);
  ctx.fillStyle = '#069';
  ctx.fillText('seeding-cms', 2, 2);
  return c.toDataURL();
}
"""

IDENTITY_PROBE = """
() => ({
  ua: navigator.userAgent,
  w: screen.width,
  h: screen.height,
  lang: navigator.language,
  platform: navigator.platform
})
"""


def _profile(fp: dict | None = None) -> Profile:
    return Profile(fingerprint=fp or fpm.generate(), os_family="windows", locale="en-US")


async def _probe(profile: Profile) -> dict:
    async with open_profile(profile, headless=True, humanize=False) as (_browser, context):
        page = await context.new_page()
        await page.goto("about:blank")
        identity = await page.evaluate(IDENTITY_PROBE)
        identity["canvas"] = await page.evaluate(CANVAS_PROBE)
        return identity


async def test_page_sees_the_fingerprint_we_pinned():
    profile = _profile()
    seen = await _probe(profile)

    assert seen["ua"] == profile.fingerprint["navigator.userAgent"]
    assert seen["w"] == profile.fingerprint["screen.width"]
    assert seen["h"] == profile.fingerprint["screen.height"]
    assert seen["platform"] == profile.fingerprint["navigator.platform"]
    # Ngon ngu di qua tham so `locale=` chu khong qua config.
    assert seen["lang"] == profile.locale


async def test_same_profile_is_the_same_machine_across_launches():
    """Bat bien quan trong nhat cua giai doan 02.

    Mo lai cung mot profile phai ra dung mot may, ke ca canvas fingerprint.
    """
    profile = _profile()
    first = await _probe(profile)
    second = await _probe(profile)
    assert first == second


async def test_two_profiles_are_not_linkable():
    """Hai profile khac nhau phai co canvas fingerprint khac nhau.

    User agent giong nhau thi KHONG sao - nguoi dung Firefox that tren Windows deu
    chung mot chuoi UA, khac nhau moi la la. Thu phai khac la seed canvas/audio, vi
    do moi la thu noi hai tai khoan lai voi nhau.
    """
    a = await _probe(_profile())
    b = await _probe(_profile())
    assert a["canvas"] != b["canvas"]


async def test_cookie_jar_survives_a_round_trip_through_the_vault():
    """Luu storage_state ra profile roi mo lai - cookie phai con, va phai duoc ma hoa."""
    profile = _profile()

    async with open_profile(profile, headless=True, humanize=False) as (_b, context):
        await context.add_cookies(
            [{"name": "phien_thu", "value": "abc123", "domain": "example.com", "path": "/"}]
        )
        profile.set_cookies(await context.storage_state())

    assert profile.cookies_enc and "abc123" not in profile.cookies_enc

    async with open_profile(profile, headless=True, humanize=False) as (_b, context):
        names = {c["name"]: c["value"] for c in await context.cookies("https://example.com/")}

    assert names.get("phien_thu") == "abc123"
