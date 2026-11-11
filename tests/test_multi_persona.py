import pytest
from app.config import load_config
from app.profile_loader import list_available_profiles, load_profile


def test_list_available_profiles():
    profiles = list_available_profiles()
    assert "default" in profiles
    assert "vapt" in profiles
    assert "appsec" in profiles
    assert "soc" in profiles
    assert "backend" in profiles


def test_load_all_persona_profiles():
    for name in ("vapt", "appsec", "soc", "backend"):
        prof = load_profile(name)
        assert prof.name != ""
        assert len(prof.skills) > 0
        assert len(prof.target_roles) > 0
        assert prof.headline != ""


def test_vapt_profile_focus():
    vapt = load_profile("vapt")
    assert "VAPT" in vapt.skills
    assert "OWASP Top 10" in vapt.skills
    assert "VAPT Analyst" in vapt.target_roles


def test_soc_profile_focus():
    soc = load_profile("soc")
    assert "SOC" in soc.skills
    assert "SIEM" in soc.skills
    assert "SOC Analyst" in soc.target_roles


def test_config_profile_switching():
    cfg_default = load_config("default")
    assert cfg_default.active_profile == "default"

    cfg_vapt = load_config("vapt")
    assert cfg_vapt.active_profile == "vapt"
    assert "vapt" in str(cfg_vapt.profile_dir).lower()
