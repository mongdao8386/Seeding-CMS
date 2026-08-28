"""Chien dich lap lai.

Phep tinh moc thoi gian duoc kiem rieng khong can database, vi day la cho de sai nhat:
tinh tu "bay gio" thay vi tu lan sinh truoc se lam mat cac ky bi lo, va quen chan ban
sao tu de ra ban sao se lam lich no theo cap so nhan.
"""

from datetime import UTC, datetime, timedelta

from seeding.core import recurring
from seeding.models import Campaign, Repeat

START = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


def _campaign(**kw) -> Campaign:
    """Campaign roi, khong gan session. Du cho phan tinh moc."""
    fields = {
        "name": "test",
        "starts_at": START,
        "repeat": Repeat.NONE,
        "repeat_until": None,
        "repeat_parent_id": None,
        "last_repeated_at": None,
        "stagger_window_seconds": 3600,
    }
    fields.update(kw)
    return Campaign(**fields)


# ---------------------------------------------------------------- tinh moc


def test_a_one_off_campaign_has_no_next_run():
    assert recurring.next_run(_campaign()) is None


def test_daily_steps_one_day_from_the_start():
    assert recurring.next_run(_campaign(repeat=Repeat.DAILY)) == START + timedelta(days=1)


def test_weekly_steps_seven_days():
    assert recurring.next_run(_campaign(repeat=Repeat.WEEKLY)) == START + timedelta(days=7)


def test_the_next_run_counts_from_the_last_copy_not_from_now():
    """Worker chet mat ba ngay roi song lai thi cac ky bi lo phai duoc bu lan luot.

    Tinh tu "bay gio" thi ba ky do bien mat khong dau vet.
    """
    campaign = _campaign(repeat=Repeat.DAILY, last_repeated_at=START + timedelta(days=3))
    assert recurring.next_run(campaign) == START + timedelta(days=4)


def test_a_chain_stops_after_its_end_date():
    campaign = _campaign(repeat=Repeat.DAILY, repeat_until=START + timedelta(hours=12))
    assert recurring.next_run(campaign) is None


def test_a_chain_still_runs_on_the_last_day_inside_the_window():
    campaign = _campaign(repeat=Repeat.DAILY, repeat_until=START + timedelta(days=30))
    assert recurring.next_run(campaign) == START + timedelta(days=1)


def test_a_naive_timestamp_is_read_as_utc():
    """Postgres tra ve datetime co tzinfo, nhung du lieu nhap tay thi khong chac.

    So mot datetime naive voi mot datetime co mui la TypeError - no se no ngay trong
    cron, o cho khong ai nhin.
    """
    campaign = _campaign(repeat=Repeat.DAILY, starts_at=START.replace(tzinfo=None))
    assert recurring.next_run(campaign) == START + timedelta(days=1)


def test_intervals_exist_for_every_repeating_kind():
    """Them mot kieu lap moi ma quen khai bao khoang thi no se im lang khong bao gio chay."""
    for kind in Repeat:
        if kind is Repeat.NONE:
            assert recurring.interval_for(kind) is None
        else:
            assert recurring.interval_for(kind) is not None


# ------------------------------------------------- ky bi lo thi BO, khong bu


def test_one_missed_period_spawns_that_period():
    campaign = _campaign(repeat=Repeat.DAILY)
    when, skipped = recurring.due_boundary(campaign, START + timedelta(days=1, hours=2))
    assert when == START + timedelta(days=1)
    assert skipped == 0


def test_a_week_of_missed_periods_collapses_into_one():
    """Worker chet mot tuan roi song lai ma bu du bay ky la bay chien dich cung den
    han mot luc - toan bo tai khoan dang lien tuc trong vai phut.

    Bo qua mot ngay seeding khong mat gi. Dang bu ca tuan trong mot buoi thi mat acc.
    """
    campaign = _campaign(repeat=Repeat.DAILY)
    when, skipped = recurring.due_boundary(campaign, START + timedelta(days=7, hours=1))
    assert when == START + timedelta(days=7), "phai lay ky gan nhat, khong phai ky dau"
    assert skipped == 6


def test_nothing_is_due_before_the_first_period_arrives():
    campaign = _campaign(repeat=Repeat.DAILY)
    assert recurring.due_boundary(campaign, START + timedelta(hours=5)) is None


def test_a_one_off_campaign_is_never_due():
    assert recurring.due_boundary(_campaign(), START + timedelta(days=400)) is None


def test_catching_up_never_walks_past_the_end_date():
    campaign = _campaign(repeat=Repeat.DAILY, repeat_until=START + timedelta(days=3))
    when, _ = recurring.due_boundary(campaign, START + timedelta(days=90))
    assert when == START + timedelta(days=3)


def test_an_expired_chain_is_not_due_at_all():
    campaign = _campaign(
        repeat=Repeat.DAILY,
        last_repeated_at=START + timedelta(days=3),
        repeat_until=START + timedelta(days=3),
    )
    assert recurring.due_boundary(campaign, START + timedelta(days=90)) is None
