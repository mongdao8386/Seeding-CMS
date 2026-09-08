from datetime import UTC, datetime, timedelta

from seeding.domain.models import Account
from seeding.scheduling.governor import effective_daily_cap


def _account(daily_cap=6, warmup_started_at=None):
    return Account(daily_cap=daily_cap, warmup_started_at=warmup_started_at)


def test_account_without_warmup_is_capped_at_one():
    now = datetime.now(UTC)
    assert effective_daily_cap(_account(), now, warmup_days=14) == 1


def test_cap_ramps_up_during_warmup():
    now = datetime.now(UTC)
    start = now - timedelta(days=7)
    mid = effective_daily_cap(_account(daily_cap=6, warmup_started_at=start), now, 14)
    assert 1 < mid < 6


def test_cap_reaches_full_after_warmup():
    now = datetime.now(UTC)
    start = now - timedelta(days=30)
    assert effective_daily_cap(_account(daily_cap=6, warmup_started_at=start), now, 14) == 6


def test_cap_never_drops_below_one():
    now = datetime.now(UTC)
    start = now - timedelta(days=1)
    assert effective_daily_cap(_account(daily_cap=1, warmup_started_at=start), now, 14) >= 1


# ------------------------------------------------- quiet period: nuoi truoc, dang sau


def test_quiet_period_allows_no_posts_at_all():
    """Ngay 0 va ngay 1 cua warm-up: tran la 0, khong phai 1.

    Quy tac cua nguoi van hanh: nuoi 2-3 ngay (tuong tac, follow, binh luan) roi moi
    dang. Truoc day ramp bat dau o 1 bai/ngay tu ngay dau tien - tuc la tai khoan vua
    mua ve la dang ngay, dung dieu he thong nay ton tai de tranh.
    """
    now = datetime.now(UTC)
    for days_in in (0, 1):
        start = now - timedelta(days=days_in, hours=1)
        acc = _account(daily_cap=3, warmup_started_at=start)
        assert effective_daily_cap(acc, now, warmup_days=3, quiet_days=2) == 0


def test_posting_opens_the_day_after_the_quiet_period():
    now = datetime.now(UTC)
    start = now - timedelta(days=2, hours=1)
    acc = _account(daily_cap=3, warmup_started_at=start)
    assert effective_daily_cap(acc, now, warmup_days=3, quiet_days=2) >= 1


def test_quiet_period_defaults_to_zero_for_old_callers():
    """Khong truyen quiet_days thi hanh vi y het truoc: ngay 0 duoc 1 bai."""
    now = datetime.now(UTC)
    acc = _account(daily_cap=3, warmup_started_at=now - timedelta(hours=1))
    assert effective_daily_cap(acc, now, warmup_days=3) == 1


def test_account_never_started_warmup_ignores_quiet_period():
    """Khong co warmup_started_at thi khong biet dang o ngay thu may - giu tran 1 nhu cu."""
    now = datetime.now(UTC)
    assert effective_daily_cap(_account(), now, warmup_days=3, quiet_days=2) == 1
