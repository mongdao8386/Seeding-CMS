"""Tieng Viet di duoc het duong ong.

Noi dung seeding cua nguoi dung la tieng Viet. Neu co bat ky mat xich nao lam hong dau
thanh dieu thi bai dang len sai chinh ta - va mot bai sai chinh ta la bai khong ai doc,
tuc la ca chien dich vo nghia ma khong co loi nao bao.

Nguy hiem hon la cho ma tieng Viet lam CHET tien trinh chu khong phai lam sai chu.
Console Windows mac dinh cp1252, ma cp1252 khong ma hoa duoc tieng Viet.
"""

import random

from seeding.content import hashtags
from seeding.content.spintax import combinations, content_hash, expand, rng_for

VN = "Chào mọi người, hôm nay đẹp trời quá"


def test_spintax_keeps_the_diacritics():
    rng = random.Random(1)
    out = expand("{Chào|Xin chào} mọi người", rng)
    assert out in ("Chào mọi người", "Xin chào mọi người")


def test_spintax_counts_vietnamese_options_correctly():
    assert combinations("{Chào|Xin chào|Chào bạn} {nhé|nha}") == 6


def test_hashtags_with_diacritics_survive_expansion():
    """Hashtag tieng Viet co dau la chuyen binh thuong tren Facebook va TikTok."""
    rng = random.Random(2)
    pools = {"vn": ["#sàigòn", "#hànội", "#ẩmthực", "#dulịch"]}
    out = hashtags.expand("Ăn gì hôm nay [[tags:vn:2]]", pools, rng)

    assert "Ăn gì hôm nay" in out
    picked = [w for w in out.split() if w.startswith("#")]
    assert len(picked) == 2
    assert all(tag in pools["vn"] for tag in picked)


def test_two_texts_differing_only_by_a_diacritic_are_not_the_same_content():
    """`ma` va `mã` la hai tu khac nhau. Neu hash bo dau thi he thong se tuong hai bai
    khac nhau la trung nhau, roi chan mot bai hoan toan hop le."""
    assert content_hash("con ma", "") != content_hash("con mã", "")


def test_the_seeded_rng_is_stable_with_vietnamese_input():
    import uuid

    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    template = "{Chào|Xin chào} mọi người, {đẹp trời|mát mẻ} quá"
    assert expand(template, rng_for(a, b, c)) == expand(template, rng_for(a, b, c))


def test_logging_vietnamese_does_not_kill_the_process():
    """Console Windows la cp1252. `detect()` doc chu tu trang that de nhan dien
    checkpoint roi ghi vao log - mot tai khoan Facebook tieng Viet gap checkpoint se
    lam do ca vong xu ly, dung luc no can nguoi nhat.
    """
    import structlog

    from seeding.worker.settings import configure_logging

    configure_logging()
    structlog.get_logger("test").info("checkpoint", evidence=VN, detail="Xác minh danh tính")


def test_a_vietnamese_csv_imports_with_its_diacritics_intact():
    from seeding.ops import bulk

    report = bulk.parse("platform,handle,persona\nthreads,seed_01,Sinh viên Hà Nội\n")
    assert report.ok
    assert report.rows[0].persona == "Sinh viên Hà Nội"


def test_the_csv_reader_accepts_co_as_yes():
    """Nguoi Viet go 'co' hoac 'có' vao cot start_warmup."""
    from seeding.ops import bulk

    rows = bulk.parse(
        "platform,handle,start_warmup\nthreads,a,có\nthreads,b,co\nthreads,c,khong\n"
    ).rows
    assert [r.start_warmup for r in rows] == [True, True, False]
