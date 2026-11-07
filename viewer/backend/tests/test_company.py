import config
from services.company import (
    company_logo_url,
    company_name,
    company_website,
    decision_emoji,
    is_real_compensation,
    job_compensation,
    job_mode,
    logo_dev_brand_cache,
    normalize_label,
    sanitize_job,
)


def test_company_name_non_workday_is_source_key():
    assert company_name({"provider": "greenhouse", "source_key": "acme"}) == "acme"


def test_company_name_workday_splits_on_slash():
    assert company_name({"provider": "workday", "source_key": "acme/careers"}) == "acme"


def test_company_name_workday_empty_source_key():
    assert company_name({"provider": "workday", "source_key": ""}) == ""


def test_is_real_compensation_true_cases():
    assert is_real_compensation("$120,000 - $150,000") is True
    assert is_real_compensation("Salary: 120k-150k") is True


def test_is_real_compensation_false_for_junk():
    assert is_real_compensation("REQ-12345") is False
    assert is_real_compensation("/job/12345") is False
    assert is_real_compensation("") is False
    assert is_real_compensation(None) is False


def test_is_real_compensation_false_without_value():
    assert is_real_compensation("competitive salary") is False


def test_sanitize_job_clears_fake_compensation():
    job = {"compensation": "REQ-999", "title": "x"}
    assert sanitize_job(job)["compensation"] is None


def test_sanitize_job_keeps_real_compensation():
    job = {"compensation": "$100k-$120k", "title": "x"}
    assert sanitize_job(job)["compensation"] == "$100k-$120k"


def test_normalize_label_collapses_whitespace():
    assert normalize_label("  a   b\tc\n") == "a b c"


def test_normalize_label_none():
    assert normalize_label(None) == ""


def test_job_mode_remote():
    assert job_mode("Remote - US", None) == "Remote"


def test_job_mode_hybrid():
    assert job_mode("Miami (Hybrid)", None) == "Hybrid"


def test_job_mode_onsite():
    assert job_mode("Miami, on-site", None) == "On-site"


def test_job_mode_falls_back_to_location():
    assert job_mode("Miami, FL", None) == "Miami, FL"


def test_job_mode_na_when_nothing():
    assert job_mode(None, None) == "n/a"


def test_job_compensation_normalizes_or_na():
    assert job_compensation("  $100k  ") == "$100k"
    assert job_compensation(None) == "n/a"


def test_decision_emoji_tiers():
    assert decision_emoji(4.9) == "🌟 Top pick"
    assert decision_emoji(4.6) == "🎯 Strong match"
    assert decision_emoji(4.3) == "⚡ Quick apply"
    assert decision_emoji(4.0) == "✅ Worth applying"


def test_company_logo_url_none_without_publishable_key(monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_PUBLISHABLE_KEY", None)
    assert company_logo_url("Acme") is None


def test_company_logo_url_name_based_without_cache(monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_PUBLISHABLE_KEY", "pub-key")
    logo_dev_brand_cache.clear()
    url = company_logo_url("Acme Corp")
    assert url is not None
    assert "img.logo.dev/name/Acme%20Corp" in url
    assert "token=pub-key" in url


def test_company_logo_url_uses_cached_domain(monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_PUBLISHABLE_KEY", "pub-key")
    logo_dev_brand_cache.clear()
    logo_dev_brand_cache["acme corp"] = "acme.com"
    url = company_logo_url("Acme Corp")
    assert "img.logo.dev/acme.com" in url
    logo_dev_brand_cache.clear()


def test_company_logo_url_empty_company(monkeypatch):
    monkeypatch.setattr(config, "LOGO_DEV_PUBLISHABLE_KEY", "pub-key")
    assert company_logo_url("   ") is None


def test_company_website_none_without_cache_hit():
    logo_dev_brand_cache.clear()
    assert company_website("Acme") is None


def test_company_website_uses_cached_domain():
    logo_dev_brand_cache.clear()
    logo_dev_brand_cache["acme"] = "acme.com"
    assert company_website("Acme") == "https://acme.com"
    logo_dev_brand_cache.clear()


def test_company_website_empty_company():
    assert company_website("") is None
