import json
import logging
import random
import re
import time
from threading import BoundedSemaphore
from pydantic_settings import BaseSettings, SettingsConfigDict

from openai import (
    OpenAI,
    APIStatusError,
    APIConnectionError,
    APITimeoutError,
    RateLimitError,
    BadRequestError,
)
from pydantic import ValidationError

from config import get_settings
from graph.state import AgentFinding
from guardrails.schemas import FindingsResponse
from guardrails.sanitize import redact_secrets

logger = logging.getLogger("pr_reviewer.agents")
settings = get_settings()

MAX_LLM_ATTEMPTS = 2                # unchanged — not blindly raised
MAX_RETRY_WAIT_SECONDS = 30.0
BACKOFF_BASE_SECONDS = 1.5
_RETRY_AFTER_RE = re.compile(r"try again in ([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)

# Caps how many LLM requests are in flight at once. Agents run in parallel
# (ThreadPoolExecutor in graph/workflow.py is unchanged — still 4 workers);
# this only bounds simultaneous *outbound HTTP calls* to NIM's shared
# per-account rate limit, independent of that.
_LLM_SEMAPHORE = BoundedSemaphore(settings.max_concurrent_llm_calls)

# Per-model cache: does this NIM-hosted model actually accept
# response_format={"type": "json_object"}? Only probed (and only matters)
# if settings.nvidia_use_json_mode is turned on — see config.py.
_json_mode_supported: dict[str, bool] = {}


class TransientLLMError(Exception):
    """A failure worth retrying. Carries enough detail (status code, retry
    hint, and a human-readable kind) that logs are actually debuggable —
    'transient LLM error' alone was not enough to tell a timeout from a
    503 from an empty response."""

    def __init__(self, message: str, kind: str, status_code: int | None = None,
                 retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.retry_after = retry_after


class EmptyOutputError(TransientLLMError):
    """A 200 OK with no usable content. This is NOT a network failure —
    it's the model returning nothing (often because it spent its whole
    token budget on hidden reasoning despite enable_thinking=False, or a
    genuine one-off fluke). Kept retryable, but logged and counted
    distinctly from connection/rate-limit/server errors so the two are
    never conflated in logs or in the retry decision."""


def _retry_after_from_response(e: APIStatusError) -> float | None:
    """Prefer the real Retry-After HTTP header over guessing. Groq's SDK
    put a hint in the message body ('try again in 8.2s'); NVIDIA NIM does
    not follow that convention, so the old regex against e.message never
    matched a NIM error and always fell through to blind backoff. Try the
    header first, then the old regex as a harmless fallback for providers
    that do phrase it that way, then give up and let exponential backoff
    decide."""
    response = getattr(e, "response", None)
    header_value = response.headers.get("retry-after") if response is not None else None
    if header_value:
        try:
            return float(header_value)
        except ValueError:
            pass  # not a delay-seconds value (e.g. an HTTP-date) — ignore
    match = _RETRY_AFTER_RE.search(str(e))
    return float(match.group(1)) if match else None


def _jittered_backoff(attempt: int) -> float:
    """Full-jitter exponential backoff (attempt is 1-indexed). Plain
    `2.0 * attempt` made every concurrently-failing agent retry at the
    *same* instant — four agents backing off in lockstep just re-hits an
    already-overloaded endpoint together. Randomizing the wait inside the
    exponential envelope is what actually spreads retries out."""
    ceiling = min(MAX_RETRY_WAIT_SECONDS, BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
    return random.uniform(0, ceiling)


class BaseAgent:
    name: str = "base"

class BaseAgent:
    name: str = "base"

    def __init__(self):
        self.client = OpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
            timeout=settings.llm_timeout_seconds,
            max_retries=0,
        )

        self.fast_client = OpenAI(
            base_url=settings.nvidia_base_url,
            api_key=settings.nvidia_api_key,
            timeout=settings.llm_fast_timeout_seconds,
            max_retries=0,
        )

        self.model = settings.nvidia_model
        self.fast_model = settings.nvidia_model_fast

    # ── LLM call with bounded concurrency + rate-limit-aware retry ─────

    def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        enable_thinking: bool = None,
    ) -> str:

        last_error: TransientLLMError | None = None

        for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
            try:
                return self._request_once(
                    system_prompt,
                    user_prompt,
                    model,
                    enable_thinking,
                )

            except TransientLLMError as e:
                last_error = e

                if attempt == MAX_LLM_ATTEMPTS:
                    break

                wait = (
                    e.retry_after
                    if e.retry_after is not None
                    else _jittered_backoff(attempt)
                )

                wait = min(wait, MAX_RETRY_WAIT_SECONDS)

                logger.warning(
                    "%s: %s (status=%s) — attempt %d/%d, "
                    "retrying in %.1fs. %s",
                    self.name,
                    e.kind,
                    e.status_code
                    if e.status_code is not None
                    else "n/a",
                    attempt,
                    MAX_LLM_ATTEMPTS,
                    wait,
                    str(e)[:300],
                )

                time.sleep(wait)

        raise last_error

    def _request_once(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        enable_thinking: bool = None,
    ) -> str:

        chosen_model = model or self.model

        thinking = (
            settings.nvidia_enable_thinking
            if enable_thinking is None
            else enable_thinking
        )

        extra_body = {
            "chat_template_kwargs": {
                "enable_thinking": thinking
            }
        }

        use_json_mode = (
            settings.nvidia_use_json_mode
            and _json_mode_supported.get(chosen_model, True)
        )

        started = time.monotonic()

        try:
            # Only this section is protected by the concurrency limit.
            # Agents can still execute in parallel, but only
            # max_concurrent_llm_calls HTTP requests can be active.
            with _LLM_SEMAPHORE:

                try:
                    response = self._create_completion(
                        chosen_model,
                        system_prompt,
                        user_prompt,
                        extra_body,
                        use_json_mode,
                    )

                except BadRequestError as e:
                    # Some NIM-hosted models may reject
                    # response_format={"type": "json_object"}.
                    #
                    # If that happens, disable JSON mode for this model
                    # and immediately retry using prompt-only JSON.
                    if (
                        use_json_mode
                        and "response_format" in str(e).lower()
                    ):
                        logger.warning(
                            "%s: model %s rejected "
                            "response_format=json_object; "
                            "falling back to prompt-only JSON mode",
                            self.name,
                            chosen_model,
                        )

                        _json_mode_supported[chosen_model] = False

                        response = self._create_completion(
                            chosen_model,
                            system_prompt,
                            user_prompt,
                            extra_body,
                            False,
                        )

                    else:
                        logger.error(
                            "%s: non-retryable 400 from NIM: %s",
                            self.name,
                            str(e)[:500],
                        )
                        raise

        except RateLimitError as e:
            raise TransientLLMError(
                str(e),
                kind="rate_limit (429)",
                status_code=getattr(e, "status_code", 429),
                retry_after=_retry_after_from_response(e),
            ) from e

        except APITimeoutError as e:
            raise TransientLLMError(
                str(e),
                kind="client timeout",
            ) from e

        except APIConnectionError as e:
            raise TransientLLMError(
                str(e),
                kind="connection error",
            ) from e

        except APIStatusError as e:
            # Retry 5xx errors.
            if e.status_code >= 500:
                raise TransientLLMError(
                    str(e),
                    kind=f"server error ({e.status_code})",
                    status_code=e.status_code,
                    retry_after=_retry_after_from_response(e),
                ) from e

            # 400/401/403/404/422/etc.
            # These are not transient and should not be retried.
            logger.error(
                "%s: non-retryable HTTP %s from NIM: %s",
                self.name,
                e.status_code,
                str(e)[:500],
            )
            raise

        except Exception:
            # Unexpected exception.
            # Log it here, but do not convert it into a retryable
            # TransientLLMError because we don't know whether it is safe
            # to retry.
            logger.exception(
                "%s: unexpected exception during NIM request",
                self.name,
            )
            raise

        finally:
            elapsed = time.monotonic() - started

            logger.info(
                "%s: NIM request finished | model=%s | elapsed=%.2fs",
                self.name,
                chosen_model,
                elapsed,
            )

        choice = response.choices[0]

        content = choice.message.content

        finish_reason = getattr(
            choice,
            "finish_reason",
            None,
        )

        if not content:
            raise EmptyOutputError(
                f"empty content, "
                f"finish_reason={finish_reason!r}, "
                f"response_id={getattr(response, 'id', 'n/a')}",
                kind=f"empty output "
                f"(finish_reason={finish_reason})",
            )

        if finish_reason == "length":
            logger.warning(
                "%s: response hit max_tokens "
                "(finish_reason=length) — "
                "output may be truncated JSON",
                self.name,
            )

        return content.strip()

    def _create_completion(
        self,
        model,
        system_prompt,
        user_prompt,
        extra_body,
        use_json_mode,
    ):

        kwargs = dict(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=settings.temperature,
            max_tokens=min(settings.max_tokens, 4000),
            extra_body=extra_body,
        )

        if use_json_mode:
            kwargs["response_format"] = {
                "type": "json_object"
            }

        # Fast model → fast client → shorter timeout
        #
        # Strong model → normal client → longer timeout
        client = (
            self.fast_client
            if model == settings.nvidia_model_fast
            else self.client
        )

        return client.chat.completions.create(**kwargs)

    # ── Prompt helpers ────────────────────────────────────────────────

    @staticmethod
    def _json_format_instruction() -> str:
        return (
            "Respond ONLY with a single JSON object. "
            "No prose, no markdown, no code fences, "
            "no explanation before or after — in exactly "
            "this shape:\n"
            '{"findings": [{"severity": '
            '"critical|warning|suggestion", '
            '"file": "path/to/file", '
            '"line_hint": "line ~42 or function name", '
            '"title": "short title", '
            '"detail": "what is wrong and why", '
            '"suggestion": "concrete fix"}]}\n'
            'If there are no genuine issues, '
            'respond with {"findings": []}.'
        )

    # ── Parsing ───────────────────────────────────────────────────────

    def _parse_findings(
        self,
        raw: str,
        agent_name: str,
    ) -> list[AgentFinding]:

        data = json.loads(raw)

        if isinstance(data, list):
            data = {"findings": data}

        validated = FindingsResponse.model_validate(data)

        findings = []

        for item in validated.findings:
            findings.append(
                AgentFinding(
                    agent=agent_name,
                    severity=item.severity,
                    file=item.file,
                    line_hint=item.line_hint,
                    title=redact_secrets(item.title),
                    detail=redact_secrets(item.detail),
                    suggestion=redact_secrets(item.suggestion),
                )
            )

        return findings

    @staticmethod
    def _strip_code_fences(raw: str) -> str:
        raw = raw.strip()

        if raw.startswith("```"):
            raw = re.sub(
                r"^```[a-zA-Z]*\n?",
                "",
                raw,
            )

            raw = re.sub(
                r"\n?```$",
                "",
                raw,
            )

        return raw.strip()

    @staticmethod
    def _extract_json_object(raw: str) -> str:
        """
        Best-effort rescue for models that wrap the JSON object
        in stray prose.

        This does not invent or repair fields. The extracted
        object still goes through Pydantic validation.
        """

        start = raw.find("{")
        end = raw.rfind("}")

        if start != -1 and end != -1 and end > start:
            return raw[start:end + 1]

        return raw

    def _safe_run(
        self,
        findings_key: str,
        status_key: str,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str = None,
        enable_thinking: bool = None,
    ) -> dict:

        try:
            raw = self._call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=model,
                enable_thinking=enable_thinking,
            )

        except Exception as e:
            logger.error(
                "%s: LLM call failed after retries: %s: %s",
                agent_name,
                type(e).__name__,
                e,
            )

            return {
                findings_key: [],
                status_key: "error",
                "errors": [
                    f"{agent_name} LLM call failed: {e}"
                ],
            }

        cleaned = self._strip_code_fences(raw)

        try:
            findings = self._parse_findings(
                cleaned,
                agent_name,
            )

        except (
            json.JSONDecodeError,
            ValidationError,
            ValueError,
        ) as e:

            rescued = self._extract_json_object(cleaned)

            try:
                findings = self._parse_findings(
                    rescued,
                    agent_name,
                )

            except (
                json.JSONDecodeError,
                ValidationError,
                ValueError,
            ):
                logger.error(
                    "%s: output failed schema validation: "
                    "%s | raw=%.500s",
                    agent_name,
                    e,
                    raw,
                )

                return {
                    findings_key: [],
                    status_key: "error",
                    "errors": [
                        f"{agent_name} returned malformed output "
                        "(schema validation failed)"
                    ],
                }

        return {
            findings_key: findings,
            status_key: "done",
        }
