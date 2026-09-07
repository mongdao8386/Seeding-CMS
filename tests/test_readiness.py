"""Tai khoan da san sang nhan viec chua.

Truong hop te nhat KHONG phai la job that bai. La profile CO nhung khong co proxy: luc
do trinh duyet van mo, van vao duoc trang, chi la di ra bang dia chi nha nguoi dung -
va moi tai khoan chay nhu vay deu hien ra tren cung mot IP truoc mat nen tang.

Khong co loi nao bao. Do la ly do phep kiem nay ton tai, va ly do worker goi no chu
khong chi giao dien.
"""

import uuid

from seeding.core.readiness import check
from seeding.models import Account, AccountStatus, Platform, Profile


def _account(**kw) -> Account:
    fields = {
        "platform": Platform.TIKTOK,
        "handle": "acc",
        "status": AccountStatus.WARMING,
        "secrets_enc": None,
    }
    fields.update(kw)
    return Account(**fields)


def _profile(proxy: bool = True, cookies: bool = True) -> Profile:
    return Profile(
        proxy_id=uuid.uuid4() if proxy else None,
        cookies_enc="da-ma-hoa" if cookies else None,
    )


# --------------------------------------------------------- nen tang trinh duyet


def test_a_fully_set_up_account_is_ready():
    assert check(_account(), _profile()).ready


def test_no_profile_is_not_ready():
    result = check(_account(), None)
    assert not result.ready
    assert "profile" in result.reason


def test_a_profile_with_no_proxy_is_refused_and_says_why_it_matters():
    """Day la cai bay: no khong lam job that bai, no lam job chay bang IP that."""
    result = check(_account(), _profile(proxy=False))
    assert not result.ready
    assert "own IP" in result.reason


def test_a_profile_that_never_signed_in_is_not_ready():
    result = check(_account(), _profile(cookies=False))
    assert not result.ready
    assert "signed in" in result.reason


# ------------------------------------------------------------ trang thai acc


def test_a_dead_account_is_never_ready_even_with_everything_else():
    assert not check(_account(status=AccountStatus.DEAD), _profile()).ready


def test_a_suspended_account_is_not_ready():
    assert not check(_account(status=AccountStatus.SUSPENDED), _profile()).ready


def test_an_account_waiting_for_a_person_is_not_given_more_work():
    """Giao them viec cho tai khoan dang o hang doi tiep quan chi lam no chet nhanh hon."""
    result = check(_account(status=AccountStatus.NEEDS_HUMAN), _profile())
    assert not result.ready
    assert "takeover" in result.reason


def test_a_brand_new_account_can_still_be_scheduled():
    """NEW la trang thai binh thuong cua acc vua nhap - chan no lai thi khong bao gio
    bat dau duoc."""
    assert check(_account(status=AccountStatus.NEW), _profile()).ready


# ------------------------------------------------------------------- reddit


def test_reddit_needs_no_profile_because_it_goes_through_the_api():
    """Doi Reddit phai co profile va proxy la doi mot thu no khong dung den, va tai
    khoan Reddit se nam mai o trang thai chua san sang."""
    account = _account(platform=Platform.REDDIT, secrets_enc="da-ma-hoa")
    assert check(account, None).ready


def test_reddit_without_credentials_is_not_ready():
    result = check(_account(platform=Platform.REDDIT), None)
    assert not result.ready
    assert "credentials" in result.reason


# ------------------------------------------------- thu tu bao loi co y nghia


def test_the_missing_profile_is_reported_before_the_missing_proxy():
    """Thu tu kiem la thu tu nguoi van hanh phai sua: chua co profile thi noi ve proxy
    la noi ve mot thu chua ton tai."""
    assert "profile" in check(_account(), None).reason
