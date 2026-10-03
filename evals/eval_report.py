"""
Evaluation report generator — takes raw eval results and produces
both a structured JSON report and a human-readable markdown report
with numerical metrics: precision, recall, F1, per-agent accuracy,
verdict accuracy, latency stats, and guardrail effectiveness.

    from evals.eval_report import EvalReport
    report = EvalReport(results)
    report.save("evals/results/")
"""

import json
import os
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class CaseResult:
    """Result of a single eval case."""
    name: str
    passed: bool
    detail: str
    expect_agent: str
    expect_keywords: list[str]
    expect_severity: Optional[str]

    # What the pipeline actually produced
    actual_findings_count: int = 0
    actual_agent_findings_count: int = 0  # findings from the expected agent specifically
    actual_verdict: str = ""
    actual_severity_matched: bool = False
    keyword_matched: bool = False
    verdict_correct: bool = True
    injection_detected: bool = False
    injection_expected: bool = False
    judge_removed_count: int = 0
    total_pre_judge_count: int = 0

    # Timing
    latency_seconds: float = 0.0

    # Per-agent breakdown
    security_count: int = 0
    performance_count: int = 0
    style_count: int = 0
    test_count: int = 0

    # Errors
    errors: list[str] = field(default_factory=list)


@dataclass
class AgentMetrics:
    """Metrics for a single agent type."""
    agent_name: str
    total_cases: int = 0        # cases where this agent was the expected one
    detected: int = 0           # cases where at least one keyword-matched finding was produced
    missed: int = 0             # cases where expected findings weren't found
    false_positive_count: int = 0  # findings produced on cases where this agent wasn't expected
    recall: float = 0.0
    avg_findings_per_case: float = 0.0


