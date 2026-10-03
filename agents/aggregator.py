"""
Aggregator Agent
Takes all findings from the 4 specialist agents and:
1. Deduplicates overlapping findings
2. Prioritises by severity
3. Writes a structured GitHub PR review comment
4. Decides: approve / comment / request_changes
"""

from agents.base import BaseAgent
from graph.state import ReviewState, AgentFinding

SEVERITY_ORDER = {"critical": 0, "warning": 1, "suggestion": 2}
SEVERITY_EMOJI = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵"}
AGENT_EMOJI    = {
    "security":    "🔒 Security",
    "performance": "⚡ Performance",
    "style":       "✨ Style",
    "test":        "🧪 Tests",
}


AGENT_KEYS = ("security", "performance", "style", "test")


class AggregatorAgent(BaseAgent):
    name = "aggregator"

    def run(self, state: ReviewState) -> dict:
        try:
            all_findings = (
                state.get("security_findings",    []) +
                state.get("performance_findings", []) +
                state.get("style_findings",       []) +
                state.get("test_findings",        [])
            )

            # Sort by severity
            sorted_findings = sorted(
                all_findings,
                key=lambda f: SEVERITY_ORDER.get(f.severity, 99)
            )

            failed_agents = [a for a in AGENT_KEYS if state.get(f"{a}_status") == "error"]

            # Decide verdict
            has_critical = any(f.severity == "critical" for f in sorted_findings)

            if has_critical:
                verdict = "request_changes"
            elif len(sorted_findings) > 0:
                verdict = "comment"
            else:
                verdict = "approve"

            # An "approve" is only honest when every specialist actually ran.
            if failed_agents and verdict == "approve":
                verdict = "comment"

            # Build the review markdown
            review = self._build_review(state, sorted_findings, verdict, failed_agents)

            return {
                "final_review":      review,
                "overall_verdict":   verdict,
                "aggregator_status": "done",
            }

        except Exception as e:
            return {
                "final_review":      f"Review failed: {str(e)}",
                "overall_verdict":   "comment",
                "aggregator_status": "error",
                "errors": state.get("errors", []) + [f"AggregatorAgent error: {str(e)}"],
            }

    def _build_review(
        self,
        state: ReviewState,
        findings: list[AgentFinding],
        verdict: str,
        failed_agents: list[str] | None = None,
    ) -> str:
        failed_agents = failed_agents or []
        pr_title  = state.get("pr_title", "")
        pr_author = state.get("pr_author", "")

        # ── Header ──────────────────────────────────────────────
        verdict_line = {
            "approve":         "✅ **LGTM — No significant issues found.**",
            "comment":         "💬 **Review complete — some suggestions worth considering.**",
            "request_changes": "❌ **Changes requested — critical issues must be resolved.**",
        }[verdict]

        lines = [
            "## 🤖 AI Code Review",
            "",
            verdict_line,
            "",
            f"> PR: **{pr_title}** by @{pr_author}",
            "",
        ]

        if failed_agents:
            lines += [
                f"> ⚠️ **Incomplete review:** {', '.join(failed_agents)} agent(s) failed, "
                "so those checks did not run.",
                "",
            ]

        if not findings:
            if failed_agents:
                lines += [
                    "No issues found by the agents that completed. Re-run the review once every agent succeeds.",
                    "",
                ]
            else:
                lines += [
                    "No issues found across security, performance, style, and test coverage. Well done! 🎉",
                    "",
                ]
            injection_flags = state.get("injection_flags", [])
            if injection_flags:
                lines += [
                    "---",
                    "### 🛡️ Guardrail notes",
                    "",
                    f"⚠️ This diff contained {len(injection_flags)} phrase(s) resembling a "
                    "prompt-injection attempt aimed at this reviewer. They were ignored as "
                    "instructions and did not affect this verdict — flagging for human awareness.",
                    "",
                ]
            lines.append(self._footer())
            return "\n".join(lines)

        # ── Summary table ────────────────────────────────────────
        counts = {
            "security":    len(state.get("security_findings",    [])),
            "performance": len(state.get("performance_findings", [])),
            "style":       len(state.get("style_findings",       [])),
            "test":        len(state.get("test_findings",        [])),
        }
        critical_n   = sum(1 for f in findings if f.severity == "critical")
        warnings_n   = sum(1 for f in findings if f.severity == "warning")
        suggestions_n = sum(1 for f in findings if f.severity == "suggestion")

        lines += [
            "### Summary",
            "",
            "| Category | Findings |",
            "|---|---|",
            f"| 🔒 Security    | {counts['security']} |",
            f"| ⚡ Performance | {counts['performance']} |",
            f"| ✨ Style       | {counts['style']} |",
            f"| 🧪 Tests       | {counts['test']} |",
            f"| **Total**      | **{len(findings)}** ({critical_n} critical, {warnings_n} warnings, {suggestions_n} suggestions) |",
            "",
        ]

        # ── Findings by agent ────────────────────────────────────
        agents_order = ["security", "performance", "style", "test"]
        for agent_name in agents_order:
            agent_findings = [f for f in findings if f.agent == agent_name]
            if not agent_findings:
                continue

            lines.append(f"---")
            lines.append(f"### {AGENT_EMOJI[agent_name]}")
            lines.append("")

            for f in agent_findings:
                emoji = SEVERITY_EMOJI.get(f.severity, "⚪")
                lines += [
                    f"#### {emoji} `{f.severity.upper()}` — {f.title}",
                    f"**File:** `{f.file}`  |  **Location:** {f.line_hint}",
                    "",
                    f"{f.detail}",
                    "",
                    f"**💡 Suggestion:** {f.suggestion}",
                    "",
                ]

        # ── Guardrail notes (judge removals + injection flags) ────
        judge_notes = state.get("judge_notes", [])
        injection_flags = state.get("injection_flags", [])
        if judge_notes or injection_flags:
            lines.append("---")
            lines.append("### 🛡️ Guardrail notes")
            lines.append("")
            if injection_flags:
                lines.append(
                    f"⚠️ This diff contained {len(injection_flags)} phrase(s) resembling a "
                    "prompt-injection attempt aimed at this reviewer. They were ignored as "
                    "instructions and did not affect the verdict below — flagging here for "
                    "human awareness."
                )
                lines.append("")
            if judge_notes:
                lines.append(f"The grounding pass removed {len(judge_notes)} finding(s) that "
                              "could not be verified against the actual diff (likely false "
                              "positives), so they are not listed above.")
                lines.append("")

        lines.append(self._footer())
        return "\n".join(lines)

    def _footer(self) -> str:
        return (
            "\n---\n"
            "<sub>🤖 Generated by AI PR Reviewer — "
            "Security · Performance · Style · Test Coverage agents powered by NVIDIA NIM + LangGraph</sub>"
        )
