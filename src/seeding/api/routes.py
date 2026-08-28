from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from seeding.config import get_settings
from seeding.core import activity as activity_mod
from seeding.core import bulk, recurring, survival, takeover, vault
from seeding.core import fingerprint as fpm
from seeding.core import hashtags as tags_mod
from seeding.core import profiles as profiles_mod
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
    HashtagSet,
    JobStatus,
    Persona,
    Platform,
    PlatformWindow,
    PostJob,
    Profile,
    Proxy,
    ProxyStatus,
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
    GroupIn2,
    GroupOut,
    JobOut,
    NamedOut,
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
    ResolveIn,
    SessionEventOut,
    StatsOut,
    TakeoverOut,
    WindowIn,
    WindowOut,
    WorkspaceIn,
)

router = APIRouter()

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


@router.get("/personas", response_model=list[NamedOut])
async def list_personas(s: AsyncSession = Depends(get_session)) -> list[Persona]:
    stmt = select(Persona).order_by(Persona.created_at)
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


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(s: AsyncSession = Depends(get_session)) -> list[Account]:
    return list((await s.execute(select(Account).order_by(Account.created_at))).scalars().all())


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


@router.get("/proxies", response_model=list[ProxyOut])
async def list_proxies(s: AsyncSession = Depends(get_session)) -> list[Proxy]:
    return list((await s.execute(select(Proxy).order_by(Proxy.created_at))).scalars().all())


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
        result.error = f"{type(exc).__name__}: {exc}"

    result.latency_ms = int((time.perf_counter() - started) * 1000)

    proxy.status = ProxyStatus.OK if result.ok else ProxyStatus.FAILING
    proxy.last_checked_at = datetime.now(UTC)
    proxy.last_exit_ip = result.exit_ip
    proxy.last_error = result.error
    return result


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


@router.get("/profiles", response_model=list[ProfileOut])
async def list_profiles(s: AsyncSession = Depends(get_session)) -> list[ProfileOut]:
    rows = (
        (
            await s.execute(
                select(Profile, Account)
                .join(Account, Account.id == Profile.account_id)
                .order_by(Profile.created_at)
            )
        )
        .unique()
        .all()
    )
    return [_profile_out(profile, account, profile.proxy) for profile, account in rows]


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


@router.get("/content", response_model=list[ContentSummary])
async def list_content(s: AsyncSession = Depends(get_session)) -> list[ContentItem]:
    stmt = select(ContentItem).order_by(ContentItem.created_at.desc()).limit(200)
    return list((await s.execute(stmt)).scalars().all())


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


@router.get("/campaigns", response_model=list[CampaignSummary])
async def list_campaigns(s: AsyncSession = Depends(get_session)) -> list[CampaignSummary]:
    """Danh sach chien dich kem so job theo trang thai - du de ve man hinh lich."""
    campaigns = (
        (await s.execute(select(Campaign).order_by(Campaign.starts_at.desc()).limit(100)))
        .scalars()
        .all()
    )
    return await _summaries(s, list(campaigns))


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


@router.put("/windows", response_model=WindowOut)
async def set_window(body: WindowIn, s: AsyncSession = Depends(get_session)) -> PlatformWindow:
    """Dat khung gio cho mot nen tang. Moi nen tang mot ban ghi, goi lai la ghi de."""
    if body.active_from_hour >= body.active_to_hour:
        raise HTTPException(
            400,
            "The window must start before it ends. A window that wraps past midnight is not "
            "supported — accounts awake at 4am are the pattern this feature exists to avoid.",
        )

    window = (
        await s.execute(select(PlatformWindow).where(PlatformWindow.platform == body.platform))
    ).scalar_one_or_none()

    if window is None:
        window = PlatformWindow(platform=body.platform)
        s.add(window)

    window.active_from_hour = body.active_from_hour
    window.active_to_hour = body.active_to_hour
    window.note = body.note
    await s.commit()
    return window


@router.delete("/windows/{platform}", response_model=DeleteOut)
async def clear_window(platform: Platform, s: AsyncSession = Depends(get_session)) -> DeleteOut:
    """Bo khung rieng, quay ve mac dinh."""
    window = (
        await s.execute(select(PlatformWindow).where(PlatformWindow.platform == platform))
    ).scalar_one_or_none()
    if window is None:
        raise HTTPException(404, "That platform has no window of its own")

    await s.delete(window)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"{platform.value} is back on the default window")


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
async def import_template() -> str:
    """File CSV mau. Mot dong Reddit, mot dong nen tang trinh duyet."""
    return bulk.template()


def _report_out(report: bulk.Report) -> dict:
    """Bao cao kiem file, dang JSON.

    Bi mat KHONG bao gio di nguoc ra: chi tra ve SO luong truong bi mat cua moi dong.
    Tra ve gia tri de "nguoi dung xem lai cho chac" nghia la mat khau di qua mang va
    nam trong nhat ky trinh duyet.
    """
    return {
        "ok": report.ok,
        "ready": len(report.rows),
        "unknown_columns": report.unknown_columns,
        "rows": [
            {
                "line": r.line,
                "platform": r.platform.value,
                "handle": r.handle,
                "persona": r.persona,
                "daily_cap": r.daily_cap,
                "start_warmup": r.start_warmup,
                "secret_count": len(r.secrets),
            }
            for r in report.rows
        ],
        "problems": [
            {"line": p.line, "handle": p.handle, "detail": p.detail} for p in report.problems
        ],
    }


async def _read_csv(file: UploadFile) -> str:
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
    file: UploadFile = File(...), s: AsyncSession = Depends(get_session)
) -> dict:
    """Kiem file va tra ve ket qua. KHONG tao gi ca.

    Hai lua la co y: mot file 200 dong hong o dong 173 ma nhap thang thi 172 dong da
    nam trong database, va nguoi dung khong biet phai sua tu dau.
    """
    report = await bulk.check_against_db(s, bulk.parse(await _read_csv(file)))
    return _report_out(report)


@router.post("/accounts/import")
async def import_accounts(
    workspace_id: uuid.UUID,
    file: UploadFile = File(...),
    persona_id: uuid.UUID | None = None,
    partial: bool = False,
    s: AsyncSession = Depends(get_session),
) -> dict:
    """Tao tai khoan tu file.

    Mac dinh: co MOT dong hong la khong nhap gi ca. `partial=true` de nhap cac dong
    hop le va bo qua phan hong - chi nen dung khi da xem ket qua kiem.
    """
    report = await bulk.check_against_db(s, bulk.parse(await _read_csv(file)))

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

    try:
        created = await bulk.apply(s, workspace_id, report.rows, default_persona_id=persona_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "created": len(created),
        "handles": [a.handle for a in created],
        "skipped": len(report.problems),
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
