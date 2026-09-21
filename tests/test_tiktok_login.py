"""Dang nhap TikTok tu dong bang thong tin da luu - trang gia, khong mo Camoufox, khong ra mang.

Kiem: go dung ten + mat khau, tu lay ma email va dien vao, CAPTCHA thi cho nguoi (khong tu giai),
sai mat khau thi dung han, va hang doi dang nhap xep tung acc cach nhau."""

from __future__ import annotations

import uuid
from itertools import pairwise
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import select

from seeding.api.main import app
from seeding.config import get_settings
from seeding.db import SessionLocal
from seeding.domain import fingerprint as fpm
from seeding.domain.defaults import ensure_defaults
from seeding.domain.models import (
    Account,
    AccountRole,
    AccountStatus,
    ActivityJob,
    ActivityKind,
    JobStatus,
    Platform,
    Profile,
)
from seeding.ops import mailbox
from seeding.platforms.base import InteractResult
from seeding.platforms.tiktok import login_browser as lb

R = lb.RECIPE


class _Locator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    @property
    def first(self):
        return self

    async def is_visible(self, timeout=0):
        return self.page.shown(self.selector)

    async def count(self):
        return 1 if self.page.shown(self.selector) else 0

    async def click(self, **kw):
        self.page.log.append(f"click:{self.selector}")
        self.page.clicked(self.selector)

    async def type(self, ch, delay=0):
        self.page.typed[self.selector] = self.page.typed.get(self.selector, "") + ch


class _Page:
    """May trang thai: form -> (code | captcha | error | home)."""

    def __init__(self, after_submit: str):
        self.state = "form"
        self.after_submit = after_submit
        self.log: list[str] = []
        self.typed: dict[str, str] = {}
        self.url = lb.LOGIN_URL
        self.polls = 0
        self.human_solves_after: int | None = None

    def visible(self) -> set[str]:
        if self.state == "form":
            return {R.username[0], R.password[0], R.submit[0]}
        if self.state == "code":
            return {R.code_input[0], R.code_submit[0]}
        if self.state == "captcha":
            return {R.captcha[0]}
        if self.state == "home":
            return {R.logged_in[0]}
        return set()

    def shown(self, selector: str) -> bool:
        """Moi lan luong NHIN vao captcha la mot nhip; nguoi giai xong sau vai nhip."""
        if self.state == "captcha" and selector == R.captcha[0]:
            self.polls += 1
            if self.human_solves_after is not None and self.polls > self.human_solves_after:
                self._go_home()
        return selector in self.visible()

    def _go_home(self):
        self.state = "home"
        self.url = "https://www.tiktok.com/foryou"

    def clicked(self, selector):
        if self.state == "form" and selector == R.submit[0]:
            if self.after_submit == "home":
                self._go_home()
            else:
                self.state = self.after_submit
        elif self.state == "code" and selector == R.code_submit[0]:
            self._go_home()

    def locator(self, selector):
        return _Locator(self, selector)

    async def goto(self, url, **kw):
        self.log.append(f"goto:{url}")

    async def inner_text(self, _sel):
        if self.state == "error":
            return "Username or password doesn't match our records. Try again."
        return "Log in"


class _Open:
    def __init__(self, page):
        self.page = page
        self.headless = None

    def __call__(self, profile, *, headless, humanize):
        self.headless = headless
        page = self.page

        class _Ctx:
            async def __aenter__(self_inner):
                class _Context:
                    async def new_page(self_c):
                        return page

                    async def cookies(self_c, url=None):
                        return []

                return None, _Context()

            async def __aexit__(self_inner, *exc):
                return None

        return _Ctx()


async def _sleep(_s):
    return None


def _job(secrets: dict, role=AccountRole.BOOSTER):
    account = Account(id=uuid.uuid4(), handle="thu", role=role, platform=Platform.TIKTOK)
    account.set_secrets(secrets)
    job = ActivityJob(id=uuid.uuid4(), kind=ActivityKind.LOGIN, account_id=account.id)
    job.__dict__["account"] = account
    return job


def _profile():
    p = Profile(id=uuid.uuid4(), account_id=uuid.uuid4(), fingerprint={})
    p.__dict__["proxy"] = None
    return p


class _NoSession:
    async def commit(self):
        return None


