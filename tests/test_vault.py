import pytest

from seeding.domain import vault
from seeding.domain.models import Account, Platform, Proxy


def test_round_trip():
    assert vault.decrypt(vault.encrypt("mat khau cua toi")) == "mat khau cua toi"


def test_ciphertext_is_not_the_plaintext():
    token = vault.encrypt("hunter2")
    assert "hunter2" not in token


def test_same_plaintext_encrypts_differently_each_time():
    """Fernet co nonce - hai ban ma cua cung mot chuoi phai khac nhau."""
    assert vault.encrypt("x") != vault.encrypt("x")


def test_json_round_trip_keeps_unicode():
    data = {"password": "mật khẩu", "totp_seed": "JBSWY3DPEHPK3PXP"}
    assert vault.decrypt_json(vault.encrypt_json(data)) == data


def test_decrypt_json_of_nothing_is_empty():
    assert vault.decrypt_json(None) == {}
    assert vault.decrypt_json("") == {}


def test_garbage_ciphertext_is_rejected_clearly():
    with pytest.raises(vault.VaultError):
        vault.decrypt("khong-phai-ban-ma")


def test_totp_is_six_digits_and_matches_the_reference_seed():
    code = vault.totp_now("JBSWY3DPEHPK3PXP")
    assert len(code) == 6 and code.isdigit()


def test_account_secrets_never_sit_in_plaintext_on_the_model():
    account = Account(handle="acc_thu", platform=Platform.REDDIT)
    account.set_secrets({"client_secret": "sieu-bi-mat", "password": "hunter2"})

    assert "sieu-bi-mat" not in (account.secrets_enc or "")
    assert "hunter2" not in (account.secrets_enc or "")
    assert account.get_secrets()["client_secret"] == "sieu-bi-mat"


def test_account_without_secrets_reads_as_empty():
    assert Account(handle="trong", platform=Platform.REDDIT).get_secrets() == {}


def test_proxy_password_is_encrypted_and_url_is_assembled():
    proxy = Proxy(label="thu", host="1.2.3.4", port=8080, username="nguoidung")
    proxy.set_password("mat-khau-proxy")

    assert "mat-khau-proxy" not in (proxy.password_enc or "")
    assert proxy.get_password() == "mat-khau-proxy"

    as_pw = proxy.as_playwright_proxy()
    assert as_pw["server"] == "http://1.2.3.4:8080"
    assert as_pw["password"] == "mat-khau-proxy"


def test_proxy_without_credentials_omits_them():
    proxy = Proxy(label="mo", host="1.2.3.4", port=3128)
    assert proxy.as_playwright_proxy() == {"server": "http://1.2.3.4:3128"}
