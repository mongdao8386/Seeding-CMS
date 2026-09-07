"""Doc cookie tu nhieu dinh dang, doi thanh storage_state cua Playwright.

Acc mua san hau nhu luon di kem mot chuoi cookie, va no la thu dang gia nhat trong ca
dong: co cookie song thi khong phai dang nhap tay, tuc la bo qua ca buoc cham nhat khi
dua vai tram tai khoan vao he thong.

Ba dinh dang hay gap, va ham `parse` nhan het:

    c_user=100012345; xs=41%3Aabc...; fr=0aXyZ...     chuoi noi bang dau cham phay
    [{"name": "c_user", "value": "...", "domain": ...}]   mang JSON (EditThisCookie)
    {"cookies": [...], "origins": [...]}                  storage_state day du

Chuoi cham phay thieu `domain`, nen phai suy tu nen tang. Do la ly do `parse` bat buoc
nhan `platform`: doan sai ten mien thi trinh duyet nhan cookie nhung khong bao gio gui
di, va tai khoan hien ra nhu chua dang nhap ma khong co loi nao ca.

MOT DIEU KHONG KIEM DUOC O DAY, va no quan trong hon moi thu trong file nay: cookie
duoc cap cho MOT thiet bi tai MOT dia chi. Dan no vao mot profile co fingerprint khac
va di ra bang mot proxy khac chinh la tinh huong ma nen tang dung cookie de phat hien.
Cookie hop le ve cu phap khong co nghia la no se song.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from seeding.models import Platform

# Ten mien de gan cho cookie khi chuoi khong noi ro. Dau cham dan dau la co y: cookie
# phien cua cac nen tang nay duoc cap cho ca ten mien con.
DOMAINS: dict[Platform, str] = {
    Platform.FACEBOOK: ".facebook.com",
    Platform.INSTAGRAM: ".instagram.com",
    Platform.THREADS: ".threads.net",
    Platform.X: ".x.com",
    Platform.TIKTOK: ".tiktok.com",
    Platform.YOUTUBE: ".youtube.com",
    Platform.REDDIT: ".reddit.com",
}

# Cookie cho biet "co mot phien dang nhap". Thieu chung thi chuoi van dung cu phap
# nhung tai khoan se hien ra nhu chua dang nhap.
#
# Chi liet ke nhung nen tang chac chan. Doan bua o day con te hon la khong doan: mot
# canh bao sai lam nguoi ta vut di nhung cookie hoan toan tot.
SESSION_COOKIES: dict[Platform, tuple[str, ...]] = {
    Platform.FACEBOOK: ("c_user", "xs"),
    Platform.INSTAGRAM: ("sessionid",),
    Platform.THREADS: ("sessionid",),
    Platform.X: ("auth_token",),
    Platform.TIKTOK: ("sessionid",),
    Platform.REDDIT: ("reddit_session",),
}

# Cookie thiet bi - co mat khong co nghia la da dang nhap. Nguoi ban doi khi chi dua
# nhung cai nay.
DEVICE_ONLY = {"datr", "sb", "fr", "wd", "dpr", "ig_did", "mid", "guest_id", "tt_webid"}


class CookieError(ValueError):
    pass


@dataclass(slots=True)
class ParsedCookies:
    storage_state: dict
    count: int
    names: list[str]
    warnings: list[str] = field(default_factory=list)

    @property
    def looks_logged_in(self) -> bool:
        return not any(w.startswith("No session cookie") for w in self.warnings)


def _clean(value: str) -> str:
    return value.strip().strip('"').strip("'")


# Ky tu KHONG duoc phep trong ten cookie (RFC 6265 token). Dau cach va dau dieu khien
# cung khong duoc.
_BAD_IN_NAME = set('()<>@,;:\\"/[]?={} \t')


def _repair_name(name: str) -> str | None:
    """Cat bo phan rac dinh vao dau ten cookie. Tra ve None neu khong cuu duoc.

    Vi sao can: file acc mua san hay co nhieu cot hon so ten cot o dong tieu de, va khi
    phan thua duoc noi lai vao o cookie thi cai ten cookie DAU TIEN bi dinh ca cuc do
    o dang truoc:

        M.C512_BAY.0.U.MsaArtifacts.-ChD3...|9e5f94bc-...|ai_do@hom_thu.com|tt_csrf_token

    Ten that la doan sau dau `|` cuoi cung. Neu khong cat, cookie do vua vo dung vua
    NUOT MAT mot cookie that - o day la `tt_csrf_token`, thu can cho moi thao tac dang
    bai. Va mot ten chua ky tu cam co the lam trinh duyet tu choi CA danh sach.
    """
    candidate = name.rsplit("|", 1)[-1].strip() if "|" in name else name.strip()
    if not candidate or any(ch in _BAD_IN_NAME for ch in candidate):
        return None
    return candidate


def _from_pairs(raw: str, domain: str, repaired: list[str] | None = None) -> list[dict]:
    """Doc chuoi `ten=gia_tri; ten2=gia_tri2`.

    Tach o dau `=` DAU TIEN chu khong phai moi dau `=`: gia tri cookie phien thuong
    la base64 va co ca dau `=` ben trong. Tach het thi cookie quan trong nhat hong.
    """
    out: list[dict] = []
    for piece in raw.split(";"):
        piece = piece.strip()
        if not piece or "=" not in piece:
            continue
        name, value = piece.split("=", 1)
        name = _clean(name)
        if not name:
            continue

        fixed = _repair_name(name)
        if fixed is None:
            # Khong cuu duoc thi BO, khong luu. Mot ten chua ky tu cam co the lam
            # trinh duyet tu choi ca danh sach, va luc do ca phien mat chu khong chi
            # mot cookie.
            if repaired is not None:
                repaired.append(f"dropped a cookie whose name is not usable: {name[:40]}…")
            continue
        if fixed != name and repaired is not None:
            repaired.append(f"trimmed junk off the front of '{fixed}'")
        name = fixed

        out.append(
            {
                "name": name,
                "value": _clean(value),
                "domain": domain,
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return out


def _from_list(rows: list, domain: str, repaired: list[str] | None = None) -> list[dict]:
    """Doc mang JSON kieu EditThisCookie / Cookie-Editor.

    Cac phan mo rong dat ten khac nhau cho cung mot thu (`expirationDate` va `expires`,
    `sameSite` viet hoa khac nhau). Chuan hoa ve dung thu Playwright nhan, va BO QUA
    khoa la thay vi de nguyen - `new_context` se tu choi ca danh sach neu gap khoa no
    khong biet, va loi do khong noi gi ve cookie nao gay ra.
    """
    out: list[dict] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = _clean(str(item.get("name", "")))
        if not name:
            continue
        fixed = _repair_name(name)
        if fixed is None:
            if repaired is not None:
                repaired.append(f"dropped a cookie whose name is not usable: {name[:40]}…")
            continue
        if fixed != name and repaired is not None:
            repaired.append(f"trimmed junk off the front of '{fixed}'")
        name = fixed

        same_site = str(item.get("sameSite", "Lax")).capitalize()
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "Lax"

        cookie = {
            "name": name,
            "value": str(item.get("value", "")),
            "domain": _clean(str(item.get("domain") or domain)) or domain,
            "path": _clean(str(item.get("path") or "/")) or "/",
            "httpOnly": bool(item.get("httpOnly", False)),
            "secure": bool(item.get("secure", True)),
            "sameSite": same_site,
        }

        expires = item.get("expirationDate", item.get("expires"))
        if isinstance(expires, (int, float)) and expires > 0:
            cookie["expires"] = float(expires)

        out.append(cookie)
    return out


def parse(raw: str, platform: Platform) -> ParsedCookies:
    """Doi mot chuoi cookie bat ky thanh storage_state cua Playwright."""
    raw = (raw or "").strip()
    if not raw:
        raise CookieError("the cookie field is empty")

    domain = DOMAINS.get(platform)
    if domain is None:
        raise CookieError(f"no cookie domain known for {platform.value}")

    warnings: list[str] = []
    repaired: list[str] = []
    origins: list = []

    if raw.startswith("{") or raw.startswith("["):
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CookieError(f"looks like JSON but will not parse: {exc}") from exc

        if isinstance(loaded, dict):
            # storage_state day du - giu nguyen ca `origins` (localStorage), vi mot so
            # nen tang giu token dang nhap o do chu khong o cookie.
            cookies = _from_list(loaded.get("cookies", []), domain, repaired)
            origins = loaded.get("origins", []) or []
        elif isinstance(loaded, list):
            cookies = _from_list(loaded, domain, repaired)
        else:
            raise CookieError("JSON must be an array of cookies or a storage state object")
    else:
        cookies = _from_pairs(raw, domain, repaired)

    if not cookies:
        raise CookieError("no cookies found in that value")

    names = [c["name"] for c in cookies]
    warnings.extend(repaired)

    expected = SESSION_COOKIES.get(platform)
    if expected:
        missing = [n for n in expected if n not in names]
        if missing:
            warnings.append(
                f"No session cookie for {platform.value}: missing {', '.join(missing)}. "
                "The browser will accept these but the account will look signed out."
            )

    if names and all(n in DEVICE_ONLY for n in names):
        warnings.append(
            "These are device cookies only — they identify a browser, not a logged-in person."
        )

    return ParsedCookies(
        storage_state={"cookies": cookies, "origins": origins},
        count=len(cookies),
        names=names,
        warnings=warnings,
    )
