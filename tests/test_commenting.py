"""Seeding bang binh luan.

Seeding ngoai doi phan lon la BINH LUAN chu khong phai dang len tuong minh: mot tai
khoan moi lap ma tuan nao cung dang bai quang cao la mau hinh de thay, con mot tai
khoan de lai binh luan duoi bai nguoi khac thi lan vao dam dong.

Cac test o day khong mo trinh duyet. Chung kiem hai thu de sai am tham: chon dung
nhanh (dang bai hay binh luan) tu `target`, va tu choi som nhung cau hinh chac chan
hong TRUOC khi ton mot phien Camoufox 400MB.
"""

import uuid
from datetime import UTC, datetime

from seeding.adapters import browser
from seeding.adapters.base import get
from seeding.core.planner import _build_job
from seeding.models import (
    Campaign,
    CampaignGroup,
    ContentItem,
    Platform,
    PostKind,
    Variant,
)


def _variant(title="Tieu de", body="Noi dung binh luan") -> Variant:
    return Variant(title=title, body=body, content_hash="x")


# ------------------------------------------------------- planner mang kind di theo


def _job_target(post_kind: PostKind, target: dict) -> dict:
    campaign = Campaign(
        id=uuid.uuid4(),
        name="c",
        starts_at=datetime(2026, 8, 22, tzinfo=UTC),
        stagger_window_seconds=0,
    )
    group = CampaignGroup(
        id=uuid.uuid4(), name="g", platform=Platform.X, post_kind=post_kind, target=target
    )
    content = ContentItem(id=uuid.uuid4(), title_template="t", body_template="b", media_ref=None)
    job = _build_job(campaign, group, content, uuid.uuid4(), "key", {})
    return job.target


def test_the_planner_tells_the_adapter_which_kind_of_action_this_is():
    """Khong mang `kind` theo thi adapter mac dinh dang bai - va mot chien dich binh
    luan se lang le dang len tuong tung tai khoan."""
    assert _job_target(PostKind.COMMENT, {"url": "https://x.com/a/1"})["kind"] == "comment"
    assert _job_target(PostKind.POST, {"subreddit": "test"})["kind"] == "post"


def test_the_planner_keeps_the_platform_target_alongside_the_kind():
    target = _job_target(PostKind.COMMENT, {"url": "https://x.com/a/1"})
    assert target["url"] == "https://x.com/a/1"


# ------------------------------------------------- tu choi som, truoc khi mo browser


def _adapter(platform=Platform.X) -> browser.BrowserAdapter:
    return get(platform)


def test_a_comment_without_a_url_is_refused():
    problem = _adapter()._comment_precheck(_variant(), {"kind": "comment"})
    assert problem is not None
    assert "url" in problem.error


def test_a_comment_with_no_body_is_refused_and_says_why():
    """Chi lay `body`: `title` khong co cho nao de di trong mot binh luan.

    Bo qua am tham thi noi dung nguoi ta soan bien mat ma khong ai biet.
    """
    problem = _adapter()._comment_precheck(
        _variant(body=""), {"kind": "comment", "url": "https://x.com/a/1"}
    )
    assert problem is not None
    assert "body" in problem.error.lower()


def test_whitespace_does_not_count_as_a_body():
    problem = _adapter()._comment_precheck(
        _variant(body="   \n  "), {"kind": "comment", "url": "https://x.com/a/1"}
    )
    assert problem is not None


def test_a_well_formed_comment_passes_the_precheck():
    assert (
        _adapter()._comment_precheck(_variant(), {"kind": "comment", "url": "https://x.com/a/1"})
        is None
    )


def test_a_platform_without_a_comment_recipe_says_so_instead_of_pretending():
    naked = browser.BrowserAdapter(Platform.X, browser.RECIPES[Platform.X], None)
    problem = naked._comment_precheck(_variant(), {"kind": "comment", "url": "https://x.com/a/1"})
    assert problem is not None
    assert "recipe" in problem.error.lower()
    assert problem.retryable is False, "thieu cong thuc la loi cau hinh, thu lai khong giup gi"


# -------------------------------------------------------------- cong thuc binh luan


def test_every_comment_recipe_can_find_a_box_to_type_in():
    """Thieu `editor` thi adapter chay den giua chung roi moi hong, sau khi da mo phien."""
    for platform, recipe in browser.COMMENT_RECIPES.items():
        assert recipe.editor, f"{platform.value} co cong thuc binh luan ma khong co o nhap"


def test_a_recipe_with_no_submit_button_is_allowed_because_enter_sends_it():
    """Facebook gui binh luan bang Enter, khong co nut rieng. Do la that, khong phai thieu sot."""
    assert browser.COMMENT_RECIPES[Platform.FACEBOOK].submit == ()
