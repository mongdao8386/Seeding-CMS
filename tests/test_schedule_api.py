"""Noi dung -> lich -> huy, qua API that tren DB that (don sach sau khi xong).

Kiem dung cai da hong khi chay tay: xoa mot bai da tung len lich phai xoa duoc - chien
dich tro vao bai bang FK khong cascade, va API phai tu don chien dich truoc.
"""

import datetime as dt
import uuid

import httpx
import pytest
from httpx import ASGITransport

from seeding.api.main import app
from seeding.config import get_settings


@pytest.fixture(scope="module")
async def client():
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"authorization": f"Bearer {get_settings().api_token}"},
        timeout=60,
    ) as c:
        yield c


async def test_content_scheduled_then_deleted_takes_its_jobs_with_it(client):
    ready = (await client.get("/accounts", params={"ready": "true", "limit": 1})).json()["items"]
    if not ready:
        pytest.skip("khong co tai khoan san sang trong DB")

    created = (
        await client.post(
            "/content", json={"title": f"thu {uuid.uuid4().hex[:6]} {{a|b}}", "body": "x"}
        )
    ).json()
    assert created["combinations"] == 2
    cid = created["id"]

    try:
        far = (dt.date.today() + dt.timedelta(days=20)).isoformat()
        r = await client.post(
            "/schedule",
            json={"content_id": cid, "account_ids": [ready[0]["id"]], "start_date": far},
        )
        assert r.status_code == 200, r.text
        jobs = r.json()
        assert len(jobs) == 1 and jobs[0]["status"] == "scheduled"
        assert "{" not in jobs[0]["title"]

        listed = (await client.get("/schedule", params={"start": far, "days": 3})).json()
        assert any(j["id"] == jobs[0]["id"] for j in listed)

        counted = next(c for c in (await client.get("/content")).json() if c["id"] == cid)
        assert counted["jobs_scheduled"] == 1

        r = await client.delete(f"/content/{cid}")
        assert r.status_code == 200, r.text
        listed = (await client.get("/schedule", params={"start": far, "days": 3})).json()
        assert not any(j["id"] == jobs[0]["id"] for j in listed)
    finally:
        await client.delete(f"/content/{cid}?force=true")


async def test_scheduling_refuses_an_account_that_is_not_ready(client):
    blocked = (await client.get("/accounts", params={"ready": "false", "limit": 1})).json()["items"]
    if not blocked:
        pytest.skip("moi tai khoan deu san sang")
    created = (await client.post("/content", json={"title": "thu", "body": ""})).json()
    try:
        r = await client.post(
            "/schedule", json={"content_id": created["id"], "account_ids": [blocked[0]["id"]]}
        )
        assert r.status_code == 409
        assert blocked[0]["handle"] in r.json()["detail"]
    finally:
        await client.delete(f"/content/{created['id']}?force=true")


async def test_moving_a_job_snaps_to_the_requested_golden_hour(client):
    ready = (await client.get("/accounts", params={"ready": "true", "limit": 1})).json()["items"]
    if not ready:
        pytest.skip("khong co tai khoan san sang trong DB")
    created = (await client.post("/content", json={"title": "doi ngay", "body": ""})).json()
    try:
        far = dt.date.today() + dt.timedelta(days=21)
        jobs = (
            await client.post(
                "/schedule",
                json={
                    "content_id": created["id"],
                    "account_ids": [ready[0]["id"]],
                    "start_date": far.isoformat(),
                },
            )
        ).json()
        target = far + dt.timedelta(days=2)
        r = await client.patch(
            f"/schedule/{jobs[0]['id']}", json={"date": target.isoformat(), "hour": 10}
        )
        assert r.status_code == 200, r.text
        when = dt.datetime.fromisoformat(r.json()["scheduled_at"])
        local = when.astimezone(dt.timezone(dt.timedelta(hours=7)))
        assert local.date() == target and local.hour == 10
    finally:
        await client.delete(f"/content/{created['id']}?force=true")
