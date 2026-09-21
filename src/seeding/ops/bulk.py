"""Nhap tai khoan hang loat tu CSV.

Nhap tay tung cai mot la viec on voi muoi tai khoan va khong the chiu duoc voi mot
tram. Nhung nhap hang loat co mot cai bay rieng: mot file 200 dong ma dong 173 sai
dinh dang thi 172 dong truoc do da nam trong database, va nguoi dung khong biet phai
sua tu dau.

Nen module nay lam hai lua:
  - `parse` doc va kiem TOAN BO file, khong cham vao database. Tra ve ca dong hop le
    lan dong hong, kem so dong de sua.
  - `apply` chi chay khi nguoi dung da nhin thay ket qua kiem va dong y.

Cot bat buoc:  platform, handle
Cot tuy chon:  persona, daily_cap, start_warmup, va bat ky cot bi mat nao duoi day.

Cot bi mat duoc ma hoa truoc khi ghi xuong, giong het duong tao tung cai:
    Reddit           client_id, client_secret, username, password
    Nen tang browser password, totp_seed, recovery_email, recovery_password,
                     mail_refresh_token, mail_client_id, backup_email

Dinh dang nguoi ban (co hay khong co dong tieu de deu nhan):
    username|password|hotmail|pass_hotmail|cookie
    username|passtiktok|email|password|refresh_token|client_id|mailKP|cookie

CANH BAO nam trong tai lieu chu khong chi o day: mot file CSV chua mat khau la mot
file mat khau nam tren o dia. Xoa no sau khi nhap xong.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.domain.models import Account, AccountRole, AccountStatus, Persona, Platform
from seeding.ops import cookies as cookies_mod

REQUIRED = ("platform", "handle")

# Cot bi mat, theo nen tang. Chi nhung ten nay moi duoc coi la bi mat; cot la khong
# doan duoc se bi bao la khong hieu, thay vi lang le bi nem vao vault.
SECRET_FIELDS = (
    "client_id",
    "client_secret",
    "username",
    "password",
    "totp_seed",
    "recovery_email",
    # Mat khau cua hom thu khoi phuc. Acc mua san hau nhu luon di kem, va thieu no thi
    # den luc nen tang doi xac minh qua email la het duong.
    "recovery_password",
    # Hotmail/Outlook OAuth2 di kem acc mua san: doc hom thu lay ma xac minh ma khong can
    # mat khau. `client_id` cua hom thu KHAC `client_id` cua app Reddit - xem resolve_headers.
    "mail_refresh_token",
    "mail_client_id",
    # "mail KP" (mail khoi phuc) cua chinh hom thu do.
    "backup_email",
)

# `cookie` KHONG nam trong SECRET_FIELDS: no khong di vao vault cua Account ma di vao
# cookie jar cua Profile. Xu ly rieng trong `apply`.
KNOWN = (
    set(REQUIRED) | {"persona", "daily_cap", "start_warmup", "cookie", "role"} | set(SECRET_FIELDS)
)

# Cot `role`: channel (xay kenh, mac dinh) | booster (tuong tac cheo). Nhan ca tieng Viet.
_BOOSTER_WORDS = {"booster", "boost", "tuong tac", "tương tác", "tuongtac", "cheo", "chéo", "b"}


def parse_role(raw: str | None, default: AccountRole = AccountRole.CHANNEL) -> AccountRole:
    v = (raw or "").strip().lower()
    if not v:
        return default
    if any(w in v for w in _BOOSTER_WORDS):
        return AccountRole.BOOSTER
    return AccountRole.CHANNEL


# Ten cot ma nguoi ban acc hay dung, doi sang ten cua he thong. Bat nguoi dung sua lai
# dong tieu de cua mot file 500 dong la mot buoc thua khong mua duoc gi.
ALIASES = {
    "uid": "handle",
    "user": "handle",
    "hotmail": "recovery_email",
    "mail": "recovery_email",
    "email": "recovery_email",
    "pass": "password",
    "pass_hotmail": "recovery_password",
    "passmail": "recovery_password",
    "mail_pass": "recovery_password",
    "2fa": "totp_seed",
    "twofa": "totp_seed",
    "secret_2fa": "totp_seed",
    "cookies": "cookie",
    "refresh_token": "mail_refresh_token",
    "refreshtoken": "mail_refresh_token",
    "mailkp": "backup_email",
    "mail_kp": "backup_email",
    "emailkp": "backup_email",
    "email_kp": "backup_email",
    "mailkhoiphuc": "backup_email",
    "mail_khoi_phuc": "backup_email",
    "mail_recovery": "backup_email",
    "recovery_mail": "backup_email",
}

# Cot mat khau RIENG cua nen tang: passtiktok, pass_fb, tiktok_pass, passacc... File co cot
# nay thi cot `password` tran (thuong dung ngay sau `email`) la mat khau CUA HOM THU.
_PLATFORM_WORDS = "tiktok|tik|tt|fb|facebook|ig|insta|instagram|x|twitter|reddit|acc|account|nick"
_ACCOUNT_PASS = re.compile(
    rf"^(?:pass(?:word)?[_\-\s]?(?:{_PLATFORM_WORDS})|(?:{_PLATFORM_WORDS})[_\-\s]?pass(?:word)?)$"
)
_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# Hai dinh dang nguoi ban hay giao KHONG kem dong tieu de.
SELLER_HEADER = ("username", "password", "hotmail", "pass_hotmail", "cookie")
SELLER_OAUTH_HEADER = (
    "username",
    "passtiktok",
    "email",
    "password",
    "refresh_token",
    "client_id",
    "mailkp",
    "cookie",
)


# Dau moi acc trong file nguoi ban: `ten|matkhau|email@...|`. Email o o thu ba la moc chac: ben
# trong cookie khong bao gio co dang `a|b|c@d.e|`.
_RECORD_START = re.compile(r"([^\s|]{2,80})\|([^\s|]{1,160})\|([^\s|@]+@[^\s|@]+\.[^\s|]+)\|")


def split_glued_records(text: str) -> tuple[str, int]:
    """Tach cac acc DINH LIEN tren mot dong thanh moi acc mot dong.

    Chep danh sach tu trang web / Zalo / Telegram hay bien dau xuong dong thanh dau cach:
    50 acc thanh MOT dong 351 o (21/09/2026). Moi cho thay `ten|matkhau|email|` dung sau
    khoang trang (khong phai dau dong) la mot acc moi -> doi khoang trang do thanh xuong dong.
    Tra ve (van ban moi, so cho da tach).
    """
    out: list[str] = []
    last = 0
    splits = 0
    for m in _RECORD_START.finditer(text):
        i = m.start()
        j = i
        while j > 0 and text[j - 1] in " \t\u00a0":
            j -= 1
        if j == i or j == 0 or text[j - 1] in "\r\n":
            continue  # dau van ban / dau dong / dinh sat khong khoang trang: khong phai cho noi
        out.append(text[last:j])
        out.append("\n")
        last = i
        splits += 1
    out.append(text[last:])
    return "".join(out), splits


def _header_cell(cell: str) -> str:
    """O tieu de co chu thua cua nguoi ban ("Format username", "Cookie MAIL TRUST OAuth2 LIVE
    LOGIN duoc") -> lay tu dau tien la ten cot that."""
    names = KNOWN | set(ALIASES)
    if cell in names or _ACCOUNT_PASS.match(cell):
        return cell
    for token in cell.replace(",", " ").split():
        if token in names or _ACCOUNT_PASS.match(token):
            return token
    return cell


def resolve_headers(raw: list[str], default_platform: Platform | None = None) -> list[str]:
    """Ten cot cua nguoi ban -> ten cua he thong, co xet NGU CANH ca dong tieu de.

    `username|passtiktok|email|password|refresh_token|client_id|mailKP|cookie`: o day
    `password` la mat khau email (mat khau TikTok da co cot rieng), va `client_id` la cua
    hom thu (di cung refresh_token), khong phai app Reddit.
    """
    has_account_pass = any(_ACCOUNT_PASS.match(h) for h in raw)
    out: list[str] = []
    for h in raw:
        if _ACCOUNT_PASS.match(h):
            out.append("password")
        elif has_account_pass and h in ("password", "pass"):
            out.append("recovery_password")
        else:
            out.append(ALIASES.get(h, h))
    if "mail_refresh_token" in out and default_platform is not Platform.REDDIT:
        out = ["mail_client_id" if n == "client_id" else n for n in out]
    return out


def looks_like_header(cells: list[str]) -> bool:
    """Dong dau la tieu de khi co it nhat hai o la TEN COT (khong phai du lieu)."""
    names = KNOWN | set(ALIASES)
    cells = [_header_cell(c) for c in cells]
    hits = sum(1 for c in cells if c in names or _ACCOUNT_PASS.match(c))
    return hits >= 2


def infer_header(cells: list[str]) -> tuple[str, ...] | None:
    """Doan dinh dang tu DONG DU LIEU dau tien khi file khong co tieu de."""
    # 6 cot (khong mailKP, khong cookie) cung la dinh dang OAuth: nhan ra bang client_id GUID.
    if len(cells) >= 6 and "@" in cells[2] and _GUID.match(cells[5].strip()):
        return SELLER_OAUTH_HEADER
    if len(cells) >= 8 and "@" in cells[2] and (_GUID.match(cells[5]) or "@" in cells[6]):
        return SELLER_OAUTH_HEADER
    if len(cells) >= 4 and "@" in cells[2]:
        return SELLER_HEADER
    return None


_TRUE = {"1", "true", "yes", "y", "co", "có"}


@dataclass(slots=True)
class Row:
    """Mot dong da qua kiem, san sang tao."""

    line: int
    platform: Platform
    handle: str
    persona: str | None
    daily_cap: int
    start_warmup: bool
    role: AccountRole = AccountRole.CHANNEL
    secrets: dict = field(default_factory=dict)
    # Chuoi cookie nguyen van. Doc thanh phien that o buoc TAO, nhung van duoc THU doc
    # o buoc kiem - xem `cookie_note`.
    cookie: str | None = None
    # Ket qua thu doc cookie: None = doc duoc va co ca cookie phien. Co chu = van de.
    #
    # Ban dau buoc kiem chi DEM o cookie co chu hay khong roi bao "14 with a saved
    # session". Do la mot loi hua ma buoc tao co the khong giu duoc: chuoi hong, hoac
    # chi co cookie thiet bi, deu dem thanh "co phien". Nguoi dung nhap xong, thay 14
    # tai khoan, va chi phat hien ra khi bai dang dau tien that bai.
    cookie_note: str | None = None


@dataclass(slots=True)
class Problem:
    line: int
    handle: str
    detail: str


@dataclass(slots=True)
class Report:
    rows: list[Row] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    unknown_columns: list[str] = field(default_factory=list)
    # Cot da duoc doi ten tu ten cua nguoi ban sang ten cua he thong. Bao ra de nguoi
    # dung thay minh khong go nham cot nao.
    renamed_columns: dict = field(default_factory=dict)
    # So dong ma phan thua da duoc noi lai vao cot cuoi. Thuong la cookie TikTok co
    # chua dau `|` - bao ra de nguoi dung biet chuyen do da xay ra.
    rejoined_rows: int = 0
    # File khong co dong tieu de: dinh dang da doan (de nguoi dung thay minh duoc hieu dung).
    inferred_header: str | None = None
    # Chi dan moi dong tieu de: khong phai loi, chi la chua co acc nao. Giao dien hien goi y.
    header_only: bool = False
    # So dong co chu trong o dan (ke ca dong tieu de). Giao dien doi chieu voi so dong doc duoc
    # de nguoi dung THAY khi co dong bi nuot, thay vi tin vao mot con so.
    input_lines: int = 0
    # So acc dinh lien tren mot dong da duoc tach ra (chep tu web/Zalo lam mat xuong dong).
    glued_records: int = 0

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def with_cookies(self) -> int:
        """Dong co cookie DUNG duoc - da doc thu va co ca cookie phien."""
        return sum(1 for r in self.rows if r.cookie and not r.cookie_note)

    @property
    def cookie_problems(self) -> int:
        return sum(1 for r in self.rows if r.cookie and r.cookie_note)


def sniff_delimiter(text: str) -> str:
    """Doan dau phan cach tu dong tieu de.

    File acc mua san gan nhu luon dung `|` chu khong phai dau phay. Bat nguoi dung doi
    het sang dau phay truoc khi nhap la mot buoc thua, va no con lam hong du lieu: mat
    khau va cookie thuong CO dau phay ben trong.
    """
    first = text.lstrip("﻿").splitlines()
    header = first[0] if first else ""
    counts = {d: header.count(d) for d in ("|", "\t", ";", ",")}
    # File KHONG co dong tieu de thi dong dau la du lieu, va cookie trong do co hang chuc
    # dau `;` (va ca dau phay) - dem nhieu nhat se chon nham (21/09/2026: acc that dan vao
    # bi bao "missing: handle"). `|` va tab khong xuat hien tu nhien trong ten cot, mat
    # khau hay email, nen thay tu 3 cai tro len la dau phan cach that.
    for strong in ("|", "\t"):
        if counts[strong] >= 3:
            return strong
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def parse(
    text: str,
    default_platform: Platform | None = None,
    default_role: AccountRole = AccountRole.CHANNEL,
) -> Report:
    """Doc va kiem ca file. Khong cham database.

    Dong hong khong lam dung ca file: nguoi dung can thay HET moi loi trong mot lan,
    chu khong phai sua mot dong roi chay lai de gap loi tiep theo.

    `default_platform` dien vao cho nhung dong khong co cot `platform`. Mot file 500
    acc Facebook khong nen bat nguoi ta lap lai chu "facebook" 500 lan.
    """
    report = Report()

    # Excel luon luu kem BOM. Khong cat thi cot dau tien ten la "﻿platform" va
    # file bi bao la thieu cot bat buoc - loi kho hieu nhat co the doi vao mat nguoi
    # dung, vi nhin bang mat thi file hoan toan dung.
    delimiter = sniff_delimiter(text)
    clean = text.lstrip("\ufeff")
    if delimiter == "|":
        clean, report.glued_records = split_glued_records(clean)
    first_line = next((ln for ln in clean.splitlines() if ln.strip()), "")
    first_cells = [c.strip() for c in first_line.split(delimiter)]
    inferred = None
    if first_line and not looks_like_header([c.lower() for c in first_cells]):
        inferred = infer_header(first_cells)
    # File nguoi ban (phan cach bang `|` hoac tab) KHONG co khai niem "truong trong ngoac kep".
    # De csv xu ly ngoac kep thi mot doan cookie nam sau dau `|` ma bat dau bang dau " se nuot
    # luon cac DONG phia sau cho toi dau " ke tiep: 21/09/2026, 50 acc dan vao chi con 1 dong.
    # Voi hai dau phan cach nay moi dong luon la mot acc. File dau phay / cham phay van la CSV
    # chuan, giu nguyen cach doc ngoac kep.
    quoting = csv.QUOTE_NONE if delimiter in ("|", "\t") else csv.QUOTE_MINIMAL
    report.input_lines = sum(1 for ln in clean.splitlines() if ln.strip())
    if inferred is not None:
        # Khong co dong tieu de: dong dau da la du lieu. Dung dinh dang doan duoc.
        reader = csv.DictReader(
            io.StringIO(clean), fieldnames=list(inferred), delimiter=delimiter, quoting=quoting
        )
        report.inferred_header = delimiter.join(inferred)
        first_data_line = 1
    else:
        reader = csv.DictReader(io.StringIO(clean), delimiter=delimiter, quoting=quoting)
        first_data_line = 2
    if reader.fieldnames is None:
        report.problems.append(Problem(0, "", "The file is empty."))
        return report

    raw_headers = [_header_cell((h or "").strip().lower()) for h in reader.fieldnames]
    headers = resolve_headers(raw_headers, default_platform)
    header_map = dict(zip(raw_headers, headers, strict=True))
    report.renamed_columns = {
        raw: new for raw, new in zip(raw_headers, headers, strict=True) if raw != new
    }

    # File acc mua san dat ten cot dinh danh la `username`, va do cung la ten mot cot
    # bi mat cua Reddit - nen khong the doi thang no thanh `handle` trong ALIASES.
    #
    # Giai quyet theo tinh huong: khong co cot `handle` nao thi `username` DONG THOI
    # dong vai tro do, va van o lai trong phan bi mat. Co ca hai cot thi giu nguyen ca
    # hai, vi luc do nguoi dung da noi ro y minh.
    username_as_handle = "handle" not in headers and "username" in headers
    if username_as_handle:
        report.renamed_columns["username"] = "handle + username"

    missing = [c for c in REQUIRED if c not in headers]
    if username_as_handle:
        missing = [c for c in missing if c != "handle"]
    if default_platform is not None:
        # Nen tang da duoc chon o ngoai, khong bat buoc phai co trong file nua.
        missing = [c for c in missing if c != "platform"]
    if missing:
        report.problems.append(Problem(1, "", f"The header row is missing: {', '.join(missing)}"))
        return report

    report.unknown_columns = sorted({h for h in headers if h and h not in KNOWN})

    last_column = headers[-1] if headers else ""
    rejoined = 0

    seen: set[tuple[str, str]] = set()
    for offset, raw in enumerate(reader, start=first_data_line):
        row = {
            header_map.get(_header_cell((k or "").strip().lower()), (k or "").strip().lower()): (
                v or ""
            ).strip()
            for k, v in raw.items()
            if k is not None
        }

        # Dong co nhieu truong hon so cot. csv gom phan thua vao khoa None, va bo di
        # thi mat du lieu HOAN TOAN AM THAM.
        #
        # Day khong phai truong hop hiem - no la truong hop THUONG GAP nhat voi acc
        # TikTok: cookie `ttwid` chua dau `|` khong ma hoa, dung bang dau phan cach cua
        # file. Cot cookie chi nhan duoc mau dau, va bao "no cookies found in that
        # value" - mot cau khong noi gi ve nguyen nhan that.
        overflow = [str(x) for x in (raw.get(None) or []) if x is not None]
        if overflow:
            if last_column == "cookie":
                # Cot cuoi la cookie: no la chuoi tu do va duoc phep chua dau phan cach.
                # Noi lai nguyen ven.
                row["cookie"] = delimiter.join([row.get("cookie", ""), *overflow])
                rejoined += 1
            else:
                report.problems.append(
                    Problem(
                        offset,
                        row.get("handle", ""),
                        f"this row has {len(overflow)} more field(s) than the header. The "
                        f"separator '{delimiter}' probably appears inside one of the values.",
                    )
                )
                continue
        # cookie nam nham cot: nguoi ban bo cot mailKP o vai dong, chuoi cookie troi vao cho
        # cua mail khoi phuc. Mot dia chi mail khong bao gio co dang `a=b; c=d`.
        stray = row.get("backup_email", "")
        if stray and "=" in stray and "@" not in stray.split(";")[0]:
            # Cookie co the con bi tach tiep boi dau phan cach ben trong no: noi lai.
            rest = row.get("cookie", "")
            row["cookie"] = stray + (delimiter + rest if rest else "")
            row["backup_email"] = ""
        handle = row.get("handle", "") or (row.get("username", "") if username_as_handle else "")

        if not any(row.values()):
            continue  # dong trong o cuoi file la chuyen binh thuong

        if not handle:
            report.problems.append(Problem(offset, "", "handle is empty"))
            continue

        if not row.get("platform") and default_platform is not None:
            row["platform"] = default_platform.value
        try:
            platform = Platform(row.get("platform", "").lower())
        except ValueError:
            report.problems.append(
                Problem(
                    offset,
                    handle,
                    f"'{row.get('platform')}' is not a platform. "
                    f"Use one of: {', '.join(p.value for p in Platform)}",
                )
            )
            continue

        # Trung trong chinh file nay. De database bao thi no bao o dong dau tien no
        # gap, con nguoi dung can biet CA HAI dong de xoa dung cai.
        key = (platform.value, handle.lower())
        if key in seen:
            report.problems.append(
                Problem(offset, handle, f"{handle} appears twice for {platform.value} in this file")
            )
            continue
        seen.add(key)

        cap_raw = row.get("daily_cap") or "3"
        try:
            daily_cap = int(cap_raw)
        except ValueError:
            report.problems.append(
                Problem(offset, handle, f"daily_cap '{cap_raw}' is not a number")
            )
            continue
        if daily_cap < 1:
            report.problems.append(Problem(offset, handle, "daily_cap must be at least 1"))
            continue

        # Thu doc cookie ngay o day. Khong nem loi ra: mot chuoi hong chi lam hong DONG
        # do, va nguoi dung van nen thay ca file trong mot lan.
        raw_cookie = row.get("cookie") or None
        cookie_note = None
        if raw_cookie:
            try:
                parsed = cookies_mod.parse(raw_cookie, platform)
                if parsed.warnings:
                    cookie_note = parsed.warnings[0]
            except cookies_mod.CookieError as exc:
                cookie_note = str(exc)

        warmup_raw = row.get("start_warmup")
        start_warmup = True if warmup_raw in (None, "") else warmup_raw.lower() in _TRUE

        report.rows.append(
            Row(
                line=offset,
                platform=platform,
                handle=handle,
                persona=row.get("persona") or None,
                daily_cap=daily_cap,
                start_warmup=start_warmup,
                role=parse_role(row.get("role"), default_role),
                secrets={k: row[k] for k in SECRET_FIELDS if row.get(k)},
                cookie=raw_cookie,
                cookie_note=cookie_note,
            )
        )

    report.rejoined_rows = rejoined

    if not report.rows and not report.problems:
        report.header_only = True
        report.problems.append(
            Problem(
                1,
                "",
                "Mới có dòng tiêu đề, chưa có dòng tài khoản nào (the file has a header but no "
                f"rows). Các cột được hiểu là: {delimiter.join(h for h in headers if h)}",
            )
        )

    return report


async def check_against_db(session: AsyncSession, report: Report) -> Report:
    """Them cac loi chi thay duoc khi doi chieu voi database.

    Tach khoi `parse` de phan doc file van kiem duoc ma khong can database - va de
    nguoi dung thay loi dinh dang ngay ca khi Postgres dang chet.
    """
    if not report.rows:
        return report

    handles = {r.handle for r in report.rows}
    existing = {
        (a.platform.value, a.handle.lower())
        for a in (await session.execute(select(Account).where(Account.handle.in_(handles))))
        .scalars()
        .all()
    }

    kept: list[Row] = []
    for row in report.rows:
        if (row.platform.value, row.handle.lower()) in existing:
            report.problems.append(
                Problem(
                    row.line,
                    row.handle,
                    f"{row.handle} already exists on {row.platform.value}",
                )
            )
            continue
        kept.append(row)

    report.rows = kept
    return report


async def apply(
    session: AsyncSession,
    workspace_id,
    rows: list[Row],
    *,
    default_persona_id=None,
    pool=None,
) -> tuple[list[Account], list[str]]:
    """Tao tai khoan, va tao ca profile cho nhung dong co cookie.

    Chi goi khi `parse` va `check_against_db` da sach.

    Persona duoc tao neu chua co: bat nguoi dung tao tay 12 persona truoc khi nhap
    duoc file la lam mat het cai loi cua viec nhap hang loat.

    Dong nao co cookie thi tao luon profile kem phien dang nhap. Do la ca ly do cot
    cookie ton tai: khong co no thi moi tai khoan phai chay `login_profile.py` bang
    tay, va voi vai tram acc thi day la buoc cham nhat trong toan bo quy trinh.

    Tra ve (tai khoan da tao, cac canh bao). Canh bao khong chan viec tao: cookie hong
    thi tai khoan van dang nhap tay duoc, mat mot buoc chu khong mat tai khoan.
    """
    from seeding.domain import profiles as profiles_mod
    from seeding.ops import cookies as cookies_mod

    warnings: list[str] = []
    # `pool` (ops/proxypool.ProxyPool): mot proxy dung chung toi da ACCOUNTS_PER_PROXY acc,
    # acc moi vao proxy dang it nguoi nhat. Booster khong can proxy nen khong chiem cho.
    personas: dict[str, Persona] = {
        p.name.lower(): p
        for p in (
            await session.execute(select(Persona).where(Persona.workspace_id == workspace_id))
        )
        .scalars()
        .all()
    }

    created: list[Account] = []
    for row in rows:
        persona_id = default_persona_id
        if row.persona:
            persona = personas.get(row.persona.lower())
            if persona is None:
                persona = Persona(workspace_id=workspace_id, name=row.persona)
                session.add(persona)
                await session.flush()
                personas[row.persona.lower()] = persona
            persona_id = persona.id

        if persona_id is None:
            raise ValueError(
                f"Line {row.line} ({row.handle}) has no persona, and no default was given."
            )

        account = Account(
            persona_id=persona_id,
            platform=row.platform,
            handle=row.handle,
            daily_cap=row.daily_cap,
            role=row.role,
        )
        if row.secrets:
            account.set_secrets(row.secrets)
        if row.start_warmup:
            account.warmup_started_at = datetime.now(UTC)
            account.status = AccountStatus.WARMING

        session.add(account)
        created.append(account)

    await session.commit()

    # Profile tao SAU khi tai khoan da commit: create_profile can account.id that.
    for account, row in zip(created, rows, strict=True):
        # Moi acc deu co profile, CO HAY KHONG co cookie: acc khong cookie phai dang nhap
        # trong trinh duyet cua profile (mat khau + ma tu email), ma khong co profile thi nut
        # "Mo trinh duyet" khong co gi de mo (21/09/2026: 80/100 acc nguoi ban giao khong
        # kem cookie). Acc xay kenh lay mot cho proxy; booster khong can.
        parsed = None
        if row.cookie:
            try:
                parsed = cookies_mod.parse(row.cookie, account.platform)
            except cookies_mod.CookieError as exc:
                warnings.append(f"Line {row.line} ({row.handle}): cookie not usable — {exc}")

        profile = await profiles_mod.create_profile(
            session,
            account,
            proxy=pool.take() if pool and row.role is not AccountRole.BOOSTER else None,
        )
        if parsed is not None:
            await profiles_mod.save_cookies(session, profile, parsed.storage_state)
            for warning in parsed.warnings:
                warnings.append(f"Line {row.line} ({row.handle}): {warning}")
        if profile.proxy_id is None and row.role is not AccountRole.BOOSTER:
            warnings.append(
                f"Line {row.line} ({row.handle}): profile created with NO proxy. It will go out "
                "on your own address until you attach one."
            )

    return created, warnings


def template() -> str:
    """File mau de tai ve.

    Dung dau `|` chu khong phai dau phay, va do la lua chon co ly do: mat khau va nhat
    la CHUOI COOKIE thuong co dau phay ben trong. File mau dung dau phay se day nguoi
    dung vao dung cai bay do ngay tu dong dau tien.
    """
    return (
        "platform|handle|persona|daily_cap|start_warmup|"
        "client_id|client_secret|username|password|totp_seed|"
        "recovery_email|recovery_password|cookie\n"
        "reddit|seed_reddit_01|Hanoi students|3|yes|"
        "abc123|secret456|seed_reddit_01|hunter2|||\n"
        "facebook|seed.fb.01|Hanoi students|2|yes|"
        "|||hunter2|JBSWY3DPEHPK3PXP|backup@example.com|Mailpass1|"
        "c_user=100012345; xs=41%3Aabc==\n"
    )


def seller_template() -> str:
    """File mau theo dung dinh dang cua nguoi ban acc.

    `username|password|hotmail|pass_hotmail|cookie` - khong co cot `platform`, vi ca
    file thuong la mot nen tang va nen tang duoc chon o ngoai luc nhap.
    """
    return (
        "username|password|hotmail|pass_hotmail|cookie\n"
        "seed.fb.01|Matkhau123|abc@hotmail.com|Mailpass1|"
        "c_user=100012345; xs=41%3Aabc==\n"
        "seed.fb.02|Matkhau456|def@hotmail.com|Mailpass2|"
        "c_user=100067890; xs=41%3Adef==\n"
    )
