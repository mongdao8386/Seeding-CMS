"""Khung gio vang dang bai.

Hai lop: `slots.choose` thuan tuy (moc nao, mui gio nao, tra deu ra sao), va planner
that su bam job vao moc (khong co moc thi van nhu cu). Cuoi cung la API round-trip
tren DB that, dung nen tang `youtube` de khong dung vao bang TikTok cua nguoi van hanh.
"""

import random
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings
from seeding.domain.models import Campaign, CampaignGroup, ContentItem, Platform, PostKind
from seeding.scheduling import planner, slots

VN = ZoneInfo("Asia/Ho_Chi_Minh")

# Bang cua nguoi van hanh cho TikTok, thu Ba va thu Tu.
TABLE = {1: [time(2), time(4), time(9)], 2: [time(7), time(8), time(23)]}


def _vn(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=VN)


# ---------------------------------------------------------------- choose()


def test_picks_a_slot_on_the_first_day_that_still_has_one():
    # 2026-09-07 la thu Hai. Thu Hai khong co moc -> thu Ba.
    when = slots.choose(TABLE, not_before=_vn(2026, 9, 7, 20), rng=random.Random(1), zone=VN)
    local = when.astimezone(VN)
    assert local.date() == datetime(2026, 9, 8).date()
    assert local.time() in TABLE[1]
    assert when.tzinfo is UTC, "planner luu UTC"


def test_slots_already_passed_today_are_skipped():
    # Thu Ba 05:00: 02h va 04h da qua, chi con 09h.
    when = slots.choose(TABLE, not_before=_vn(2026, 9, 8, 5), rng=random.Random(7), zone=VN)
    assert when.astimezone(VN) == _vn(2026, 9, 8, 9)


def test_the_hour_itself_still_counts():
    when = slots.choose(TABLE, not_before=_vn(2026, 9, 8, 9), rng=random.Random(7), zone=VN)
    assert when.astimezone(VN) == _vn(2026, 9, 8, 9)


def test_after_the_last_slot_of_the_day_it_rolls_forward():
    # Thu Tu 23:30 -> thu Nam khong co, ... -> thu Ba tuan sau.
    when = slots.choose(TABLE, not_before=_vn(2026, 9, 9, 23, 30), rng=random.Random(3), zone=VN)
    local = when.astimezone(VN)
    assert local.date() == datetime(2026, 9, 15).date()
    assert local.time() in TABLE[1]


def test_accounts_are_spread_across_the_days_slots_not_stacked_on_the_first():
    """Bay tai khoan cung dang luc 2h00 la mot mau hinh. Rai qua 2h/4h/9h thi khong."""
    picks = {
        slots.choose(TABLE, not_before=_vn(2026, 9, 7, 20), rng=random.Random(seed), zone=VN)
        .astimezone(VN)
        .time()
        for seed in range(40)
    }
    assert picks == set(TABLE[1])


def test_same_seed_same_slot():
    a = slots.choose(TABLE, not_before=_vn(2026, 9, 7, 20), rng=random.Random(42), zone=VN)
    b = slots.choose(TABLE, not_before=_vn(2026, 9, 7, 20), rng=random.Random(42), zone=VN)
    assert a == b


def test_hours_are_read_in_the_audience_timezone_not_utc():
    """ "2h00" la 2 gio sang Viet Nam = 19:00 UTC hom truoc. Nham UTC la lech 7 tieng."""
    single = {1: [time(2)]}
    when = slots.choose(single, not_before=_vn(2026, 9, 7, 20), rng=random.Random(0), zone=VN)
    assert when == datetime(2026, 9, 7, 19, 0, tzinfo=UTC)


def test_an_empty_table_is_an_error_not_a_silent_default():
    with pytest.raises(ValueError):
        slots.choose({}, not_before=_vn(2026, 9, 7, 20), rng=random.Random(0), zone=VN)


# ----------------------------------------------------------------- planner


def _campaign(starts_at: datetime, window: int = 3600) -> Campaign:
    return Campaign(id=uuid.uuid4(), starts_at=starts_at, stagger_window_seconds=window)


def _group() -> CampaignGroup:
    return CampaignGroup(
        id=uuid.uuid4(),
        platform=Platform.TIKTOK,
        post_kind=PostKind.POST,
        target={},
        account_ids=[],
    )


