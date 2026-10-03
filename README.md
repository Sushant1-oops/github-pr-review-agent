# 🤖 AI PR Reviewer — Multi-Agent GitHub Code Review

Automatically reviews GitHub Pull Requests using 4 specialist AI agents running in parallel.

## Architecture

```
GitHub PR (webhook or manual URL)
        ↓
FastAPI server receives trigger
        ↓
LangGraph orchestrates 4 parallel agents:
  ├── 🔒 Security Agent     → vulnerabilities, secrets, injections
  ├── ⚡ Performance Agent  → O(n²), N+1 queries, memory leaks
  ├── ✨ Style Agent        → naming, complexity, dead code
  └── 🧪 Test Agent        → missing test cases & edge cases
        ↓
Aggregator Agent writes structured review
        ↓
Posts review comment to GitHub PR
        ↓
React dashboard shows live agent status via WebSocket
```

---

## ⚡ Quickstart (15 minutes)

### Step 1 — Get your API keys

**NVIDIA NIM (free):**
1. Go to https://build.nvidia.com
2. Create account → API Keys → Generate API Key
3. Copy the key (starts with `nvapi-`)

**GitHub Personal Access Token:**
1. GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
2. Click "Generate new token (classic)"
3. Select scopes: `repo` (full), `pull_requests`
4. Copy the token

---

### Step 2 — Clone & configure

```bash
git clone https://github.com/YOUR_USERNAME/ai-pr-reviewer
cd ai-pr-reviewer

# Copy env file
cp .env.example .env
```

Edit `.env`:
```
NVIDIA_API_KEY=nvapi_your_key_here
GITHUB_TOKEN=ghp_your_token_here
GITHUB_WEBHOOK_SECRET=any_random_string_123
```

---

### Step 3 — Backend setup

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Server runs at: http://localhost:8000
API docs at:    http://localhost:8000/docs

---

### Step 4 — Frontend setup

```bash
cd frontend
npm install
npm run dev
```

Dashboard runs at: http://localhost:5173

---

### Step 5 — Test it manually

1. Open http://localhost:5173
2. Paste any GitHub PR URL: `https://github.com/owner/repo/pull/42`
3. Click "Review PR"
4. Watch the 4 agents run live in the dashboard
5. Check the PR on GitHub — the review comment will be posted automatically

---

## Webhook Setup (auto-trigger on PR open)

To have reviews trigger automatically whenever a PR is opened:

1. **Expose your local server** (use ngrok for testing):
   ```bash
   ngrok http 8000
   # Copy the https URL e.g. https://abc123.ngrok.io
   ```

2. **Add webhook in GitHub:**
   - Go to your repo → Settings → Webhooks → Add webhook
   - Payload URL: `https://abc123.ngrok.io/webhook/github`
   - Content type: `application/json`
   - Secret: same value as `GITHUB_WEBHOOK_SECRET` in your `.env`
   - Events: select "Pull requests"
   - Click "Add webhook"

3. Open a PR → review triggers automatically!

---

## Project Structure

```
ai-pr-reviewer/
├── main.py                   # FastAPI app — webhook + manual API + WebSocket
├── config.py                 # Pydantic settings from .env
├── requirements.txt
├── .env.example
│
├── agents/
│   ├── base.py               # Base class — NVIDIA NIM client, JSON parsing, error recovery
│   ├── security.py           # Finds vulnerabilities, secrets, injections
│   ├── performance.py        # Finds O(n²), N+1, memory leaks
│   ├── style.py              # Naming, complexity, dead code
│   ├── test_coverage.py      # Missing test cases & edge cases
│   └── aggregator.py         # Synthesizes all findings → GitHub review
│
├── graph/
│   ├── state.py              # LangGraph ReviewState TypedDict
│   └── workflow.py           # LangGraph graph — parallel fan-out + aggregation
│
├── tools/
│   └── github_tools.py       # Fetch PR diff, post review, verify webhook signature
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx             # Full dashboard with live WebSocket updates
        └── index.css
```

---

## Resume Bullet Points

```
• Built a multi-agent GitHub PR review system using LangGraph, running Security,
  Performance, Style, and Test Coverage agents in parallel via ThreadPoolExecutor.

• Integrated GitHub Webhooks API to auto-trigger reviews on PR open/sync events;
  agents post structured review comments directly to GitHub via PyGitHub.

• Streamed live agent status updates to a React dashboard using FastAPI WebSockets,
  enabling real-time visibility into each agent's reasoning pipeline.

• Used NVIDIA NIM (Nemotron 3 Super 120B) for heavy analysis and Nemotron 3.5
  lightweight agents — optimising latency and free-tier API quota.
```

---

## How to Extend

| Feature | How |
|---|---|
| Add a new agent | Copy `agents/style.py`, write new system prompt, add node to `graph/workflow.py` |
| Use OpenAI instead | Change `_call_llm` in `base.py` to use `openai` client |
| Persist reviews | Replace `reviews_store` dict in `main.py` with PostgreSQL + SQLAlchemy |
| Deploy | `docker build -t ai-pr-reviewer . && docker run -p 8000:8000 ai-pr-reviewer` |
| Run on PRs automatically | Add the webhook URL to your GitHub org-level settings |

