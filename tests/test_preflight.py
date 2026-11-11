from app.preflight import PreFlightChecker


def test_preflight_empty_url():
    active, reason = PreFlightChecker.check_url("")
    assert not active
    assert "Empty" in reason


def test_preflight_foreign_linkedin_subdomain_rejected():
    active, reason = PreFlightChecker.check_url("https://fr.linkedin.com/jobs/view/1234567")
    assert not active
    assert "Foreign LinkedIn subdomain" in reason


def test_preflight_domestic_and_global_accepted():
    # In-memory mock / check that Indian and global domains are not rejected by the subdomain gate
    # (they will attempt probe or return gracefully)
    active, reason = PreFlightChecker.check_url("https://in.linkedin.com/jobs/view/test-id")
    # Will either be active or return dead/bypassed, but NOT rejected by the foreign subdomain gate
    assert "Foreign LinkedIn subdomain" not in reason
