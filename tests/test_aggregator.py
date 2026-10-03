from agents.aggregator import AggregatorAgent
from graph.state import initial_state, AgentFinding


def _state_with_findings(*findings):
    state = initial_state("owner/repo", 1, "Test PR", "author", "diff")
    by_agent = {"security": [], "performance": [], "style": [], "test": []}
    for f in findings:
        by_agent[f.agent].append(f)
    state["security_findings"] = by_agent["security"]
    state["performance_findings"] = by_agent["performance"]
    state["style_findings"] = by_agent["style"]
    state["test_findings"] = by_agent["test"]
    return state


def _finding(agent="security", severity="suggestion", title="x"):
    return AgentFinding(agent=agent, severity=severity, file="f.py", line_hint="", title=title, detail="", suggestion="")


def test_no_findings_yields_approve():
    agg = AggregatorAgent()
    result = agg.run(_state_with_findings())
    assert result["overall_verdict"] == "approve"
    assert "No issues found" in result["final_review"]


def test_critical_finding_yields_request_changes():
    agg = AggregatorAgent()
    state = _state_with_findings(_finding(severity="critical"))
    result = agg.run(state)
    assert result["overall_verdict"] == "request_changes"


def test_only_warnings_yields_comment_not_request_changes():
    agg = AggregatorAgent()
    state = _state_with_findings(_finding(severity="warning"))
    result = agg.run(state)
    assert result["overall_verdict"] == "comment"


def test_only_suggestions_yields_comment_not_approve():
    agg = AggregatorAgent()
    state = _state_with_findings(_finding(severity="suggestion"))
    result = agg.run(state)
    assert result["overall_verdict"] == "comment"


def test_critical_beats_warning_in_verdict():
    agg = AggregatorAgent()
    state = _state_with_findings(
        _finding(severity="warning"),
        _finding(agent="performance", severity="critical"),
    )
    result = agg.run(state)
    assert result["overall_verdict"] == "request_changes"


def test_injection_flags_surfaced_in_clean_review():
    agg = AggregatorAgent()
    state = _state_with_findings()
    state["injection_flags"] = ["ignore all previous instructions"]
    result = agg.run(state)
    assert "prompt-injection" in result["final_review"].lower() or "guardrail" in result["final_review"].lower()


def test_failed_agent_does_not_yield_approve():
    state = _state_with_findings()
    state["security_status"] = "error"
    result = AggregatorAgent().run(state)
    assert result["overall_verdict"] == "comment"
    assert "Incomplete review" in result["final_review"]
