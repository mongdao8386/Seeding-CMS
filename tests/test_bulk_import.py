"""Nhap tai khoan hang loat tu CSV.

Cai duoc kiem o day la LUA KIEM, khong phai lua tao: mot file 200 dong ma dong 173
sai dinh dang thi 172 dong truoc do da nam trong database, va nguoi dung khong biet
phai sua tu dau. `parse` phai bat het moi loi trong mot lan doc, khong dung o loi dau.
"""

from seeding.core import bulk
from seeding.models import Platform

GOOD = """platform,handle,persona,daily_cap,start_warmup,password
reddit,seed_01,Hanoi students,3,yes,hunter2
facebook,seed.fb.01,Hanoi students,2,no,hunter3
"""


def _lines(report: bulk.Report) -> list[int]:
    return [p.line for p in report.problems]


# ------------------------------------------------------------------ duong tot


def test_a_clean_file_parses_every_row():
    report = bulk.parse(GOOD)
    assert report.ok
    assert len(report.rows) == 2
    assert [r.handle for r in report.rows] == ["seed_01", "seed.fb.01"]


def test_platforms_come_back_as_the_real_enum():
    rows = bulk.parse(GOOD).rows
    assert rows[0].platform is Platform.REDDIT
    assert rows[1].platform is Platform.FACEBOOK


def test_secret_columns_are_collected_into_the_vault_payload():
    """Cot bi mat phai di vao `secrets` de duoc ma hoa, khong phai thanh truong thuong."""
    assert bulk.parse(GOOD).rows[0].secrets == {"password": "hunter2"}


def test_start_warmup_reads_the_words_people_actually_type():
    rows = bulk.parse(GOOD).rows
    assert rows[0].start_warmup is True
    assert rows[1].start_warmup is False


def test_start_warmup_defaults_to_true_when_the_column_is_absent():
    """Bo trong thi phai la co ram. Tao mot tram tai khoan roi cho chung dang ngay
    hom sau la cach nhanh nhat de mat ca tram."""
    report = bulk.parse("platform,handle\nreddit,seed_01\n")
    assert report.rows[0].start_warmup is True
    assert report.rows[0].daily_cap == 3


def test_blank_lines_at_the_end_are_not_errors():
    report = bulk.parse(GOOD + "\n\n")
    assert report.ok
    assert len(report.rows) == 2


def test_a_utf8_bom_and_odd_casing_in_headers_still_work():
    """Excel luon luu kem BOM, va nguoi ta hay viet hoa dau cot."""
    report = bulk.parse("﻿Platform,Handle\nreddit,seed_01\n")
    assert report.ok
    assert report.rows[0].handle == "seed_01"


# ------------------------------------------------------------------- bat loi


def test_a_missing_required_column_is_reported_before_anything_else():
    report = bulk.parse("handle,password\nseed_01,hunter2\n")
    assert not report.ok
    assert "platform" in report.problems[0].detail


def test_an_empty_file_says_so():
    assert not bulk.parse("").ok


def test_a_header_with_no_rows_says_so():
    report = bulk.parse("platform,handle\n")
    assert not report.ok
    assert "no rows" in report.problems[0].detail


def test_an_unknown_platform_names_the_ones_that_exist():
    report = bulk.parse("platform,handle\nmyspace,seed_01\n")
    assert not report.ok
    assert "reddit" in report.problems[0].detail


def test_a_bad_daily_cap_is_caught_instead_of_crashing():
    report = bulk.parse("platform,handle,daily_cap\nreddit,seed_01,lots\n")
    assert not report.ok
    assert "daily_cap" in report.problems[0].detail


def test_a_daily_cap_of_zero_is_refused():
    """0 nghia la tai khoan khong bao gio dang - im lang va vo hinh, khong phai loi
    ai se nghi den khi di tim vi sao chien dich khong chay."""
    assert not bulk.parse("platform,handle,daily_cap\nreddit,seed_01,0\n").ok


def test_every_broken_row_is_reported_in_one_pass():
    """Dung o loi dau tien nghia la nguoi dung sua mot dong, chay lai, gap loi tiep -
    voi file 200 dong do la ca buoi chieu."""
    report = bulk.parse("platform,handle\nmyspace,a\nreddit,\norkut,c\n")
    assert len(report.problems) == 3
    assert _lines(report) == [2, 3, 4]


def test_problems_carry_the_line_number_from_the_file_itself():
    """So dong phai khop voi cai nguoi dung thay trong Excel, ke ca dong tieu de."""
    report = bulk.parse("platform,handle\nreddit,ok_one\nmyspace,bad_one\n")
    assert report.problems[0].line == 3


def test_a_handle_repeated_inside_the_file_is_caught_before_the_database_sees_it():
    """Database se bao o dong dau tien no gap; nguoi dung can biet CA HAI dong."""
    report = bulk.parse("platform,handle\nreddit,seed_01\nreddit,seed_01\n")
    assert not report.ok
    assert report.problems[0].line == 3
    assert len(report.rows) == 1


def test_the_same_handle_on_two_platforms_is_fine():
    """Mot nguoi that hay dung cung mot ten o moi noi. Do khong phai trung lap."""
    report = bulk.parse("platform,handle\nreddit,seed_01\nfacebook,seed_01\n")
    assert report.ok
    assert len(report.rows) == 2


def test_a_column_nobody_recognises_is_surfaced_rather_than_silently_dropped():
    """Go sai ten cot bi mat (`pasword`) thi tai khoan duoc tao ma khong co mat khau,
    va no chi lo ra khi dang nhap that bai."""
    report = bulk.parse("platform,handle,pasword\nreddit,seed_01,hunter2\n")
    assert report.unknown_columns == ["pasword"]
    assert report.rows[0].secrets == {}


# ---------------------------------------------------------------- file mau


def test_the_template_parses_cleanly_with_the_parser_that_reads_it():
    """File mau ma khong doc duoc bang chinh parser cua minh la loi te nhat co the co."""
    report = bulk.parse(bulk.template())
    assert report.ok, [p.detail for p in report.problems]
    assert len(report.rows) == 2


def test_the_template_has_no_unknown_columns():
    assert bulk.parse(bulk.template()).unknown_columns == []
