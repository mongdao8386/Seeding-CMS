"""Do thi tuong tac cheo: cac luat an toan, kiem bang toan hoc chu khong bang y kien.

Fingerprint hong thi mat mot tai khoan. Do thi hong thi mat CA CUM trong mot lan quet.
Nen cac test o day khong kiem "ham co chay khong" ma kiem cac tinh chat cua HINH DANG
ma ham sinh ra - do moi la thu nen tang nhin thay.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from seeding.core import graph
from seeding.core.graph import _density, _pick_edge


def _ids(n: int) -> list[uuid.UUID]:
    return [uuid.uuid4() for _ in range(n)]


def _grow(count: int, edges_wanted: int, rng: random.Random) -> set:
    """Chay _pick_edge nhieu lan de dung mot do thi, dung luat that."""
    ids = _ids(count)
    edges: set = set()
    following: dict = {}
    for _ in range(edges_wanted):
        picked = _pick_edge(ids, edges, following, rng)
        if picked is None:
            break
        edges.add(picked)
        following[picked[0]] = following.get(picked[0], 0) + 1
    return edges


# ------------------------------------------------------------------- mat do


def test_density_of_an_empty_graph_is_zero():
    assert _density(10, 0) == 0.0


def test_density_of_a_complete_graph_is_one():
    """Do thi day la thu tuyet doi khong duoc tao ra. Biet no bang 1.0 la de nhan ra no."""
    assert _density(5, 5 * 4) == 1.0


def test_density_does_not_divide_by_zero_on_a_single_account():
    assert _density(1, 0) == 0.0


def test_the_ceiling_is_far_below_a_complete_graph():
    """0.15 khong phai con so thieng, nhung no phai o phia cong dong nguoi that
    (0.01-0.10) chu khong phai phia do thi day."""
    assert 0 < graph.MAX_DENSITY < 0.25


# ------------------------------------------------------------ khong tao trung


def test_the_same_edge_is_never_created_twice():
    rng = random.Random(1)
    edges = _grow(8, 40, rng)
    assert len(edges) == len(set(edges))


def test_an_account_never_follows_itself():
    rng = random.Random(2)
    for follower, target in _grow(6, 30, rng):
        assert follower != target


# ---------------------------------------------------- khong ai thanh trung tam


def test_no_account_exceeds_the_following_ceiling():
    """Mot tai khoan theo doi tat ca nhung tai khoan con lai la trung tam cua cum, va
    trung tam la thu re nhat de tim."""
    rng = random.Random(3)
    edges = _grow(40, 500, rng)

    following: dict = {}
    for follower, _ in edges:
        following[follower] = following.get(follower, 0) + 1

    assert max(following.values()) <= graph.MAX_INTERNAL_FOLLOWING


def test_no_account_collects_far_more_edges_than_the_rest():
    """Cai can tranh la TRUNG TAM, khong phai su chenh lech.

    Phan bo hoan toan deu - moi tai khoan theo doi dung n nguoi - moi la thu bat thuong:
    do thi xa hoi that co duoi dai. Nen o day chi kiem rang khong ai vot han len, chu
    khong doi moi nguoi bang nhau.
    """
    rng = random.Random(4)
    edges = _grow(20, 60, rng)

    following: dict = {}
    for follower, _ in edges:
        following[follower] = following.get(follower, 0) + 1

    counts = list(following.values())
    mean = sum(counts) / len(counts)
    assert max(counts) <= mean * 2.5, f"mot tai khoan gom qua nhieu canh: {sorted(counts)}"


def test_the_degree_distribution_is_not_perfectly_flat():
    """Hai muoi tai khoan theo doi dung ba nguoi moi cai la mot hinh dang duoc tao ra,
    khong phai mot hinh dang moc len.

    Do tren nhieu hat giong chu khong mot: day la tinh chat xac suat, va mot hat giong
    duy nhat co the tinh co ra phang ma khong co nghia la ham sai.
    """
    varied = 0
    for seed in range(8):
        following: dict = {}
        for follower, _ in _grow(20, 60, random.Random(seed)):
            following[follower] = following.get(follower, 0) + 1
        if len(set(following.values())) > 1:
            varied += 1

    assert varied >= 6, f"chi {varied}/8 hat giong cho ra phan bo co do lech"


def test_the_planner_replays_the_same_graph_from_the_same_seed():
    """`edges` la set cac UUID, ma thu tu duyet set phu thuoc hash - no doi moi lan
    chay tien trinh. Neu khong sap xep truoc khi xao thi cung mot hat giong cho ra do
    thi khac nhau, va luc no lam sai thi khong dung lai duoc de xem."""
    ids = _ids(10)

    def build(seed: int) -> list:
        edges: set = set()
        following: dict = {}
        rng = random.Random(seed)
        out = []
        for _ in range(12):
            picked = _pick_edge(ids, edges, following, rng)
            if picked is None:
                break
            edges.add(picked)
            following[picked[0]] = following.get(picked[0], 0) + 1
            out.append(picked)
        return out

    assert build(99) == build(99)


def test_growth_stops_instead_of_looping_forever_when_the_graph_is_full():
    """Het cho ma khong dung thi vong lap treo - im lang, o trong worker, luc 3 gio sang."""
    rng = random.Random(5)
    ids = _ids(3)
    edges: set = set()
    following: dict = {}
    for _ in range(100):
        picked = _pick_edge(ids, edges, following, rng)
        if picked is None:
            break
        edges.add(picked)
        following[picked[0]] = following.get(picked[0], 0) + 1
    assert _pick_edge(ids, edges, following, rng) is None
    assert len(edges) == 3 * 2, "do thi ba dinh day la sau canh"


# -------------------------------------------------------- khong doi xung hoan toan


def test_follows_are_not_all_reciprocated():
    """A theo doi B thi B theo doi lai A, dung 100% cac cap - do la hinh dang cua mot
    danh sach duoc gioi thieu, khong phai cua nhung nguoi tim thay nhau."""
    rng = random.Random(6)
    edges = _grow(30, 200, rng)
    if len(edges) < 10:
        pytest.skip("qua it canh de do")

    mutual = sum(1 for f, t in edges if (t, f) in edges)
    assert mutual / len(edges) < 0.7


def test_some_follows_are_reciprocated_though():
    """Khong co cap nao theo doi lan nhau cung la mot hinh dang la."""
    rng = random.Random(7)
    edges = _grow(12, 60, rng)
    mutual = sum(1 for f, t in edges if (t, f) in edges)
    assert mutual > 0


# ------------------------------------------------------------------- hang so


def test_engagement_never_covers_every_follower():
    """Bai nao cung dung mot nhom thich la mau hinh ro hon ca so luot thich."""
    assert max(graph.ENGAGE_SHARE) < 1.0


def test_the_first_like_never_arrives_within_a_minute():
    """Muoi hai luot thich trong bon muoi giay la nhip cua mot cai nut."""
    low, _ = graph.ENGAGE_DELAY
    assert low >= timedelta(minutes=5)


def test_engagement_is_spread_over_hours_not_minutes():
    low, high = graph.ENGAGE_DELAY
    assert high - low >= timedelta(hours=2)


def test_reposting_is_rare():
    """Chia se lai cong khai, o lai vinh vien, va noi hai tai khoan truoc mat moi nguoi."""
    assert 0 < graph.REPOST_CHANCE <= 0.1


def test_the_graph_grows_slowly():
    """Nam muoi canh trong mot buoi sang la mot su kien, khong phai mot mang xa hoi."""
    assert graph.MAX_NEW_EDGES_PER_DAY <= 15


# ------------------------------------------------------------------- do dac


def _audit_of(edges: set, ids: list) -> graph.GraphAudit:
    """Dung GraphAudit truc tiep tu mot do thi cho san, khong can database."""
    edge_set = set(edges)
    mutual = sum(1 for f, t in edge_set if (t, f) in edge_set) // 2
    following: dict = {}
    touched: set = set()
    for f, t in edge_set:
        following[f] = following.get(f, 0) + 1
        touched.add(f)
        touched.add(t)

    result = graph.GraphAudit(
        accounts=len(ids),
        edges=len(edge_set),
        density=_density(len(ids), len(edge_set)),
        mutual_pairs=mutual,
        mutual_rate=(mutual / len(edge_set)) if edge_set else 0.0,
        max_following=max(following.values(), default=0),
        isolated=len(set(ids) - touched),
    )
    return result


def test_a_complete_graph_is_over_the_density_ceiling():
    """Day la truong hop phai bi bat. Neu no lot qua thi ca `audit` la trang tri."""
    ids = _ids(6)
    complete = {(a, b) for a in ids for b in ids if a != b}
    assert _audit_of(complete, ids).density > graph.MAX_DENSITY


def test_a_sparse_graph_is_under_the_ceiling():
    ids = _ids(20)
    sparse = {(ids[i], ids[(i + 1) % 20]) for i in range(20)}
    assert _audit_of(sparse, ids).density <= graph.MAX_DENSITY


def test_an_audit_with_no_warnings_reports_itself_safe():
    assert graph.GraphAudit(0, 0, 0.0, 0, 0.0, 0, 0).safe is True


def test_an_audit_with_a_warning_is_not_safe():
    audit = graph.GraphAudit(0, 0, 0.0, 0, 0.0, 0, 0, warnings=["bad"])
    assert audit.safe is False


def test_the_audit_dict_carries_the_ceiling_so_a_reader_can_judge_the_number():
    """`density: 0.31` khong noi len gi neu khong biet tran la bao nhieu."""
    assert "max_density" in graph.GraphAudit(0, 0, 0.0, 0, 0.0, 0, 0).as_dict()


# ---------------------------------------------- thu khong do duoc thi phai noi


@pytest.mark.asyncio
async def test_the_audit_always_admits_what_it_cannot_see(monkeypatch):
    """He thong chi thay canh giua cac tai khoan cua minh. Ty le voi nguoi that ben
    ngoai moi la con so quan trong nhat, va no khong nam trong database.

    Canh bao do phai LUON hien khi co canh. Lang di mot gioi han khong do duoc thi
    nguoi van hanh se tuong con so tren man hinh la toan bo su that.
    """
    ids = _ids(4)
    edges = [(ids[0], ids[1]), (ids[1], ids[2])]

    class FakeAccount:
        def __init__(self, id):
            self.id = id
            self.platform = "threads"

    async def fake_live(_session, _platform=None):
        return [FakeAccount(i) for i in ids]

    async def fake_edges(_session):
        return edges

    monkeypatch.setattr(graph, "_live_accounts", fake_live)
    monkeypatch.setattr(graph, "_edges", fake_edges)

    result = await graph.audit(None)
    assert result.edges == 2
    assert any("Unverifiable" in w for w in result.warnings)


@pytest.mark.asyncio
async def test_an_empty_graph_raises_no_alarm(monkeypatch):
    """Chua co canh nao thi khong co gi de canh bao - noi thua lam nguoi ta quen doc."""

    async def fake_live(_session, _platform=None):
        return []

    async def fake_edges(_session):
        return []

    monkeypatch.setattr(graph, "_live_accounts", fake_live)
    monkeypatch.setattr(graph, "_edges", fake_edges)

    result = await graph.audit(None)
    assert result.warnings == []
    assert result.safe is True


# ------------------------------------------------------------ tuong tac bai


@pytest.mark.asyncio
async def test_a_post_with_no_link_gets_no_engagement():
    """Khong co lien ket thi khong biet tuong tac vao dau. Doan mot URL nghia la tha
    cam xuc vao bai cua nguoi la."""

    class FakeJob:
        id = uuid.uuid4()
        account_id = uuid.uuid4()
        remote_url = None

    assert await graph.engage_with(None, FakeJob(), now=datetime.now(UTC)) == []


# ------------------------------------------------- khong lap viec khong lam duoc


def test_reddit_has_no_interaction_recipe():
    """Reddit di bang API, khong co profile trinh duyet. Do la ly do no phai bi loai
    khoi do thi - chu khong phai vi quen viet cong thuc cho no."""
    from seeding.browser.interact import RECIPES
    from seeding.models import Platform

    assert Platform.REDDIT not in RECIPES


def test_every_platform_with_a_recipe_can_build_a_profile_url():
    """Thieu mau URL thi job theo doi chay den giua chung roi moi hong, sau khi da mo
    mot phien trinh duyet 400MB."""
    from seeding.browser.interact import RECIPES, profile_url

    for platform in RECIPES:
        url = profile_url(platform, "someone")
        assert url and url.startswith("https://"), platform


def test_a_leading_at_sign_is_not_doubled_in_the_url():
    """Nguoi ta go handle co ca @ va khong co @. `https://x.com/@@ten` la mot trang 404."""
    from seeding.browser.interact import profile_url
    from seeding.models import Platform

    assert profile_url(Platform.X, "@seed_01") == profile_url(Platform.X, "seed_01")


# ------------------------------------------- ty le vo nghia o N nho


def test_a_tiny_account_set_can_still_have_a_few_follows():
    """Voi ba tai khoan, mot canh duy nhat da la 17% mat do - tren tran. Ap ty le o
    day nghia la nhom nho khong bao gio co noi mot luot theo doi nao, trong khi mot
    nguoi theo doi mot nguoi khac trong nhom ba nguoi la chuyen khong ai de y.
    """
    assert graph.MIN_ACCOUNTS_FOR_DENSITY > 3


def test_a_small_set_is_still_capped_in_absolute_terms():
    """Bo qua ty le khong co nghia la tha cua. Duoi nguong van phai thua canh."""
    rng = random.Random(31)
    ids = _ids(4)
    edges: set = set()
    following: dict = {}
    ceiling = len(ids)
    for _ in range(ceiling):
        picked = _pick_edge(ids, edges, following, rng)
        assert picked is not None
        edges.add(picked)
        following[picked[0]] = following.get(picked[0], 0) + 1

    # Bon tai khoan, bon canh: xa do thi day (12 canh).
    assert len(edges) == 4
    assert len(edges) < 4 * 3
