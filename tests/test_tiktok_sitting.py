"""Phien luot xem TikTok: lap lich thuan tuy va giai ma ke hoach.

Ngan sach mot ngay phai rai het len 2-3 phien, ngay chi-xem khong co hanh dong nao,
follow/binh luan/dang lai khong bao gio nhieu hon so tim trong cung phien, va ke hoach
di qua target_url phai doc lai duoc nguyen ven."""

from __future__ import annotations

import random
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

from seeding.domain.models import ActivityKind
from seeding.platforms import outreach
from seeding.platforms.tiktok import sitting

DAY = date(2026, 9, 9)
WINDOW = (
    datetime(2026, 9, 9, 0, 0, tzinfo=UTC),
    datetime(2026, 9, 9, 16, 0, tzinfo=UTC),
)


def _account(started_days_ago: int | None = 3):
    started = (
        datetime.now(UTC) - timedelta(days=started_days_ago)
        if started_days_ago is not None
        else None
    )
    return SimpleNamespace(id=uuid.uuid4(), handle="thu", warmup_started_at=started)


def test_budget_is_spread_across_sittings_and_never_exceeds_likes():
    jobs = sitting.build_sittings(
        _account(),
        outreach.Budget(likes=6, follows=3, comments=2, reposts=1),
        ["làm đẹp"],
        day=DAY,
        window=WINDOW,
        rng=random.Random(7),
    )
    assert 2 <= len(jobs) <= 3
    plans = [sitting.decode(j.target_url) for j in jobs]
    assert all(j.kind is ActivityKind.BROWSE_FEED for j in jobs)
    assert sum(p.likes for p in plans) == 6
    for p in plans:
        assert p.follows <= p.likes and p.comments <= p.likes and p.reposts <= p.likes
        assert p.videos > p.likes, "khong tha tim video dau tien"
        assert 4 <= p.videos <= 9
    assert sum(1 for p in plans if p.source == "search") == 1
    assert [j.scheduled_at for j in jobs] == sorted(j.scheduled_at for j in jobs)
    assert all(WINDOW[0] <= j.scheduled_at <= WINDOW[1] for j in jobs)


def test_watch_only_sittings_carry_no_actions():
    jobs = sitting.build_sittings(
        _account(),
        outreach.Budget(likes=6, follows=3, comments=2, reposts=1),
        [],
        day=DAY,
        window=WINDOW,
        rng=random.Random(1),
        watch_only=True,
    )
    plans = [sitting.decode(j.target_url) for j in jobs]
    assert plans and all(p.watch_only for p in plans)
    assert all(p.source == "foryou" for p in plans), "khong co tu khoa thi chi For You"


def test_first_warmup_day_is_watch_only(monkeypatch):
    from seeding import config

    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(warm_watch_only_days=1))
    monkeypatch.setattr(sitting, "get_settings", config.get_settings)
    now = datetime.now(UTC) + timedelta(minutes=1)
    assert sitting.watch_only_today(_account(0), now)
    assert not sitting.watch_only_today(_account(1), now)
    assert sitting.watch_only_today(_account(None), now), "chua bat dau warm-up = ngay 0"


def test_plan_round_trips_through_target_url_and_describes_itself():
    plan = sitting.Plan(source="search", keyword="ẩm thực", videos=6, likes=2, follows=1)
    assert sitting.decode(plan.dumps()) == plan
    assert sitting.decode("https://www.tiktok.com/@a/video/1") is None
    assert sitting.decode("sitting:{broken") is None
    text = sitting.describe(plan)
    assert "ẩm thực" in text and "6 video" in text and "2 tim" in text and "1 follow" in text
    assert "chỉ xem" in sitting.describe(sitting.Plan(videos=4))
    assert plan.url("https://www.tiktok.com").startswith("https://www.tiktok.com/search?q=")
    assert sitting.Plan().url("https://www.tiktok.com") == "https://www.tiktok.com/foryou"
