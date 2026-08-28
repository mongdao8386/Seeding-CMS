"""Ghim fingerprint cho tung profile, bang chinh co che cua Camoufox.

Ban dau module nay tu sinh fingerprint bang BrowserForge roi truyen vao Camoufox.
Cach do SAI, va test trinh duyet da bat duoc: Camoufox bo qua fingerprint ngoai va
canh bao "Passing your own fingerprint is not recommended". Ly do chinh dang: user
agent phai khop voi phien ban Firefox that cua binary Camoufox, neu khong thi chinh
fingerprint do tu mau thuan - dung kieu tin hieu ma ca he thong nay co de tranh.

Cach dung: lay mot preset cua Camoufox, doi thanh config phang, luu xuong DB, roi
tra lai nguyen van cho lan mo trinh duyet sau qua tham so `config=`.

Config phang chua ca `canvas:seed`, `audio:seed` va `fonts:spacing_seed`. Day moi la
thu quan trong nhat: chung lam cho canvas va audio fingerprint on dinh qua cac phien
cua CUNG mot profile, va khac nhau giua cac profile.
"""

from __future__ import annotations

import camoufox.fingerprints as cff
from camoufox.pkgman import installed_verstr
from camoufox.webgl.sample import sample_webgl


def firefox_version() -> str | None:
    """Phien ban Firefox cua binary Camoufox dang cai, vd '152'.

    Preset duoc viet lai theo phien ban nay de user agent khong noi doi ve chinh
    trinh duyet dang chay.
    """
    try:
        return installed_verstr().split(".")[0]
    except Exception:
        # Chua tai binary thi cu de Camoufox tu quyet luc chay.
        return None


# Mot phan cac preset chua cap WebGL ma chinh Camoufox khong tra duoc du lieu, hoac
# co nhung khong hop le cho he dieu hanh dang chon. Mo trinh duyet se hong voi
# ValueError. Vi fingerprint duoc ghim vinh vien, mot profile tao nham preset do se
# hong mai mai - phai loai ngay tu luc sinh.
_MAX_ROLLS = 25

# Camoufox dung ma OS ngan trong CSDL WebGL cua no.
_OS_SHORT = {"windows": "win", "macos": "mac", "linux": "lin"}


def generate(os_family: str = "windows") -> dict:
    """Sinh config fingerprint cho mot profile MOI.

    Goi dung mot lan trong doi cua profile. Ket qua luu xuong DB va khong bao gio
    sinh lai - fingerprint doi giua cac phien cua cung mot tai khoan la bat thuong
    ro rang hon la mot fingerprint tam thuong nhung on dinh.
    """
    version = firefox_version()

    for _ in range(_MAX_ROLLS):
        preset = cff.get_random_preset(os=os_family, ff_version=version)
        if preset is None:
            raise RuntimeError(
                f"Camoufox khong co preset nao cho os={os_family!r}. "
                "Kiem tra lai binary da tai chua: python -m camoufox fetch"
            )

        # Co y KHONG dat navigator.language: Camoufox muon ngon ngu di qua tham so
        # `locale=` de no dong bo cac thu khac theo. Locale luu rieng tren Profile.
        config = dict(cff.from_preset(preset, ff_version=version))

        if is_launchable(config, os_family):
            return config

    raise RuntimeError(
        f"Rut {_MAX_ROLLS} lan van chi gap preset WebGL khong dung duoc cho "
        f"os={os_family!r}. Co the ban Camoufox da doi - kiem tra lai fingerprint-presets.json."
    )


def is_launchable(config: dict, os_family: str = "windows") -> bool:
    """Config nay co mo duoc trinh duyet khong?

    Hoi thang CSDL WebGL cua Camoufox thay vi tu giu danh sach den. Day dung la doan
    ma Camoufox chay luc khoi dong, nen kiem o day khong bao gio lech voi thuc te.

    Kiem truoc con hon de mot profile chet nam trong DB roi moi phat hien luc dang bai.
    """
    vendor = config.get("webGl:vendor")
    renderer = config.get("webGl:renderer")
    if not vendor or not renderer:
        return True  # Khong ghim WebGL thi Camoufox tu chon lay mot cap hop le.

    try:
        sample_webgl(_OS_SHORT.get(os_family, "win"), vendor, renderer)
        return True
    except ValueError:
        return False


def summary(config: dict) -> str:
    """Mot dong de doc trong log va tren dashboard."""
    ua = config.get("navigator.userAgent", "?")
    short_ua = ua.split(") ", 1)[0] + ")" if ") " in ua else ua
    w, h = config.get("screen.width"), config.get("screen.height")
    return f"{short_ua} | {w}x{h} | {config.get('navigator.platform', '?')}"


def is_pinned(config: dict) -> bool:
    """Config co day du cac seed lam fingerprint on dinh qua cac phien khong?

    Thieu seed thi Camoufox se tu sinh moi lan mo, tuc la canvas va audio doi sau
    moi phien du user agent van giu nguyen.
    """
    return all(k in config for k in ("canvas:seed", "audio:seed", "fonts:spacing_seed"))
