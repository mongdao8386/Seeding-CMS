"""Quan ly bai DA DANG: xoa tren nen tang, sua chu thich.

Mot bai da len la mot Attempt(ok=True) co remote_id / remote_url. Xoa hay sua no la mot
viec cua worker (di qua proxy cua tai khoan, bang client cua nen tang), ghi thanh mot
ActivityJob kind DELETE / EDIT de hien tren dong thoi gian; ke hoach nam trong
target_url dang "manage:{json}" nhu doi danh tinh.

Nen tang nao lam duoc gi:
    TikTok      xoa (web: /api/aweme/delete/); sua chu thich: khong (web khong co)
    Instagram   xoa, sua chu thich
    X           xoa; sua: khong (chi tai khoan tra tien)
    Reddit      xoa, sua (API)
    Facebook    khong - mo trinh duyet lam tay
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from seeding.domain.models import ActivityJob, ActivityKind, Attempt, Platform

PREFIX = "manage:"

SUPPORTED: dict[ActivityKind, frozenset[Platform]] = {
    ActivityKind.DELETE: frozenset(
        {Platform.TIKTOK, Platform.INSTAGRAM, Platform.X, Platform.REDDIT}
    ),
    ActivityKind.EDIT: frozenset({Platform.INSTAGRAM, Platform.REDDIT}),
}

WHY_NOT: dict[tuple[ActivityKind, Platform], str] = {
    (
        ActivityKind.EDIT,
        Platform.TIKTOK,
    ): "TikTok không sửa được chú thích qua web — mở trình duyệt làm tay.",
    (ActivityKind.EDIT, Platform.X): "X chỉ cho sửa bài với tài khoản trả phí.",
    (ActivityKind.DELETE, Platform.FACEBOOK): "Facebook: mở trình duyệt xoá tay.",
    (ActivityKind.EDIT, Platform.FACEBOOK): "Facebook: mở trình duyệt sửa tay.",
}


@dataclass(frozen=True, slots=True)
class Plan:
    action: str  # delete | edit
    attempt_id: str
    remote_id: str
    remote_url: str
    caption: str | None = None

    @property
    def kind(self) -> ActivityKind:
        return ActivityKind.EDIT if self.action == "edit" else ActivityKind.DELETE


def supported(kind: ActivityKind, platform: Platform) -> str | None:
    """None neu lam duoc, khong thi ly do."""
    if platform in SUPPORTED.get(kind, frozenset()):
        return None
    return WHY_NOT.get((kind, platform), f"{platform.value} chưa hỗ trợ {kind.value}")


def encode(plan: Plan) -> str:
    data = {
        "action": plan.action,
        "attempt_id": plan.attempt_id,
        "remote_id": plan.remote_id,
        "remote_url": plan.remote_url,
    }
    if plan.caption is not None:
        data["caption"] = plan.caption
    return PREFIX + json.dumps(data, ensure_ascii=False, sort_keys=True)


def decode(target_url: str | None) -> Plan | None:
    if not target_url or not target_url.startswith(PREFIX):
        return None
    try:
        d = json.loads(target_url[len(PREFIX) :])
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("action") not in ("delete", "edit"):
        return None
    return Plan(
        action=d["action"],
        attempt_id=str(d.get("attempt_id") or ""),
        remote_id=str(d.get("remote_id") or ""),
        remote_url=str(d.get("remote_url") or ""),
        caption=d.get("caption"),
    )


def describe(plan: Plan | None) -> str:
    if plan is None:
        return "?"
    if plan.action == "delete":
        return "Xoá bài đã đăng"
    return "Sửa chú thích"


async def mark_done(session: AsyncSession, job: ActivityJob, plan: Plan) -> None:
    """Ghi len Attempt goc: xoa luc nao / sua luc nao va chu thich moi. Khong xoa dong
    Attempt - bai da tung len la lich su co that."""
    try:
        attempt = await session.get(Attempt, uuid.UUID(plan.attempt_id))
    except ValueError:
        attempt = None
    if attempt is None:
        return
    metrics = dict(attempt.metrics or {})
    now = datetime.now(UTC).isoformat()
    if plan.action == "delete":
        metrics["deleted_at"] = now
    else:
        metrics["edited_at"] = now
        metrics["caption"] = plan.caption
    attempt.metrics = metrics
