"""
LangGraph Workflow

  START → parallel_review (Security + Performance + Style + Test, fan-out)
        → judge             (LLM-as-judge grounding pass — drops hallucinated findings)
        → aggregate         (build final review + verdict from the JUDGED findings)
        → END

The judge sits strictly between the specialists and the aggregator: the
aggregator only ever sees findings the judge has already checked, so a
hallucinated or injected finding cannot reach the text that gets posted
to a real PR.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from langgraph.graph import StateGraph, END

from graph.state import ReviewState
from agents.security import SecurityAgent
from agents.performance import PerformanceAgent
from agents.style import StyleAgent
from agents.test_coverage import TestCoverageAgent
from agents.judge import JudgeAgent
from agents.aggregator import AggregatorAgent

logger = logging.getLogger("pr_reviewer.workflow")

_security = SecurityAgent()
_performance = PerformanceAgent()
_style = StyleAgent()
_test = TestCoverageAgent()
_judge = JudgeAgent()
_aggregator = AggregatorAgent()

AGENT_TIMEOUT_SECONDS = 150  # covers rate-limit backoff retries


def parallel_review_node(state: ReviewState) -> dict:
    """Fan-out: run all 4 specialist agents concurrently.

    Each agent's own status field is set independently here — a timeout
    or exception in ONE agent must never be conflated with the others.
    """
    def run_agent(agent, state):
        return agent.run(state)

    # One worker per specialist so all four run concurrently.
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            "security": executor.submit(run_agent, _security, state),
            "performance": executor.submit(run_agent, _performance, state),
            "style": executor.submit(run_agent, _style, state),
            "test": executor.submit(run_agent, _test, state),
        }
        results = {}
        errors = list(state.get("errors", []))
        for name, future in futures.items():
            try:
                agent_result = future.result(timeout=AGENT_TIMEOUT_SECONDS)
                agent_errors = agent_result.pop("errors", [])
                errors.extend(agent_errors)
                results.update(agent_result)
            except Exception as e:
                logger.error("%s agent failed/timed out: %s", name, e)
                results[f"{name}_status"] = "error"
                results[f"{name}_findings"] = []
                errors.append(f"{name} timed out or crashed: {e}")
        results["errors"] = errors
    return results


def judge_node(state: ReviewState) -> dict:
    return _judge.run(state)


def aggregate_node(state: ReviewState) -> dict:
    return _aggregator.run(state)


def build_graph():
    g = StateGraph(ReviewState)
    g.add_node("parallel_review", parallel_review_node)
    g.add_node("judge", judge_node)
    g.add_node("aggregate", aggregate_node)
    g.set_entry_point("parallel_review")
    g.add_edge("parallel_review", "judge")
    g.add_edge("judge", "aggregate")
    g.add_edge("aggregate", END)
    return g.compile()


review_graph = build_graph()


def run_review(state: ReviewState) -> ReviewState:
    return review_graph.invoke(state)
