"""Kiem tra nhip thao tac ma khong can trinh duyet va khong phai cho that.

Cac ham humanize nhan `sleep` tu ngoai vao, nen o day truyen mot ham gia chi ghi lai
do dai roi tra ve ngay. Nho vay do duoc HANH VI thay vi chi do rang code chay khong loi.
"""

import random

from seeding.browser import humanize


class FakeClock:
    """Thay asyncio.sleep: ghi lai moi khoang cho, khong cho that."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)

    @property
    def total(self) -> float:
        return sum(self.waits)


class FakeLocator:
    def __init__(self) -> None:
        self.typed: list[str] = []
        self.clicks = 0

    async def click(self) -> None:
        self.clicks += 1

    async def type(self, text: str, delay: int = 0) -> None:
        self.typed.append(text)

    @property
    def text(self) -> str:
        return "".join(self.typed)


class FakeMouse:
    def __init__(self) -> None:
        self.wheels: list[int] = []

    async def wheel(self, dx: int, dy: int) -> None:
        self.wheels.append(dy)


class FakePage:
    def __init__(self) -> None:
        self.mouse = FakeMouse()


async def test_types_the_whole_text_one_character_at_a_time():
    loc, clock = FakeLocator(), FakeClock()
    await humanize.type_like_person(loc, "Xin chao!", rng=random.Random(1), sleep=clock)

    assert loc.text == "Xin chao!"
    assert all(len(chunk) == 1 for chunk in loc.typed), "phai go tung ky tu mot"


async def test_clicks_the_editor_and_pauses_before_typing():
    loc, clock = FakeLocator(), FakeClock()
    await humanize.type_like_person(loc, "a", rng=random.Random(1), sleep=clock)

    assert loc.clicks == 1
    assert clock.waits[0] >= 0.3, "phai nhin vao o soan mot lat truoc khi go"


async def test_keystroke_delays_are_not_uniform():
    """Go deu tam tap la dau vet may moc ro nhat."""
    loc, clock = FakeLocator(), FakeClock()
    await humanize.type_like_person(loc, "a" * 40, rng=random.Random(7), sleep=clock)

    strokes = clock.waits[1:]  # bo khoang cho dau tien
    assert len(set(strokes)) > 30, "do tre giua cac phim phai thay doi"


async def test_pauses_longer_after_punctuation():
    """Nguoi that dung lai o cuoi cau."""
    rng_seed = 3
    plain, clock_a = FakeLocator(), FakeClock()
    await humanize.type_like_person(plain, "aaaa", rng=random.Random(rng_seed), sleep=clock_a)

    punct, clock_b = FakeLocator(), FakeClock()
    await humanize.type_like_person(punct, "a.a.", rng=random.Random(rng_seed), sleep=clock_b)

    assert clock_b.total > clock_a.total


async def test_typing_speed_is_in_a_human_range():
    loc, clock = FakeLocator(), FakeClock()
    text = "Mot doan dai vua du de do toc do go cho on dinh."
    await humanize.type_like_person(loc, text, rng=random.Random(11), sleep=clock, cps=6.5)

    cps = len(text) / clock.total
    assert 2 < cps < 12, f"toc do {cps:.1f} ky tu/giay khong giong nguoi"


async def test_scroll_feed_does_the_requested_rounds():
    page, clock = FakePage(), FakeClock()
    done = await humanize.scroll_feed(page, rounds=6, rng=random.Random(2), sleep=clock)

    assert done == 6
    assert len(page.mouse.wheels) == 6
    assert len(clock.waits) == 6, "moi nhip cuon phai co mot khoang dung"


async def test_scrolling_sometimes_goes_back_up():
    """Nguoi that hay luot qua roi quay lai xem lai."""
    page, clock = FakePage(), FakeClock()
    await humanize.scroll_feed(page, rounds=120, rng=random.Random(5), sleep=clock)

    assert any(dy < 0 for dy in page.mouse.wheels)
    assert sum(1 for dy in page.mouse.wheels if dy < 0) < 60, "khong duoc cuon nguoc qua nhieu"


async def test_warm_up_reads_the_feed_before_anything_else():
    """Vao trang la dang ngay roi thoat la mau hinh bot ro nhat."""
    page, clock = FakePage(), FakeClock()
    await humanize.warm_up(page, rng=random.Random(4), sleep=clock)

    assert page.mouse.wheels, "warm_up phai cuon feed"
    assert clock.total > 4, "warm_up ma xong trong vai giay thi khong con y nghia gi"
