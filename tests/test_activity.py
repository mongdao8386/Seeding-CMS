"""Lich hoat dong nen: phai rai deu trong khung gio thuc va khong bi don cum."""

import random
from collections import Counter
from datetime import UTC, date, datetime
from itertools import pairwise

from seeding.core.activity import (
    ACTIVE_FROM,
    ACTIVE_TO,
    ACTIVITY_PER_POST,
    _pick_kind,
    _slots,
)
from seeding.models import ActivityKind

DAY = date(2026, 8, 22)


def test_makes_the_requested_number_of_slots():
    assert len(_slots(DAY, 18, random.Random(1))) == 18


def test_every_slot_falls_inside_waking_hours():
    """Tai khoan hoat dong luc 4 gio sang moi ngay la bat thuong ro hon la it hoat dong."""
    low = datetime.combine(DAY, ACTIVE_FROM, tzinfo=UTC)
    high = datetime.combine(DAY, ACTIVE_TO, tzinfo=UTC)
    for when in _slots(DAY, 30, random.Random(2)):
        assert low <= when <= high


def test_slots_come_out_in_order():
    slots = _slots(DAY, 20, random.Random(3))
    assert slots == sorted(slots)


def test_slots_do_not_bunch_up():
    """Random tu do hay tao ra cum ba bon lan lien tiep roi im lang ca buoi.

    Chia o roi lech trong o thi khoang cach nho nhat van phai dang ke.
    """
    slots = _slots(DAY, 16, random.Random(4))
    gaps = [(b - a).total_seconds() for a, b in pairwise(slots)]
    bucket = (16 * 3600) / 16
    assert min(gaps) > bucket * 0.05


def test_asking_for_nothing_gives_nothing():
    assert _slots(DAY, 0, random.Random(1)) == []


def test_browsing_the_feed_is_the_most_common_activity():
    """Cuon feed la viec pho bien nhat cua nguoi that."""
    rng = random.Random(9)
    counts = Counter(_pick_kind(rng) for _ in range(4000))
    assert counts.most_common(1)[0][0] is ActivityKind.BROWSE_FEED
    assert counts[ActivityKind.BROWSE_FEED] > counts[ActivityKind.WATCH_VIDEO]


def test_every_kind_shows_up_eventually():
    rng = random.Random(10)
    seen = {_pick_kind(rng) for _ in range(4000)}
    assert seen == set(ActivityKind)


def test_there_is_much_more_ambient_activity_than_posting():
    """Ty le nay la ca diem cua he thong con - dat qua thap thi vo nghia."""
    assert ACTIVITY_PER_POST >= 5
