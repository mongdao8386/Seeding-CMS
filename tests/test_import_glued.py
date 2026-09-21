"""Dan acc that 21/09/2026: dong tieu de cua nguoi ban co chu quang cao, va 50 acc DINH LIEN
tren mot dong (chep tu web/Zalo bien xuong dong thanh dau cach) -> "this row has 343 more
fields than the header"."""

from __future__ import annotations

from seeding.domain.models import AccountRole, Platform
from seeding.ops import bulk

GUID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
JUNK_HEADER = (
    "Format username|passtiktok|email|password|refresh_token|client_id|mailKP|"
    "Cookie MAIL TRUST OAuth2 LIVE LOGIN được, LẤY CODE ĐƯỢC"
)


def _record(i: int, cookie: bool = True) -> str:
    base = (
        f"user77{i:03d}|Viet@!{i}|box{i}@hotmail.com|mp{i}x|"
        f"M.C5{i:02d}_BAY.0.U.-tok{i}$a*b!c|{GUID}"
    )
    if not cookie:
        return base
    jar = "; ".join(f"k{j}=v{j}" for j in range(20))
    tail = f"sessionid=s{i}abc; store-country-code=vn; sid_ucp_v1=1.0.1-x{i}"
    return f"{base}|kp{i}@getnada.com|{jar}; {tail}"


def test_fifty_accounts_glued_on_one_line_under_a_noisy_header():
    data = " ".join(_record(i) for i in range(1, 51))
    report = bulk.parse(JUNK_HEADER + chr(10) + data, default_platform=Platform.TIKTOK)
    assert report.ok, [p.detail for p in report.problems][:3]
    assert len(report.rows) == 50 and report.with_cookies == 50
    assert report.glued_records == 49
    assert report.unknown_columns == [], "chu quang cao trong o tieu de khong duoc thanh cot la"
    first, last = report.rows[0], report.rows[-1]
    assert first.handle == "user77001" and last.handle == "user77050"
    assert first.secrets["password"] == "Viet@!1" and first.secrets["recovery_password"] == "mp1x"
    assert (
        last.secrets["mail_client_id"] == GUID
        and last.secrets["backup_email"] == "kp50@getnada.com"
    )
    assert "sessionid=s50abc" in last.cookie and "user77" not in last.cookie


def test_glued_rows_without_any_header_and_with_cookieless_accounts():
    parts = [_record(1), _record(2, cookie=False), _record(3), _record(4, cookie=False)]
    report = bulk.parse(
        "  ".join(parts), default_platform=Platform.TIKTOK, default_role=AccountRole.BOOSTER
    )
    assert report.ok, [p.detail for p in report.problems]
    assert [r.handle for r in report.rows] == ["user77001", "user77002", "user77003", "user77004"]
    assert report.with_cookies == 2
    assert {r.role for r in report.rows} == {AccountRole.BOOSTER}
    assert report.rows[1].cookie is None and report.rows[1].secrets["mail_client_id"] == GUID


def test_everything_on_one_line_including_the_header():
    text = JUNK_HEADER + " " + " ".join(_record(i) for i in range(1, 4))
    report = bulk.parse(text, default_platform=Platform.TIKTOK)
    assert report.ok, [p.detail for p in report.problems]
    assert [r.handle for r in report.rows] == ["user77001", "user77002", "user77003"]
    assert report.with_cookies == 3


def test_properly_separated_rows_are_left_alone():
    text = chr(10).join(_record(i) for i in range(1, 6)) + chr(10)
    split, n = bulk.split_glued_records(text)
    assert n == 0 and split == text


def test_an_email_inside_a_cookie_value_does_not_start_a_new_record():
    cookie = "a=1; note=see me@mail.com for details; sessionid=zzz"
    line = f"user1|pw|m1@hotmail.com|mp|M.C5_tok|{GUID}|kp@getnada.com|{cookie}"
    split, n = bulk.split_glued_records(line)
    assert n == 0 and split == line