---

## Architecture v2 — Guardrails, LLM-as-judge, MCP

```
GitHub PR (webhook or manual URL, now requires X-API-Key on manual)
        ↓
FastAPI server (rate-limited, idempotent by head_sha)
        ↓
LangGraph orchestrates:
  ├── 🔒 Security · ⚡ Performance · ✨ Style · 🧪 Test   (parallel, structured-JSON output, schema-validated)
        ↓
  ├── 🧑‍⚖️ Judge Agent   → grounds every finding against the real diff, drops hallucinations,
  │                        flags prompt-injection attempts found in the PR content
        ↓
  └── Aggregator        → builds the review from JUDGED findings only, decides verdict
        ↓
Secrets redacted out of finding text → posted to GitHub PR
        ↓
React dashboard shows live per-agent status via WebSocket (each agent's OWN status,
not a shared top-level status — a posting failure no longer paints every agent red)
```

### Guardrails (`guardrails/`)
- **Prompt injection defense** — the PR diff is untrusted, attacker-controlled text.
  It's wrapped in explicit delimiters before reaching any LLM, and `sanitize.py`
  scans for classic injection phrasing ("ignore previous instructions", etc.) and
  surfaces it in the posted review rather than silently trusting it.
- **Secret redaction** — before any finding is posted publicly, `redact_secrets()`
  strips out matched secret patterns (API keys, tokens, private key blocks) so the
  Security agent's own review comment can't leak the secret it found.
- **Structured output validation** — every agent is forced through
  `guardrails/schemas.py`'s Pydantic models with a JSON-mode capability probe and a prompt-only fallback
  for models that don't support structured output server-side. Malformed output
  is a loud, logged failure now, not a silently-swallowed empty list.
- **Hard caps** — `MAX_FINDINGS_PER_AGENT`, field-length limits, and `MAX_DIFF_CHARS`
  bound cost and prevent a single runaway generation from producing an unbounded review.

### LLM-as-judge (`agents/judge.py`)
Runs after the four specialists, before the aggregator. One batched call reviews
every finding against the actual diff and drops anything not genuinely grounded in
it — catching hallucinations and successful injection attempts before they can
reach a real, public PR comment. Fails open (keeps findings, logs loudly) if the
judge call itself errors, rather than silently discarding a real review.

### Evals (`evals/`)
`evals/fixtures.py` has hand-written PR diffs with a deliberately unambiguous
planted issue each (SQL injection, hardcoded secret, N+1 query, missing test
coverage, a clean PR, and a prompt-injection attempt). `python -m evals.run_eval`
runs the real graph — real LLM calls — against each and reports pass/fail. This is
a starting harness, not a benchmark: add fixtures as you find real failure modes.

### MCP (`tools/mcp_server.py`) — built on FastMCP 2.0
The GitHub operations (`fetch_pr_diff`, `post_pr_review`, `get_pr_metadata`,
`parse_github_pr_url`) are also exposed as a standalone MCP server built with
[FastMCP 2.0](https://github.com/jlowin/fastmcp) (the `fastmcp` package — this
project does not use the lower-level `mcp` SDK directly anywhere), so any MCP
client (Claude Code, Claude Desktop, etc.) can call them directly without going
through this FastAPI app.

```bash
pip install fastmcp

# STDIO transport — for local MCP clients (Claude Code, Claude Desktop)
python -m tools.mcp_server

# HTTP transport — for remote clients
python -m tools.mcp_server --http --port 8765
```

### Auth & abuse prevention
`POST /api/review` now requires an `X-API-Key` header matching `API_KEY` in `.env`
and fails closed (503) if that's unset — previously anyone who could reach the
server could trigger reviews against arbitrary PRs on your GitHub token's quota.
Both trigger paths are rate-limited per-IP. `GITHUB_WEBHOOK_SECRET` no longer has
an insecure default — it's required.

### Tests
`pytest tests/` runs guardrail, URL-parsing, webhook-signature, and verdict-logic
tests with no API calls or network access required (see `tests/conftest.py`).

---

## Tech Stack

- **LangGraph** — agent state machine and graph orchestration
- **NVIDIA NIM** — free LLM inference (Nemotron 3 Super 120B + Nemotron 3.5 Lightning 30B)
- **FastAPI** — webhook receiver, REST API, WebSocket server
- **PyGitHub** — GitHub API client for fetching diffs and posting reviews
- **React + Vite** — live dashboard with WebSocket agent status streaming
- **Pydantic** — structured output validation for every agent (`guardrails/schemas.py`)
- **tenacity** — bounded retries on GitHub API calls (LLM retries are hand-rolled in `agents/base.py` to honor NIM's rate-limit hints)
- **slowapi** — per-IP rate limiting on trigger endpoints
- **FastMCP 2.0** (`fastmcp` package) — GitHub PR operations exposed as standalone MCP tools
- **pytest** — guardrail, parsing, and verdict-logic unit tests
