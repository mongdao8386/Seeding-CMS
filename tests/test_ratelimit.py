from datetime import UTC, datetime, timedelta

from seeding.core.ratelimit import effective_daily_cap
from seeding.models import Account


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
