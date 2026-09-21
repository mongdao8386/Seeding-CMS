"""Proxy: danh sach, dan hang loat, thu, xoa. Mot acc mot proxy - so proxy phai bang so acc."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import DEFAULT_PAGE, MAX_PAGE, get_session, paginate
from seeding.api.schemas import (
    DeleteOut,
    Page,
    ProxyAttachOut,
    ProxyImportOut,
    ProxyOut,
    ProxyTestOut,
)
from seeding.domain.models import Account, Profile, Proxy, ProxyKind, ProxyStatus
from seeding.ops import proxy_stats, proxylist, proxypool, proxytest

router = APIRouter(prefix="/proxies", tags=["proxies"])

SCHEMES = {"http", "https", "socks5"}


@router.get("", response_model=Page[ProxyOut])
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
    rows, total = await paginate(s, stmt.order_by(Proxy.created_at), limit, offset)
    proxies = [r[0] for r in rows]

    # Nhieu acc chung mot proxy: gom thanh danh sach (dict() o day tung lang le bo bot acc).
    bound: dict[uuid.UUID, list[str]] = {}
    rows_bound = await s.execute(
        select(Profile.proxy_id, Account.handle)
        .join(Account, Account.id == Profile.account_id)
        .where(Profile.proxy_id.in_([p.id for p in proxies] or [uuid.uuid4()]))
        .order_by(Account.handle)
    )
    for proxy_id, handle in rows_bound.all():
        bound.setdefault(proxy_id, []).append(handle)
    cap = proxypool.capacity()
    items = []
    for p in proxies:
        out = ProxyOut.model_validate(p)
        out.bound_handles = bound.get(p.id, [])
        out.bound_count = len(out.bound_handles)
        out.bound_handle = out.bound_handles[0] if out.bound_handles else None
        out.capacity = cap
        stats = await proxy_stats.read(p.id)
        out.tiktok_render = proxy_stats.summary(stats)
        out.tiktok_last_ok = stats.get("last_ok") if stats else None
        items.append(out)
    return Page[ProxyOut](items=items, total=total, limit=limit, offset=offset)


@router.post("/import", response_model=ProxyImportOut)
async def import_proxies(
    text: str = Form(...),
    label_prefix: str = Form("P"),
    kind: ProxyKind = Form(ProxyKind.RESIDENTIAL),
    scheme: str = Form("http"),
    test: bool = Form(True),
    s: AsyncSession = Depends(get_session),
) -> ProxyImportOut:
    """Dan danh sach: `host:port`, `host:port:user:pass`, `user:pass@host:port`, co
    `scheme://` cung duoc. `test` thi thu tung cai ngay - proxy chua thu la an so."""
    if scheme.lower() not in SCHEMES:
        raise HTTPException(422, f"scheme phải là một trong {sorted(SCHEMES)}")
    report = proxylist.parse(text, default_scheme=scheme.lower())

    existing = {
        (p.host.lower(), p.port) for p in (await s.execute(select(Proxy))).unique().scalars().all()
    }
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

    created: list[Proxy] = []
    skipped: list[dict] = []
    for parsed in report.rows:
        if (parsed.host.lower(), parsed.port) in existing:
            skipped.append(
                {"line": parsed.line, "raw": f"{parsed.host}:{parsed.port}", "detail": "đã có"}
            )
            continue
        proxy = Proxy(
            label=next_label(),
            host=parsed.host,
            port=parsed.port,
            scheme=parsed.scheme,
            username=parsed.username,
            kind=kind,
        )
        if parsed.password:
            proxy.set_password(parsed.password)
        s.add(proxy)
        created.append(proxy)
        existing.add((parsed.host.lower(), parsed.port))
    await s.commit()

    results: list[dict] = []
    if test and created:
        # Tuan tu, khong song song: bat hai muoi ket noi cung luc tu mot may la dung
        # mau hinh nha cung cap proxy hay chan.
        for proxy in created:
            r = await proxytest.run(proxy)
            results.append(
                {"label": proxy.label, "ok": r.ok, "exit_ip": r.exit_ip, "error": r.error}
            )
        await s.commit()

    # Proxy moi vao: acc xay kenh dang thieu proxy duoc gan ngay, khong phai nhap lai.
    attach = await proxypool.attach_missing(s) if created else {"attached": 0}

    exits = [r["exit_ip"] for r in results if r["exit_ip"]]
    return ProxyImportOut(
        attached=int(attach["attached"]),
        created=len(created),
        labels=[p.label for p in created],
        tested=len(results),
        passed=sum(1 for r in results if r["ok"]),
        duplicate_exit_ips=sorted({ip for ip in exits if exits.count(ip) > 1}),
        results=results,
        skipped=skipped,
        problems=[{"line": p.line, "raw": p.raw, "detail": p.detail} for p in report.problems],
    )


@router.post("/attach-missing", response_model=ProxyAttachOut)
async def attach_missing(s: AsyncSession = Depends(get_session)) -> ProxyAttachOut:
    """Gan proxy cho acc xay kenh con thieu (proxy OK dang it acc nhat, toi da
    ACCOUNTS_PER_PROXY acc moi proxy). Acc da co proxy khong bi doi."""
    return ProxyAttachOut(**(await proxypool.attach_missing(s)))


@router.post("/{proxy_id}/test", response_model=ProxyTestOut)
async def test_proxy(proxy_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> ProxyTestOut:
    proxy = await s.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(404, "Không có proxy này")
    r = await proxytest.run(proxy)
    await s.commit()
    return ProxyTestOut(ok=r.ok, exit_ip=r.exit_ip, latency_ms=r.latency_ms, error=r.error)


@router.delete("/{proxy_id}", response_model=DeleteOut)
async def delete_proxy(proxy_id: uuid.UUID, s: AsyncSession = Depends(get_session)) -> DeleteOut:
    proxy = await s.get(Proxy, proxy_id)
    if proxy is None:
        raise HTTPException(404, "Không có proxy này")
    bound = (
        (await s.execute(select(Profile).where(Profile.proxy_id == proxy_id)))
        .unique()
        .scalars()
        .all()
    )
    if bound:
        raise HTTPException(
            409,
            f"{len(bound)} tài khoản đang gắn proxy này. Xoá là chúng mở trình duyệt bằng IP "
            "thật của bạn. Đổi proxy cho chúng trước.",
        )
    label = proxy.label
    await s.delete(proxy)
    await s.commit()
    return DeleteOut(deleted=True, detail=f"Đã xoá {label}")
