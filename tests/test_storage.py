"""Kho file: thu muc tren may, va Supabase Storage.

Phan Supabase duoc kiem bang transport gia, nen chay duoc ma khong can khoa that. Cai
duoc kiem la GIAO THUC: dung URL, dung header, dung phuong thuc - do la nhung thu se
sai am tham neu chi doc tai lieu roi doan.
"""

import httpx
import pytest

from seeding.core import storage


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"not really a video, but bytes are bytes")
    return path


# ------------------------------------------------------------------ local


def test_local_round_trip(tmp_path, sample):
    store = storage.LocalStorage(tmp_path / "store")
    store.put("sources/clip.mp4", sample)

    assert store.exists("sources/clip.mp4")
    assert store.fetch("sources/clip.mp4", tmp_path / "x").read_bytes() == sample.read_bytes()

    store.delete("sources/clip.mp4")
    assert not store.exists("sources/clip.mp4")


def test_local_refuses_a_key_that_escapes_the_store(tmp_path, sample):
    """Khoa den tu ten file nguoi dung dat, nen phai coi la du lieu khong tin duoc."""
    store = storage.LocalStorage(tmp_path / "store")
    with pytest.raises(storage.StorageError, match="escapes"):
        store.put("../../escaped.mp4", sample)


def test_local_fetch_of_something_missing_says_so(tmp_path):
    store = storage.LocalStorage(tmp_path / "store")
    with pytest.raises(storage.StorageError, match="not in the store"):
        store.fetch("sources/nope.mp4", tmp_path / "x")


def test_deleting_something_that_is_already_gone_is_not_an_error(tmp_path):
    storage.LocalStorage(tmp_path / "store").delete("sources/gone.mp4")


# --------------------------------------------------------------- supabase


def _recorder(status: int = 200, body: bytes = b"payload"):
    """Transport gia, ghi lai moi request de kiem giao thuc."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handle), seen


def _store(tmp_path, transport):
    return storage.SupabaseStorage(
        "https://demo.supabase.co/",  # dau / thua co y: phai duoc cat di
        "service-key-abc",
        "seeding-media",
        tmp_path / "cache",
        transport=transport,
    )


def test_upload_hits_the_object_endpoint_with_the_service_key(tmp_path, sample):
    transport, seen = _recorder(200)
    _store(tmp_path, transport).put("sources/clip.mp4", sample)

    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == (
        "https://demo.supabase.co/storage/v1/object/seeding-media/sources/clip.mp4"
    )
    assert request.headers["authorization"] == "Bearer service-key-abc"
    assert request.headers["apikey"] == "service-key-abc"
    assert request.headers["content-type"] == "video/mp4"
    # Upload lai cung mot ten la y dinh binh thuong, khong phai loi.
    assert request.headers["x-upsert"] == "true"
    assert request.content == sample.read_bytes()


def test_a_failed_upload_raises_instead_of_passing_silently(tmp_path, sample):
    transport, _ = _recorder(403, b"row level security")
    with pytest.raises(storage.StorageError, match="upload failed"):
        _store(tmp_path, transport).put("sources/clip.mp4", sample)


def test_fetch_downloads_once_then_serves_from_cache(tmp_path):
    """ffmpeg doc file chu khong doc URL, nen moi lan render deu can ban local."""
    transport, seen = _recorder(200, b"remote bytes")
    store = _store(tmp_path, transport)

    first = store.fetch("sources/clip.mp4", tmp_path / "unused")
    assert first.read_bytes() == b"remote bytes"
    assert len(seen) == 1

    second = store.fetch("sources/clip.mp4", tmp_path / "unused")
    assert second == first
    assert len(seen) == 1, "lan thu hai phai lay tu cache, khong goi mang lai"


def test_a_missing_object_raises(tmp_path):
    transport, _ = _recorder(404, b"")
    with pytest.raises(storage.StorageError, match="download failed"):
        _store(tmp_path, transport).fetch("sources/gone.mp4", tmp_path / "x")


def test_delete_uses_the_delete_method_and_clears_the_cache(tmp_path):
    transport, seen = _recorder(200, b"bytes")
    store = _store(tmp_path, transport)

    cached = store.fetch("sources/clip.mp4", tmp_path / "x")
    assert cached.exists()

    store.delete("sources/clip.mp4")
    assert seen[-1].method == "DELETE"
    assert not cached.exists(), "xoa tren kho ma con ban cache thi lan sau doc ra file ma"


def test_exists_uses_head_so_it_does_not_pull_the_whole_file(tmp_path):
    transport, seen = _recorder(200)
    assert _store(tmp_path, transport).exists("sources/clip.mp4") is True
    assert seen[0].method == "HEAD"


def test_exists_is_false_when_the_object_is_not_there(tmp_path):
    transport, _ = _recorder(404)
    assert _store(tmp_path, transport).exists("sources/clip.mp4") is False


# ------------------------------------------------------------------ chon backend


def test_build_defaults_to_local(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "get_settings", lambda: _settings(backend="local"))
    assert isinstance(storage.build(tmp_path, tmp_path / "cache"), storage.LocalStorage)


def test_build_refuses_supabase_without_credentials(tmp_path, monkeypatch):
    """Thieu khoa thi phai bao ngay, khong duoc im lang quay ve local.

    Am tham dung local nghia la mot worker ghi file vao dia rieng cua no, con cac worker
    khac khong bao gio thay - va khong ai biet cho toi luc bai dang thieu media.
    """
    monkeypatch.setattr(storage, "get_settings", lambda: _settings(backend="supabase"))
    with pytest.raises(storage.StorageError, match="SUPABASE_URL"):
        storage.build(tmp_path, tmp_path / "cache")


def test_build_rejects_a_backend_it_does_not_know(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "get_settings", lambda: _settings(backend="dropbox"))
    with pytest.raises(storage.StorageError, match="Unknown MEDIA_BACKEND"):
        storage.build(tmp_path, tmp_path / "cache")


def test_build_makes_a_supabase_store_when_fully_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(
        storage,
        "get_settings",
        lambda: _settings(backend="supabase", url="https://demo.supabase.co", key="k", bucket="b"),
    )
    store = storage.build(tmp_path, tmp_path / "cache")
    assert isinstance(store, storage.SupabaseStorage)
    assert store.bucket == "b"


class _settings:
    def __init__(self, *, backend="local", url="", key="", bucket=""):
        self.media_backend = backend
        self.supabase_url = url
        self.supabase_service_key = key
        self.supabase_bucket = bucket
