from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, selectinload

from seeding.config import get_settings
from seeding.core import activity as activity_mod
from seeding.core import bulk, graph, proxylist, readiness, recurring, survival, takeover, vault
from seeding.core import desktop as desktop_mod
from seeding.core import devices as devices_mod
from seeding.core import fingerprint as fpm
from seeding.core import hashtags as tags_mod
from seeding.core import profiles as profiles_mod
from seeding.core import slots as slots_mod
from seeding.core.planner import plan_campaign
from seeding.core.spintax import combinations, content_hash, expand, rng_for
from seeding.db import get_session
from seeding.models import (
    Account,
    AccountStatus,
    ActivityJob,
    Attempt,
    Campaign,
    CampaignGroup,
    ContentItem,
    Device,
    DeviceStatus,
    HashtagSet,
    JobStatus,
    Persona,
    Platform,
    PlatformWindow,
    PostJob,
    PostSlot,
    Profile,
    Proxy,
    ProxyKind,
    ProxyStatus,
    Relationship,
    Repeat,
    SessionEvent,
    TakeoverRequest,
    TakeoverStatus,
    Workspace,
)
from seeding.schemas import (
    AccountIn,
    AccountOut,
    AccountPatch,
    ActivityOut,
    CampaignIn,
    CampaignOut,
    CampaignPatch,
    CampaignSummary,
    ContentIn,
    ContentOut,
    ContentPatch,
    ContentSummary,
    DeleteOut,
    DeviceIn,
    DeviceOut,
    DevicePatch,
    GroupIn2,
    GroupOut,
    JobOut,
    NamedOut,
    OpenProfileIn,
    OpenProfileOut,
    Page,
    PersonaIn,
    PreviewIn,
    PreviewOut,
    PreviewSample,
    ProfileIn,
    ProfileOut,
    ProfilePatch,
    ProxyIn,
    ProxyOut,
    ProxyPatch,
    ProxyTestAllOut,
    ProxyTestAllRow,
    ProxyTestOut,
    RenameIn,
    ResolveIn,
    SessionEventOut,
    SlotIn,
    SlotMeta,
    SlotOut,
    StatsOut,
    TakeoverOut,
    WindowIn,
    WindowOut,
    WorkspaceIn,
    WorkspaceOut,
)

router = APIRouter()


# Tran cung cho mot lan goi. Khong phai de tiet kiem bang - de mot loi go nham
# `limit=100000` khong keo ca database vao bo nho roi lam chet API.
MAX_PAGE = 500
DEFAULT_PAGE = 50


