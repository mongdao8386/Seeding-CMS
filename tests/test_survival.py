"""Phan tich song sot.

Con so o day dan den quyet dinh ton tien - doi nha cung cap proxy, keo dai warm-up,
ha nhip dang. Nen cai duoc kiem nhieu nhat khong phai phep chia, ma la nhung cho con
so co the noi doi: nhom qua nho, va tai khoan chua chet bi tinh nham la da chet.
"""

from datetime import UTC, datetime, timedelta

from seeding.core import survival
from seeding.models import AccountStatus, ProxyKind

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _fact(
    *,
    status=AccountStatus.ACTIVE,
    age_days=30,
    warmup_days: float | None = 7,
    posted_days_ago: float | None = 1,
    daily_cap=3,
    proxy_kind=ProxyKind.RESIDENTIAL,
    proxy_label="Provider A",
    takeovers=0,
) -> survival._Fact:
    created = NOW - timedelta(days=age_days)
    return survival._Fact(
        status=status,
        created_at=created,
        warmup_started_at=(created if warmup_days is not None else None),
        last_posted_at=(
            None
            if posted_days_ago is None
            else (
                created + timedelta(days=warmup_days)
                if warmup_days is not None
                else NOW - timedelta(days=posted_days_ago)
            )
        ),
        daily_cap=daily_cap,
        proxy_kind=proxy_kind,
        proxy_label=proxy_label,
        proxy_region="vn",
        takeovers=takeovers,
    )


# --------------------------------------------------------------------- cohort


def test_survival_is_the_share_still_standing():
    facts = [_fact() for _ in range(3)] + [_fact(status=AccountStatus.DEAD)]
    cohort = survival._cohort("x", facts, NOW)
    assert cohort.n == 4
    assert cohort.alive == 3
    assert cohort.survival == 0.75


def test_a_suspended_account_counts_as_gone():
    """Bi treo thi ve thuc te la mat. Tinh no la "con song" lam moi ty le dep len."""
    cohort = survival._cohort("x", [_fact(status=AccountStatus.SUSPENDED)], NOW)
    assert cohort.gone == 1
    assert cohort.survival == 0.0


def test_an_account_waiting_for_a_person_is_still_counted_alive():
    """NEEDS_HUMAN la cuu duoc. Tinh no la chet thi moi checkpoint deu thanh mot cai
    chet gia, va so lieu se bao dong nhung thu khong dang bao dong."""
    cohort = survival._cohort("x", [_fact(status=AccountStatus.NEEDS_HUMAN)], NOW)
    assert cohort.alive == 1
    assert cohort.needs_human == 1


def test_takeovers_per_account_averages_over_the_whole_cohort():
    facts = [_fact(takeovers=4), _fact(takeovers=0)]
    assert survival._cohort("x", facts, NOW).takeovers_per_account == 2.0


def test_an_empty_cohort_does_not_divide_by_zero():
    cohort = survival._cohort("x", [], NOW)
    assert cohort.survival == 0.0
    assert cohort.takeovers_per_account == 0.0


# ------------------------------------------------------- nhom nho khong dang tin


def test_a_small_cohort_is_marked_untrustworthy():
    """Voi 8 tai khoan mot nhom thi chenh lech 60% va 75% la nhieu, khong phai phat hien."""
    cohort = survival._cohort("x", [_fact() for _ in range(survival.MIN_COHORT - 1)], NOW)
    assert cohort.trustworthy is False


def test_a_big_enough_cohort_is_marked_trustworthy():
    cohort = survival._cohort("x", [_fact() for _ in range(survival.MIN_COHORT)], NOW)
    assert cohort.trustworthy is True


def test_the_flag_travels_with_the_row_so_a_reader_cannot_miss_it():
    row = survival._cohort("x", [_fact()], NOW).as_dict()
    assert row["trustworthy"] is False
    assert row["n"] == 1


# --------------------------------------------------------------- so ngay song


def test_a_living_account_is_measured_up_to_now_not_to_its_last_post():
    """Tinh den lan dang cuoi thi mot tai khoan khoe manh dang nghi cuoi tuan se hien
    ra nhu vua chet."""
    fact = _fact(age_days=30, warmup_days=2)
    assert survival._days_lived(fact, NOW) == 30


def test_a_dead_account_is_measured_to_its_last_post():
    fact = _fact(status=AccountStatus.DEAD, age_days=30, warmup_days=10)
    assert survival._days_lived(fact, NOW) == 10


def test_median_days_lived_only_looks_at_accounts_that_actually_died():
    """Tron ca tai khoan con song vao thi so nay do tuoi doi dan chu khong do tuoi tho."""
    facts = [
        _fact(status=AccountStatus.DEAD, age_days=40, warmup_days=10),
        _fact(status=AccountStatus.DEAD, age_days=40, warmup_days=20),
        _fact(age_days=365),
    ]
    assert survival._cohort("x", facts, NOW).median_days_lived == 15.0


def test_median_is_none_when_nothing_has_died_yet():
    assert survival._cohort("x", [_fact()], NOW).median_days_lived is None


# ------------------------------------------------------------------ chia nhom


def test_grouping_puts_the_biggest_cohort_first():
    """Nhom lon nhat la nhom dang tin nhat, nen no phai o tren."""
    facts = [_fact(proxy_label="A") for _ in range(2)] + [_fact(proxy_label="B") for _ in range(5)]
    cohorts = survival._group(facts, lambda f: f.proxy_label, NOW)
    assert [c.label for c in cohorts] == ["B", "A"]


def test_accounts_with_no_proxy_are_their_own_cohort_not_dropped():
    """Bo di thi tong khong khop voi so tai khoan, va khong ai doi chieu duoc."""
    facts = [_fact(), _fact(proxy_kind=None, proxy_label=None)]
    labels = [c.label for c in survival._group(facts, survival._kind_label, NOW)]
    assert "no proxy" in labels


def test_every_account_lands_in_exactly_one_posting_rate_bucket():
    for cap in range(1, 20):
        assert survival._rate_bucket(_fact(daily_cap=cap))


def test_warmup_buckets_split_at_the_documented_boundaries():
    assert survival._warmup_bucket(_fact(age_days=30, warmup_days=1), NOW) == "under 3 days"
    assert survival._warmup_bucket(_fact(age_days=30, warmup_days=5), NOW) == "3-7 days"
    assert survival._warmup_bucket(_fact(age_days=30, warmup_days=10), NOW) == "7-14 days"
    assert survival._warmup_bucket(_fact(age_days=60, warmup_days=40), NOW) == "14+ days"


def test_an_account_that_never_warmed_up_is_shown_as_such():
    fact = _fact(warmup_days=None, posted_days_ago=1)
    assert survival._warmup_bucket(fact, NOW) == "no warm-up"


def test_an_account_still_warming_counts_its_warm_up_up_to_now():
    """Chua dang lan nao thi no van dang trong warm-up, khong phai warm-up dai 0 ngay."""
    fact = _fact(age_days=9, warmup_days=9, posted_days_ago=None)
    assert survival._warmup_bucket(fact, NOW) == "7-14 days"
