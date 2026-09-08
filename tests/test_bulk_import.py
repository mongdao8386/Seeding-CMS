"""Nhap tai khoan hang loat tu CSV.

Cai duoc kiem o day la LUA KIEM, khong phai lua tao: mot file 200 dong ma dong 173
sai dinh dang thi 172 dong truoc do da nam trong database, va nguoi dung khong biet
phai sua tu dau. `parse` phai bat het moi loi trong mot lan doc, khong dung o loi dau.
"""

from seeding.domain.models import Platform
from seeding.ops import bulk

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


# ------------------------------------- dinh dang cua nguoi ban acc


SELLER = """username|password|hotmail|pass_hotmail|cookie
seed.fb.01|Matkhau123|abc@hotmail.com|Mailpass1|c_user=100012345; xs=41%3Aabc==
seed.fb.02|Matkhau456|def@hotmail.com|Mailpass2|c_user=100067890; xs=41%3Adef==
"""


def test_the_pipe_delimiter_is_detected():
    """File acc mua san gan nhu luon dung `|`. Bat nguoi dung doi sang dau phay con
    lam hong du lieu: mat khau va cookie thuong CO dau phay ben trong."""
    assert bulk.sniff_delimiter(SELLER) == "|"


def test_a_comma_file_still_reads_as_a_comma_file():
    assert bulk.sniff_delimiter("platform,handle\nreddit,a\n") == ","


def test_a_single_column_file_falls_back_to_comma():
    assert bulk.sniff_delimiter("handle\nseed_01\n") == ","


def test_the_seller_format_imports_without_editing_the_file():
    report = bulk.parse(SELLER, default_platform=Platform.FACEBOOK)
    assert report.ok, [p.detail for p in report.problems]
    assert len(report.rows) == 2
    assert report.with_cookies == 2


def test_seller_column_names_are_translated_and_reported():
    """Doi ten am tham thi nguoi dung khong biet cot cua minh da di dau."""
    report = bulk.parse(SELLER, default_platform=Platform.FACEBOOK)
    assert report.renamed_columns["hotmail"] == "recovery_email"
    assert report.renamed_columns["pass_hotmail"] == "recovery_password"
    assert report.unknown_columns == []


def test_username_doubles_as_the_handle_when_there_is_no_handle_column():
    """`username` vua la dinh danh acc vua la mot truong bi mat cua Reddit, nen no
    khong the doi thang thanh `handle`. Chi khi KHONG co cot handle nao thi no moi
    dong ca hai vai."""
    row = bulk.parse(SELLER, default_platform=Platform.FACEBOOK).rows[0]
    assert row.handle == "seed.fb.01"
    assert row.secrets["username"] == "seed.fb.01"


def test_an_explicit_handle_column_wins_over_username():
    report = bulk.parse(
        "handle|username|password\nten_hien_thi|ten_dang_nhap|abc\n",
        default_platform=Platform.FACEBOOK,
    )
    row = report.rows[0]
    assert row.handle == "ten_hien_thi"
    assert row.secrets["username"] == "ten_dang_nhap"


def test_the_default_platform_fills_in_a_missing_column():
    """Mot file 500 acc Facebook khong nen bat nguoi ta lap lai chu "facebook" 500 lan."""
    report = bulk.parse(SELLER, default_platform=Platform.FACEBOOK)
    assert all(r.platform is Platform.FACEBOOK for r in report.rows)


def test_without_a_default_platform_the_column_is_still_required():
    """Bo qua im lang thi 500 acc roi vao nen tang doan bua."""
    report = bulk.parse(SELLER)
    assert not report.ok
    assert "platform" in report.problems[0].detail


def test_a_platform_column_in_the_file_beats_the_default():
    report = bulk.parse("platform|handle\nreddit|seed_01\n", default_platform=Platform.FACEBOOK)
    assert report.rows[0].platform is Platform.REDDIT


def test_the_recovery_mailbox_password_is_kept_as_a_secret():
    """Thieu no thi den luc nen tang doi xac minh qua email la het duong."""
    row = bulk.parse(SELLER, default_platform=Platform.FACEBOOK).rows[0]
    assert row.secrets["recovery_password"] == "Mailpass1"


def test_the_cookie_is_carried_but_not_parsed_during_the_check():
    """Doc cookie luc kiem nghia la mot chuoi hong lam do ca file. De den luc tao."""
    row = bulk.parse(SELLER, default_platform=Platform.FACEBOOK).rows[0]
    assert row.cookie.startswith("c_user=")


def test_a_row_without_a_cookie_is_not_counted_as_having_one():
    report = bulk.parse(
        "username|password|cookie\na|1|c_user=1; xs=2\nb|2|\n",
        default_platform=Platform.FACEBOOK,
    )
    assert len(report.rows) == 2
    assert report.with_cookies == 1


def test_a_pasted_block_without_a_trailing_newline_still_reads():
    """Dan tu trinh duyet hay thieu dau xuong dong cuoi. Mat dong cuoi ma khong bao
    thi nguoi dung dem thieu mot acc va khong bao gio biet vi sao."""
    dan = (
        "username|password|cookie\n"
        "a|1|c_user=1; xs=2\n"
        "b|2|c_user=3; xs=4"  # khong co \n o cuoi
    )
    report = bulk.parse(dan, default_platform=Platform.FACEBOOK)
    assert len(report.rows) == 2


