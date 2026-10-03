"""
Runs the actual LangGraph pipeline (real LLM calls — needs NVIDIA_API_KEY)
against evals/fixtures.py and reports detailed numerical metrics.

    python -m evals.run_eval

This is NOT a mock — it exercises the same graph, same agents, same
judge, same schema validation that production runs. It costs real API
calls; keep the fixture set small and deliberate rather than large.

Pass/fail criteria per case:
  1. The expected agent produced at least one finding whose title/detail
     contains one of expect_keywords (case-insensitive substring), OR
     the case expects no findings and none were produced.
  2. The overall verdict did not equal expect_verdict_not, if set.
  3. For the prompt-injection fixture: the injection is detected AND
     does not suppress the real finding.

Metrics collected:
  - Per-case: pass/fail, keyword match, verdict check, latency, finding counts
  - Aggregate: precision, recall, F1, per-agent accuracy, verdict accuracy,
    latency stats, guardrail effectiveness, judge effectiveness
"""

import sys
import time
import logging

from evals.fixtures import CASES
from evals.eval_report import CaseResult, EvalReport
from graph.state import initial_state
from graph.workflow import run_review

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("evals")


def run_case(case) -> CaseResult:
    """Run a single eval case through the full pipeline and collect metrics."""
    result_obj = CaseResult(
        name=case.name,
        passed=False,
        detail="",
        expect_agent=case.expect_agent,
        expect_keywords=case.expect_keywords,
        expect_severity=getattr(case, "expect_severity", None),
        injection_expected=(case.name == "prompt_injection_attempt"),
    )

    t0 = time.time()

    try:
        state = initial_state(
            repo_full_name="eval/fixture",
            pr_number=0,
            pr_title=f"[eval] {case.name}",
            pr_author="eval-harness",
            diff_text=case.diff_text,
        )
        result = run_review(state)
    except Exception as e:
        result_obj.latency_seconds = time.time() - t0
        result_obj.detail = f"exception: {e}"
        result_obj.errors = [str(e)]
        return result_obj

    result_obj.latency_seconds = time.time() - t0

    # ── Collect raw counts ────────────────────────────────────────────
    sec_findings = result.get("security_findings", [])
    perf_findings = result.get("performance_findings", [])
    style_findings = result.get("style_findings", [])
    test_findings = result.get("test_findings", [])

    result_obj.security_count = len(sec_findings)
    result_obj.performance_count = len(perf_findings)
    result_obj.style_count = len(style_findings)
    result_obj.test_count = len(test_findings)

    all_findings = sec_findings + perf_findings + style_findings + test_findings
    result_obj.actual_findings_count = len(all_findings)
    result_obj.actual_verdict = result.get("overall_verdict", "unknown")

    # Judge stats
    judge_notes = result.get("judge_notes", [])
    result_obj.judge_removed_count = len(judge_notes)
    # Pre-judge count = post-judge findings + removed findings
    result_obj.total_pre_judge_count = len(all_findings) + len(judge_notes)

    # Injection detection
    injection_flags = result.get("injection_flags", [])
    result_obj.injection_detected = len(injection_flags) > 0

    # Errors from pipeline
    result_obj.errors = result.get("errors", [])

    # ── Evaluate: keyword matching ────────────────────────────────────
    findings_key = f"{case.expect_agent}_findings" if case.expect_agent != "none" else None

    if case.expect_agent == "none":
        # Clean PR: no findings expected
        if all_findings:
            result_obj.detail = f"expected no findings, got {len(all_findings)}: {[f.title for f in all_findings]}"
            result_obj.keyword_matched = False
        else:
            result_obj.keyword_matched = True  # correctly empty
            result_obj.detail = "correctly produced no findings"
    else:
        relevant = result.get(findings_key, [])
        result_obj.actual_agent_findings_count = len(relevant)

        matched = any(
            any(kw.lower() in (f.title + " " + f.detail).lower() for kw in case.expect_keywords)
            for f in relevant
        )
        result_obj.keyword_matched = matched

        if not matched:
            result_obj.detail = (
                f"no {case.expect_agent} finding matched keywords {case.expect_keywords}; "
                f"got: {[f.title for f in relevant]}"
            )
        else:
            result_obj.detail = "ok"

    # ── Evaluate: verdict check ───────────────────────────────────────
    if case.expect_verdict_not and result.get("overall_verdict") == case.expect_verdict_not:
        result_obj.verdict_correct = False
        result_obj.detail += f" | verdict was '{case.expect_verdict_not}' which should have been avoided"
    else:
        result_obj.verdict_correct = True

    # ── Evaluate: severity check ──────────────────────────────────────
    if hasattr(case, 'expect_severity') and case.expect_severity and case.expect_agent != "none":
        relevant = result.get(findings_key, [])
        result_obj.actual_severity_matched = any(
            f.severity == case.expect_severity for f in relevant
        )

    # ── Evaluate: injection-specific check ────────────────────────────
    if case.name == "prompt_injection_attempt":
        if not injection_flags:
            result_obj.detail += " | injection was not detected/flagged by guardrails"

    # ── Final pass/fail ───────────────────────────────────────────────
    passed = True
    if case.expect_agent == "none":
        if all_findings:
            passed = False
    else:
        if not result_obj.keyword_matched:
            passed = False
    if not result_obj.verdict_correct:
        passed = False
    if case.name == "prompt_injection_attempt" and not result_obj.injection_detected:
        passed = False

    result_obj.passed = passed
    if passed and result_obj.detail == "":
        result_obj.detail = "ok"

    return result_obj


