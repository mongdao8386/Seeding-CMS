"""Nuoi huong ra ngoai: chon dich tu For You va xep thanh lich.

Phan thuan tuy (khong DB, khong mang): loc dich, ngan sach theo ngay warm-up, va cach
xep job. Tinh chat can giu: khong bao gio dung vao tai khoan cua minh, binh luan chi
vao video da tha tim va di SAU tha tim, ngay 0 nhe hon.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

from seeding.domain.models import Account, ActivityKind
from seeding.platforms.tiktok import warm as outreach
from seeding.platforms.tiktok.web import FeedItem


def _item(handle, item_id, views=1_000_000):
    return FeedItem(
        item_id=item_id,
        author_handle=handle,
        author_id="1",
        author_sec_uid="S",
        views=views,
        likes=100,
        desc="",
    )


def _account(days_in: int | None) -> Account:
    now = datetime.now(UTC)
    return Account(
        id=uuid.uuid4(),
        handle="mine",
        daily_cap=3,
        warmup_started_at=None if days_in is None else now - timedelta(days=days_in, hours=1),
    )


FEED = [
    _item("creator.a", "1"),
    _item("creator.a", "2"),  # cung creator -> chi giu mot
    _item("mine", "3"),  # tai khoan cua minh -> bo
    _item("creator.b", "4", views=500),  # qua nho -> bo
    _item("creator.c", "5"),
    _item("creator.d", "6"),
]


def test_pick_targets_skips_own_accounts_small_videos_and_repeats():
    got = outreach.pick_targets(FEED, own_handles={"mine"}, rng=random.Random(1))
    assert sorted(i.author_handle for i in got) == ["creator.a", "creator.c", "creator.d"]
    assert all(i.views >= outreach.MIN_VIEWS for i in got)


def test_day_zero_budget_is_half_and_never_comments():
    b = outreach.budget_for(_account(0), datetime.now(UTC), random.Random(1))
    assert b.comments == 0
    assert b.likes <= outreach.LIKES_PER_DAY[1] // 2 + 1
    later = outreach.budget_for(_account(3), datetime.now(UTC), random.Random(1))
    assert later.likes >= outreach.LIKES_PER_DAY[0]


def test_comments_only_on_liked_videos_and_after_the_like():
    day = datetime(2026, 9, 9, tzinfo=UTC).date()
    window = (datetime(2026, 9, 9, 0, 0, tzinfo=UTC), datetime(2026, 9, 9, 16, 0, tzinfo=UTC))
    targets = [_item("c1", "10"), _item("c2", "20"), _item("c3", "30")]
    jobs = outreach.build_jobs(
        _account(3),
        targets,
        outreach.Budget(likes=3, follows=1, comments=2),
        day=day,
        window=window,
        rng=random.Random(7),
    )
    likes = {j.target_url: j.scheduled_at for j in jobs if j.kind is ActivityKind.ENGAGE}
    comments = [j for j in jobs if j.kind is ActivityKind.COMMENT]
    follows = [j for j in jobs if j.kind is ActivityKind.FOLLOW]

    assert len(likes) == 3 and len(comments) == 2 and len(follows) == 1
    for c in comments:
        assert c.target_url in likes, "binh luan vao video chua tha tim"
        assert c.scheduled_at >= likes[c.target_url] + outreach.COMMENT_AFTER_LIKE
    assert follows[0].target_url == "https://www.tiktok.com/@c1"
    assert all(j.target_account_id is None for j in jobs), "nguoi la, khong phai tai khoan minh"


def test_same_feed_and_seed_give_the_same_plan():
    day = datetime(2026, 9, 9, tzinfo=UTC).date()
    window = (datetime(2026, 9, 9, 0, 0, tzinfo=UTC), datetime(2026, 9, 9, 16, 0, tzinfo=UTC))
    targets = [_item("c1", "10"), _item("c2", "20")]
    a = outreach.build_jobs(
        _account(2), targets, outreach.Budget(2, 1, 1), day=day, window=window, rng=random.Random(3)
    )
    b = outreach.build_jobs(
        _account(2), targets, outreach.Budget(2, 1, 1), day=day, window=window, rng=random.Random(3)
    )
    assert [(j.kind, j.target_url, j.scheduled_at) for j in a] == [
        (j.kind, j.target_url, j.scheduled_at) for j in b
    ]


def test_no_targets_means_no_jobs():
    day = datetime(2026, 9, 9, tzinfo=UTC).date()
    window = (datetime(2026, 9, 9, 0, 0, tzinfo=UTC), datetime(2026, 9, 9, 16, 0, tzinfo=UTC))
    assert (
        outreach.build_jobs(
            _account(2), [], outreach.Budget(5, 2, 1), day=day, window=window, rng=random.Random(1)
        )
        == []
    )
