import json
import time
from unittest.mock import patch, MagicMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)

from agents.base import (
    BaseAgent,
    EmptyOutputError,
    TransientLLMError,
    _jittered_backoff,
    _retry_after_from_response,
)
from agents.performance import PerformanceAgent
from agents.security import SecurityAgent
from agents.style import StyleAgent
from agents.test_coverage import TestCoverageAgent
from graph import workflow
from graph.state import initial_state

DIFF = "diff --git a/x.py b/x.py\n+x = 1\n"
EMPTY_FINDINGS = json.dumps({"findings": []})


def _state():
    return initial_state("owner/repo", 1, "Test PR", "author", DIFF)


def _fake_request(method="POST"):
    return httpx.Request(method, "https://integrate.api.nvidia.com/v1/chat/completions")


def _fake_status_error(cls, status_code, headers=None):
    response = httpx.Response(status_code, headers=headers or {}, request=_fake_request())
    return cls("boom", response=response, body=None)


def _fake_completion(content=EMPTY_FINDINGS, finish_reason="stop"):
    message = MagicMock(content=content)
    choice = MagicMock(message=message, finish_reason=finish_reason)
    return MagicMock(choices=[choice], id="cmpl-test")


# ── Parallelism / isolation (pre-existing behavior, still required) ────

def test_specialists_run_in_parallel():
    def slow_llm(self, system_prompt, user_prompt, model=None, enable_thinking=None):
        time.sleep(0.5)
        return EMPTY_FINDINGS

    with patch.object(BaseAgent, "_call_llm", slow_llm):
        start = time.perf_counter()
        result = workflow.parallel_review_node(_state())
        elapsed = time.perf_counter() - start

    # Sequential execution of four 0.5s calls would take >= 2.0s.
    assert elapsed < 1.5
    for key in ("security_status", "performance_status", "style_status", "test_status"):
        assert result[key] == "done"


def test_one_failing_agent_does_not_affect_others():
    def flaky_llm(self, system_prompt, user_prompt, model=None, enable_thinking=None):
        if self.name == "performance":
            raise RuntimeError("provider down")
        return EMPTY_FINDINGS

    with patch.object(BaseAgent, "_call_llm", flaky_llm):
        result = workflow.parallel_review_node(_state())

    assert result["performance_status"] == "error"
    assert result["security_status"] == "done"
    assert result["style_status"] == "done"
    assert result["test_status"] == "done"


def test_json_format_instruction_defines_findings_schema():
    assert '"findings"' in BaseAgent._json_format_instruction()


def test_every_specialist_has_format_instruction():
    for cls in (SecurityAgent, PerformanceAgent, StyleAgent, TestCoverageAgent):
        assert '"findings"' in cls()._json_format_instruction()


# ── Backoff math ─────────────────────────────────────────────────────

def test_jittered_backoff_is_randomized_within_envelope():
    # Same attempt number, many draws — must not all collapse to one
    # value (that was the original bug: fixed 2.0 * attempt for every
    # concurrently-retrying agent) and must stay within the exponential
    # envelope.
    samples = {round(_jittered_backoff(2), 6) for _ in range(30)}
    assert len(samples) > 1
    for s in samples:
        assert 0 <= s <= 3.0  # ceiling for attempt=2: base(1.5) * 2^1 = 3.0


def test_jittered_backoff_respects_cap():
    from agents.base import MAX_RETRY_WAIT_SECONDS
    assert _jittered_backoff(20) <= MAX_RETRY_WAIT_SECONDS


def test_retry_after_header_is_honored_over_message_text():
    e = _fake_status_error(RateLimitError, 429, headers={"retry-after": "7"})
    assert _retry_after_from_response(e) == 7.0


def test_retry_after_missing_returns_none():
    e = _fake_status_error(RateLimitError, 429, headers={})
    assert _retry_after_from_response(e) is None


# ── Error classification (the actual bug fix) ──────────────────────

def test_5xx_is_retried_with_status_code_recorded():
    agent = SecurityAgent()
    err = _fake_status_error(InternalServerError, 503)
    with patch.object(agent.client.chat.completions, "create", side_effect=err):
        with pytest.raises(TransientLLMError) as exc_info:
            agent._request_once("sys", "user")
    assert exc_info.value.status_code == 503
    assert "503" in exc_info.value.kind


def test_401_is_not_retried_and_propagates_as_is():
    from openai import AuthenticationError
    agent = SecurityAgent()
    err = _fake_status_error(AuthenticationError, 401)
    with patch.object(agent.client.chat.completions, "create", side_effect=err):
        with pytest.raises(AuthenticationError):
            agent._request_once("sys", "user")
    # Must NOT have been wrapped as a TransientLLMError (i.e. must not
    # silently trigger a retry loop for a bad API key).


def test_timeout_is_retryable_and_distinct_from_server_error():
    agent = SecurityAgent()
    err = APITimeoutError(request=_fake_request())
    with patch.object(agent.client.chat.completions, "create", side_effect=err):
        with pytest.raises(TransientLLMError) as exc_info:
            agent._request_once("sys", "user")
    assert exc_info.value.status_code is None  # client-side, no HTTP status
    assert "timeout" in exc_info.value.kind


def test_connection_error_is_retryable():
    agent = SecurityAgent()
    err = APIConnectionError(request=_fake_request())
    with patch.object(agent.client.chat.completions, "create", side_effect=err):
        with pytest.raises(TransientLLMError) as exc_info:
            agent._request_once("sys", "user")
    assert "connection" in exc_info.value.kind


def test_empty_content_is_not_conflated_with_network_error():
    agent = SecurityAgent()
    with patch.object(agent.client.chat.completions, "create",
                       return_value=_fake_completion(content="", finish_reason="length")):
        with pytest.raises(EmptyOutputError) as exc_info:
            agent._request_once("sys", "user")
    # Distinct exception type from a generic TransientLLMError, and the
    # finish_reason that caused it is preserved for debugging.
    assert "length" in str(exc_info.value)
    assert isinstance(exc_info.value, TransientLLMError)  # still retryable


def test_malformed_json_is_not_retried_as_a_network_error():
    agent = SecurityAgent()
    with patch.object(BaseAgent, "_call_llm", return_value="not json at all"), \
         patch("time.sleep") as mock_sleep:
        result = agent._safe_run(
            "security_findings", "security_status", "security", "sys", "user",
        )
    mock_sleep.assert_not_called()  # no retry loop was entered
    assert result["security_status"] == "error"


def test_response_format_off_by_default():
    from config import get_settings
    assert get_settings().nvidia_use_json_mode is False


def test_semaphore_below_worker_count_by_default():
    from config import get_settings
    settings = get_settings()
    assert settings.max_concurrent_llm_calls < 4  # < the 4 parallel specialists
