"""Tuong tac cheo giua cac tai khoan cua chinh minh: theo doi, tha cam xuc, chia se lai.

Day la tinh nang co ich nhat va nguy hiem nhat trong ca he thong.

Co ich: mot bai dang khong co tuong tac nao thi khong lan duoc. Vai luot thich dau tien
la thu quyet dinh nen tang co day bai di xa hay khong.

Nguy hiem: no tao ra mot DO THI. Va do thi hanh vi moi la cach nen tang bat trai tai
khoan - de hon nhieu so voi fingerprint. Fingerprint hong thi mat mot tai khoan; do thi
hong thi mat CA CUM trong mot lan quet, vi mot tai khoan bi gan co dan ra tat ca nhung
tai khoan lien quan.

Hinh dang lo ra ngay lap tuc:

    - Do thi day. Nam muoi tai khoan ai cung theo doi tat ca moi nguoi. Trong doi that
      khong ton tai cum nao nhu vay, ke ca gia dinh.
    - Doi xung hoan toan. A theo doi B thi B theo doi lai A, dung 100% cac cap.
    - Khep kin. Tai khoan chi theo doi tai khoan cua minh, khong theo doi ai ben ngoai.
    - Dong bo. Bai vua len bon muoi giay da co muoi hai luot thich, deu tu dung nhung
      tai khoan lan nao cung thich.

Module nay khong cho phep tao ra nhung hinh dang do. Cac luat nam TRONG ham chu khong
phai la tuy chon co the tat - mot tuy chon "cho phep do thi day" chi ton tai de co
nguoi bat no vao luc ba gio sang.

MOT DIEU KHONG DO DUOC, ghi ro o day va lap lai trong `audit()`: he thong chi thay canh
GIUA CAC TAI KHOAN CUA MINH. No khong biet moi tai khoan theo doi bao nhieu nguoi that
ben ngoai - ma ty le noi/ngoai moi la con so quan trong nhat. Mot tai khoan theo doi 8
tai khoan noi bo va 300 nguoi that thi hoan toan binh thuong; cung 8 canh do ma khong
theo doi ai khac thi la mot cai bay. Hai truong hop nay giong het nhau trong database.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from seeding.models import (
    Account,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    JobStatus,
    PostJob,
    Relationship,
    RelationStatus,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------- luat

# Mat do toi da cua do thi noi bo: so canh chia cho so canh co the co.
#
# Do thi day la 1.0. Cong dong nguoi that thuong nam trong khoang 0.01-0.10. Lay 0.15
# la da rong rai. Vuot moc nay thi khong con la "mot nhom nguoi quen nhau" nua, ma la
# mot vat the khong ton tai trong tu nhien.
MAX_DENSITY = 0.15

# Duoi nguong nay thi KHONG ap mat do, vi mat do la mot ty le va ty le thi vo nghia
# o N nho. Voi ba tai khoan, mot canh duy nhat da la 17% - tren tran, trong khi mot
# nguoi theo doi mot nguoi khac trong nhom ba nguoi la chuyen khong ai de y.
#
# Duoi nguong, luat la so tuyet doi: trung binh moi tai khoan mot canh, khong hon.
MIN_ACCOUNTS_FOR_DENSITY = 10

# Ty le cac cap theo doi lan nhau. Trong doi that con so nay khong phai 0 cung khong
# phai 1: co qua lai, nhung khong phai luon luon.
TARGET_MUTUAL_RATE = 0.25

# Toi da bao nhieu tai khoan noi bo ma MOT tai khoan duoc theo doi. Tran cung, ap
# truoc ca mat do: no la thu chan mot tai khoan bien thanh trung tam cua ca cum.
MAX_INTERNAL_FOLLOWING = 12

# Bao nhieu canh moi duoc tao trong mot ngay, tren toan he thong. Do thi phai LON LEN
# theo thoi gian. Nam muoi canh xuat hien trong mot buoi sang la mot su kien, khong
# phai mot mang xa hoi.
MAX_NEW_EDGES_PER_DAY = 8

# Bao nhieu phan tram nguoi theo doi se tuong tac voi mot bai. Khong bao gio la tat ca.
ENGAGE_SHARE = (0.2, 0.45)

# Cho bao lau roi moi tuong tac. Luot thich dau tien khong duoc den sau bon muoi giay:
# do la nhip cua mot cai nut, khong phai cua mot nguoi tinh co luot thay.
ENGAGE_DELAY = (timedelta(minutes=18), timedelta(hours=20))

# Chia se lai la hanh dong de thay nhat: no cong khai, no o lai vinh vien tren trang ca
# nhan, va no noi hai tai khoan lai voi nhau ngay truoc mat moi nguoi. Rat hiem.
REPOST_CHANCE = 0.06


# ------------------------------------------------------------------- do dac


@dataclass(slots=True)
class GraphAudit:
    """Do thi hien tai dang co hinh gi."""

    accounts: int
    edges: int
    density: float
    mutual_pairs: int
    mutual_rate: float
    max_following: int
    isolated: int
    warnings: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return not self.warnings

    def as_dict(self) -> dict:
        return {
            "accounts": self.accounts,
            "edges": self.edges,
            "density": round(self.density, 4),
            "mutual_pairs": self.mutual_pairs,
            "mutual_rate": round(self.mutual_rate, 3),
            "max_following": self.max_following,
            "isolated": self.isolated,
            "max_density": MAX_DENSITY,
            "safe": self.safe,
            "warnings": self.warnings,
        }


def _density(nodes: int, edges: int) -> float:
    """Mat do cua do thi co huong: canh that chia cho canh co the co."""
    possible = nodes * (nodes - 1)
    return edges / possible if possible else 0.0


async def _live_accounts(session: AsyncSession, platform=None) -> list[Account]:
    """Tai khoan con dung duoc. Acc chet khong tao canh moi va khong tinh vao mat do."""
    stmt = select(Account).where(
        Account.status.in_([AccountStatus.NEW, AccountStatus.WARMING, AccountStatus.ACTIVE])
    )
    if platform is not None:
        stmt = stmt.where(Account.platform == platform)
    return list((await session.execute(stmt)).unique().scalars().all())


async def _edges(session: AsyncSession) -> list[tuple[uuid.UUID, uuid.UUID]]:
    rows = (await session.execute(select(Relationship.follower_id, Relationship.target_id))).all()
    return [(a, b) for a, b in rows]


async def audit(session: AsyncSession, platform=None) -> GraphAudit:
    """Do thi noi bo dang co hinh gi, va cho nao dang nguy hiem.

    Chay duoc bat cu luc nao. Muc dich la de nguoi van hanh nhin thay hinh dang truoc
    khi nen tang nhin thay no.
    """
    accounts = await _live_accounts(session, platform)
    ids = {a.id for a in accounts}
    edges = [(f, t) for f, t in await _edges(session) if f in ids and t in ids]

    edge_set = set(edges)
    mutual = sum(1 for f, t in edge_set if (t, f) in edge_set) // 2

    following: dict[uuid.UUID, int] = {}
    touched: set[uuid.UUID] = set()
    for f, t in edges:
        following[f] = following.get(f, 0) + 1
        touched.add(f)
        touched.add(t)

    density = _density(len(ids), len(edge_set))
    result = GraphAudit(
        accounts=len(ids),
        edges=len(edge_set),
        density=density,
        mutual_pairs=mutual,
        mutual_rate=(mutual / len(edge_set)) if edge_set else 0.0,
        max_following=max(following.values(), default=0),
        isolated=len(ids - touched),
    )

    if density > MAX_DENSITY and len(ids) >= MIN_ACCOUNTS_FOR_DENSITY:
        result.warnings.append(
            f"The internal follow graph is {density:.0%} dense — above the {MAX_DENSITY:.0%} "
            "ceiling. A cluster where everyone follows everyone does not occur naturally, "
            "and one flagged account exposes the rest."
        )
    if result.mutual_rate > 0.7 and len(edge_set) >= 10:
        result.warnings.append(
            f"{result.mutual_rate:.0%} of follows are reciprocated. Real follows are not "
            "symmetric that often — this reads as a set of accounts introduced to each other "
            "rather than found."
        )
    if result.max_following > MAX_INTERNAL_FOLLOWING:
        result.warnings.append(
            f"One account follows {result.max_following} of your own accounts, over the "
            f"{MAX_INTERNAL_FOLLOWING} ceiling. It has become the hub of the cluster, and a hub "
            "is the cheapest thing to find."
        )

    # Canh bao nay LUON hien khi co canh, va co y nhu vay: no la thu he thong khong tu
    # kiem tra duoc, nen no phai duoc nhac lai chu khong duoc lang di.
    if edge_set:
        result.warnings.append(
            "Unverifiable from here: this only counts follows between your own accounts. "
            "What matters more is the ratio to real accounts each one follows. If these are "
            "the only accounts they follow, the cluster is obvious no matter how sparse it is."
        )

    return result


# --------------------------------------------------------------- lap do thi


async def plan_follows(
    session: AsyncSession,
    *,
    platform=None,
    budget: int = MAX_NEW_EDGES_PER_DAY,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> list[Relationship]:
    """Them mot it canh moi, trong gioi han an toan. Chay mot lan moi ngay.

    Khong bao gio tao du do thi trong mot lan. Mot mang xa hoi lon len tung it mot;
    nam muoi canh xuat hien cung mot buoi sang la mot su kien khong giai thich duoc.
    """
    rng = rng or random.Random()
    now = now or datetime.now(UTC)
    budget = max(0, min(budget, MAX_NEW_EDGES_PER_DAY))

    accounts = await _live_accounts(session, platform)
    if len(accounts) < 2 or budget == 0:
        return []

    # Chi lap canh cho nen tang thuc su lam duoc. Reddit di bang API, khong co profile
    # trinh duyet va khong co cong thuc theo doi - lap canh cho no la tao ra viec khong
    # bao gio lam duoc, va nhung canh do se nam mai o trang thai `planned` trong khi
    # `audit()` van dem chung vao mat do.
    from seeding.browser.interact import RECIPES as INTERACT_RECIPES

    by_platform: dict = {}
    for account in accounts:
        if account.platform not in INTERACT_RECIPES:
            continue
        by_platform.setdefault(account.platform, []).append(account)

    if not by_platform:
        log.info("graph.no_supported_platform", accounts=len(accounts))
        return []

    existing = set(await _edges(session))
    following: dict[uuid.UUID, int] = {}
    for f, _t in existing:
        following[f] = following.get(f, 0) + 1

    created: list[Relationship] = []

    for group in by_platform.values():
        if len(group) < 2:
            continue

        ids = [a.id for a in group]
        edges_here = {(f, t) for f, t in existing if f in set(ids) and t in set(ids)}

        # Bao nhieu canh nua thi cham tran cua rieng nen tang nay.
        if len(ids) >= MIN_ACCOUNTS_FOR_DENSITY:
            ceiling = int(MAX_DENSITY * len(ids) * (len(ids) - 1))
        else:
            # N nho: dem canh thay vi do ty le. Trung binh mot canh moi tai khoan.
            ceiling = len(ids)
        room = ceiling - len(edges_here)

        for _ in range(budget):
            if room <= 0 or len(created) >= budget:
                break

            candidate = _pick_edge(ids, edges_here, following, rng)
            if candidate is None:
                break
            follower, target = candidate

            edge = Relationship(follower_id=follower, target_id=target)
            session.add(edge)
            created.append(edge)
            edges_here.add((follower, target))
            existing.add((follower, target))
            following[follower] = following.get(follower, 0) + 1
            room -= 1

    if created:
        await session.commit()
        log.info("graph.planned", edges=len(created))
    return created


def _pick_edge(
    ids: list[uuid.UUID],
    edges: set[tuple[uuid.UUID, uuid.UUID]],
    following: dict[uuid.UUID, int],
    rng: random.Random,
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """Chon mot canh moi, uu tien nhung tai khoan dang theo doi it nhat.

    Uu tien do la thu chan TRUNG TAM hinh thanh. Chon hoan toan ngau nhien thi vai tai
    khoan se tinh co gom nhieu canh, va mot trung tam la thu re nhat de tim.

    Chan trung tam khong co nghia la lam cho phang tuyet doi. Hai muoi tai khoan theo
    doi dung ba nguoi moi cai la mot hinh dang duoc TAO RA chu khong phai moc len; do
    thi xa hoi that co duoi dai. Nhanh "theo doi lai" o duoi co y khong tuan theo thu
    tu nay, va chinh no tao ra do lech tu nhien do.

    Mot phan cac canh duoc tao theo chieu nguoc lai canh da co (theo doi lai), nhung
    chi mot phan: doi xung 100% la hinh dang cua mot danh sach duoc gioi thieu, khong
    phai cua nhung nguoi tim thay nhau.
    """
    # Theo doi lai mot canh da co - chi thinh thoang.
    if edges and rng.random() < TARGET_MUTUAL_RATE:
        # `edges` la mot set cac UUID, ma thu tu duyet set phu thuoc vao hash - no doi
        # moi lan chay tien trinh. Sap xep truoc khi xao de ket qua TAI LAP DUOC theo
        # hat giong, giong nhu spintax. Mot bo lap do thi cho ra ket qua khac nhau moi
        # lan chay lai voi cung dau vao thi khong the go loi duoc khi no lam sai.
        back = sorted(((t, f) for f, t in edges if (t, f) not in edges), key=str)
        rng.shuffle(back)
        for follower, target in back:
            if following.get(follower, 0) < MAX_INTERNAL_FOLLOWING:
                return follower, target

    # Nguoi theo doi: uu tien acc dang theo doi it nhat.
    order = sorted(ids, key=lambda i: (following.get(i, 0), rng.random()))
    for follower in order:
        if following.get(follower, 0) >= MAX_INTERNAL_FOLLOWING:
            continue
        targets = [t for t in ids if t != follower and (follower, t) not in edges]
        if targets:
            return follower, rng.choice(targets)

    return None


# ------------------------------------------------------------ tuong tac bai


async def engage_with(
    session: AsyncSession,
    job: PostJob,
    *,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> list[ActivityJob]:
    """Lap lich tuong tac cho mot bai VUA DANG THANH CONG.

    Ba luat, moi luat chan mot hinh dang bi bat:

      - Chi nhung tai khoan DA theo doi nguoi dang. Mot luot thich tu tai khoan chua
        bao gio thay bai nay o dau la mot canh khong giai thich duoc.
      - Chi mot phan, khong bao gio tat ca. Bai nao cung dung mot nhom thich la mau
        hinh ro hon ca so luot thich.
      - Cach nhau va cham. Muoi hai luot thich trong bon muoi giay la nhip cua mot cai
        nut, khong phai cua nhung nguoi tinh co luot thay.
    """
    rng = rng or random.Random()
    now = now or datetime.now(UTC)

    if not job.remote_url:
        # Khong co lien ket thi khong biet tuong tac vao dau. Khong doan.
        return []

    followers = list(
        (
            await session.execute(
                select(Account)
                .join(Relationship, Relationship.follower_id == Account.id)
                .where(
                    Relationship.target_id == job.account_id,
                    Relationship.status == RelationStatus.DONE,
                    Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
                )
            )
        )
        .unique()
        .scalars()
        .all()
    )
    if not followers:
        return []

    share = rng.uniform(*ENGAGE_SHARE)
    count = max(1, min(len(followers), round(len(followers) * share)))
    chosen = rng.sample(followers, count)

    low, high = ENGAGE_DELAY
    span = (high - low).total_seconds()

    jobs: list[ActivityJob] = []
    for account in chosen:
        kind = ActivityKind.REPOST if rng.random() < REPOST_CHANCE else ActivityKind.ENGAGE
        when = now + low + timedelta(seconds=rng.uniform(0, span))
        activity = ActivityJob(
            account_id=account.id,
            kind=kind,
            scheduled_at=when,
            duration_seconds=rng.randint(25, 110),
            target_account_id=job.account_id,
            target_url=job.remote_url,
        )
        session.add(activity)
        jobs.append(activity)

    await session.commit()
    log.info("graph.engagement_planned", post=str(job.id), count=len(jobs))
    return jobs


async def due_follow_jobs(
    session: AsyncSession,
    *,
    limit: int = 4,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> list[ActivityJob]:
    """Bien cac canh dang cho thanh job that, mot it moi lan.

    Canh duoc lap ke hoach truoc roi moi thuc hien sau, va rai ra: mot tai khoan bam
    theo doi tam nguoi trong hai phut la mot chuoi hanh dong khong ai lam.
    """
    rng = rng or random.Random()
    now = now or datetime.now(UTC)

    pending = list(
        (
            await session.execute(
                select(Relationship)
                .join(Account, Account.id == Relationship.follower_id)
                .where(
                    Relationship.status == RelationStatus.PLANNED,
                    Account.status.in_([AccountStatus.WARMING, AccountStatus.ACTIVE]),
                )
                .order_by(Relationship.created_at)
                .limit(limit)
            )
        )
        .unique()
        .scalars()
        .all()
    )

    jobs: list[ActivityJob] = []
    for edge in pending:
        already = (
            await session.execute(
                select(func.count())
                .select_from(ActivityJob)
                .where(
                    ActivityJob.account_id == edge.follower_id,
                    ActivityJob.target_account_id == edge.target_id,
                    ActivityJob.kind == ActivityKind.FOLLOW,
                    ActivityJob.status.in_([JobStatus.SCHEDULED, JobStatus.RUNNING]),
                )
            )
        ).scalar_one()
        if already:
            continue

        job = ActivityJob(
            account_id=edge.follower_id,
            kind=ActivityKind.FOLLOW,
            scheduled_at=now + timedelta(minutes=rng.randint(5, 240)),
            duration_seconds=rng.randint(30, 120),
            target_account_id=edge.target_id,
        )
        session.add(job)
        jobs.append(job)

    if jobs:
        await session.commit()
    return jobs


async def mark_edge(
    session: AsyncSession,
    follower_id: uuid.UUID,
    target_id: uuid.UUID,
    ok: bool,
    detail: str | None = None,
) -> None:
    """Ghi ket qua that cua mot lan theo doi.

    Canh chi tinh la DONE khi trinh duyet lam duoc that. Coi canh da lap ke hoach la da
    xong thi `audit()` se bao mot do thi khong ton tai, va ca tinh toan mat do tro nen
    vo nghia.
    """
    edge = (
        await session.execute(
            select(Relationship).where(
                Relationship.follower_id == follower_id,
                Relationship.target_id == target_id,
            )
        )
    ).scalar_one_or_none()
    if edge is None:
        return

    edge.status = RelationStatus.DONE if ok else RelationStatus.FAILED
    edge.done_at = datetime.now(UTC) if ok else None
    edge.note = detail
    await session.commit()
