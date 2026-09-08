"""Nuoi theo tu khoa va binh luan sticker: tron feed + tim kiem, bo trung video, tu khoa
tu persona + .env, sticker khong chu, va TikTok doc duoc body tim kiem."""

from __future__ import annotations

import random
import uuid
from typing import ClassVar

from seeding.content import comments
from seeding.platforms import outreach
from seeding.platforms.tiktok import web as tw


def test_sticker_comments_have_no_words():
    for platform in ("tiktok", "instagram", "x", "reddit"):
        for i in range(20):
            s = comments.sticker_text(uuid.UUID(int=i), platform)
            assert s and not any(ch.isalpha() and ch.isascii() and platform != "tiktok" for ch in s)
            if platform == "tiktok":
                assert s.startswith("[") and s.endswith("]")
            else:
                assert not any(ch.isalnum() for ch in s)
    jid = uuid.uuid4()
    assert comments.sticker_text(jid) == comments.sticker_text(jid)


def test_warm_comment_style_switch():
    jid = uuid.uuid4()
    assert comments.warm_comment(jid, "tiktok", style="sticker").startswith("[")
    assert comments.warm_comment(jid, "tiktok", style="text") in comments.COMMENTS
    got = {
        comments.warm_comment(uuid.UUID(int=i), "x", style="mixed") in comments.COMMENTS
        for i in range(30)
    }
    assert got == {True, False}, "mixed phai ra ca hai kieu"


def test_keywords_merge_persona_and_env():
    assert outreach.keywords_from(["làm đẹp", "du lịch"], " ẩm thực, làm đẹp ,") == [
        "làm đẹp",
        "du lịch",
        "ẩm thực",
    ]
    assert outreach.keywords_from(None, "") == []


class _Item:
    def __init__(self, item_id, author, views=100_000):
        self.item_id = item_id
        self.author_handle = author
        self.views = views
        self.url = f"https://x/{author}/{item_id}"


class _Src:
    searched: ClassVar[list[str]] = []

    async def feed(self, count):
        return [_Item("1", "a"), _Item("2", "b")]

    async def search(self, keyword, count):
        _Src.searched.append(keyword)
        if keyword == "hỏng":
            raise RuntimeError("search broke")
        return [_Item("2", "b"), _Item("3", "c"), _Item("4", "d")]


async def test_gather_mixes_feed_and_search_and_survives_a_broken_keyword():
    _Src.searched.clear()
    items = await outreach.gather_targets(_Src(), random.Random(1), ["hỏng", "đẹp"])
    assert sorted(_Src.searched) == ["hỏng", "đẹp"]
    picked = outreach.pick_targets(items, own_handles=set(), rng=random.Random(1), min_views=1)
    assert sorted(i.item_id for i in picked) == ["1", "2", "3", "4"], "bo trung video, giu du"


async def test_gather_without_keywords_or_search_is_just_the_feed():
    class _FeedOnly:
        async def feed(self, count):
            return [_Item("9", "z")]

    items = await outreach.gather_targets(_FeedOnly(), random.Random(1), ["x"])
    assert [i.item_id for i in items] == ["9"]


def test_tiktok_search_body_parses_like_a_feed():
    body = {
        "data": [
            {
                "type": 1,
                "item": {
                    "id": "11",
                    "desc": "d",
                    "author": {"uniqueId": "a", "id": "1", "secUid": "S"},
                    "stats": {"playCount": 50000, "diggCount": 5},
                },
            },
            {"type": 4, "user_list": []},
            {"type": 1, "item": {"id": "", "author": {"uniqueId": "b"}}},
        ]
    }
    got = tw.parse_search(body)
    assert [i.item_id for i in got] == ["11"] and got[0].views == 50000
