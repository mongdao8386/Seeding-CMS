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
    Nen tang browser password, totp_seed, recovery_email

CANH BAO nam trong tai lieu chu khong chi o day: mot file CSV chua mat khau la mot
file mat khau nam tren o dia. Xoa no sau khi nhap xong.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.models import Account, AccountStatus, Persona, Platform

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
)

KNOWN = set(REQUIRED) | {"persona", "daily_cap", "start_warmup"} | set(SECRET_FIELDS)

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
    secrets: dict = field(default_factory=dict)


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

    @property
    def ok(self) -> bool:
        return not self.problems


def parse(text: str) -> Report:
    """Doc va kiem ca file. Khong cham database.

    Dong hong khong lam dung ca file: nguoi dung can thay HET moi loi trong mot lan,
    chu khong phai sua mot dong roi chay lai de gap loi tiep theo.
    """
    report = Report()

    # Excel luon luu kem BOM. Khong cat thi cot dau tien ten la "﻿platform" va
    # file bi bao la thieu cot bat buoc - loi kho hieu nhat co the doi vao mat nguoi
    # dung, vi nhin bang mat thi file hoan toan dung.
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None:
        report.problems.append(Problem(0, "", "The file is empty."))
        return report

    headers = [(h or "").strip().lower() for h in reader.fieldnames]
    missing = [c for c in REQUIRED if c not in headers]
    if missing:
        report.problems.append(Problem(1, "", f"The header row is missing: {', '.join(missing)}"))
        return report

    report.unknown_columns = sorted({h for h in headers if h and h not in KNOWN})

    seen: set[tuple[str, str]] = set()
    for offset, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        handle = row.get("handle", "")

        if not any(row.values()):
            continue  # dong trong o cuoi file la chuyen binh thuong

        if not handle:
            report.problems.append(Problem(offset, "", "handle is empty"))
            continue

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
                secrets={k: row[k] for k in SECRET_FIELDS if row.get(k)},
            )
        )

    if not report.rows and not report.problems:
        report.problems.append(Problem(1, "", "The file has a header but no rows."))

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
    session: AsyncSession, workspace_id, rows: list[Row], *, default_persona_id=None
) -> list[Account]:
    """Tao tai khoan. Chi goi khi `parse` va `check_against_db` da sach.

    Persona duoc tao neu chua co: bat nguoi dung tao tay 12 persona truoc khi nhap
    duoc file la lam mat het cai loi cua viec nhap hang loat.
    """
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
        )
        if row.secrets:
            account.set_secrets(row.secrets)
        if row.start_warmup:
            account.warmup_started_at = datetime.now(UTC)
            account.status = AccountStatus.WARMING

        session.add(account)
        created.append(account)

    await session.commit()
    return created


def template() -> str:
    """File mau de tai ve. Mot dong Reddit, mot dong nen tang trinh duyet."""
    return (
        "platform,handle,persona,daily_cap,start_warmup,"
        "client_id,client_secret,username,password,totp_seed,recovery_email\n"
        "reddit,seed_reddit_01,Hanoi students,3,yes,"
        "abc123,secret456,seed_reddit_01,hunter2,,\n"
        "facebook,seed.fb.01,Hanoi students,2,yes,"
        ",,,hunter2,JBSWY3DPEHPK3PXP,backup@example.com\n"
    )
