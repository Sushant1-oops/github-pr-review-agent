"""
Strict schemas for everything an LLM agent is allowed to produce.

Why this exists: the old implementation regex-hunted for a JSON array in
free-text model output and silently returned [] on anything malformed —
so a truncated response, a hallucinated field, or an injected instruction
that corrupted the output all failed the exact same (silent) way. That is
the wrong failure mode for something that posts directly to a public PR.

Every agent response is now forced through this schema. Anything that
doesn't validate is a loud, logged error — not an empty list.
"""

from typing import Literal
from pydantic import BaseModel, Field, field_validator

Severity = Literal["critical", "warning", "suggestion"]

# Hard caps prevent a single runaway/malicious generation from producing
# an unbounded review (cost blowup, spam, or a denial-of-service on the
# PR comment thread itself).
MAX_FINDINGS_PER_AGENT = 25
MAX_FIELD_LEN = 1200


class Finding(BaseModel):
    severity: Severity = "suggestion"
    file: str = Field(default="unknown", max_length=500)
    line_hint: str = Field(default="", max_length=200)
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=MAX_FIELD_LEN)
    suggestion: str = Field(default="", max_length=MAX_FIELD_LEN)

    @field_validator("title", "detail", "suggestion", mode="before")
    @classmethod
    def _coerce_str(cls, v):
        if v is None:
            return ""
        return str(v)


class FindingsResponse(BaseModel):
    """The full expected shape of one agent's structured output."""
    findings: list[Finding] = Field(default_factory=list)

    @field_validator("findings")
    @classmethod
    def _cap_count(cls, v: list[Finding]) -> list[Finding]:
        return v[:MAX_FINDINGS_PER_AGENT]


class JudgeVerdict(BaseModel):
    """Output of the LLM-as-judge grounding pass over one finding."""
    grounded: bool
    reason: str = Field(default="", max_length=300)
