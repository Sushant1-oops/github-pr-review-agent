"""
FastAPI Application
Endpoints:
  POST /webhook/github     — receives GitHub PR webhook events (HMAC-verified)
  POST /api/review         — manual review trigger, requires X-API-Key
  GET  /api/review/{id}    — get review result by id
  GET  /api/reviews        — list recent reviews
  WS   /ws/review/{id}     — WebSocket stream of agent status updates

Security notes vs the original version:
  - /api/review now requires a caller-supplied API key (settings.api_key).
    Previously anyone who could reach this server could trigger reviews
    against arbitrary PRs on your GitHub token's quota — a real cost /
    abuse vector, not a theoretical one.
  - Both trigger paths are rate-limited (per-IP) so a single caller can't
    exhaust your NVIDIA NIM/GitHub quota.
  - Webhook events are deduplicated by (repo, pr_number, head_sha) so a
    `synchronize` firing twice doesn't re-review and re-post every time.
  - Internal exception strings are logged, not echoed verbatim to callers.
"""

import json
import logging
import uuid
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import get_settings
from tools.github_tools import fetch_pr, format_diff_for_llm, post_review_comment, parse_pr_url, verify_webhook_signature
from graph.state import initial_state
from graph.workflow import run_review

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pr_reviewer.main")

settings = get_settings()
limiter = Limiter(key_func=get_remote_address)

# ── In-memory store (swap for Redis/Postgres in production — see README) ──
reviews_store: dict[str, dict] = {}
ws_connections: dict[str, list[WebSocket]] = {}
# Idempotency: (repo, pr_number, head_sha) -> review_id, so a duplicate
# webhook delivery for the same commit doesn't trigger a second review.
_dedupe_index: dict[tuple, str] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("AI PR Reviewer started")
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="AI PR Reviewer",
    description="Multi-agent GitHub PR code review — LangGraph + NVIDIA NIM, with guardrails and an LLM-as-judge grounding pass",
    version="2.0.0",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


# ── Auth dependency for manual trigger ───────────────────────────────

async def require_api_key(x_api_key: str = Header(default="")):
    if not settings.api_key:
        # No key configured — fail closed rather than silently allowing
        # open access, so a missing .env value can't accidentally expose
        # the endpoint in production.
        raise HTTPException(status_code=503, detail="Manual review endpoint is not configured")
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


# ── Pydantic Models ───────────────────────────────────────────────

class ManualReviewRequest(BaseModel):
    pr_url: str   # e.g. https://github.com/owner/repo/pull/42


class ReviewResponse(BaseModel):
    review_id: str
    status: str
    message: str


# ── Background review task ────────────────────────────────────────

def _serialize_findings(result: dict) -> tuple[dict, list]:
    finding_keys = [
        ("security_findings", "security_count"),
        ("performance_findings", "performance_count"),
        ("style_findings", "style_count"),
        ("test_findings", "test_count"),
    ]
    serialized, all_list = {}, []
    for fkey, ckey in finding_keys:
        raw = result.get(fkey, [])
        dicts = [f.to_dict() if hasattr(f, "to_dict") else f for f in raw]
        serialized[fkey] = dicts
        serialized[ckey] = len(dicts)
        all_list.extend(dicts)
    return serialized, all_list


