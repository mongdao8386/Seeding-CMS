"""Tai khoan song duoc bao lau, va cai gi lam no chet.

Day la cau hoi duy nhat thuc su quan trong khi van hanh seeding, va cung la cau hoi
gan nhu khong ai do. Nguoi ta doi proxy vi "nghe noi loai kia tot hon", keo dai warm-up
vi "cho chac", roi khong bao gio biet thu nao co tac dung.

He thong da ghi du de tra loi: Account co warmup_started_at va status, Profile noi
account voi proxy, TakeoverRequest dem so lan bi chan.

MOT CANH BAO nam ngay trong ket qua chu khong chi trong tai lieu: voi 8 tai khoan mot
nhom thi chenh lech 60% va 75% la nhieu, khong phai phat hien. Moi hang deu mang `n`,
va `trustworthy` chi bat khi n du lon. Doc bang so tuyet doi thi nguoi ta se doi ca
ha tang proxy vi mot khac biet do may rui.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.models import Account, AccountStatus, Profile, Proxy, ProxyKind, TakeoverRequest

# Duoi nguong nay thi con so chi de tham khao, khong de ra quyet dinh. 12 khong phai
# con so thieng - no chi du de mot tai khoan chet khong lam ty le nhay 20 diem.
MIN_COHORT = 12

# Coi la "da chet" - khong quay lai duoc nua.
_GONE = (AccountStatus.DEAD, AccountStatus.SUSPENDED)


@dataclass(slots=True)
class Cohort:
    """Mot nhom tai khoan cung mot dac diem."""

    label: str
    n: int
    alive: int
    gone: int
    needs_human: int
    # Tong so lan phai nho nguoi, chia cho so tai khoan. Doc duoc hon ty le chet vi
    # no hien ra som - mot nhom bi chan lien tuc se chet, chi la chua chet.
    takeovers_per_account: float
    median_days_lived: float | None

    @property
    def survival(self) -> float:
        return round(self.alive / self.n, 3) if self.n else 0.0

    @property
    def trustworthy(self) -> bool:
        return self.n >= MIN_COHORT

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "n": self.n,
            "alive": self.alive,
            "gone": self.gone,
            "needs_human": self.needs_human,
            "survival": self.survival,
            "takeovers_per_account": round(self.takeovers_per_account, 2),
            "median_days_lived": self.median_days_lived,
            "trustworthy": self.trustworthy,
        }


@dataclass(slots=True)
class _Fact:
    """Tat ca nhung gi biet ve mot tai khoan, gom lai de chia nhom kieu nao cung duoc."""

    status: AccountStatus
    created_at: datetime
    warmup_started_at: datetime | None
    last_posted_at: datetime | None
    daily_cap: int
    proxy_kind: ProxyKind | None
    proxy_label: str | None
    proxy_region: str | None
    takeovers: int


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _days_lived(fact: _Fact, now: datetime) -> float:
    """Bao nhieu ngay tu luc tao den luc chet - hoac den bay gio neu con song.

    Khong co cot "chet luc nao", nen voi tai khoan da chet lay lan dang cuoi cung lam
    moc. No hoi som hon su that mot chut; ghi ro o day de khong ai doc con so nay nhu
    la thoi diem chinh xac.
    """
    end = now
    if fact.status in _GONE:
        end = _aware(fact.last_posted_at) or now
    start = _aware(fact.created_at) or now
    return max(0.0, (end - start).total_seconds() / 86_400)


async def _facts(session: AsyncSession) -> list[_Fact]:
    """Mot cau truy van cho tat ca. Chia nhom lam trong bo nho.

    Chia nhom bang SQL nghia la mot cau truy van cho moi cach chia, va them mot cach
    chia moi la them mot cau. So tai khoan o day la hang tram, khong phai hang trieu.
    """
    counts = dict(
        (
            await session.execute(
                select(TakeoverRequest.account_id, func.count()).group_by(
                    TakeoverRequest.account_id
                )
            )
        ).all()
    )

    rows = (
        await session.execute(
            select(Account, Proxy)
            .outerjoin(Profile, Profile.account_id == Account.id)
            .outerjoin(Proxy, Proxy.id == Profile.proxy_id)
        )
    ).all()

    return [
        _Fact(
            status=account.status,
            created_at=account.created_at,
            warmup_started_at=account.warmup_started_at,
            last_posted_at=account.last_posted_at,
            daily_cap=account.daily_cap,
            proxy_kind=proxy.kind if proxy else None,
            proxy_label=proxy.label if proxy else None,
            proxy_region=proxy.region if proxy else None,
            takeovers=counts.get(account.id, 0),
        )
        for account, proxy in rows
    ]


def _cohort(label: str, facts: list[_Fact], now: datetime) -> Cohort:
    gone = [f for f in facts if f.status in _GONE]
    return Cohort(
        label=label,
        n=len(facts),
        alive=len(facts) - len(gone),
        gone=len(gone),
        needs_human=len([f for f in facts if f.status is AccountStatus.NEEDS_HUMAN]),
        takeovers_per_account=(sum(f.takeovers for f in facts) / len(facts)) if facts else 0.0,
        median_days_lived=_median([_days_lived(f, now) for f in gone]),
    )


def _group(facts: list[_Fact], key, now: datetime) -> list[Cohort]:
    buckets: dict[str, list[_Fact]] = {}
    for fact in facts:
        buckets.setdefault(key(fact), []).append(fact)
    return sorted(
        (_cohort(label, rows, now) for label, rows in buckets.items()),
        key=lambda c: (-c.n, c.label),
    )


def _warmup_bucket(fact: _Fact, now: datetime) -> str:
    """Warm-up dai bao nhieu truoc khi tai khoan bat dau dang that.

    Voi tai khoan chua dang lan nao, tinh den bay gio: no van dang trong warm-up.
    """
    started = _aware(fact.warmup_started_at)
    if started is None:
        return "no warm-up"
    end = _aware(fact.last_posted_at) or now
    days = max(0.0, (end - started).total_seconds() / 86_400)
    if days < 3:
        return "under 3 days"
    if days < 7:
        return "3-7 days"
    if days < 14:
        return "7-14 days"
    return "14+ days"


def _kind_label(fact: _Fact) -> str:
    return fact.proxy_kind.value if fact.proxy_kind else "no proxy"


def _rate_bucket(fact: _Fact) -> str:
    cap = fact.daily_cap
    if cap <= 1:
        return "1 post/day"
    if cap <= 3:
        return "2-3 posts/day"
    if cap <= 5:
        return "4-5 posts/day"
    return "6+ posts/day"


async def report(session: AsyncSession, now: datetime | None = None) -> dict:
    """Ty le song sot, cat theo bon cach.

    Bon cach nay khong phai tuy tien: chung dung voi bon thu nguoi van hanh thuc su
    doi duoc - loai proxy, nha cung cap, do dai warm-up, va nhip dang.
    """
    now = now or datetime.now(UTC)
    facts = await _facts(session)

    if not facts:
        return {
            "total": 0,
            "detail": "No accounts yet - there is nothing to measure.",
            "min_cohort": MIN_COHORT,
            "by_proxy_kind": [],
            "by_proxy_label": [],
            "by_warmup_length": [],
            "by_posting_rate": [],
        }

    overall = _cohort("all accounts", facts, now)
    return {
        "total": len(facts),
        "min_cohort": MIN_COHORT,
        "overall": overall.as_dict(),
        "by_proxy_kind": [c.as_dict() for c in _group(facts, _kind_label, now)],
        # Nguoi ta dat ten nha cung cap vao label, nen day la cach gan nhat voi "proxy
        # cua ai". Khong co cot provider rieng, va doan tu host thi sai nhieu hon dung.
        "by_proxy_label": [
            c.as_dict() for c in _group(facts, lambda f: f.proxy_label or "no proxy", now)
        ],
        "by_warmup_length": [
            c.as_dict() for c in _group(facts, lambda f: _warmup_bucket(f, now), now)
        ],
        "by_posting_rate": [c.as_dict() for c in _group(facts, _rate_bucket, now)],
    }