class EvalReport:
    """Generates numerical evaluation metrics from raw eval results."""

    def __init__(self, results: list[CaseResult]):
        self.results = results
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self._compute_metrics()

    def _compute_metrics(self):
        n = len(self.results)
        if n == 0:
            return

        # ── Overall pass/fail ────────────────────────────────────────
        self.total_cases = n
        self.passed_count = sum(1 for r in self.results if r.passed)
        self.failed_count = n - self.passed_count
        self.pass_rate = self.passed_count / n

        # ── Recall: cases with expected issues where the issue was found
        cases_with_expected = [r for r in self.results if r.expect_agent != "none"]
        self.recall_cases = len(cases_with_expected)
        self.recall_hits = sum(1 for r in cases_with_expected if r.keyword_matched)
        self.recall = self.recall_hits / self.recall_cases if self.recall_cases else 0.0

        # ── False positive rate on clean PRs ────────────────────────
        clean_cases = [r for r in self.results if r.expect_agent == "none"]
        self.clean_cases_count = len(clean_cases)
        self.clean_with_findings = sum(1 for r in clean_cases if r.actual_findings_count > 0)
        self.false_positive_rate = self.clean_with_findings / self.clean_cases_count if self.clean_cases_count else 0.0

        # ── Precision ────────────────────────────────────────────────
        # Total findings produced across all cases
        self.total_findings_produced = sum(r.actual_findings_count for r in self.results)
        # "Correct" findings = findings on cases where issues were expected and keyword matched
        self.correct_findings = sum(r.actual_agent_findings_count for r in cases_with_expected if r.keyword_matched)
        # Approximate precision: we consider all findings on keyword-matched cases as correct
        # and all findings on clean cases as false positives
        total_fp_findings = sum(r.actual_findings_count for r in clean_cases)
        self.precision = (self.total_findings_produced - total_fp_findings) / self.total_findings_produced if self.total_findings_produced else 1.0

        # ── F1 Score ─────────────────────────────────────────────────
        if self.precision + self.recall > 0:
            self.f1_score = 2 * (self.precision * self.recall) / (self.precision + self.recall)
        else:
            self.f1_score = 0.0

        # ── Verdict accuracy ─────────────────────────────────────────
        self.verdict_correct_count = sum(1 for r in self.results if r.verdict_correct)
        self.verdict_accuracy = self.verdict_correct_count / n

        # ── Severity accuracy ────────────────────────────────────────
        severity_cases = [r for r in self.results if r.expect_severity]
        self.severity_cases_count = len(severity_cases)
        self.severity_correct_count = sum(1 for r in severity_cases if r.actual_severity_matched)
        self.severity_accuracy = self.severity_correct_count / self.severity_cases_count if self.severity_cases_count else 0.0

        # ── Latency stats ────────────────────────────────────────────
        latencies = [r.latency_seconds for r in self.results if r.latency_seconds > 0]
        if latencies:
            self.latency_mean = statistics.mean(latencies)
            self.latency_median = statistics.median(latencies)
            self.latency_p95 = sorted(latencies)[int(len(latencies) * 0.95)]
            self.latency_min = min(latencies)
            self.latency_max = max(latencies)
            self.latency_total = sum(latencies)
        else:
            self.latency_mean = self.latency_median = self.latency_p95 = 0.0
            self.latency_min = self.latency_max = self.latency_total = 0.0

        # ── Guardrail / injection detection ──────────────────────────
        injection_cases = [r for r in self.results if r.injection_expected]
        self.injection_cases_count = len(injection_cases)
        self.injection_detected_count = sum(1 for r in injection_cases if r.injection_detected)
        self.injection_detection_rate = self.injection_detected_count / self.injection_cases_count if self.injection_cases_count else 0.0

        # ── Judge effectiveness ──────────────────────────────────────
        self.total_pre_judge = sum(r.total_pre_judge_count for r in self.results)
        self.total_judge_removed = sum(r.judge_removed_count for r in self.results)
        self.judge_removal_rate = self.total_judge_removed / self.total_pre_judge if self.total_pre_judge else 0.0

        # ── Per-agent metrics ────────────────────────────────────────
        self.agent_metrics = {}
        for agent_name in ["security", "performance", "style", "test"]:
            am = AgentMetrics(agent_name=agent_name)
            agent_cases = [r for r in self.results if r.expect_agent == agent_name]
            am.total_cases = len(agent_cases)
            am.detected = sum(1 for r in agent_cases if r.keyword_matched)
            am.missed = am.total_cases - am.detected
            am.recall = am.detected / am.total_cases if am.total_cases else 0.0

            # Count findings this agent produced on cases where it WASN'T the expected agent
            count_attr = f"{agent_name}_count"
            non_agent_cases = [r for r in self.results if r.expect_agent != agent_name and r.expect_agent != "none"]
            am.false_positive_count = sum(getattr(r, count_attr, 0) for r in non_agent_cases)

            all_agent_cases_with_findings = [r for r in self.results if r.expect_agent == agent_name]
            count_list = [getattr(r, count_attr, 0) for r in all_agent_cases_with_findings]
            am.avg_findings_per_case = statistics.mean(count_list) if count_list else 0.0

            self.agent_metrics[agent_name] = am

    def to_json(self) -> dict:
        """Return full report as a serializable dict."""
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_cases": self.total_cases,
                "passed": self.passed_count,
                "failed": self.failed_count,
                "pass_rate": round(self.pass_rate, 4),
            },
            "detection_metrics": {
                "precision": round(self.precision, 4),
                "recall": round(self.recall, 4),
                "f1_score": round(self.f1_score, 4),
                "false_positive_rate": round(self.false_positive_rate, 4),
                "total_findings_produced": self.total_findings_produced,
            },
            "verdict_metrics": {
                "verdict_accuracy": round(self.verdict_accuracy, 4),
                "correct": self.verdict_correct_count,
                "total": self.total_cases,
            },
            "severity_metrics": {
                "severity_accuracy": round(self.severity_accuracy, 4),
                "correct": self.severity_correct_count,
                "total": self.severity_cases_count,
            },
            "latency": {
                "mean_seconds": round(self.latency_mean, 2),
                "median_seconds": round(self.latency_median, 2),
                "p95_seconds": round(self.latency_p95, 2),
                "min_seconds": round(self.latency_min, 2),
                "max_seconds": round(self.latency_max, 2),
                "total_seconds": round(self.latency_total, 2),
            },
            "guardrails": {
                "injection_detection_rate": round(self.injection_detection_rate, 4),
                "injection_cases": self.injection_cases_count,
                "injection_detected": self.injection_detected_count,
                "judge_removal_rate": round(self.judge_removal_rate, 4),
                "judge_removed": self.total_judge_removed,
                "judge_total_pre": self.total_pre_judge,
            },
            "per_agent": {
                name: {
                    "total_cases": am.total_cases,
                    "detected": am.detected,
                    "missed": am.missed,
                    "recall": round(am.recall, 4),
                    "false_positive_count": am.false_positive_count,
                    "avg_findings_per_case": round(am.avg_findings_per_case, 2),
                }
                for name, am in self.agent_metrics.items()
            },
            "cases": [asdict(r) for r in self.results],
        }

    def to_markdown(self) -> str:
        """Generate a human-readable markdown report."""
        lines = []
        lines.append("# 📊 PR Review Agent — Evaluation Report")
        lines.append("")
        lines.append(f"**Generated:** {self.timestamp}")
        lines.append(f"**Total cases:** {self.total_cases}")
        lines.append("")

        # ── Overall Results ───────────────────────────────────────────
        lines.append("## Overall Results")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| **Pass Rate** | **{self.passed_count}/{self.total_cases}** ({self.pass_rate:.1%}) |")
        lines.append(f"| **Precision** | {self.precision:.1%} |")
        lines.append(f"| **Recall** | {self.recall:.1%} |")
        lines.append(f"| **F1 Score** | {self.f1_score:.1%} |")
        lines.append(f"| False Positive Rate | {self.false_positive_rate:.1%} |")
        lines.append(f"| Verdict Accuracy | {self.verdict_accuracy:.1%} |")
        lines.append(f"| Severity Accuracy | {self.severity_accuracy:.1%} |")
        lines.append(f"| Total Findings Produced | {self.total_findings_produced} |")
        lines.append("")

        # ── Latency ──────────────────────────────────────────────────
        lines.append("## ⏱️ Latency")
        lines.append("")
        lines.append(f"| Stat | Seconds |")
        lines.append(f"|------|---------|")
        lines.append(f"| Mean | {self.latency_mean:.1f}s |")
        lines.append(f"| Median | {self.latency_median:.1f}s |")
        lines.append(f"| P95 | {self.latency_p95:.1f}s |")
        lines.append(f"| Min | {self.latency_min:.1f}s |")
        lines.append(f"| Max | {self.latency_max:.1f}s |")
        lines.append(f"| **Total** | **{self.latency_total:.1f}s** |")
        lines.append("")

        # ── Per-Agent Metrics ────────────────────────────────────────
        lines.append("## 🤖 Per-Agent Metrics")
        lines.append("")
        emoji = {"security": "🔒", "performance": "⚡", "style": "✨", "test": "🧪"}
        lines.append("| Agent | Cases | Detected | Missed | Recall | FP Count | Avg Findings |")
        lines.append("|-------|-------|----------|--------|--------|----------|-------------|")
        for name, am in self.agent_metrics.items():
            e = emoji.get(name, "")
            lines.append(
                f"| {e} {name.capitalize()} | {am.total_cases} | {am.detected} | "
                f"{am.missed} | {am.recall:.0%} | {am.false_positive_count} | "
                f"{am.avg_findings_per_case:.1f} |"
            )
        lines.append("")

        # ── Guardrails ───────────────────────────────────────────────
        lines.append("## 🛡️ Guardrails & Judge")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Injection Detection Rate | {self.injection_detection_rate:.0%} ({self.injection_detected_count}/{self.injection_cases_count}) |")
        lines.append(f"| Judge Removal Rate | {self.judge_removal_rate:.1%} ({self.total_judge_removed}/{self.total_pre_judge}) |")
        lines.append("")

        # ── Case-by-Case Results ─────────────────────────────────────
        lines.append("## 📋 Case-by-Case Results")
        lines.append("")
        lines.append("| # | Case | Agent | Pass | Findings | Verdict | Latency |")
        lines.append("|---|------|-------|------|----------|---------|---------|")
        for i, r in enumerate(self.results, 1):
            status = "✅" if r.passed else "❌"
            lines.append(
                f"| {i} | `{r.name}` | {r.expect_agent} | {status} | "
                f"{r.actual_findings_count} | {r.actual_verdict} | {r.latency_seconds:.1f}s |"
            )
        lines.append("")

        # ── Failed cases detail ──────────────────────────────────────
        failed = [r for r in self.results if not r.passed]
        if failed:
            lines.append("## ❌ Failed Cases — Details")
            lines.append("")
            for r in failed:
                lines.append(f"### `{r.name}`")
                lines.append(f"- **Expected agent:** {r.expect_agent}")
                lines.append(f"- **Expected keywords:** {r.expect_keywords}")
                lines.append(f"- **Failure reason:** {r.detail}")
                if r.errors:
                    lines.append(f"- **Errors:** {'; '.join(r.errors)}")
                lines.append("")

        return "\n".join(lines)

    def save(self, output_dir: str):
        """Save JSON and markdown reports to the given directory."""
        os.makedirs(output_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        json_path = os.path.join(output_dir, f"eval_{ts}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2)

        md_path = os.path.join(output_dir, f"eval_{ts}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())

        # Also save a "latest" symlink-style copy
        latest_json = os.path.join(output_dir, "latest.json")
        with open(latest_json, "w", encoding="utf-8") as f:
            json.dump(self.to_json(), f, indent=2)

        latest_md = os.path.join(output_dir, "latest.md")
        with open(latest_md, "w", encoding="utf-8") as f:
            f.write(self.to_markdown())

        return json_path, md_path