async def run_review_task(review_id: str, repo: str, pr_number: int):
    """Run the full multi-agent review pipeline in background."""
    try:
        reviews_store[review_id]["status"] = "fetching"
        await broadcast_status(review_id, "fetching", "Fetching PR from GitHub...")

        ctx = fetch_pr(repo, pr_number)
        diff_txt = format_diff_for_llm(ctx)

        reviews_store[review_id].update({
            "status": "running",
            "pr_title": ctx.title,
            "pr_author": ctx.author,
            "files_count": len(ctx.files),
            "head_sha": ctx.head_sha,
        })
        await broadcast_status(review_id, "running", "Agents running in parallel...")

        state = initial_state(
            repo_full_name=repo,
            pr_number=pr_number,
            pr_title=ctx.title,
            pr_author=ctx.author,
            diff_text=diff_txt,
        )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, run_review, state)

        serialized_findings, all_findings_list = _serialize_findings(result)

        verdict = result["overall_verdict"]
        try:
            post_review_comment(
                repo_full_name=repo,
                pr_number=pr_number,
                review_body=result["final_review"],
                approve=(verdict == "approve" and len(all_findings_list) == 0),
            )
            posted = True
        except Exception as e:
            # A failure to POST the review must not be conflated with the
            # agents' own status — that is exactly the bug that made every
            # agent card show "error" together in the old UI. The agents
            # already finished; only posting failed.
            logger.error("Failed to post review to GitHub for %s#%s: %s", repo, pr_number, e)
            posted = False
            result.setdefault("errors", []).append(f"Failed to post review to GitHub: {e}")

        reviews_store[review_id].update({
            "status": "done",
            "posted": posted,
            "verdict": verdict,
            "final_review": result["final_review"],
            "findings_count": len(all_findings_list),
            **serialized_findings,
            "security_status": result.get("security_status", "done"),
            "performance_status": result.get("performance_status", "done"),
            "style_status": result.get("style_status", "done"),
            "test_status": result.get("test_status", "done"),
            "judge_status": result.get("judge_status", "done"),
            "judge_notes": result.get("judge_notes", []),
            "injection_flags": result.get("injection_flags", []),
            "errors": result.get("errors", []),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        await broadcast_status(review_id, "done", "Review complete!")

    except Exception as e:
        logger.exception("Review %s failed", review_id)
        reviews_store[review_id].update({
            "status": "error",
            "error": "Internal error while processing this review. See server logs.",
        })
        await broadcast_status(review_id, "error", "Internal error — see server logs")


async def broadcast_status(review_id: str, status: str, message: str):
    data = json.dumps({"status": status, "message": message, "review": reviews_store.get(review_id, {})})
    sockets = ws_connections.get(review_id, [])
    dead = []
    for ws in sockets:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        sockets.remove(ws)


def _queue_review(repo: str, pr_number: int, pr_url: str, trigger: str,
                   background_tasks: BackgroundTasks, head_sha: str = None) -> str:
    """Shared queueing logic with idempotency by (repo, pr_number, head_sha)."""
    dedupe_key = (repo, pr_number, head_sha)
    if head_sha and dedupe_key in _dedupe_index:
        existing_id = _dedupe_index[dedupe_key]
        if existing_id in reviews_store:
            logger.info("Duplicate review request for %s#%s@%s — reusing %s", repo, pr_number, head_sha, existing_id)
            return existing_id

    review_id = str(uuid.uuid4())[:8]
    reviews_store[review_id] = {
        "review_id": review_id,
        "repo": repo,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trigger": trigger,
    }
    if head_sha:
        _dedupe_index[dedupe_key] = review_id

    background_tasks.add_task(run_review_task, review_id, repo, pr_number)
    return review_id


# ── Routes ────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "AI PR Reviewer is running", "docs": "/docs"}


@app.get("/api/reviews")
async def list_reviews():
    sorted_reviews = sorted(reviews_store.values(), key=lambda r: r.get("created_at", ""), reverse=True)
    return {"reviews": sorted_reviews[:50]}


@app.get("/api/review/{review_id}")
async def get_review(review_id: str):
    review = reviews_store.get(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@app.post("/api/review", response_model=ReviewResponse, dependencies=[Depends(require_api_key)])
@limiter.limit("10/minute")
async def manual_review(request: Request, body: ManualReviewRequest, background_tasks: BackgroundTasks):
    """Manually trigger a review by pasting a GitHub PR URL. Requires X-API-Key."""
    try:
        repo, pr_number = parse_pr_url(body.pr_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    review_id = _queue_review(repo, pr_number, body.pr_url, trigger="manual", background_tasks=background_tasks)
    return ReviewResponse(review_id=review_id, status="queued", message=f"Review started for PR #{pr_number} in {repo}")


@app.post("/webhook/github")
@limiter.limit("30/minute")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    payload_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_webhook_signature(payload_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(payload_bytes)
    event = request.headers.get("X-GitHub-Event", "")

    if event != "pull_request":
        return {"message": f"Ignored event: {event}"}

    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return {"message": f"Ignored PR action: {action}"}

    pr = payload["pull_request"]
    repo = payload["repository"]["full_name"]
    pr_number = pr["number"]
    head_sha = pr.get("head", {}).get("sha")

    review_id = _queue_review(
        repo, pr_number, pr["html_url"],
        trigger=f"webhook:{action}", background_tasks=background_tasks, head_sha=head_sha,
    )
    return {"message": "Review queued", "review_id": review_id}


@app.websocket("/ws/review/{review_id}")
async def websocket_review(websocket: WebSocket, review_id: str):
    await websocket.accept()

    if review_id not in ws_connections:
        ws_connections[review_id] = []
    ws_connections[review_id].append(websocket)

    review = reviews_store.get(review_id, {})
    await websocket.send_text(json.dumps({"status": review.get("status", "unknown"), "message": "Connected", "review": review}))

    try:
        while True:
            await asyncio.sleep(30)
            try:
                await websocket.send_text(json.dumps({"type": "ping"}))
            except Exception:
                break
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if websocket in ws_connections.get(review_id, []):
            ws_connections[review_id].remove(websocket)
