import json

from seeding.core import fingerprint as fpm


def test_generate_produces_a_camoufox_config():
    cfg = fpm.generate()
    assert cfg["navigator.userAgent"].startswith("Mozilla/5.0")
    assert cfg["screen.width"] > 0
    assert cfg["fonts"]


def test_user_agent_matches_the_installed_browser():
    """Fingerprint noi doi ve chinh trinh duyet dang chay la tu mau thuan.

    Day la ly do khong tu sinh fingerprint bang BrowserForge nua: user agent phai
    khop voi phien ban Firefox that cua binary Camoufox.
    """
    version = fpm.firefox_version()
    if version is None:
        return  # chua tai binary
    assert f"Firefox/{version}" in fpm.generate()["navigator.userAgent"]


def test_config_carries_the_seeds_that_make_it_stable():
    """Thieu seed thi canvas va audio doi sau moi phien du user agent van giu nguyen."""
    assert fpm.is_pinned(fpm.generate())


def test_is_pinned_rejects_a_config_missing_seeds():
    cfg = fpm.generate()
    del cfg["canvas:seed"]
    assert not fpm.is_pinned(cfg)


def test_config_survives_the_json_column():
    cfg = fpm.generate()
    assert json.loads(json.dumps(cfg)) == cfg


def test_two_profiles_get_different_seeds():
    """Cung user agent thi duoc, nhung seed phai khac - do moi la thu phan biet may."""
    seeds = {fpm.generate()["canvas:seed"] for _ in range(8)}
    assert len(seeds) > 1


def test_locale_is_not_baked_into_the_config():
    """Camoufox muon ngon ngu di qua tham so `locale=`, khong qua config."""
    assert "navigator.language" not in fpm.generate()


def test_summary_is_one_readable_line():
    line = fpm.summary(fpm.generate())
    assert "\n" not in line
    assert "|" in line


def test_never_returns_a_preset_camoufox_cannot_launch():
    """Mot phan preset co cap WebGL ma Camoufox khong tra duoc du lieu.

    Fingerprint duoc ghim vinh vien, nen profile tao nham preset do hong mai mai.
    Sinh 60 lan de kha nang gap it nhat mot lan la rat cao neu bo loc hong.
    """
    for _ in range(60):
        assert fpm.is_launchable(fpm.generate())


def test_is_launchable_flags_a_pair_camoufox_has_no_data_for():
    cfg = fpm.generate()
    cfg["webGl:vendor"] = "Mozilla"
    cfg["webGl:renderer"] = "Mozilla"
    assert not fpm.is_launchable(cfg)


def test_is_launchable_allows_a_config_that_does_not_pin_webgl():
    cfg = fpm.generate()
    cfg.pop("webGl:vendor", None)
    cfg.pop("webGl:renderer", None)
    assert fpm.is_launchable(cfg)