def _content() -> ContentItem:
    return ContentItem(id=uuid.uuid4(), title_template="A", body_template="B", media_ref=None)


def test_planner_lands_each_job_on_a_slot_plus_a_few_minutes():
    starts = _vn(2026, 9, 7, 20).astimezone(UTC)
    for _ in range(12):
        job = planner._build_job(
            _campaign(starts), _group(), _content(), uuid.uuid4(), "k", {}, slots=TABLE, zone=VN
        )
        local = job.scheduled_at.astimezone(VN)
        slot = datetime.combine(
            local.date(),
            min(
                TABLE[1],
                key=lambda t: abs(
                    (datetime.combine(local.date(), t, tzinfo=VN) - local).total_seconds()
                ),
            ),
            tzinfo=VN,
        )
        drift = (local - slot).total_seconds()
        assert 0 <= drift <= slots.JITTER_MAX_SECONDS, f"{local} lech {drift}s khoi moc {slot}"


def test_planner_without_slots_keeps_the_old_start_plus_spread_behaviour():
    starts = datetime(2026, 9, 7, 13, 0, tzinfo=UTC)
    job = planner._build_job(_campaign(starts, 600), _group(), _content(), uuid.uuid4(), "k", {})
    assert starts <= job.scheduled_at <= starts + timedelta(seconds=600)


def test_slot_jitter_is_capped_even_when_the_campaign_spread_is_an_hour():
    starts = _vn(2026, 9, 7, 20).astimezone(UTC)
    job = planner._build_job(
        _campaign(starts, 3600),
        _group(),
        _content(),
        uuid.uuid4(),
        "k",
        {},
        slots={1: [time(2)]},
        zone=VN,
    )
    assert (
        _vn(2026, 9, 8, 2)
        <= job.scheduled_at
        <= _vn(2026, 9, 8, 2) + timedelta(seconds=slots.JITTER_MAX_SECONDS)
    )


# --------------------------------------------------------------------- API


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


async def test_slots_round_trip_replaces_rather_than_appends(client):
    try:
        r = await client.put(
            "/slots", json={"platform": "youtube", "weekdays": [0], "hours": [6, 10, 22]}
        )
        assert r.status_code == 200, r.text
        assert sorted(s["hour"] for s in r.json()) == [6, 10, 22]

        # Gui lai voi mot moc: la thay the, khong phai them vao.
        r = await client.put("/slots", json={"platform": "youtube", "weekdays": [0], "hours": [6]})
        assert [s["hour"] for s in r.json()] == [6]

        listed = [s for s in (await client.get("/slots")).json() if s["platform"] == "youtube"]
        assert [(s["weekday"], s["hour"]) for s in listed] == [(0, 6)]

        meta = (await client.get("/slots/meta")).json()
        assert meta["timezone"] == get_settings().schedule_timezone
    finally:
        await client.delete("/slots/youtube")


async def test_bad_hours_are_rejected(client):
    r = await client.put("/slots", json={"platform": "youtube", "weekdays": [0], "hours": [25]})
    assert r.status_code == 422


# ------------------------------------------------------------------ defer()


def test_deferral_lands_on_the_next_golden_slot_not_plus_one_hour():
    """Job bi governor chan luc thu Ba 03:30 (VN). +1h la 04:30 - khong phai moc nao.

    Moc ke tiep cach it nhat mot tieng: 04h thi qua gan (30 phut), nen phai la 09h.
    """
    now = _vn(2026, 9, 8, 3, 30)  # thu Ba
    when = slots.defer(TABLE, now=now, rng=random.Random(1), zone=VN).astimezone(VN)
    assert when == _vn(2026, 9, 8, 9)


def test_deferral_without_a_table_is_plus_one_hour():
    now = _vn(2026, 9, 8, 3, 30)
    assert slots.defer(None, now=now, rng=random.Random(1), zone=VN) == now + timedelta(hours=1)
    assert slots.defer({}, now=now, rng=random.Random(1), zone=VN) == now + timedelta(hours=1)


def test_deferral_rolls_to_the_next_day_when_today_is_spent():
    # Thu Ba 22:00: het moc thu Ba -> thu Tu 07h.
    now = _vn(2026, 9, 8, 22)
    when = slots.defer(TABLE, now=now, rng=random.Random(1), zone=VN).astimezone(VN)
    assert when.date() == datetime(2026, 9, 9).date()
    assert when.time() in TABLE[2]