SECRETS = {
    "username": "user123",
    "password": "Pw@!123",
    "recovery_email": "a@hotmail.com",
    "mail_refresh_token": "RT",
    "mail_client_id": "cid",
}


@pytest.fixture(autouse=True)
def _stub_finish(monkeypatch):
    async def finish(session, profile, context, note):
        return InteractResult(True, note)

    monkeypatch.setattr(lb, "_finish", finish)


async def test_types_the_saved_credentials_and_lands_logged_in():
    page = _Page(after_submit="home")
    opened = _Open(page)
    res = await lb.run(_NoSession(), _profile(), _job(SECRETS), open=opened, sleep=_sleep)
    assert res.ok, res.detail
    assert opened.headless is False, "luon co cua so: captcha la viec cua nguoi"
    assert page.typed[R.username[0]] == "user123" and page.typed[R.password[0]] == "Pw@!123"
    assert page.log[0] == f"goto:{lb.LOGIN_URL}"


async def test_reads_the_email_code_and_types_it(monkeypatch):
    page = _Page(after_submit="code")
    calls = []

    async def fetch(secrets, *, platform=None, since_minutes=30):
        calls.append(platform)
        return mailbox.MailCode("482913", "482913 is your code", "TikTok", None, None)

    res = await lb.run(
        _NoSession(), _profile(), _job(SECRETS), open=_Open(page), sleep=_sleep, fetch_code=fetch
    )
    assert res.ok and "mã lấy từ email" in res.detail
    assert page.typed[R.code_input[0]] == "482913" and calls == ["tiktok"]


async def test_a_captcha_is_left_for_the_human_and_the_flow_resumes_after():
    page = _Page(after_submit="captcha")
    page.human_solves_after = 3
    res = await lb.run(_NoSession(), _profile(), _job(SECRETS), open=_Open(page), sleep=_sleep)
    assert res.ok and "captcha do người giải" in res.detail
    assert not [e for e in page.log if "captcha" in e], "may khong bao gio bam vao captcha"


async def test_an_unsolved_captcha_is_retried_later_not_forced():
    page = _Page(after_submit="captcha")
    res = await lb.run(
        _NoSession(), _profile(), _job(SECRETS), open=_Open(page), sleep=_sleep, human_wait_s=0.2
    )
    assert not res.ok and res.retryable and "captcha" in res.detail


async def test_a_wrong_password_stops_for_good():
    page = _Page(after_submit="error")
    res = await lb.run(_NoSession(), _profile(), _job(SECRETS), open=_Open(page), sleep=_sleep)
    assert not res.ok and not res.retryable and "mật khẩu" in res.detail


async def test_no_saved_password_never_opens_a_browser():
    page = _Page(after_submit="home")
    res = await lb.run(
        _NoSession(), _profile(), _job({"username": "u"}), open=_Open(page), sleep=_sleep
    )
    assert not res.ok and page.log == []


async def test_a_channel_account_without_a_proxy_is_refused():
    page = _Page(after_submit="home")
    res = await lb.run(
        _NoSession(),
        _profile(),
        _job(SECRETS, role=AccountRole.CHANNEL),
        open=_Open(page),
        sleep=_sleep,
    )
    assert not res.ok and "proxy" in res.detail and page.log == []


def test_error_strings_map_to_reasons():
    assert lb.page_error("Maximum number of attempts reached. Try again later.")[1] is True
    assert lb.page_error("Your account was banned")[1] is False
    assert lb.page_error("Welcome back") is None


# ------------------------------------------------------------------ hang doi (API + DB)


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


@pytest.fixture
async def fleet():
    tag = uuid.uuid4().hex[:6]
    ids = SimpleNamespace(tag=tag, accounts={})
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)

        async def make(name, *, secrets, cookie=False, alive=False, profile=True):
            acc = Account(
                persona_id=persona.id,
                platform=Platform.TIKTOK,
                handle=f"lg_{tag}_{name}",
                status=AccountStatus.WARMING,
                role=AccountRole.BOOSTER,
            )
            acc.set_secrets(secrets)
            s.add(acc)
            await s.flush()
            ids.accounts[name] = acc.id
            if profile:
                p = Profile(
                    account_id=acc.id,
                    fingerprint=fpm.generate(),
                    os_family="windows",
                    locale="auto",
                )
                if cookie:
                    p.set_cookies({"cookies": [{"name": "sessionid", "value": "x"}]})
                    p.session_alive = alive
                s.add(p)

        await make("a", secrets=SECRETS)
        await make("b", secrets=SECRETS)
        await make("live", secrets=SECRETS, cookie=True, alive=True)
        await make("nopass", secrets={"username": "u"})
        await s.commit()
    yield ids
    async with SessionLocal() as s:
        for aid in ids.accounts.values():
            obj = await s.get(Account, aid)
            if obj is not None:
                await s.delete(obj)
        await s.commit()


