import hashlib
import hmac

import pytest

from tools.github_tools import parse_pr_url, verify_webhook_signature


@pytest.mark.parametrize("url,expected_repo,expected_num", [
    ("https://github.com/octocat/hello-world/pull/42", "octocat/hello-world", 42),
    ("https://github.com/octocat/hello-world/pull/42/", "octocat/hello-world", 42),
    ("http://github.com/my-org/my.repo_name/pull/7", "my-org/my.repo_name", 7),
])
def test_parse_pr_url_valid(url, expected_repo, expected_num):
    repo, num = parse_pr_url(url)
    assert repo == expected_repo
    assert num == expected_num


@pytest.mark.parametrize("bad_url", [
    "https://gitlab.com/owner/repo/pull/1",             # wrong host
    "https://github.com/owner/repo/issues/1",           # not a PR
    "https://github.com/owner/repo/pull/abc",           # non-numeric
    "not a url at all",
    "https://github.com/owner/repo/pull/1; rm -rf /",   # injection attempt
])
def test_parse_pr_url_rejects_invalid(bad_url):
    with pytest.raises(ValueError):
        parse_pr_url(bad_url)


def test_verify_webhook_signature_accepts_correct_signature(monkeypatch):
    from config import get_settings
    get_settings.cache_clear()
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "my-test-secret")
    get_settings.cache_clear()

    payload = b'{"action": "opened"}'
    sig = "sha256=" + hmac.new(b"my-test-secret", payload, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(payload, sig) is True
    get_settings.cache_clear()


def test_verify_webhook_signature_rejects_bad_signature():
    payload = b'{"action": "opened"}'
    bad_sig = "sha256=" + "0" * 64
    assert verify_webhook_signature(payload, bad_sig) is False


def test_verify_webhook_signature_rejects_missing_header():
    assert verify_webhook_signature(b"payload", None) is False
    assert verify_webhook_signature(b"payload", "") is False


def test_verify_webhook_signature_rejects_wrong_prefix():
    assert verify_webhook_signature(b"payload", "sha1=deadbeef") is False