def _safe_print(*args, **kwargs):
    """Print that handles Windows cp1252 encoding gracefully."""
    import io
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        text = " ".join(str(a) for a in args)
        # Replace problematic Unicode chars with ASCII equivalents
        safe = text.encode("ascii", errors="replace").decode("ascii")
        print(safe, **{k: v for k, v in kwargs.items() if k != "end"})


def main():
    # Force UTF-8 for Windows console
    import sys as _sys
    if _sys.platform == "win32":
        import io
        _sys.stdout = io.TextIOWrapper(_sys.stdout.buffer, encoding="utf-8", errors="replace")
        _sys.stderr = io.TextIOWrapper(_sys.stderr.buffer, encoding="utf-8", errors="replace")

    print("=" * 70)
    print("  PR Review Agent -- End-to-End Evaluation Suite")
    print("  Real LLM calls to NVIDIA NIM API")
    print(f"  {len(CASES)} test cases")
    print("=" * 70)
    print()

    results = []
    for i, case in enumerate(CASES, 1):
        print(f"[{i}/{len(CASES)}] Running: {case.name} ... ", end="", flush=True)

        case_result = run_case(case)
        results.append(case_result)

        status = "PASS" if case_result.passed else "FAIL"
        print(f"{status} ({case_result.latency_seconds:.1f}s) -- {case_result.detail}")
        time.sleep(1.5)

    # ── Generate report ───────────────────────────────────────────────
    print()
    print("=" * 70)
    print("  Generating evaluation report...")
    print("=" * 70)

    report = EvalReport(results)

    # Save to evals/results/
    json_path, md_path = report.save("evals/results")
    print(f"  JSON report: {json_path}")
    print(f"  Markdown report: {md_path}")

    # Print summary to console
    print()
    print("=" * 70)
    print("  EVALUATION SUMMARY")
    print("=" * 70)
    print(f"  Pass Rate:       {report.passed_count}/{report.total_cases} ({report.pass_rate:.1%})")
    print(f"  Precision:       {report.precision:.1%}")
    print(f"  Recall:          {report.recall:.1%}")
    print(f"  F1 Score:        {report.f1_score:.1%}")
    print(f"  FP Rate:         {report.false_positive_rate:.1%}")
    print(f"  Verdict Acc:     {report.verdict_accuracy:.1%}")
    print(f"  Severity Acc:    {report.severity_accuracy:.1%}")
    print(f"  Mean Latency:    {report.latency_mean:.1f}s")
    print(f"  Injection Det:   {report.injection_detection_rate:.0%}")
    print(f"  Judge Removal:   {report.judge_removal_rate:.1%}")
    print()

    print("  Per-Agent Recall:")
    for name, am in report.agent_metrics.items():
        print(f"    {name:12s}: {am.detected}/{am.total_cases} ({am.recall:.0%})")
    print()
    print("=" * 70)

    sys.exit(0 if report.failed_count == 0 else 1)


if __name__ == "__main__":
    main()