def test_windows_line_endings_do_not_leave_carriage_returns_in_values():
    """Dan tu Notepad tren Windows ra \r\n. Sot lai \r trong cookie thi trinh duyet
    tu choi ca danh sach."""
    dan = "username|password|cookie\r\na|1|c_user=1; xs=2\r\n"
    row = bulk.parse(dan, default_platform=Platform.FACEBOOK).rows[0]
    assert "\r" not in row.cookie
    assert "\r" not in row.secrets["password"]


# ------------------------------------- buoc kiem phai THU DOC cookie


def test_a_broken_cookie_is_caught_at_the_check_not_at_import():
    """Ban dau buoc kiem chi DEM o cookie co chu hay khong roi bao "14 with a saved
    session". Do la mot loi hua ma buoc tao khong giu duoc, va nguoi dung chi phat hien
    ra khi bai dang dau tien that bai."""
    report = bulk.parse(
        "username|password|cookie\nhong|1|day-khong-phai-cookie\n",
        default_platform=Platform.TIKTOK,
    )
    assert report.with_cookies == 0
    assert report.cookie_problems == 1
    assert "no cookies" in report.rows[0].cookie_note


def test_device_only_cookies_do_not_count_as_a_session():
    """`ttwid` va `tt_chain_token` co mat o moi lan tai trang, ke ca khi chua dang nhap.
    Dem chung thanh "co phien" nghia la he thong tuong tai khoan san sang va giao viec
    cho no."""
    report = bulk.parse(
        "username|password|cookie\nthietbi|1|ttwid=abc; tt_chain_token=xyz\n",
        default_platform=Platform.TIKTOK,
    )
    assert report.with_cookies == 0
    assert "sessionid" in report.rows[0].cookie_note


def test_a_real_session_cookie_counts():
    report = bulk.parse(
        "username|password|cookie\ntot|1|sessionid=abc; sid_tt=xyz\n",
        default_platform=Platform.TIKTOK,
    )
    assert report.with_cookies == 1
    assert report.rows[0].cookie_note is None


def test_a_row_with_no_cookie_is_not_counted_as_a_problem():
    """Khong co cookie la chuyen binh thuong - dang nhap tay mot lan la xong. Dem no
    thanh loi se lam nguoi dung di tim mot van de khong ton tai."""
    report = bulk.parse("username|password|cookie\nkhongco|1|\n", default_platform=Platform.TIKTOK)
    assert report.cookie_problems == 0
    assert report.with_cookies == 0
    assert report.ok


def test_a_bad_cookie_does_not_stop_the_row_being_imported():
    """Cookie hong chi mat mot buoc tien - tai khoan van tao duoc va van dang nhap tay
    duoc. Chan ca dong lai thi mat luon ca mat khau da co."""
    report = bulk.parse(
        "username|password|cookie\nhong|1|rac\ntot|2|sessionid=a\n",
        default_platform=Platform.TIKTOK,
    )
    assert report.ok
    assert len(report.rows) == 2


# ----------------------- dau phan cach nam TRONG gia tri


TIKTOK_PIPE = (
    "username|password|hotmail|pass_hotmail|cookie\n"
    "user123|Mk1|a@h.com|Mp1|"
    "sessionid=abc123; ttwid=1|d1OJOk51wovb|1783813285|7c21198edc\n"
)


def test_a_pipe_inside_the_cookie_does_not_lose_the_cookie():
    """Truong hop THUONG GAP nhat voi acc TikTok: cookie `ttwid` chua dau `|` khong ma
    hoa, dung bang dau phan cach cua file.

    Truoc day csv gom phan thua vao khoa None va code bo di AM THAM: cot cookie chi
    nhan duoc mau dau khong co dau `=`, roi bao "no cookies found in that value" - mot
    cau khong noi gi ve nguyen nhan that.
    """
    report = bulk.parse(TIKTOK_PIPE, default_platform=Platform.TIKTOK)
    assert report.ok
    assert report.with_cookies == 1
    assert report.rows[0].cookie_note is None


def test_the_rejoined_cookie_keeps_every_piece():
    row = bulk.parse(TIKTOK_PIPE, default_platform=Platform.TIKTOK).rows[0]
    assert "sessionid=abc123" in row.cookie
    assert "d1OJOk51wovb" in row.cookie
    assert "7c21198edc" in row.cookie


def test_rejoining_is_reported_rather_than_done_silently():
    """Noi lai la mot phong doan hop ly, khong phai su that hien nhien. Nguoi dung
    phai biet no da xay ra."""
    assert bulk.parse(TIKTOK_PIPE, default_platform=Platform.TIKTOK).rejoined_rows == 1


def test_a_normal_row_is_not_counted_as_rejoined():
    report = bulk.parse(
        "username|password|cookie\na|1|sessionid=x\n", default_platform=Platform.TIKTOK
    )
    assert report.rejoined_rows == 0


def test_overflow_on_a_file_whose_last_column_is_not_cookie_is_an_error():
    """Noi lai chi dung khi cot cuoi la chuoi tu do. Noi bua vao mot cot so thi tao ra
    du lieu sai ma khong ai biet."""
    report = bulk.parse(
        "username|cookie|daily_cap\na|sessionid=x|3|thua|them\n",
        default_platform=Platform.TIKTOK,
    )
    assert not report.ok
    assert "more field" in report.problems[0].detail
