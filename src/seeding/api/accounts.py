"""Man hinh Tai khoan: danh sach, chi tiet, nhap hang loat, sua, xoa."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.api.deps import DEFAULT_PAGE, MAX_PAGE, get_session, paginate
from seeding.api.schemas import (
    AccountDetail,
    AccountPatch,
    AccountRow,
    DeleteOut,
    ImportResult,
    Page,
)
from seeding.domain import readiness
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountStatus,
    Attempt,
    Platform,
    PostJob,
    Profile,
    Proxy,
    ProxyStatus,
)
from seeding.ops import bulk

router = APIRouter(prefix="/accounts", tags=["accounts"])


def _warm_day(account: Account, now: datetime) -> int | None:
    if account.warmup_started_at is None:
        return None
    return (now - account.warmup_started_at).days + 1


def _row(account: Account, profile: Profile | None, verdict) -> AccountRow:
    out = AccountRow.model_validate(account)
    out.warm_day = _warm_day(account, datetime.now(UTC))
    if profile is not None:
        out.proxy_label = profile.proxy.label if profile.proxy else None
        # Chua kiem lan nao thi khong biet - None, khong phai False. Co phien (cookie)
        # ma bao 'chet' vi chua ai kiem la sai su that.
        out.session_alive = profile.session_alive if profile.last_health_at else None
    if verdict is not None:
        out.ready = verdict.ready
        out.blocked_reason = verdict.reason
    return out


@router.get("", response_model=Page[AccountRow])
async def list_accounts(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    platform: Platform | None = None,
    status: AccountStatus | None = None,
    ready: bool | None = None,
    s: AsyncSession = Depends(get_session),
) -> Page[AccountRow]:
    """Danh sach, loc ngay trong truy van. `ready` loc theo readiness (sau khi tai trang)."""
    stmt = select(Account).options(selectinload(Account.profile).selectinload(Profile.proxy))
    if q:
        stmt = stmt.where(Account.handle.ilike(f"%{q}%"))
    if platform is not None:
        stmt = stmt.where(Account.platform == platform)
    if status is not None:
        stmt = stmt.where(Account.status == status)

    # Loc theo readiness khong dich duoc thanh WHERE (no la logic Python), nen khi co
    # `ready` thi lay ca bang roi loc - doi tai khoan mot may la vai tram, chap nhan duoc.
    if ready is None:
        rows, total = await paginate(s, stmt.order_by(Account.created_at), limit, offset)
        accounts = [r[0] for r in rows]
    else:
        accounts = list((await s.execute(stmt.order_by(Account.created_at))).unique().scalars())
        accounts = [a for a in accounts if readiness.check(a, a.profile).ready is ready]
        total = len(accounts)
        accounts = accounts[offset : offset + limit]

    items = [_row(a, a.profile, readiness.check(a, a.profile)) for a in accounts]
    return Page[AccountRow](items=items, total=total, limit=limit, offset=offset)


@router.get("/import/template", response_class=PlainTextResponse)
async def import_template(seller: bool = True) -> str:
    """Mau dan vao. Mac dinh la dinh dang cua nguoi ban acc."""
    return bulk.seller_template() if seller else bulk.template()


def _report_out(report: bulk.Report) -> dict:
    """Bi mat KHONG di nguoc ra - chi so luong. Cookie la phien dang nhap song."""
    return {
        "ok": report.ok,
        "ready": len(report.rows),
        "with_cookies": report.with_cookies,
        "cookie_problems": report.cookie_problems,
        "rejoined_rows": report.rejoined_rows,
        "unknown_columns": report.unknown_columns,
        "renamed_columns": report.renamed_columns,
        "rows": [
            {
                "line": r.line,
                "platform": r.platform.value,
                "handle": r.handle,
                "daily_cap": r.daily_cap,
                "secret_count": len(r.secrets),
                "has_cookie": bool(r.cookie),
                "cookie_note": r.cookie_note,
            }
            for r in report.rows
        ],
        "problems": [
            {"line": p.line, "handle": p.handle, "detail": p.detail} for p in report.problems
        ],
    }


@router.post("/import/check")
async def import_check(
    text: str = Form(...),
    platform: Platform = Form(Platform.TIKTOK),
    s: AsyncSession = Depends(get_session),
) -> dict:
    """Kiem doan dan vao. KHONG tao gi ca."""
    if len(text) > 2_000_000:
        raise HTTPException(413, "Nhiều chữ hơn một danh sách tài khoản nên có.")
    report = await bulk.check_against_db(s, bulk.parse(text, default_platform=platform))
    return _report_out(report)


@router.post("/import", response_model=ImportResult)
async def import_accounts(
    text: str = Form(...),
    platform: Platform = Form(Platform.TIKTOK),
    partial: bool = Form(False),
    attach_proxies: bool = Form(True),
    s: AsyncSession = Depends(get_session),
) -> ImportResult:
    """Tao tai khoan tu doan dan vao. Dong co cookie thi tao luon profile co phien.

    `attach_proxies`: gan cho moi profile mot proxy CON RANH va da thu OK. Mot acc mot
    proxy, khong dung chung. Het proxy ranh thi acc con lai nam o "thieu proxy".
    """
    if len(text) > 2_000_000:
        raise HTTPException(413, "Nhiều chữ hơn một danh sách tài khoản nên có.")
    report = await bulk.check_against_db(s, bulk.parse(text, default_platform=platform))

    if report.problems and not partial:
        return ImportResult(
            created=0,
            handles=[],
            profiles_with_session=0,
            skipped=len(report.problems),
            warnings=[
                f"{len(report.problems)} dòng có vấn đề — chưa nhập gì. Sửa lại, hoặc chọn "
                "“nhập các dòng tốt”."
            ],
            problems=[
                {"line": p.line, "handle": p.handle, "detail": p.detail} for p in report.problems
            ],
        )
    if not report.rows:
        raise HTTPException(400, "Không có dòng nào dùng được.")

    spare: list[Proxy] = []
    if attach_proxies:
        spare = list(
            (
                await s.execute(
                    select(Proxy)
                    .outerjoin(Profile, Profile.proxy_id == Proxy.id)
                    .where(Profile.id.is_(None), Proxy.status == ProxyStatus.OK)
                    .order_by(Proxy.created_at)
                )
            )
            .unique()
            .scalars()
            .all()
        )

    workspace, persona = await ensure_defaults(s)
    try:
        created, warnings = await bulk.apply(
            s, workspace.id, report.rows, default_persona_id=persona.id, proxies=spare
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if attach_proxies and len(spare) < report.with_cookies:
        warnings.append(
            f"Chỉ có {len(spare)} proxy rảnh đã thử OK cho {report.with_cookies} tài khoản có "
            "phiên. Số còn lại đang thiếu proxy — dán thêm proxy là chúng dùng được."
        )

    return ImportResult(
        created=len(created),
        handles=[a.handle for a in created],
        profiles_with_session=report.with_cookies,
        skipped=len(report.problems),
        warnings=warnings,
        problems=[
            {"line": p.line, "handle": p.handle, "detail": p.detail} for p in report.problems
        ],
    )


@router.get("/{account_id}", response_model=AccountDetail)
async def get_account(
    account_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> AccountDetail:
    account = (
        (
            await s.execute(
                select(Account)
                .where(Account.id == account_id)
                .options(selectinload(Account.profile).selectinload(Profile.proxy))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if account is None:
        raise HTTPException(404, "Không có tài khoản này")

    profile = account.profile
    base = _row(account, profile, readiness.check(account, profile))
    out = AccountDetail(**base.model_dump())
    if profile is not None:
        jar = profile.get_cookies() or {}
        names = {c.get("name") for c in jar.get("cookies", [])}
        fp = profile.fingerprint or {}
        out.profile_id = profile.id
        out.cookie_count = len(names)
        out.session_cookie = bool(names & {"sessionid", "c_user", "sessionid_ss"})
        out.user_agent = fp.get("navigator.userAgent") or (fp.get("navigator") or {}).get(
            "userAgent"
        )
        out.timezone = fp.get("timezone") or None
        out.last_login_at = profile.last_login_at
        out.last_health_at = profile.last_health_at
        if profile.proxy is not None:
            out.proxy_host = f"{profile.proxy.host}:{profile.proxy.port}"
            out.proxy_exit_ip = profile.proxy.last_exit_ip
    return out


@router.patch("/{account_id}", response_model=AccountRow)
async def update_account(
    account_id: uuid.UUID, body: AccountPatch, s: AsyncSession = Depends(get_session)
) -> AccountRow:
    account = (
        (
            await s.execute(
                select(Account)
                .where(Account.id == account_id)
                .options(selectinload(Account.profile).selectinload(Profile.proxy))
            )
        )
        .unique()
        .scalar_one_or_none()
    )
    if account is None:
        raise HTTPException(404, "Không có tài khoản này")
    if body.status is not None:
        account.status = body.status
    if body.daily_cap is not None:
        account.daily_cap = body.daily_cap
    await s.commit()
    return _row(account, account.profile, readiness.check(account, account.profile))


@router.delete("/{account_id}", response_model=DeleteOut)
async def delete_account(
    account_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa han. Co bai da dang thi phai force - xoa la mat luon bang chung vi sao no chet."""
    account = await s.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "Không có tài khoản này")
    posted = int(
        (
            await s.execute(
                select(func.count())
                .select_from(Attempt)
                .join(PostJob, PostJob.id == Attempt.job_id)
                .where(PostJob.account_id == account_id, Attempt.ok.is_(True))
            )
        ).scalar_one()
    )
    if posted and not force:
        raise HTTPException(
            409,
            f"{account.handle} đã đăng {posted} bài. Xoá là mất lịch sử đó — muốn xoá thật thì "
            "gửi force=true.",
        )
    handle = account.handle
    await s.delete(account)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"Đã xoá {handle}")
