"""Thong ke proxy tai duoc TikTok hay khong, ghi tu job trinh duyet, doc ra dashboard."""

from __future__ import annotations

import uuid

from seeding.ops import flags, proxy_stats


async def test_render_outcomes_accumulate_and_summarise():
    pid = uuid.uuid4()
    try:
        assert await proxy_stats.read(pid) is None
        assert proxy_stats.summary(None) is None

        await proxy_stats.note_render(pid, True, 151.4)
        await proxy_stats.note_render(pid, False, 480)
        await proxy_stats.note_render(pid, True, 109)

        stats = await proxy_stats.read(pid)
        assert stats["ok"] == 2 and stats["fail"] == 1 and stats["last_ok"] is True
        assert stats["avg_s"] == 130
        assert [r["ok"] for r in stats["recent"]] == [True, False, True]
        assert proxy_stats.summary(stats) == "2/3 · ~130s"
    finally:
        await flags.set_flag(f"proxy:{pid}:tiktok", {}, ttl_seconds=1)


async def test_recent_list_is_capped():
    pid = uuid.uuid4()
    try:
        for i in range(proxy_stats.KEEP_RECENT + 3):
            await proxy_stats.note_render(pid, i % 2 == 0, 100)
        stats = await proxy_stats.read(pid)
        assert len(stats["recent"]) == proxy_stats.KEEP_RECENT
        assert stats["ok"] + stats["fail"] == proxy_stats.KEEP_RECENT + 3
    finally:
        await flags.set_flag(f"proxy:{pid}:tiktok", {}, ttl_seconds=1)


async def test_no_proxy_is_a_no_op():
    await proxy_stats.note_render(None, True, 1)  # khong nem, khong ghi
