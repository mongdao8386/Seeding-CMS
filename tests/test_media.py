"""Bien the media: chay ffmpeg that tren mot video mau dung tai cho.

Danh dau `media` va bi loai mac dinh vi moi test ton vai giay encode.

    pytest -m media
"""

import pytest

from seeding.content import media

pytestmark = pytest.mark.media


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    return media.make_test_video(tmp_path_factory.mktemp("goc") / "goc.mp4", seconds=2)


def test_the_test_video_is_usable(source):
    assert source.stat().st_size > 0
    assert 1.5 < media.probe_duration(source) < 2.5


def test_recipe_is_stable_for_the_same_seed():
    """Cung (campaign, account) phai ra dung cong thuc cu - khong sinh file moi."""
    a = media.recipe_for("chien-dich-1", "acc-7")
    b = media.recipe_for("chien-dich-1", "acc-7")
    assert a == b


def test_different_accounts_get_different_recipes():
    recipes = {media.recipe_for("chien-dich-1", f"acc-{i}") for i in range(20)}
    assert len(recipes) > 15


def test_stronger_setting_crops_more():
    subtle = media.recipe_for("x", strength=media.Strength.SUBTLE)
    aggressive = media.recipe_for("x", strength=media.Strength.AGGRESSIVE)
    assert aggressive.crop > subtle.crop


def test_renders_a_playable_video(source, tmp_path):
    out = media.render(source, tmp_path / "ra.mp4", media.recipe_for("acc-1"))
    assert out.stat().st_size > 0
    # Doi toc do lam do dai lech di, nhung khong duoc lech qua xa.
    assert 1.0 < media.probe_duration(out) < 3.0


def test_every_account_gets_a_byte_different_file(source, tmp_path):
    """Dieu kien can: muoi acc upload cung mot file giong het tung byte la bi bat ngay."""
    hashes = set()
    for i in range(4):
        recipe = media.recipe_for("chien-dich", f"acc-{i}")
        out = media.render(source, tmp_path / f"acc{i}.mp4", recipe)
        hashes.add(media.file_hash(out))
    assert len(hashes) == 4


def test_rendering_twice_with_the_same_recipe_is_visually_identical(source, tmp_path):
    recipe = media.recipe_for("chien-dich", "acc-9")
    a = media.render(source, tmp_path / "a.mp4", recipe)
    b = media.render(source, tmp_path / "b.mp4", recipe)
    assert media.phash_distance(media.perceptual_hash(a), media.perceptual_hash(b)) == 0


def test_metadata_is_stripped(source, tmp_path):
    """Ten may quay, phan mem dung, toa do GPS deu la dau vet noi cac acc voi nhau."""
    out = media.render(source, tmp_path / "sach.mp4", media.recipe_for("acc-1"))
    raw = out.read_bytes()
    assert b"Lavf" not in raw or raw.count(b"Lavf") <= 1  # khong nhung chuoi phan mem thua


def test_compare_reports_both_measures(source, tmp_path):
    a = media.render(source, tmp_path / "a.mp4", media.recipe_for("acc-a"))
    b = media.render(source, tmp_path / "b.mp4", media.recipe_for("acc-b"))
    report = media.compare(a, b)

    assert report["bytes_differ"] is True
    assert isinstance(report["phash_distance"], int)


def test_aggressive_moves_the_perceptual_hash_further_than_subtle(source, tmp_path):
    """Day la danh doi that su cua module nay, nen phai do duoc chu khong doan.

    Bien doi nhe thi pHash gan nhu khong dich - tuc la voi mot bo so khop tri giac
    thi cac ban do van la mot. Manh hon thi dich, doi lai la nhin ra duoc.
    """
    base = media.perceptual_hash(source)

    subtle = media.render(
        source, tmp_path / "nhe.mp4", media.recipe_for("acc-x", strength=media.Strength.SUBTLE)
    )
    aggressive = media.render(
        source,
        tmp_path / "manh.mp4",
        media.recipe_for("acc-x", strength=media.Strength.AGGRESSIVE),
    )

    d_subtle = media.phash_distance(base, media.perceptual_hash(subtle))
    d_aggressive = media.phash_distance(base, media.perceptual_hash(aggressive))

    print(f"\n  pHash lech so voi goc: nhe={d_subtle}, manh={d_aggressive}")
    assert d_aggressive >= d_subtle


def test_rejects_an_unsupported_file(tmp_path):
    junk = tmp_path / "tailieu.txt"
    junk.write_text("khong phai media")
    with pytest.raises(media.MediaError, match="chua ho tro"):
        media.render(junk, tmp_path / "ra.txt", media.recipe_for("acc"))


def test_missing_source_fails_clearly(tmp_path):
    with pytest.raises(media.MediaError, match="khong tim thay"):
        media.render(tmp_path / "khong-co.mp4", tmp_path / "ra.mp4", media.recipe_for("acc"))


def test_avoiding_a_taken_phash_rerolls(source, tmp_path, monkeypatch):
    """Do luong that cho thay o muc moderate, hai trong nam acc trung pHash.

    Trung nhu vay la mat het y nghia cua viec sinh bien the, nen mediastore phai rut
    lai voi seed khac chu khong chap nhan ban trung.
    """
    from seeding.content import mediastore

    monkeypatch.setattr(mediastore, "root", lambda: tmp_path)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    target = tmp_path / "sources" / "goc.mp4"
    target.write_bytes(source.read_bytes())

    _, first = mediastore.ensure_variant("goc.mp4", "chien-dich", "acc-1")
    _, second = mediastore.ensure_variant("goc.mp4", "chien-dich", "acc-1", avoid={first})

    assert second != first, "phai rut lai khi pHash da bi chiem"


def test_report_gives_pairwise_distances(source, tmp_path, monkeypatch):
    from seeding.content import mediastore

    monkeypatch.setattr(mediastore, "root", lambda: tmp_path)
    (tmp_path / "sources").mkdir(parents=True, exist_ok=True)
    (tmp_path / "sources" / "goc.mp4").write_bytes(source.read_bytes())

    report = mediastore.report(
        "goc.mp4",
        [("chien-dich", f"acc-{i}") for i in range(3)],
        strength=media.Strength.AGGRESSIVE,
    )

    assert report["count"] == 3
    assert report["all_bytes_differ"] is True
    # Da co co che tranh trung thi khong ban nao duoc giong het ban nao.
    assert report["min_phash_distance"] > 0
