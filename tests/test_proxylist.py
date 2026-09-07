"""Doc danh sach proxy dan vao.

Bat bien cua he thong la mot acc mot proxy, nen so proxy luon phai bang so tai khoan -
va nghia la danh sach nay se dai. Doc sai mot dong o day thi mot tai khoan chay bang
proxy sai, hoac te hon, khong co proxy nao.

Cho de sai am tham nhat la `a:b:c:d`: no co the la host:port:user:pass ma cung co the
la thu khac. Doan sai thi mat khau roi vao o cong, va loi bao ra sau do noi ve mot
chuyen hoan toan khong lien quan.
"""

import pytest

from seeding.core import proxylist


def one(text: str):
    return proxylist.parse_one(text, line=1)


# ----------------------------------------------------------- bon dinh dang


def test_host_and_port():
    p = one("1.2.3.4:8080")
    assert (p.host, p.port, p.username) == ("1.2.3.4", 8080, None)


def test_host_port_user_pass():
    """Dinh dang pho bien nhat cua nguoi ban proxy o Viet Nam.

    Ten mien va ten dang nhap o day la gia. Proxy that cua nguoi van hanh khong bao
    gio duoc dat vao test - kho ma nay len GitHub, con proxy thi la thu mua bang tien
    va dung duoc ngay khi biet dia chi.
    """
    p = one("zl47160.example.com:31159:nguoidung:matkhau")
    assert (p.host, p.port, p.username, p.password) == (
        "zl47160.example.com",
        31159,
        "nguoidung",
        "matkhau",
    )


def test_user_pass_at_host_port():
    p = one("nguoidung:matkhau@5.6.7.8:9000")
    assert (p.host, p.port, p.username, p.password) == ("5.6.7.8", 9000, "nguoidung", "matkhau")


def test_a_scheme_prefix_is_honoured():
    assert one("socks5://u:p@9.9.9.9:1080").scheme == "socks5"


def test_no_scheme_falls_back_to_the_default():
    assert proxylist.parse_one("1.2.3.4:8080", 1, default_scheme="socks5").scheme == "socks5"


def test_a_scheme_the_system_cannot_speak_is_refused():
    """Tao proxy voi scheme la thi no se hong luc MO TRINH DUYET, cach cho nhap ba tang."""
    with pytest.raises(ValueError, match="not a scheme"):
        one("ftp://1.2.3.4:8080")


# ------------------------------------------------------------- cho de sai


def test_a_password_containing_an_at_sign_still_parses():
    """Mat khau proxy hay co @. Tach o dau @ DAU TIEN thi host bi cat sai."""
    p = one("user:mat@khau@5.6.7.8:9000")
    assert p.host == "5.6.7.8"
    assert p.password == "mat@khau"


def test_four_parts_whose_second_is_not_a_port_is_refused_rather_than_guessed():
    """Doan bua o day thi mat khau roi vao o cong, va loi bao ra noi ve chuyen khac."""
    with pytest.raises(ValueError, match="not a port"):
        one("host:khongphaicong:user:pass")


def test_a_username_with_no_password_is_kept():
    p = one("chi_co_user@1.2.3.4:8080")
    assert p.username == "chi_co_user"
    assert p.password is None


def test_port_zero_is_not_a_port():
    with pytest.raises(ValueError, match="not a port"):
        one("1.2.3.4:0")


def test_a_port_above_the_range_is_refused():
    with pytest.raises(ValueError, match="not a port"):
        one("1.2.3.4:99999")


def test_a_line_that_makes_no_sense_says_what_shapes_are_accepted():
    """Bao 'khong hieu' ma khong noi cai gi hieu duoc thi nguoi dung phai di doan."""
    with pytest.raises(ValueError, match="host:port"):
        one("khong-hieu-gi-ca")


# ------------------------------------------------------------ ca danh sach


def test_reads_a_mixed_list():
    report = proxylist.parse(
        "1.2.3.4:8080\nhost.com:31159:u:p\nu2:p2@5.6.7.8:9000\nsocks5://u3:p3@9.9.9.9:1080\n"
    )
    assert report.ok
    assert len(report.rows) == 4
    assert report.with_auth == 3


def test_comments_and_blank_lines_are_skipped():
    report = proxylist.parse("# danh sach thang 9\n\n1.2.3.4:8080\n\n")
    assert report.ok
    assert len(report.rows) == 1


def test_one_bad_line_does_not_stop_the_rest():
    """Nguoi dung can thay HET moi dong sai trong mot lan, giong het phan nhap acc."""
    report = proxylist.parse("1.2.3.4:8080\nhong\n5.6.7.8:9000\n")
    assert len(report.rows) == 2
    assert len(report.problems) == 1
    assert report.problems[0].line == 2


def test_a_duplicate_in_the_list_is_caught_before_the_database_sees_it():
    """Hai ban ghi cung host:port la MOT loi ra duoc dem thanh hai - va bat bien
    mot-acc-mot-proxy im lang vo."""
    report = proxylist.parse("1.2.3.4:8080\n1.2.3.4:8080\n")
    assert len(report.rows) == 1
    assert "twice" in report.problems[0].detail


def test_the_same_host_on_a_different_port_is_not_a_duplicate():
    """Nha cung cap hay cap nhieu cong tren cung mot host, moi cong mot IP thoat."""
    report = proxylist.parse("1.2.3.4:8080\n1.2.3.4:8081\n")
    assert report.ok
    assert len(report.rows) == 2


def test_line_numbers_match_what_the_user_sees():
    report = proxylist.parse("# ghi chu\n1.2.3.4:8080\nhong\n")
    assert report.problems[0].line == 3


def test_an_empty_list_says_so():
    assert not proxylist.parse("   \n\n").ok
