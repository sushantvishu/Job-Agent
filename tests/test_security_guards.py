import pytest
from pathlib import Path
from app.config import MaskedSecret, load_config
from app.cover_email_composer import CoverEmailComposer
from app.profile_loader import load_profile


def test_masked_secret_repr():
    secret = MaskedSecret("super_secret_smtp_password")
    # In repr, secret is masked
    assert "**********" in repr(secret)
    assert "super_secret_smtp_password" not in repr(secret)
    # Underlying value remains intact for authenticators
    assert secret.get_secret_value() == "super_secret_smtp_password"
    assert secret == "super_secret_smtp_password"


def test_path_traversal_validation(tmp_path: Path):
    cfg = load_config()
    safe_profile = cfg.project_root / "profile" / "profile.json"
    assert cfg.validate_safe_path(safe_profile) == safe_profile.resolve()

    # Outside traversal attempt
    with pytest.raises(ValueError, match="Path traversal violation"):
        outside_path = cfg.project_root.parent / "etc" / "passwd"
        cfg.validate_safe_path(outside_path)


def test_email_html_escaping():
    cfg = load_config()
    prof = load_profile(cfg.profile_path)
    composer = CoverEmailComposer(profile=prof)

    # Scraped malicious / adversarial string
    malicious_role = "<script>alert('xss')</script> VAPT Analyst & Tester"
    malicious_company = "CyberSec <Evil> Ltd & Sons"

    html_body, plain_body = composer._compose_with_template(
        role=malicious_role,
        company=malicious_company,
        poster_name="Recruiter <Boss>",
        skills_mentioned=["VAPT", "OWASP"],
    )

    # Verify HTML escaping
    assert "<script>" not in html_body
    assert "&lt;script&gt;" in html_body
    assert "&lt;Evil&gt;" in html_body
    assert "&amp;" in html_body
