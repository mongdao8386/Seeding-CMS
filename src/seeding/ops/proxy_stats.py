"""Proxy nao tai duoc web TikTok, bao lau - do tu chinh cac job trinh duyet.

Do 08/09/2026: proxy dan cu "luc duoc luc khong" quanh moc 2-4 phut, hai proxy khong bao
gio hien trang. Truoc day chi biet dieu do bang script do tay; gio moi job trinh duyet
ghi lai ket qua cho proxy cua no (Redis, khong migration), va man hinh Tai khoan hien
"TikTok 3/5 · ~150s" canh moi proxy de nguoi van hanh biet proxy nao nen thay.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from seeding.ops import flags

KEEP_RECENT = 8


def _key(proxy_id: uuid.UUID | str) -> str:
    return f"proxy:{proxy_id}:tiktok"


async def note_render(proxy_id: uuid.UUID | str | None, ok: bool, seconds: float | None) -> None:
    """Mot lan mo trang TikTok qua proxy: trang hien (ok, sau bao lau) hay khong."""
    if proxy_id is None:
        return
    cur = await flags.get_flag(_key(proxy_id)) or {}
    recent = list(cur.get("recent") or [])
    recent.append({"ok": ok, "s": round(seconds) if seconds is not None else None})
    recent = recent[-KEEP_RECENT:]
    oks = [r["s"] for r in recent if r["ok"] and r["s"] is not None]
    await flags.set_flag(
        _key(proxy_id),
        {
            "ok": int(cur.get("ok") or 0) + (1 if ok else 0),
            "fail": int(cur.get("fail") or 0) + (0 if ok else 1),
            "recent": recent,
            "avg_s": round(sum(oks) / len(oks)) if oks else None,
            "last_ok": ok,
            "at": datetime.now(UTC).isoformat(),
        },
    )


async def read(proxy_id: uuid.UUID | str) -> dict | None:
    return await flags.get_flag(_key(proxy_id))


def summary(stats: dict | None) -> str | None:
    """'3/5 · ~150s' de hien tren dashboard. None khi chua do lan nao."""
    if not stats:
        return None
    total = int(stats.get("ok") or 0) + int(stats.get("fail") or 0)
    if not total:
        return None
    text = f"{stats.get('ok') or 0}/{total}"
    if stats.get("avg_s"):
        text += f" · ~{stats['avg_s']}s"
    return text