async def _paginate[T](s: AsyncSession, stmt, limit: int, offset: int) -> tuple[list, int]:
    """Lay mot trang, kem tong so ban ghi khop dieu kien loc.

    Dem bang mot cau rieng dung tren cung dieu kien WHERE. Dem trong Python sau khi
    da LIMIT thi con so tra ve luon bang so dong cua trang - dung nhu cai khong ai
    can biet.
    """
    total = int(
        (
            await s.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    )
    rows = (await s.execute(stmt.limit(limit).offset(offset))).unique().all()
    return rows, total


# Nhung so do Playwright chap nhan cho proxy.
PROXY_SCHEMES = {"http", "https", "socks5"}

# Proxy mat hon chung nay giay de tra loi thi cung khong dung duoc cho automation:
# mot phien trinh duyet co hang chuc request, va cho lau nhu vay la job het gio.
# Con so nay cung quyet dinh 'test all' mat bao lau khi ca dai proxy deu chet.
PROXY_TEST_TIMEOUT = 12


@router.post("/workspaces")
async def create_workspace(body: WorkspaceIn, s: AsyncSession = Depends(get_session)) -> dict:
    ws = Workspace(name=body.name)
    s.add(ws)
    await s.commit()
    return {"id": str(ws.id), "name": ws.name}


@router.get("/stats", response_model=StatsOut)
async def stats(s: AsyncSession = Depends(get_session)) -> StatsOut:
    """Nhung con so dashboard can, gom trong mot lan goi."""

    async def count(stmt) -> int:
        return int((await s.execute(stmt)).scalar_one())

    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    base = select(func.count())

    return StatsOut(
        accounts=await count(base.select_from(Account)),
        accounts_needing_human=await count(
            base.select_from(Account).where(Account.status == AccountStatus.NEEDS_HUMAN)
        ),
        profiles_alive=await count(
            base.select_from(Profile).where(Profile.session_alive.is_(True))
        ),
        profiles_total=await count(base.select_from(Profile)),
        jobs_scheduled=await count(
            base.select_from(PostJob).where(PostJob.status == JobStatus.SCHEDULED)
        ),
        jobs_succeeded=await count(
            base.select_from(PostJob).where(PostJob.status == JobStatus.SUCCEEDED)
        ),
        jobs_failed=await count(
            base.select_from(PostJob).where(PostJob.status == JobStatus.FAILED)
        ),
        activity_scheduled_today=await count(
            base.select_from(ActivityJob).where(
                ActivityJob.scheduled_at >= today,
                ActivityJob.status == JobStatus.SCHEDULED,
            )
        ),
    )


@router.get("/workspaces", response_model=list[NamedOut])
async def list_workspaces(s: AsyncSession = Depends(get_session)) -> list[Workspace]:
    stmt = select(Workspace).order_by(Workspace.created_at)
    return list((await s.execute(stmt)).scalars().all())


@router.get("/workspaces/detail", response_model=list[WorkspaceOut])
async def workspace_detail(s: AsyncSession = Depends(get_session)) -> list[WorkspaceOut]:
    """Workspace kem so thu moi cai dang giu.

    Dem bang bon cau gom nhom thay vi mot cau cho moi workspace: danh sach nay co the
    dai, va N+1 truy van cho mot man hinh cai dat la cach de nhat de no cham dan ma
    khong ai de y.
    """
    workspaces = list((await s.execute(select(Workspace).order_by(Workspace.created_at))).scalars())

    persona_counts = dict(
        (
            await s.execute(
                select(Persona.workspace_id, func.count()).group_by(Persona.workspace_id)
            )
        ).all()
    )
    account_counts = dict(
        (
            await s.execute(
                select(Persona.workspace_id, func.count())
                .join(Account, Account.persona_id == Persona.id)
                .group_by(Persona.workspace_id)
            )
        ).all()
    )
    campaign_counts = dict(
        (
            await s.execute(
                select(Campaign.workspace_id, func.count()).group_by(Campaign.workspace_id)
            )
        ).all()
    )
    content_counts = dict(
        (
            await s.execute(
                select(ContentItem.workspace_id, func.count()).group_by(ContentItem.workspace_id)
            )
        ).all()
    )

    return [
        WorkspaceOut(
            id=w.id,
            name=w.name,
            personas=persona_counts.get(w.id, 0),
            accounts=account_counts.get(w.id, 0),
            campaigns=campaign_counts.get(w.id, 0),
            content=content_counts.get(w.id, 0),
        )
        for w in workspaces
    ]


@router.patch("/workspaces/{workspace_id}", response_model=NamedOut)
async def rename_workspace(
    workspace_id: uuid.UUID, body: RenameIn, s: AsyncSession = Depends(get_session)
) -> Workspace:
    workspace = await s.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(404, "No such workspace")
    workspace.name = body.name
    await s.commit()
    return workspace


@router.delete("/workspaces/{workspace_id}", response_model=DeleteOut)
async def delete_workspace(
    workspace_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa mot workspace va moi thu ben trong.

    Day la thao tac xoa nang nhat trong ca he thong: no keo theo persona, tai khoan,
    profile, va cookie jar cua tung profile. Mat cookie jar nghia la phai dang nhap tay
    lai tung tai khoan mot - khong khoi phuc duoc.
    """
    workspace = await s.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(404, "No such workspace")

    accounts = int(
        (
            await s.execute(
                select(func.count())
                .select_from(Account)
                .join(Persona, Persona.id == Account.persona_id)
                .where(Persona.workspace_id == workspace_id)
            )
        ).scalar_one()
    )
    campaigns = int(
        (
            await s.execute(
                select(func.count())
                .select_from(Campaign)
                .where(Campaign.workspace_id == workspace_id)
            )
        ).scalar_one()
    )

    if (accounts or campaigns) and not force:
        raise HTTPException(
            409,
            f"{workspace.name} still holds {accounts} account(s) and {campaigns} campaign(s). "
            "Deleting it removes them, their profiles, and the saved logins inside — those "
            "cannot be recovered, only signed in again by hand. Delete with force=true if that "
            "is what you want.",
        )

    name = workspace.name
    await s.delete(workspace)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{name} removed")


@router.get("/personas", response_model=list[NamedOut])
async def list_personas(
    workspace_id: uuid.UUID | None = None, s: AsyncSession = Depends(get_session)
) -> list[Persona]:
    """Persona, loc theo workspace.

    Truoc day tra ve TAT CA persona cua moi workspace. Hau qua khong phai la danh sach
    dai - la o chon workspace tro nen vo nghia: chon workspace nao thi danh sach persona
    van y het, va chon mot persona co san se lang le dat tai khoan vao workspace cua
    persona do chu khong phai cai vua chon.
    """
    stmt = select(Persona).order_by(Persona.created_at)
    if workspace_id is not None:
        stmt = stmt.where(Persona.workspace_id == workspace_id)
    return list((await s.execute(stmt)).scalars().all())


@router.post("/personas")
async def create_persona(body: PersonaIn, s: AsyncSession = Depends(get_session)) -> dict:
    persona = Persona(**body.model_dump())
    s.add(persona)
    await s.commit()
    return {"id": str(persona.id), "name": persona.name}


@router.post("/accounts", response_model=AccountOut)
async def create_account(body: AccountIn, s: AsyncSession = Depends(get_session)) -> Account:
    data = body.model_dump()
    start_warmup = data.pop("start_warmup")
    secrets = data.pop("secrets")
    account = Account(**data)
    if secrets:
        account.set_secrets(secrets)
    if start_warmup:
        account.warmup_started_at = datetime.now(UTC)
        account.status = AccountStatus.WARMING
    s.add(account)
    await s.commit()
    return account


@router.get("/accounts", response_model=Page[AccountOut])
async def list_accounts(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    platform: Platform | None = None,
    status: AccountStatus | None = None,
    workspace_id: uuid.UUID | None = None,
    s: AsyncSession = Depends(get_session),
) -> Page[AccountOut]:
    """Danh sach tai khoan, mot trang mot lan.

    Loc ngay trong cau truy van chu khong loc o giao dien: voi 200 tai khoan thi tai
    het ve roi loc bang JavaScript nghia la tai 200 ban ghi de hien ra 8 cai.
    """
    stmt = select(Account)
    if q:
        stmt = stmt.where(Account.handle.ilike(f"%{q}%"))
    if platform is not None:
        stmt = stmt.where(Account.platform == platform)
    if status is not None:
        stmt = stmt.where(Account.status == status)
    if workspace_id is not None:
        # Tai khoan khong tro thang vao workspace - no di qua persona.
        stmt = stmt.join(Persona, Persona.id == Account.persona_id).where(
            Persona.workspace_id == workspace_id
        )

    rows, total = await _paginate(s, stmt.order_by(Account.created_at), limit, offset)

    accounts = [r[0] for r in rows]
    state = await readiness.for_accounts(s, [a.id for a in accounts])

    items = []
    for account in accounts:
        out = AccountOut.model_validate(account)
        verdict = state.get(account.id)
        if verdict is not None:
            out.ready = verdict.ready
            out.blocked_reason = verdict.reason
        items.append(out)

    return Page[AccountOut](items=items, total=total, limit=limit, offset=offset)


@router.get("/accounts/without-profile", response_model=list[AccountOut])
async def accounts_without_profile(s: AsyncSession = Depends(get_session)) -> list[Account]:
    """Tai khoan chua co profile - chung khong dang duoc bai nao.

    Co endpoint rieng vi day la mot phep doi chieu giua HAI bang. Truoc khi phan trang
    thi giao dien tu doi chieu duoc; sau khi phan trang thi no chi con thay trang dau
    cua moi ben, va canh bao se sai ngay khi vuot qua trang mot.
    """
    stmt = (
        select(Account)
        .outerjoin(Profile, Profile.account_id == Account.id)
        .where(
            Profile.id.is_(None),
            # Reddit di bang API, khong can profile.
            Account.platform != Platform.REDDIT,
            Account.status != AccountStatus.DEAD,
        )
        .order_by(Account.created_at)
    )
    return list((await s.execute(stmt)).unique().scalars().all())


@router.get("/accounts/needs-human", response_model=list[AccountOut])
async def accounts_needing_a_person(s: AsyncSession = Depends(get_session)) -> list[Account]:
    """Hang doi can thiep tay: tai khoan da het duong tu dong xu ly.

    Khoi phuc bang: python scripts/login_profile.py <platform> <handle>
    """
    stmt = select(Account).where(Account.status == AccountStatus.NEEDS_HUMAN)
    return list((await s.execute(stmt)).scalars().all())


@router.patch("/accounts/{account_id}", response_model=AccountOut)
async def update_account(
    account_id: uuid.UUID, body: AccountPatch, s: AsyncSession = Depends(get_session)
) -> Account:
    account = await s.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "No such account")

    if body.handle is not None:
        account.handle = body.handle
    if body.status is not None:
        account.status = body.status
    if body.daily_cap is not None:
        account.daily_cap = body.daily_cap

    if body.secrets:
        # Tron vao bi mat cu chu khong ghi de ca cum: sua rieng mat khau khong duoc
        # lam mat totp_seed, va nguoi sua cung khong doc lai duoc gia tri cu de gui kem.
        merged = account.get_secrets()
        merged.update({k: v for k, v in body.secrets.items() if v not in (None, "")})
        account.set_secrets(merged)

    await s.commit()
    return account


@router.delete("/accounts/{account_id}", response_model=DeleteOut)
async def delete_account(
    account_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa han mot tai khoan.

    Thuong ban muon `abandon` o hang doi tiep quan chu khong phai xoa: xoa la mat ca
    nhat ky phien va lich su dang bai, tuc la mat luon bang chung de biet vi sao no
    chet. Vi vay co bai da dang thi phai force.
    """
    account = await s.get(Account, account_id)
    if account is None:
        raise HTTPException(404, "No such account")

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
            f"{account.handle} has {posted} published post(s). Deleting loses that history — "
            "mark it abandoned instead, or delete with force=true.",
        )

    handle = account.handle
    await s.delete(account)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{handle} removed")


@router.post("/proxies", response_model=ProxyOut)
async def create_proxy(body: ProxyIn, s: AsyncSession = Depends(get_session)) -> Proxy:
    data = body.model_dump()
    password = data.pop("password")
    proxy = Proxy(**data)
    proxy.set_password(password)
    s.add(proxy)
    await s.commit()
    return proxy


@router.get("/proxies", response_model=Page[ProxyOut])
async def list_proxies(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    status: ProxyStatus | None = None,
    s: AsyncSession = Depends(get_session),
) -> Page[ProxyOut]:
    stmt = select(Proxy)
    if q:
        stmt = stmt.where(Proxy.label.ilike(f"%{q}%") | Proxy.host.ilike(f"%{q}%"))
    if status is not None:
        stmt = stmt.where(Proxy.status == status)

    rows, total = await _paginate(s, stmt.order_by(Proxy.created_at), limit, offset)
    return Page[ProxyOut](
        items=[ProxyOut.model_validate(r[0]) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/proxies/{proxy_id}", response_model=ProxyOut)
async def update_proxy(
    proxy_id: uuid.UUID, body: ProxyPatch, s: AsyncSession = Depends(get_session)
) -> Proxy:
    proxy = await s.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(404, "No such proxy")

    data = body.model_dump(exclude_unset=True)
    password = data.pop("password", None)

    if (scheme := data.get("scheme")) and scheme.lower() not in PROXY_SCHEMES:
        raise HTTPException(422, f"scheme must be one of {sorted(PROXY_SCHEMES)}")

    for key, value in data.items():
        if value is not None:
            setattr(proxy, key, value)
    if password:
        proxy.set_password(password)

    await s.commit()
    return proxy


@router.delete("/proxies/{proxy_id}", response_model=DeleteOut)
async def delete_proxy(proxy_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> DeleteOut:
    """Xoa proxy. Tu choi neu con profile dang gan vao no.

    Khong cho force o day: xoa proxy cua mot profile dang chay se lam profile do mo
    trinh duyet bang IP that cua may ban - dung thu phai tranh nhat.
    """
    proxy = await s.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(404, "No such proxy")

    bound = (
        (await s.execute(select(Profile).where(Profile.proxy_id == proxy_id)))
        .unique()
        .scalars()
        .all()
    )
    if bound:
        raise HTTPException(
            409,
            f"{len(bound)} profile(s) are bound to this proxy. Removing it would make them "
            "open a browser on your real IP. Rebind them first.",
        )

    label = proxy.label
    await s.delete(proxy)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{label} removed")


@router.post("/proxies/{proxy_id}/test", response_model=ProxyTestOut)
async def test_proxy(proxy_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> ProxyTestOut:
    """Ket noi that qua proxy va hoi xem no ra Internet bang IP nao.

    Ghi ket qua lai vao proxy: mot proxy chua bao gio duoc thu la mot an so, va an so
    thi khong nen gan vao tai khoan.
    """
    proxy = await s.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(404, "No such proxy")

    result = await _run_proxy_test(proxy)
    await s.commit()

    return result


def explain_proxy_failure(exc: Exception, proxy: Proxy) -> str:
    """Doi loi mang thanh mot cau noi ro phai lam gi.

    `ProxyError: 407 Proxy Authentication Required` la chinh xac ve ky thuat va vo dung
    ve thuc hanh: no khong noi rang o Username dang de trong. Nguoi van hanh cam mot
    proxy vao roi thay chu do se di kiem tra host, port, tuong lua - moi thu tru thu
    that su sai.
    """
    raw = f"{type(exc).__name__}: {exc}"
    text = str(exc).lower()

    if "407" in text or "proxy authentication" in text:
        if not proxy.username:
            return (
                "This proxy needs a username and password, and none are set. Press edit and "
                f"fill them in — the provider gives them alongside {proxy.host}. ({raw})"
            )
        return (
            f"The proxy rejected the username '{proxy.username}'. Either the password is wrong, "
            f"or the provider expects a different username format. ({raw})"
        )

    if "getaddrinfo" in text or "name or service" in text or "nodename" in text:
        return (
            f"The hostname {proxy.host} does not resolve. Check it for a typo — this failed "
            f"before any connection was attempted. ({raw})"
        )

    if "timed out" in text or "timeout" in text:
        return (
            f"No answer from {proxy.host}:{proxy.port} within {PROXY_TEST_TIMEOUT}s. The proxy "
            "may be down, the port wrong, or your IP not on the provider's allow-list. "
            f"({raw})"
        )

    if "connection refused" in text or "actively refused" in text:
        return (
            f"{proxy.host} answered but refused the connection on port {proxy.port}. That is "
            f"usually the wrong port, or the wrong scheme — this one is set to {proxy.scheme}. "
            f"({raw})"
        )

    if "403" in text:
        return (
            "The proxy accepted the login but refused the request. Providers do this when the "
            f"plan has run out or the target is blocked. ({raw})"
        )

    return raw


async def _run_proxy_test(proxy: Proxy) -> ProxyTestOut:
    """Di ra Internet that qua proxy va hoi xem no ra bang IP nao.

    Ghi ket qua len chinh doi tuong proxy; nguoi goi commit. Mot proxy chua bao gio
    duoc thu la mot an so, va an so thi khong nen gan vao tai khoan.
    """
    url = proxy.as_playwright_proxy()["server"]
    if proxy.username:
        auth = f"{proxy.username}:{proxy.get_password() or ''}@"
        url = url.replace("://", f"://{auth}", 1)

    started = time.perf_counter()
    result = ProxyTestOut(ok=False, exit_ip=None, latency_ms=None, error=None)
    try:
        async with httpx.AsyncClient(proxy=url, timeout=PROXY_TEST_TIMEOUT) as client:
            response = await client.get("https://api.ipify.org?format=json")
            response.raise_for_status()
            result.exit_ip = response.json().get("ip")
            result.ok = True
    except Exception as exc:
        result.error = explain_proxy_failure(exc, proxy)

    result.latency_ms = int((time.perf_counter() - started) * 1000)

    proxy.status = ProxyStatus.OK if result.ok else ProxyStatus.FAILING
    proxy.last_checked_at = datetime.now(UTC)
    proxy.last_exit_ip = result.exit_ip
    proxy.last_error = result.error
    return result


@router.post("/proxies/import")
async def import_proxies(
    text: str = Form(...),
    label_prefix: str = "P",
    kind: ProxyKind = ProxyKind.RESIDENTIAL,
    region: str | None = None,
    scheme: str = "http",
    test: bool = True,
    s: AsyncSession = Depends(get_session),
) -> dict:
    """Them nhieu proxy mot lan, tu danh sach dan vao.

    Bat bien cua he thong la mot acc mot proxy, nen so proxy luon phai bang so tai
    khoan. Them tung cai qua form la viec on voi hai proxy va vo ly voi bon muoi.

    Nhan bon dinh dang hay gap: `host:port`, `host:port:user:pass`,
    `user:pass@host:port`, va co ca `scheme://` o dau.

    `test=true` thi thu tung cai ngay sau khi tao. Mot proxy chua bao gio duoc thu la
    mot an so, va an so thi khong nen gan vao tai khoan.
    """
    if scheme.lower() not in PROXY_SCHEMES:
        raise HTTPException(422, f"scheme must be one of {sorted(PROXY_SCHEMES)}")

    report = proxylist.parse(text, default_scheme=scheme.lower())

    existing = {
        (p.host.lower(), p.port) for p in (await s.execute(select(Proxy))).unique().scalars().all()
    }

    created: list[Proxy] = []
    skipped: list[dict] = []

    # Danh nhan theo so dang co thi xoa vai cai roi them lai se sinh ra nhan TRUNG, va
    # hai dong trong bang trong y het nhau. Voi mot he thong ma bat bien la "mot acc
    # mot proxy", hai proxy khong phan biet duoc bang mat la mot cai bay.
    taken = set((await s.execute(select(Proxy.label))).scalars().all())
    counter = 1

    def next_label() -> str:
        nonlocal counter
        while True:
            candidate = f"{label_prefix}{counter:02d}"
            counter += 1
            if candidate not in taken:
                taken.add(candidate)
                return candidate

    for parsed in report.rows:
        if (parsed.host.lower(), parsed.port) in existing:
            skipped.append(
                {
                    "line": parsed.line,
                    "raw": f"{parsed.host}:{parsed.port}",
                    "detail": "already registered",
                }
            )
            continue

        proxy = Proxy(
            label=next_label(),
            host=parsed.host,
            port=parsed.port,
            scheme=parsed.scheme,
            username=parsed.username,
            kind=kind,
            region=region,
        )
        if parsed.password:
            proxy.set_password(parsed.password)
        s.add(proxy)
        created.append(proxy)
        existing.add((parsed.host.lower(), parsed.port))

    await s.commit()

    results: list[dict] = []
    if test and created:
        for proxy in created:
            outcome = await _run_proxy_test(proxy)
            results.append(
                {
                    "label": proxy.label,
                    "ok": outcome.ok,
                    "exit_ip": outcome.exit_ip,
                    "error": outcome.error,
                }
            )
        await s.commit()

    # Hai proxy ra cung mot IP la MOT loi ra duoc dem thanh hai - va bat bien
    # mot-acc-mot-proxy im lang vo ma khong co dau hieu gi.
    exits = [r["exit_ip"] for r in results if r["exit_ip"]]
    duplicates = sorted({ip for ip in exits if exits.count(ip) > 1})

    return {
        "created": len(created),
        "labels": [p.label for p in created],
        "tested": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "duplicate_exit_ips": duplicates,
        "results": results,
        "skipped": skipped,
        "problems": [{"line": p.line, "raw": p.raw, "detail": p.detail} for p in report.problems],
    }


@router.post("/proxies/test-all", response_model=ProxyTestAllOut)
async def test_all_proxies(s: AsyncSession = Depends(get_session)) -> ProxyTestAllOut:
    """Thu lan luot moi proxy.

    Chay tuan tu chu khong song song: bat hai muoi ket noi ra cung luc tu cung mot may
    la dung mau hinh ma nha cung cap proxy hay chan.

    Bao cao them cac IP bi trung: hai proxy ra cung mot loi thi thuc te ban chi co MOT
    loi ra, va hai tai khoan gan vao chung dang dung chung dia chi ma khong biet.
    """
    proxies = (await s.execute(select(Proxy).order_by(Proxy.created_at))).scalars().all()

    rows: list[ProxyTestAllRow] = []
    for proxy in proxies:
        result = await _run_proxy_test(proxy)
        rows.append(ProxyTestAllRow(id=proxy.id, label=proxy.label, **result.model_dump()))
    await s.commit()

    seen: dict[str, int] = {}
    for row in rows:
        if row.exit_ip:
            seen[row.exit_ip] = seen.get(row.exit_ip, 0) + 1

    return ProxyTestAllOut(
        tested=len(rows),
        passed=sum(1 for r in rows if r.ok),
        results=rows,
        duplicate_exit_ips=sorted(ip for ip, n in seen.items() if n > 1),
    )


@router.patch("/profiles/{profile_id}", response_model=ProfileOut)
async def update_profile(
    profile_id: uuid.UUID, body: ProfilePatch, s: AsyncSession = Depends(get_session)
) -> ProfileOut:
    """Sua profile. Fingerprint co y KHONG sua duoc - no la danh tinh, khong phai cai dat."""
    profile = await s.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "No such profile")

    if body.engine is not None:
        profile.engine = body.engine
    if body.locale is not None:
        profile.locale = body.locale

    if body.proxy_id is not None and body.proxy_id != profile.proxy_id:
        proxy = await s.get(Proxy, body.proxy_id)
        if proxy is None:
            raise HTTPException(404, "No such proxy")
        try:
            await profiles_mod.bind_proxy(
                s, profile, proxy, force=body.force_rebind, reason=body.rebind_reason
            )
        except profiles_mod.ProfileError as exc:
            raise HTTPException(409, str(exc)) from exc

    await s.commit()
    account = await s.get(Account, profile.account_id)
    proxy = await s.get(Proxy, profile.proxy_id) if profile.proxy_id else None
    return _profile_out(profile, account, proxy)


@router.delete("/profiles/{profile_id}", response_model=DeleteOut)
async def delete_profile(
    profile_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa profile va cookie jar cua no.

    Day la hanh dong MAT PHIEN: xoa xong thi tai khoan phai dang nhap tay lai tu dau,
    va lan tao profile moi se sinh fingerprint khac han. Vi vay profile con phien song
    thi phai force.
    """
    profile = await s.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "No such profile")

    account = await s.get(Account, profile.account_id)
    handle = account.handle if account else "this account"

    if profile.cookies_enc and not force:
        raise HTTPException(
            409,
            f"{handle} has a stored session. Deleting the profile throws away the cookie jar "
            "and the pinned fingerprint — you would have to sign in by hand again and the new "
            "profile would look like a different machine. Delete with force=true if you mean it.",
        )

    await s.delete(profile)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"profile for {handle} removed")


@router.post("/profiles", response_model=ProfileOut)
async def create_profile(body: ProfileIn, s: AsyncSession = Depends(get_session)) -> ProfileOut:
    """Tao danh tinh trinh duyet cho mot tai khoan. Chi goi duoc mot lan.

    Sau buoc nay, dang nhap bang tay: python scripts/login_profile.py <platform> <handle>
    """
    account = await s.get(Account, body.account_id)
    if account is None:
        raise HTTPException(404, "No such account")

    proxy = await s.get(Proxy, body.proxy_id) if body.proxy_id else None
    if body.proxy_id and proxy is None:
        raise HTTPException(404, "No such proxy")

    try:
        profile = await profiles_mod.create_profile(
            s,
            account,
            proxy=proxy,
            engine=body.engine,
            os_family=body.os_family,
            locale=body.locale,
        )
    except profiles_mod.ProfileError as exc:
        raise HTTPException(409, str(exc)) from exc

    return _profile_out(profile, account, proxy)


@router.get("/profiles", response_model=Page[ProfileOut])
async def list_profiles(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    platform: Platform | None = None,
    alive: bool | None = None,
    logged_in: bool | None = None,
    s: AsyncSession = Depends(get_session),
) -> Page[ProfileOut]:
    stmt = select(Profile, Account).join(Account, Account.id == Profile.account_id)
    if q:
        stmt = stmt.where(Account.handle.ilike(f"%{q}%"))
    if platform is not None:
        stmt = stmt.where(Account.platform == platform)
    if alive is not None:
        stmt = stmt.where(Profile.session_alive.is_(alive))
    if logged_in is not None:
        # Profile chua tung dang nhap la mot hang doi viec phai lam, khong phai mot bo
        # loc trang tri: chung khong dang duoc bai nao cho toi khi co nguoi dang nhap tay.
        stmt = stmt.where(
            Profile.last_login_at.isnot(None) if logged_in else Profile.last_login_at.is_(None)
        )

    rows, total = await _paginate(s, stmt.order_by(Profile.created_at), limit, offset)
    return Page[ProfileOut](
        items=[_profile_out(profile, account, profile.proxy) for profile, account in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/profiles/{profile_id}/events", response_model=list[SessionEventOut])
async def profile_events(
    profile_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> list[SessionEvent]:
    """Nhat ky vong doi phien - bang chung phien song duoc bao lau."""
    stmt = (
        select(SessionEvent)
        .where(SessionEvent.profile_id == profile_id)
        .order_by(SessionEvent.created_at.desc())
        .limit(200)
    )
    return list((await s.execute(stmt)).scalars().all())


@router.post("/profiles/{profile_id}/open", response_model=OpenProfileOut)
async def open_profile_window(
    profile_id: uuid.UUID,
    body: OpenProfileIn | None = None,
    s: AsyncSession = Depends(get_session),
) -> OpenProfileOut:
    """Mo cua so trinh duyet that cua profile nay, ngay tren may dang chay API.

    Dung de nhin tan mat mot tai khoan: kiem tra con dang nhap khong, dang nhap lai,
    giai captcha, hay chi de xem trang no thay la trang gi. Cookie duoc luu lai khi
    ban dong cua so, nen moi thu lam bang tay deu duoc giu.

    KHONG mo khi profile chua co proxy. Mo tay khong phai ngoai le cua bat bien do -
    trinh duyet se di ra bang IP nha ban va nen tang ghi lai dieu do y het nhu khi
    worker chay.
    """
    profile = await s.get(Profile, profile_id)
    if profile is None:
        raise HTTPException(404, "No such profile")

    account = await s.get(Account, profile.account_id)
    if account is None:
        raise HTTPException(409, "This profile is not attached to an account")

    verdict = readiness.check(account, profile)
    if profile.proxy_id is None:
        raise HTTPException(409, verdict.reason or "this profile has no proxy")

    url = body.url if body else None
    pid = desktop_mod.spawn(profile.id, url)

    # Phien chua dang nhap van mo duoc - do chinh la luc can mo nhat. Chi noi ro ra
    # de nguoi dung biet truoc se thay man hinh dang nhap chu khong phai feed.
    note = (
        "Browser opening. Close the window when done and the cookies are saved."
        if profile.cookies_enc
        else "Browser opening, but this profile has never signed in - expect a login screen."
    )
    return OpenProfileOut(
        profile_id=profile.id, handle=account.handle, pid=pid, url=url, detail=note
    )


def _profile_out(profile: Profile, account: Account, proxy: Proxy | None) -> ProfileOut:
    return ProfileOut(
        id=profile.id,
        account_id=account.id,
        handle=account.handle,
        platform=account.platform,
        engine=profile.engine,
        fingerprint=fpm.summary(profile.fingerprint),
        proxy_label=proxy.label if proxy else None,
        session_alive=profile.session_alive,
        last_login_at=profile.last_login_at,
        last_health_at=profile.last_health_at,
        consecutive_health_failures=profile.consecutive_health_failures,
    )


@router.get("/takeovers", response_model=list[TakeoverOut])
async def list_takeovers(s: AsyncSession = Depends(get_session)) -> list[TakeoverOut]:
    """Hang doi can thiep tay - nhung tai khoan he thong da dung lai va cho nguoi."""
    return [
        TakeoverOut(
            id=r.id,
            created_at=r.created_at,
            handle=r.account.handle,
            platform=r.account.platform,
            reason=r.reason,
            status=r.status,
            has_stuck_job=r.post_job_id is not None,
        )
        for r in await takeover.list_open(s)
    ]


@router.get("/takeovers/{takeover_id}/totp")
async def takeover_totp(takeover_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> dict:
    """Ma 2FA hien tai cua tai khoan dang bi ket.

    Chi tra ve sau chu so, khong bao gio tra ve seed. Nguoi van hanh can ma nay de go
    vao trinh duyet dang mo - khong co no thi man hinh tiep quan gan nhu vo dung.
    """
    request = await s.get(TakeoverRequest, takeover_id)
    if request is None:
        raise HTTPException(404, "No such takeover request")

    account = await s.get(Account, request.account_id)
    seed = (account.get_secrets() or {}).get("totp_seed") if account else None
    if not seed:
        return {"code": None, "note": "no totp_seed stored for this account"}

    return {"code": vault.totp_now(seed), "note": "rotates every 30 seconds"}


@router.post("/takeovers/{takeover_id}/resolve", response_model=TakeoverOut)
async def resolve_takeover(
    takeover_id: uuid.UUID, body: ResolveIn, s: AsyncSession = Depends(get_session)
) -> TakeoverOut:
    """Nguoi da giai xong. Job bi ket duoc hen lai chu khong chay ngay."""
    request = await _open_takeover(s, takeover_id)
    await takeover.resolve(s, request, by=body.by, note=body.note)
    return _takeover_out(request)


@router.post("/takeovers/{takeover_id}/abandon", response_model=TakeoverOut)
async def abandon_takeover(
    takeover_id: uuid.UUID, body: ResolveIn, s: AsyncSession = Depends(get_session)
) -> TakeoverOut:
    """Tai khoan khong cuu duoc nua - chuyen sang DEAD."""
    request = await _open_takeover(s, takeover_id)
    await takeover.abandon(s, request, by=body.by, note=body.note or "khong ghi ly do")
    return _takeover_out(request)


async def _open_takeover(s: AsyncSession, takeover_id: uuid.UUID) -> TakeoverRequest:
    request = await s.get(TakeoverRequest, takeover_id)
    if request is None:
        raise HTTPException(404, "No such takeover request")
    if request.status != TakeoverStatus.OPEN:
        raise HTTPException(409, f"This request is already {request.status.value}")
    return request


def _takeover_out(r: TakeoverRequest) -> TakeoverOut:
    return TakeoverOut(
        id=r.id,
        created_at=r.created_at,
        handle=r.account.handle,
        platform=r.account.platform,
        reason=r.reason,
        status=r.status,
        has_stuck_job=r.post_job_id is not None,
    )


@router.post("/activity/plan")
async def plan_activity(s: AsyncSession = Depends(get_session)) -> dict:
    """Lap lich hoat dong nen cho hom nay. Goi lai trong ngay khong nhan doi lich."""
    created = await activity_mod.plan_all(s)
    return {"created": created}


@router.get("/accounts/{account_id}/activity", response_model=list[ActivityOut])
async def account_activity(
    account_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> list[ActivityJob]:
    stmt = (
        select(ActivityJob)
        .where(ActivityJob.account_id == account_id)
        .order_by(ActivityJob.scheduled_at)
        .limit(200)
    )
    return list((await s.execute(stmt)).unique().scalars().all())


@router.post("/content/preview", response_model=PreviewOut)
async def preview_content(body: PreviewIn, s: AsyncSession = Depends(get_session)) -> PreviewOut:
    """Xem truoc cac bien the, va uoc luong nguy co hai tai khoan trung bai.

    So to hop cua template moi la con so quyet dinh, khong phai ve ngoai cua vai mau
    o tren: bai trung nhau giua cac tai khoan la tin hieu spam ro nhat.

    Mau o day dung seed tam; to hop that phu thuoc vao id chien dich, nen cu the se
    khac. Nhung so to hop va nguy co trung thi dung.
    """
    pools: dict[str, list[str]] = {}
    if body.workspace_id is not None:
        pools = {
            item.name.lower(): list(item.tags or [])
            for item in (
                await s.execute(
                    select(HashtagSet).where(HashtagSet.workspace_id == body.workspace_id)
                )
            )
            .scalars()
            .all()
        }

    samples: list[PreviewSample] = []
    for i in range(body.account_count):
        rng = rng_for("xem-truoc", i)
        title = tags_mod.expand(expand(body.title_template, rng), pools, rng)
        text = (
            tags_mod.expand(expand(body.body_template, rng), pools, rng)
            if body.body_template
            else ""
        )
        samples.append(
            PreviewSample(title=title, body=text, content_hash=content_hash(title, text))
        )

    both = f"{body.title_template}\n{body.body_template}"
    tag_factor = tags_mod.combination_factor(both, pools)
    total = combinations(body.title_template) * max(1, combinations(body.body_template))
    total *= tag_factor
    unique = len({s.content_hash for s in samples})

    unknown = sorted(name for name in tags_mod.referenced(both) if name not in pools)

    # Bai toan sinh nhat: xac suat co it nhat mot cap trung trong n lan rut tu N to hop.
    n = body.account_count
    risk = 1.0
    for k in range(n):
        risk *= (total - k) / total if k < total else 0.0
    risk = round(1 - risk, 4)

    warning = None
    if unknown:
        warning = (
            f"No hashtag set named {', '.join(unknown)}. The placeholder will post as "
            "literal text — create the set or fix the name."
        )
    elif total < n:
        warning = (
            f"This template has only {total} combination(s) for {n} accounts, so posts are "
            "certain to repeat. Add more {a|b|c} branches, or a hashtag pool."
        )
    elif risk > 0.2:
        warning = (
            f"{risk:.0%} chance two of the {n} accounts post the same text. Add more "
            f"{{a|b|c}} branches to raise the {total} combinations you have now — "
            "a hashtag pool raises it fastest."
        )

    return PreviewOut(
        samples=samples,
        combinations=total,
        hashtag_combinations=tag_factor,
        unique_in_sample=unique,
        collision_risk=risk,
        warning=warning,
        unknown_pools=unknown,
    )


@router.get("/content", response_model=Page[ContentSummary])
async def list_content(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    approved: bool | None = None,
    s: AsyncSession = Depends(get_session),
) -> Page[ContentSummary]:
    stmt = select(ContentItem)
    if q:
        stmt = stmt.where(
            ContentItem.title_template.ilike(f"%{q}%") | ContentItem.body_template.ilike(f"%{q}%")
        )
    if approved is not None:
        stmt = stmt.where(ContentItem.approved.is_(approved))

    rows, total = await _paginate(s, stmt.order_by(ContentItem.created_at.desc()), limit, offset)
    return Page[ContentSummary](
        items=[ContentSummary.model_validate(r[0]) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/content", response_model=ContentOut)
async def create_content(body: ContentIn, s: AsyncSession = Depends(get_session)) -> ContentItem:
    item = ContentItem(**body.model_dump())
    s.add(item)
    await s.commit()
    return item


@router.post("/content/{content_id}/approve", response_model=ContentOut)
async def approve_content(
    content_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> ContentItem:
    item = await s.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(404, "No such content")
    item.approved = True
    await s.commit()
    return item


@router.get("/campaigns", response_model=Page[CampaignSummary])
async def list_campaigns(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    s: AsyncSession = Depends(get_session),
) -> Page[CampaignSummary]:
    """Danh sach chien dich kem so job theo trang thai.

    Truoc day cat cung o 100 va khong noi gi. Mot chuoi lap hang ngay sinh 365 chien
    dich mot nam, nen moc do bi vuot qua trong ba thang - va cac chien dich cu se lang
    le bien mat khoi man hinh.
    """
    stmt = select(Campaign)
    if q:
        stmt = stmt.where(Campaign.name.ilike(f"%{q}%"))

    rows, total = await _paginate(s, stmt.order_by(Campaign.starts_at.desc()), limit, offset)
    return Page[CampaignSummary](
        items=await _summaries(s, [r[0] for r in rows]),
        total=total,
        limit=limit,
        offset=offset,
    )


async def _summaries(s: AsyncSession, campaigns: list[Campaign]) -> list[CampaignSummary]:
    """Dem job theo trang thai cho mot tap chien dich, trong MOT cau truy van.

    Tach ra vi ca danh sach chien dich lan chuoi lap lai deu can dung mot phep dem;
    lam hai ban thi som muon hai man hinh se dem ra hai con so khac nhau.
    """
    if not campaigns:
        return []

    rows = (
        await s.execute(
            select(PostJob.campaign_id, PostJob.status, func.count())
            .where(PostJob.campaign_id.in_([c.id for c in campaigns]))
            .group_by(PostJob.campaign_id, PostJob.status)
        )
    ).all()

    tally: dict = {c.id: {"total": 0} for c in campaigns}
    for campaign_id, status, n in rows:
        tally[campaign_id]["total"] += n
        tally[campaign_id][status.value] = n

    return [
        CampaignSummary(
            id=c.id,
            name=c.name,
            starts_at=c.starts_at,
            stagger_window_seconds=c.stagger_window_seconds,
            repeat=c.repeat,
            repeat_until=c.repeat_until,
            repeat_parent_id=c.repeat_parent_id,
            next_run=recurring.next_run(c),
            total_jobs=tally[c.id]["total"],
            succeeded=tally[c.id].get("succeeded", 0),
            failed=tally[c.id].get("failed", 0),
            needs_human=tally[c.id].get("needs_human", 0),
        )
        for c in campaigns
    ]


@router.patch("/content/{content_id}", response_model=ContentSummary)
async def update_content(
    content_id: uuid.UUID, body: ContentPatch, s: AsyncSession = Depends(get_session)
) -> ContentItem:
    item = await s.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(404, "No such content")

    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(item, key, value)

    await s.commit()
    return item


@router.delete("/content/{content_id}", response_model=DeleteOut)
async def delete_content(
    content_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa noi dung. Tu choi neu da co chien dich dung no."""
    item = await s.get(ContentItem, content_id)
    if item is None:
        raise HTTPException(404, "No such content")

    used = int(
        (
            await s.execute(
                select(func.count())
                .select_from(Campaign)
                .where(Campaign.content_item_id == content_id)
            )
        ).scalar_one()
    )
    if used:
        raise HTTPException(
            409,
            f"{used} campaign(s) were built from this content. Delete those first — "
            "removing it now would leave their posts without a source.",
        )

    await s.delete(item)
    await s.commit()
    return DeleteOut(deleted=True, detail="content removed")


@router.get("/campaigns/{campaign_id}/groups", response_model=list[GroupOut])
async def campaign_groups(
    campaign_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> list[GroupOut]:
    """Cac nhom trong mot chien dich, kem so job theo trang thai.

    Nhom la tang giua: mot chien dich co the nham nhieu nen tang hoac nhieu cum persona,
    va moi nhom co cua so rai va muc tieu rieng.
    """
    groups = (
        (
            await s.execute(
                select(CampaignGroup)
                .where(CampaignGroup.campaign_id == campaign_id)
                .order_by(CampaignGroup.created_at)
            )
        )
        .scalars()
        .all()
    )

    rows = (
        await s.execute(
            select(PostJob.group_id, PostJob.status, func.count())
            .where(PostJob.campaign_id == campaign_id)
            .group_by(PostJob.group_id, PostJob.status)
        )
    ).all()

    tally: dict = {g.id: {"total": 0} for g in groups}
    for group_id, status, n in rows:
        if group_id in tally:
            tally[group_id]["total"] += n
            tally[group_id][status.value] = n

    return [
        GroupOut(
            id=g.id,
            name=g.name,
            platform=g.platform,
            post_kind=g.post_kind,
            target=dict(g.target or {}),
            account_count=len(g.account_ids or []),
            total_jobs=tally[g.id]["total"],
            succeeded=tally[g.id].get("succeeded", 0),
            failed=tally[g.id].get("failed", 0),
            needs_human=tally[g.id].get("needs_human", 0),
        )
        for g in groups
    ]


@router.post("/campaigns/{campaign_id}/groups", response_model=GroupOut)
async def add_group(
    campaign_id: uuid.UUID, body: GroupIn2, s: AsyncSession = Depends(get_session)
) -> GroupOut:
    """Them mot nhom vao chien dich da co, roi lap lich cho rieng nhom do."""
    campaign = await s.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "No such campaign")

    group = CampaignGroup(
        campaign_id=campaign_id,
        name=body.name,
        platform=body.platform,
        post_kind=body.post_kind,
        target=body.target,
        account_ids=[str(a) for a in body.account_ids],
    )
    s.add(group)
    await s.commit()

    await plan_campaign(s, campaign_id)
    return (await campaign_groups(campaign_id, s))[-1]


@router.delete("/campaigns/{campaign_id}/groups/{group_id}", response_model=DeleteOut)
async def delete_group(
    campaign_id: uuid.UUID,
    group_id: uuid.UUID,
    force: bool = False,
    s: AsyncSession = Depends(get_session),
) -> DeleteOut:
    group = await s.get(CampaignGroup, group_id)
    if group is None or group.campaign_id != campaign_id:
        raise HTTPException(404, "No such group in this campaign")

    posted = int(
        (
            await s.execute(
                select(func.count())
                .select_from(PostJob)
                .where(PostJob.group_id == group_id, PostJob.status == JobStatus.SUCCEEDED)
            )
        ).scalar_one()
    )
    if posted and not force:
        raise HTTPException(
            409,
            f"{posted} post(s) from this group are already live. Deleting loses the record "
            "while the posts stay up — delete with force=true if that is what you want.",
        )

    name = group.name
    await s.delete(group)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{name} removed")


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: uuid.UUID, body: CampaignPatch, s: AsyncSession = Depends(get_session)
) -> Campaign:
    campaign = await s.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "No such campaign")

    for key, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(campaign, key, value)

    await s.commit()
    return campaign


@router.delete("/campaigns/{campaign_id}", response_model=DeleteOut)
async def delete_campaign(
    campaign_id: uuid.UUID, force: bool = False, s: AsyncSession = Depends(get_session)
) -> DeleteOut:
    """Xoa chien dich va toan bo job cua no.

    Job da dang thanh cong thi phai force: xoa la mat lich su, ma bai tren nen tang
    thi van con - sau nay khong con cach nao doi chieu.
    """
    campaign = await s.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "No such campaign")

    posted = int(
        (
            await s.execute(
                select(func.count())
                .select_from(PostJob)
                .where(PostJob.campaign_id == campaign_id, PostJob.status == JobStatus.SUCCEEDED)
            )
        ).scalar_one()
    )
    if posted and not force:
        raise HTTPException(
            409,
            f"{posted} post(s) from this campaign are already live. Deleting loses the record "
            "while the posts stay up — delete with force=true if that is what you want.",
        )

    name = campaign.name
    await s.delete(campaign)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{name} removed")


@router.post("/campaigns", response_model=CampaignOut)
async def create_campaign(body: CampaignIn, s: AsyncSession = Depends(get_session)) -> Campaign:
    settings = get_settings()
    campaign = Campaign(
        workspace_id=body.workspace_id,
        content_item_id=body.content_item_id,
        name=body.name,
        starts_at=body.starts_at or datetime.now(UTC),
        stagger_window_seconds=(
            body.stagger_window_seconds
            if body.stagger_window_seconds is not None
            else settings.stagger_window_seconds
        ),
        repeat=body.repeat,
        repeat_until=body.repeat_until,
    )
    s.add(campaign)
    await s.flush()

    for g in body.groups:
        s.add(
            CampaignGroup(
                campaign_id=campaign.id,
                name=g.name,
                platform=g.platform,
                post_kind=g.post_kind,
                target=g.target,
                account_ids=[str(a) for a in g.account_ids],
            )
        )

    await s.commit()
    return campaign


@router.post("/campaigns/{campaign_id}/plan", response_model=list[JobOut])
async def plan(campaign_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> list[JobOut]:
    """Bung chien dich thanh job. Goi lai nhieu lan van an toan."""
    try:
        await plan_campaign(s, campaign_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return await _jobs_of(s, campaign_id)


@router.get("/campaigns/{campaign_id}/jobs", response_model=list[JobOut])
async def campaign_jobs(
    campaign_id: uuid.UUID,
    group_id: uuid.UUID | None = None,
    s: AsyncSession = Depends(get_session),
) -> list[JobOut]:
    """Job cua mot chien dich. Loc theo `group_id` de xem rieng mot nhom."""
    return await _jobs_of(s, campaign_id, group_id)


async def _jobs_of(
    s: AsyncSession, campaign_id: uuid.UUID, group_id: uuid.UUID | None = None
) -> list[JobOut]:
    stmt = (
        select(PostJob)
        .where(PostJob.campaign_id == campaign_id)
        .order_by(PostJob.scheduled_at)
        .options(selectinload(PostJob.attempts))
    )
    if group_id is not None:
        stmt = stmt.where(PostJob.group_id == group_id)

    jobs = (await s.execute(stmt)).unique().scalars().all()

    out: list[JobOut] = []
    for job in jobs:
        ok_attempt = next((a for a in job.attempts if a.ok), None)
        out.append(
            JobOut(
                id=job.id,
                group_id=job.group_id,
                status=job.status,
                scheduled_at=job.scheduled_at,
                handle=job.account.handle,
                title=job.variant.title,
                content_hash=job.variant.content_hash,
                attempt_count=job.attempt_count,
                last_error=job.last_error,
                remote_url=ok_attempt.remote_url if ok_attempt else None,
            )
        )
    return out


@router.get("/jobs/{job_id}/attempts")
async def job_attempts(job_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> list[dict]:
    rows = (
        (
            await s.execute(
                select(Attempt).where(Attempt.job_id == job_id).order_by(Attempt.started_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "started_at": a.started_at,
            "finished_at": a.finished_at,
            "ok": a.ok,
            "remote_url": a.remote_url,
            "error": a.error,
        }
        for a in rows
    ]


# ------------------------------------------------------------- khung gio nen tang


@router.get("/windows", response_model=list[WindowOut])
async def list_windows(s: AsyncSession = Depends(get_session)) -> list[PlatformWindow]:
    """Khung gio thuc da dat rieng cho tung nen tang.

    Nen tang khong co trong danh sach nay dung mac dinh trong core/activity.py.
    """
    rows = (await s.execute(select(PlatformWindow).order_by(PlatformWindow.platform))).scalars()
    return list(rows)


@router.get("/windows/defaults")
async def window_defaults() -> dict:
    """Mac dinh dung cho nen tang chua dat rieng - de giao dien hien duoc gia tri that."""
    return {
        "active_from_hour": activity_mod.ACTIVE_FROM.hour,
        "active_to_hour": activity_mod.ACTIVE_TO.hour,
    }


@router.put("/windows", response_model=list[WindowOut])
async def set_window(
    body: WindowIn, s: AsyncSession = Depends(get_session)
) -> list[PlatformWindow]:
    """Dat khung gio cho mot nen tang, tren cac ngay duoc chon. Goi lai la ghi de."""
    if body.active_from_hour >= body.active_to_hour:
        raise HTTPException(
            400,
            "The window must start before it ends. A window that wraps past midnight is not "
            "supported — accounts awake at 4am are the pattern this feature exists to avoid.",
        )

    existing = {
        w.weekday: w
        for w in (
            await s.execute(select(PlatformWindow).where(PlatformWindow.platform == body.platform))
        )
        .scalars()
        .all()
    }

    out: list[PlatformWindow] = []
    for day in body.weekdays:
        window = existing.get(day)
        if window is None:
            window = PlatformWindow(platform=body.platform, weekday=day)
            s.add(window)
        window.active_from_hour = body.active_from_hour
        window.active_to_hour = body.active_to_hour
        window.note = body.note
        out.append(window)

    await s.commit()
    return out


@router.delete("/windows/{platform}", response_model=DeleteOut)
async def clear_window(
    platform: Platform,
    weekday: int | None = Query(None, ge=0, le=6),
    s: AsyncSession = Depends(get_session),
) -> DeleteOut:
    """Bo khung rieng, quay ve mac dinh. Khong truyen `weekday` thi bo ca bay ngay."""
    stmt = select(PlatformWindow).where(PlatformWindow.platform == platform)
    if weekday is not None:
        stmt = stmt.where(PlatformWindow.weekday == weekday)

    rows = list((await s.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(404, "That platform has no window of its own for those days")

    for row in rows:
        await s.delete(row)
    await s.commit()

    scope = "every day" if weekday is None else f"weekday {weekday}"
    return DeleteOut(
        deleted=True, detail=f"{platform.value} is back on the default window for {scope}"
    )


# --------------------------------------------------------- khung gio vang dang bai


@router.get("/slots", response_model=list[SlotOut])
async def list_slots(s: AsyncSession = Depends(get_session)) -> list[PostSlot]:
    """Cac moc gio dang bai da dat, moi nen tang moi thu. Nen tang khong co moc nao thi
    planner dung starts_at cua chien dich + cua so rai nhu truoc."""
    rows = (
        await s.execute(
            select(PostSlot).order_by(PostSlot.platform, PostSlot.weekday, PostSlot.hour)
        )
    ).scalars()
    return list(rows)


@router.get("/slots/meta", response_model=SlotMeta)
async def slot_meta() -> SlotMeta:
    return SlotMeta(
        timezone=get_settings().schedule_timezone, jitter_max_seconds=slots_mod.JITTER_MAX_SECONDS
    )


@router.put("/slots", response_model=list[SlotOut])
async def set_slots(body: SlotIn, s: AsyncSession = Depends(get_session)) -> list[PostSlot]:
    """Dat cac moc cho mot nen tang tren cac ngay duoc chon. THAY THE moc cu cua ngay do."""
    old = (
        await s.execute(
            select(PostSlot).where(
                PostSlot.platform == body.platform, PostSlot.weekday.in_(body.weekdays)
            )
        )
    ).scalars()
    for row in old:
        await s.delete(row)
    await s.flush()

    out: list[PostSlot] = []
    for day in body.weekdays:
        for hour in body.hours:
            slot = PostSlot(
                platform=body.platform, weekday=day, hour=hour, minute=0, note=body.note
            )
            s.add(slot)
            out.append(slot)
    await s.commit()
    return out


@router.delete("/slots/{platform}", response_model=DeleteOut)
async def clear_slots(
    platform: Platform,
    weekday: int | None = Query(None, ge=0, le=6),
    s: AsyncSession = Depends(get_session),
) -> DeleteOut:
    """Bo moc cua mot nen tang. Khong truyen `weekday` thi bo ca bay ngay."""
    stmt = select(PostSlot).where(PostSlot.platform == platform)
    if weekday is not None:
        stmt = stmt.where(PostSlot.weekday == weekday)
    rows = list((await s.execute(stmt)).scalars().all())
    if not rows:
        raise HTTPException(404, "That platform has no posting slots for those days")
    for row in rows:
        await s.delete(row)
    await s.commit()
    scope = "every day" if weekday is None else f"weekday {weekday}"
    return DeleteOut(
        deleted=True,
        detail=f"{platform.value} has no posting slots for {scope}; campaigns use their start time",
    )


# ------------------------------------------------------------ chien dich lap lai


@router.get("/campaigns/{campaign_id}/chain", response_model=list[CampaignSummary])
async def campaign_chain(
    campaign_id: uuid.UUID, s: AsyncSession = Depends(get_session)
) -> list[CampaignSummary]:
    """Ban goc cung moi ky da sinh ra tu no.

    Goi tu bat ky mat xich nao cung tra ve ca chuoi - nguoi van hanh thuong mo mot ban
    sao truoc roi moi hoi "the cac tuan truoc thi sao".
    """
    try:
        chain = await recurring.chain(s, campaign_id)
    except NoResultFound as exc:
        raise HTTPException(404, "No such campaign") from exc
    return await _summaries(s, chain)


@router.post("/campaigns/{campaign_id}/spawn-next", response_model=CampaignOut)
async def spawn_next(campaign_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> Campaign:
    """Sinh ky ke tiep ngay bay gio, khong cho cron.

    Dung de thu mot chuoi truoc khi giao no cho lich - cho mot ngay roi moi biet minh
    dat sai muc tieu la mot ngay mat.
    """
    campaign = await s.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "No such campaign")
    if campaign.repeat is Repeat.NONE:
        raise HTTPException(400, "This campaign does not repeat")

    try:
        result = await recurring.spawn(s, campaign)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result is None:
        raise HTTPException(409, "This chain has reached its end date, or has no groups")
    return result[0]


# ------------------------------------------------------- nhap tai khoan hang loat


@router.get("/accounts/import/template", response_class=PlainTextResponse)
async def import_template(seller: bool = False) -> str:
    """File CSV mau.

    `seller=true` tra ve dung dinh dang cua nguoi ban acc
    (`username|password|hotmail|pass_hotmail|cookie`) thay vi mau day du.
    """
    return bulk.seller_template() if seller else bulk.template()


def _report_out(report: bulk.Report) -> dict:
    """Bao cao kiem file, dang JSON.

    Bi mat KHONG bao gio di nguoc ra: chi tra ve SO luong truong bi mat cua moi dong.
    Tra ve gia tri de "nguoi dung xem lai cho chac" nghia la mat khau di qua mang va
    nam trong nhat ky trinh duyet.
    """
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
                "persona": r.persona,
                "daily_cap": r.daily_cap,
                "start_warmup": r.start_warmup,
                "secret_count": len(r.secrets),
                # Chi bao CO hay KHONG. Chuoi cookie la mot phien dang nhap song -
                # tra no nguoc ra qua API la de no nam trong nhat ky trinh duyet.
                "has_cookie": bool(r.cookie),
                # Ly do cookie khong dung duoc, neu co. Khong bao gio tra ve chinh
                # chuoi cookie - do la mot phien dang nhap song.
                "cookie_note": r.cookie_note,
            }
            for r in report.rows
        ],
        "problems": [
            {"line": p.line, "handle": p.handle, "detail": p.detail} for p in report.problems
        ],
    }


async def _read_csv(file: UploadFile | None, text: str | None = None) -> str:
    """Lay noi dung tu file tai len HOAC tu o dan.

    Nhan ca hai vi voi vai chuc acc thi dan thang nhanh hon han: khong phai mo Excel,
    khong phai luu file, khong phai nho minh vua luu vao dau.
    """
    if text and text.strip():
        if len(text) > 2_000_000:
            raise HTTPException(413, "That is more text than an account list should be.")
        return text

    if file is None:
        raise HTTPException(400, "Paste some accounts, or choose a file.")

    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(413, "That file is larger than 2 MB - too big to be an account list.")
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(400, "Could not read that file as text. Save it as UTF-8 CSV.")


@router.post("/accounts/import/check")
async def import_check(
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    platform: Platform | None = None,
    s: AsyncSession = Depends(get_session),
) -> dict:
    """Kiem file va tra ve ket qua. KHONG tao gi ca.

    Hai lua la co y: mot file 200 dong hong o dong 173 ma nhap thang thi 172 dong da
    nam trong database, va nguoi dung khong biet phai sua tu dau.

    `platform` dien vao cho file khong co cot do - file acc mua san hau nhu luon vay.
    """
    report = await bulk.check_against_db(
        s, bulk.parse(await _read_csv(file, text), default_platform=platform)
    )
    return _report_out(report)


@router.post("/accounts/import")
async def import_accounts(
    workspace_id: uuid.UUID,
    file: UploadFile | None = File(None),
    text: str | None = Form(None),
    persona_id: uuid.UUID | None = None,
    platform: Platform | None = None,
    partial: bool = False,
    attach_proxies: bool = False,
    s: AsyncSession = Depends(get_session),
) -> dict:
    """Tao tai khoan tu file.

    Mac dinh: co MOT dong hong la khong nhap gi ca. `partial=true` de nhap cac dong
    hop le va bo qua phan hong - chi nen dung khi da xem ket qua kiem.

    Dong co cot `cookie` se duoc tao luon profile kem phien dang nhap, bo qua buoc
    `login_profile.py`. `attach_proxies=true` thi gan cho moi profile mot proxy con
    ranh - MOI ACC MOT PROXY, khong dung chung.
    """
    report = await bulk.check_against_db(
        s, bulk.parse(await _read_csv(file, text), default_platform=platform)
    )

    if report.problems and not partial:
        return {
            "created": 0,
            "detail": (
                f"{len(report.problems)} problem(s) found - nothing was imported. "
                "Fix the file, or send partial=true to import the good rows only."
            ),
            **_report_out(report),
        }

    if not report.rows:
        raise HTTPException(400, "There are no usable rows in that file.")

    spare: list = []
    if attach_proxies:
        # Chi proxy CHUA gan cho profile nao. Dung lai mot proxy dang duoc dung nghia la
        # hai tai khoan di ra cung mot IP - lien ket ro rang nhat co the tao ra.
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

    try:
        created, warnings = await bulk.apply(
            s,
            workspace_id,
            report.rows,
            default_persona_id=persona_id,
            proxies=spare,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if attach_proxies and len(spare) < report.with_cookies:
        warnings.append(
            f"Only {len(spare)} tested proxy(ies) were free for {report.with_cookies} profile(s). "
            "The rest have none — one account, one proxy, never shared."
        )

    return {
        "created": len(created),
        "handles": [a.handle for a in created],
        "profiles_with_session": report.with_cookies,
        "skipped": len(report.problems),
        "warnings": warnings,
        "problems": [
            {"line": p.line, "handle": p.handle, "detail": p.detail} for p in report.problems
        ],
    }


# ----------------------------------------------------------------- song sot


@router.get("/analytics/survival")
async def survival_report(s: AsyncSession = Depends(get_session)) -> dict:
    """Tai khoan song duoc bao lau, cat theo proxy, warm-up va nhip dang.

    Moi hang deu mang `n` va `trustworthy`: voi 8 tai khoan mot nhom thi chenh lech
    60% va 75% la nhieu, khong phai phat hien.
    """
    return await survival.report(s)


# ------------------------------------------------------- do thi tuong tac cheo


@router.get("/graph")
async def graph_report(
    platform: Platform | None = None, s: AsyncSession = Depends(get_session)
) -> dict:
    """Do thi theo doi noi bo dang co hinh gi, va cho nao dang nguy hiem.

    Muc dich la de nguoi van hanh nhin thay hinh dang truoc khi nen tang nhin thay no.
    """
    report = await graph.audit(s, platform)
    return report.as_dict()


@router.get("/graph/edges")
async def graph_edges(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    s: AsyncSession = Depends(get_session),
) -> dict:
    """Tung canh mot, kem trang thai. Canh `planned` la chua thuc hien tren nen tang."""
    follower = aliased(Account)
    target = aliased(Account)
    stmt = (
        select(Relationship, follower, target)
        .join(follower, follower.id == Relationship.follower_id)
        .join(target, target.id == Relationship.target_id)
        .order_by(Relationship.created_at.desc())
    )
    rows, total = await _paginate(s, stmt, limit, offset)
    return {
        "items": [
            {
                "id": str(edge.id),
                "follower": f.handle,
                "target": t.handle,
                "platform": f.platform.value,
                "status": edge.status.value,
                "created_at": edge.created_at,
                "done_at": edge.done_at,
                "note": edge.note,
            }
            for edge, f, t in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/graph/plan")
async def graph_plan(
    budget: int = Query(graph.MAX_NEW_EDGES_PER_DAY, ge=1, le=graph.MAX_NEW_EDGES_PER_DAY),
    platform: Platform | None = None,
    s: AsyncSession = Depends(get_session),
) -> dict:
    """Them mot it canh moi ngay bay gio, khong cho cron.

    `budget` bi chan cung o tran mot ngay: mot o nhap cho phep tao nam muoi canh mot
    luc chi ton tai de co nguoi go nam muoi vao do.
    """
    edges = await graph.plan_follows(s, platform=platform, budget=budget)
    report = await graph.audit(s, platform)
    return {"created": len(edges), "graph": report.as_dict()}


# ---------------------------------------------------------------- thiet bi that


def _device_out(device: Device) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        serial=device.serial,
        label=device.label,
        os=device.os,
        model=device.model,
        os_version=device.os_version,
        status=device.status,
        last_seen_at=device.last_seen_at,
        last_error=device.last_error,
        account_id=device.account_id,
        handle=device.account.handle if device.account else None,
        proxy_label=device.proxy.label if device.proxy else None,
        note=device.note,
    )


@router.get("/devices/preflight")
async def device_preflight() -> dict:
    """Nhung gi con thieu de duong thiet bi chay duoc.

    Tra ve ca danh sach thay vi bao thu dau tien roi dung: cai mot thu roi chay lai de
    gap thu tiep theo, voi chuoi cong cu Android, la ca buoi chieu.
    """
    return devices_mod.preflight()


@router.post("/devices/sync")
async def device_sync(s: AsyncSession = Depends(get_session)) -> dict:
    """Doi soat may dang cam voi database.

    Khong tu them may moi: mot may cam vao de sac cung hien ra trong `adb devices`.
    May la thi tra ve trong `unknown` de nguoi van hanh tu quyet.
    """
    return await devices_mod.sync(s)


@router.get("/devices", response_model=Page[DeviceOut])
async def list_devices(
    limit: int = Query(DEFAULT_PAGE, ge=1, le=MAX_PAGE),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    status: DeviceStatus | None = None,
    s: AsyncSession = Depends(get_session),
) -> Page[DeviceOut]:
    stmt = select(Device)
    if q:
        stmt = stmt.where(Device.label.ilike(f"%{q}%") | Device.serial.ilike(f"%{q}%"))
    if status is not None:
        stmt = stmt.where(Device.status == status)

    rows, total = await _paginate(s, stmt.order_by(Device.created_at), limit, offset)
    return Page[DeviceOut](
        items=[_device_out(r[0]) for r in rows], total=total, limit=limit, offset=offset
    )


@router.post("/devices", response_model=DeviceOut)
async def create_device(body: DeviceIn, s: AsyncSession = Depends(get_session)) -> DeviceOut:
    device = Device(**body.model_dump())
    s.add(device)
    try:
        await s.commit()
    except IntegrityError as exc:
        await s.rollback()
        raise HTTPException(
            409,
            f"Either the serial {body.serial} is already registered, or that account already "
            "has a device. One account runs on one device, the same way it runs on one profile.",
        ) from exc
    await s.refresh(device)
    return _device_out(device)


@router.patch("/devices/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: uuid.UUID, body: DevicePatch, s: AsyncSession = Depends(get_session)
) -> DeviceOut:
    device = await s.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "No such device")

    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(device, key, value)

    try:
        await s.commit()
    except IntegrityError as exc:
        await s.rollback()
        raise HTTPException(409, "That account already has a device bound to it.") from exc
    await s.refresh(device)
    return _device_out(device)


@router.delete("/devices/{device_id}", response_model=DeleteOut)
async def delete_device(device_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> DeleteOut:
    device = await s.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "No such device")

    if device.account_id is not None:
        raise HTTPException(
            409,
            f"{device.label} is bound to an account. Unbind it first — an account whose device "
            "disappears has nowhere to run, and it will fail every job without saying why.",
        )

    label = device.label
    await s.delete(device)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{label} removed")
