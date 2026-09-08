"""Proxy: danh sach, dan hang loat, thu, xoa. Mot acc mot proxy - so proxy phai bang so acc."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.api.deps import DEFAULT_PAGE, MAX_PAGE, get_session, paginate
from seeding.api.schemas import DeleteOut, Page, ProxyImportOut, ProxyOut, ProxyTestOut
from seeding.domain.models import Account, Profile, Proxy, ProxyKind, ProxyStatus
from seeding.ops import proxylist, proxytest

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

    bound = dict(
        (
            await s.execute(
                select(Profile.proxy_id, Account.handle)
                .join(Account, Account.id == Profile.account_id)
                .where(Profile.proxy_id.in_([p.id for p in proxies] or [uuid.uuid4()]))
            )
        ).all()
    )
    items = []
    for p in proxies:
        out = ProxyOut.model_validate(p)
        out.bound_handle = bound.get(p.id)
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

    exits = [r["exit_ip"] for r in results if r["exit_ip"]]
    return ProxyImportOut(
        created=len(created),
        labels=[p.label for p in created],
        tested=len(results),
        passed=sum(1 for r in results if r["ok"]),
        duplicate_exit_ips=sorted({ip for ip in exits if exits.count(ip) > 1}),
        results=results,
        skipped=skipped,
        problems=[{"line": p.line, "raw": p.raw, "detail": p.detail} for p in report.problems],
    )


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
