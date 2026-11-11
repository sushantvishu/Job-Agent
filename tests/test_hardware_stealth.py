from app.browser import STEALTH_INIT_SCRIPT


def test_stealth_script_masks_webdriver():
    assert "navigator" in STEALTH_INIT_SCRIPT
    assert "webdriver" in STEALTH_INIT_SCRIPT


def test_stealth_script_normalizes_webgl():
    assert "UNMASKED_VENDOR_WEBGL" in STEALTH_INIT_SCRIPT or "37445" in STEALTH_INIT_SCRIPT
    assert "Google Inc. (NVIDIA)" in STEALTH_INIT_SCRIPT


def test_stealth_script_audio_jitter():
    assert "AudioBuffer" in STEALTH_INIT_SCRIPT
    assert "getChannelData" in STEALTH_INIT_SCRIPT


def test_stealth_script_strips_cdp_markers():
    assert "cdc_adoQpoasnfa76pfcZLmcfl" in STEALTH_INIT_SCRIPT
