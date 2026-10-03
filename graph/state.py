"""
Shared LangGraph state — every agent reads from and writes to this.
TypedDict means LangGraph can track exactly what each node changed.
"""

from typing import TypedDict, Optional
from dataclasses import dataclass, field


@dataclass
class AgentFinding:
    """A single finding from one agent."""
    agent: str           # "security" | "performance" | "style" | "test"
    severity: str        # "critical" | "warning" | "suggestion"
    file: str
    line_hint: str       # e.g. "line ~42" or "function process_data()"
    title: str
    detail: str
    suggestion: str

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON transport."""
        return {
            "agent":      self.agent,
            "severity":   self.severity,
            "file":       self.file,
            "line_hint":  self.line_hint,
            "title":      self.title,
            "detail":     self.detail,
            "suggestion": self.suggestion,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentFinding":
        """Deserialize from a dict."""
        return cls(
            agent      = data.get("agent", ""),
            severity   = data.get("severity", "suggestion"),
            file       = data.get("file", "unknown"),
            line_hint  = data.get("line_hint", ""),
            title      = data.get("title", ""),
            detail     = data.get("detail", ""),
            suggestion = data.get("suggestion", ""),
        )


class ReviewState(TypedDict):
    # ── Input ─────────────────────────────────────────────────────
    repo_full_name: str
    pr_number: int
    pr_title: str
    pr_author: str
    diff_text: str           # formatted diff string for LLM

    # ── Agent outputs ─────────────────────────────────────────────
    security_findings: list[AgentFinding]
    performance_findings: list[AgentFinding]
    style_findings: list[AgentFinding]
    test_findings: list[AgentFinding]

    # ── Agent status (for frontend streaming) ─────────────────────
    security_status: str     # "pending" | "running" | "done" | "error"
    performance_status: str
    style_status: str
    test_status: str
    judge_status: str
    aggregator_status: str

    # ── LLM-as-judge output ──────────────────────────────────────────
    judge_notes: list[str]     # human-readable notes on any findings the judge removed
    injection_flags: list[str] # suspicious phrases detected in the raw diff

    # ── Final output ──────────────────────────────────────────────
    final_review: str        # markdown formatted review for GitHub
    overall_verdict: str     # "approve" | "request_changes" | "comment"
    posted: bool             # whether it's been posted to GitHub

    # ── Error handling ────────────────────────────────────────────
    errors: list[str]


def initial_state(
    repo_full_name: str,
    pr_number: int,
    pr_title: str,
    pr_author: str,
    diff_text: str,
) -> ReviewState:
    """Return a fresh ReviewState with all defaults."""
    return ReviewState(
        repo_full_name       = repo_full_name,
        pr_number            = pr_number,
        pr_title             = pr_title,
        pr_author            = pr_author,
        diff_text            = diff_text,
        security_findings    = [],
        performance_findings = [],
        style_findings       = [],
        test_findings        = [],
        security_status      = "pending",
        performance_status   = "pending",
        style_status         = "pending",
        test_status          = "pending",
        judge_status         = "pending",
        aggregator_status    = "pending",
        judge_notes          = [],
        injection_flags      = [],
        final_review         = "",
        overall_verdict      = "comment",
        posted               = False,
        errors               = [],
    )