async def test_queue_spaces_logins_and_skips_live_or_passwordless_accounts(client, fleet):
    r = await client.post(
        "/accounts/login-queue",
        json={"ids": [str(i) for i in fleet.accounts.values()], "spacing_minutes": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Chon theo id: acc dang song van duoc xep (nguoi dung chu dong chon), thieu mat khau thi khong.
    assert body["queued"] == 3 and body["no_password"] == 1
    async with SessionLocal() as s:
        jobs = (
            (
                await s.execute(
                    select(ActivityJob)
                    .where(
                        ActivityJob.account_id.in_(list(fleet.accounts.values())),
                        ActivityJob.kind == ActivityKind.LOGIN,
                    )
                    .order_by(ActivityJob.scheduled_at)
                )
            )
            .scalars()
            .all()
        )
        assert len(jobs) == 3 and all(j.status is JobStatus.SCHEDULED for j in jobs)
        gaps = [(b.scheduled_at - a.scheduled_at).total_seconds() / 60 for a, b in pairwise(jobs)]
        assert all(3.0 <= g <= 7.0 for g in gaps), gaps

    again = await client.post(
        "/accounts/login-queue", json={"ids": [str(i) for i in fleet.accounts.values()]}
    )
    assert again.json()["queued"] == 0 and again.json()["already_queued"] == 3


async def test_queue_alternates_between_proxies(client):
    """5 acc chung mot proxy khong dang nhap lien tiep tu mot IP: xen ke voi proxy khac."""
    from sqlalchemy import delete

    from seeding.domain.models import Proxy, ProxyKind, ProxyStatus

    tag = uuid.uuid4().hex[:6]
    account_ids, proxy_ids, proxy_of = [], [], {}
    async with SessionLocal() as s:
        _, persona = await ensure_defaults(s)
        for i in range(2):
            proxy = Proxy(
                label=f"lq{tag}{i}",
                kind=ProxyKind.RESIDENTIAL,
                host=f"lq-{tag}-{i}.example.com",
                port=9100 + i,
                status=ProxyStatus.OK,
            )
            s.add(proxy)
            await s.flush()
            proxy_ids.append(proxy.id)
        for i in range(4):
            acc = Account(
                persona_id=persona.id,
                platform=Platform.TIKTOK,
                handle=f"lq_{tag}_{i}",
                status=AccountStatus.WARMING,
            )
            acc.set_secrets(SECRETS)
            s.add(acc)
            await s.flush()
            account_ids.append(acc.id)
            # Hai acc dau chung proxy 0, hai acc sau chung proxy 1.
            proxy_of[acc.id] = proxy_ids[i // 2]
            s.add(
                Profile(
                    account_id=acc.id,
                    proxy_id=proxy_ids[i // 2],
                    fingerprint=fpm.generate(),
                    os_family="windows",
                    locale="auto",
                )
            )
        await s.commit()
    try:
        r = await client.post("/accounts/login-queue", json={"ids": [str(i) for i in account_ids]})
        assert r.status_code == 200 and r.json()["queued"] == 4, r.text
        async with SessionLocal() as s:
            jobs = (
                (
                    await s.execute(
                        select(ActivityJob)
                        .where(ActivityJob.account_id.in_(account_ids))
                        .order_by(ActivityJob.scheduled_at)
                    )
                )
                .scalars()
                .all()
            )
        lanes = [proxy_of[j.account_id] for j in jobs]
        assert all(a != b for a, b in pairwise(lanes)), "hai luot lien tiep khong chung proxy"
    finally:
        async with SessionLocal() as s:
            for aid in account_ids:
                obj = await s.get(Account, aid)
                if obj is not None:
                    await s.delete(obj)
            await s.commit()
            await s.execute(delete(Proxy).where(Proxy.id.in_(proxy_ids)))
            await s.commit()
