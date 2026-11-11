from pathlib import Path
from app.forms.selector_cache import SelectorCache


def test_selector_cache_record_and_get(tmp_path: Path):
    cache_file = tmp_path / "test_selectors.json"
    cache = SelectorCache(cache_path=cache_file)

    assert cache.get_selector("naukri.com", "notice period") is None

    cache.record_selector("naukri.com", "notice period", "input[name='notice_days']")
    assert cache.get_selector("naukri.com", "notice period") == "input[name='notice_days']"

    # Reload from disk
    new_cache = SelectorCache(cache_path=cache_file)
    assert new_cache.get_selector("naukri.com", "notice period") == "input[name='notice_days']"


def test_selector_cache_case_insensitivity(tmp_path: Path):
    cache = SelectorCache(cache_path=tmp_path / "cache.json")
    cache.record_selector("Workday.Com", "Expected CTC (in LPA)", "#expectedCtcField")
    assert cache.get_selector("workday.com", "expected ctc in lpa") == "#expectedCtcField"
