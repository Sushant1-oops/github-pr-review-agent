"""
GitHub integration tools.
- Fetch PR metadata + full diff
- Post structured review comment
- Parse diff into per-file chunks

For a reusable, client-agnostic version of these same operations exposed
as MCP tools (so any MCP client — Claude Desktop, Claude Code, this app,
or something else entirely — can call them), see tools/mcp_server.py.
This module is what main.py calls directly today; mcp_server.py wraps
the same underlying logic behind the MCP protocol.
"""

import re
import hmac
import hashlib
import logging
from typing import Optional
from dataclasses import dataclass, field

from github import Github, GithubException, Auth
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import get_settings

settings = get_settings()
gh = Github(auth=Auth.Token(settings.github_token), timeout=30)
logger = logging.getLogger("pr_reviewer.github")


# ── Data Models ──────────────────────────────────────────────────────

@dataclass
class FileDiff:
    filename: str
    status: str          # added | modified | removed
    additions: int
    deletions: int
    patch: str           # the actual diff text
    language: str = ""   # detected from extension


@dataclass
class PRContext:
    repo_full_name: str
    pr_number: int
    title: str
    description: str
    author: str
    base_branch: str
    head_branch: str
    head_sha: str = ""
    files: list[FileDiff] = field(default_factory=list)
    total_additions: int = 0
    total_deletions: int = 0


# ── Language Detection ───────────────────────────────────────────────

EXTENSION_MAP = {
    ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
    ".jsx": "JavaScript/React", ".tsx": "TypeScript/React",
    ".java": "Java", ".go": "Go", ".rs": "Rust", ".cpp": "C++",
    ".c": "C", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
    ".swift": "Swift", ".kt": "Kotlin", ".sh": "Shell",
    ".sql": "SQL", ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON", ".md": "Markdown", ".html": "HTML", ".css": "CSS",
}


def detect_language(filename: str) -> str:
    for ext, lang in EXTENSION_MAP.items():
        if filename.endswith(ext):
            return lang
    return "Unknown"


class _RetryableGithubError(Exception):
    pass


def _is_retryable(exc: GithubException) -> bool:
    return exc.status in (403, 429, 500, 502, 503, 504)


# ── Fetch PR ─────────────────────────────────────────────────────────

@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    retry=retry_if_exception_type(_RetryableGithubError),
)
def fetch_pr(repo_full_name: str, pr_number: int) -> PRContext:
    """Fetch a PR and return structured context with all file diffs."""
    try:
        repo = gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)

        ctx = PRContext(
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            title=pr.title,
            description=pr.body or "",
            author=pr.user.login,
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            head_sha=pr.head.sha,
        )

        files = pr.get_files()
        for f in files:
            if f.patch is None:
                continue
            if len(f.patch) > 15000:
                patch = f.patch[:15000] + "\n... [truncated — file too large]"
            else:
                patch = f.patch

            ctx.files.append(FileDiff(
                filename=f.filename,
                status=f.status,
                additions=f.additions,
                deletions=f.deletions,
                patch=patch,
                language=detect_language(f.filename),
            ))
            ctx.total_additions += f.additions
            ctx.total_deletions += f.deletions

        return ctx

    except GithubException as e:
        if _is_retryable(e):
            raise _RetryableGithubError(str(e)) from e
        raise ValueError(f"GitHub API error: {e.status} — {e.data.get('message', str(e))}")


# ── Format Diff for LLM ──────────────────────────────────────────────

def format_diff_for_llm(ctx: PRContext, max_chars: int = None) -> str:
    """Format PR context into a clean string for LLM consumption."""
    max_chars = max_chars or settings.max_diff_chars
    lines = [
        f"PR #{ctx.pr_number}: {ctx.title}",
        f"Author: {ctx.author}",
        f"Branch: {ctx.head_branch} -> {ctx.base_branch}",
        f"Description: {ctx.description or 'None'}",
        f"Changes: +{ctx.total_additions} -{ctx.total_deletions}",
        "",
        "=== CHANGED FILES ===",
    ]

    char_count = sum(len(l) for l in lines)

    for f in ctx.files:
        file_header = f"\n--- {f.filename} ({f.language}, {f.status}) ---\n"
        if char_count + len(file_header) + len(f.patch) > max_chars:
            lines.append(f"\n[{f.filename} omitted — token budget reached]")
            break
        lines.append(file_header)
        lines.append(f.patch)
        char_count += len(file_header) + len(f.patch)

    return "\n".join(lines)


# ── Post Review Comment ──────────────────────────────────────────────

@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=6),
    retry=retry_if_exception_type(_RetryableGithubError),
)
def post_review_comment(repo_full_name: str, pr_number: int, review_body: str, approve: bool = False) -> str:
    """Post the final aggregated review to the GitHub PR."""
    try:
        repo = gh.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)
        event = "APPROVE" if approve else "COMMENT"
        review = pr.create_review(body=review_body, event=event)
        return f"Posted review #{review.id} to PR #{pr_number}"
    except GithubException as e:
        if _is_retryable(e):
            raise _RetryableGithubError(str(e)) from e
        # A common real-world case: GitHub rejects self-approval. Fall
        # back to a plain COMMENT rather than losing the review entirely.
        if approve and e.status == 422:
            logger.warning("APPROVE rejected (likely self-review), falling back to COMMENT: %s", e)
            repo = gh.get_repo(repo_full_name)
            pr = repo.get_pull(pr_number)
            review = pr.create_review(body=review_body, event="COMMENT")
            return f"Posted review #{review.id} to PR #{pr_number} (fell back to COMMENT)"
        raise ValueError(f"Failed to post review: {e.status} — {e.data.get('message', str(e))}")


# ── Webhook Signature Verification ───────────────────────────────────

def verify_webhook_signature(payload_bytes: bytes, signature_header: Optional[str]) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature.

    Calls get_settings() at invocation time (not module-level) so the
    secret can be overridden in tests via monkeypatch + cache_clear().
    """
    if not signature_header or not signature_header.startswith("sha256="):
        return False

    current_settings = get_settings()
    expected = hmac.new(current_settings.github_webhook_secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    received = signature_header[len("sha256="):]
    return hmac.compare_digest(expected, received)


# ── Parse PR URL ──────────────────────────────────────────────────────

# Owner/repo names on GitHub are alphanumeric plus - . _ ; anchoring this
# tightly (vs. the old open-ended [^/]+) avoids passing unexpected
# characters through to the GitHub API client.
_PR_URL_RE = re.compile(
    r"^https?://github\.com/([A-Za-z0-9][A-Za-z0-9\-._]*)/([A-Za-z0-9][A-Za-z0-9\-._]*)/pull/(\d+)/?$"
)


def parse_pr_url(url: str) -> tuple[str, int]:
    """Parse a GitHub PR URL into (repo_full_name, pr_number).
    Handles: https://github.com/owner/repo/pull/123
    """
    match = _PR_URL_RE.match(url.strip())
    if not match:
        raise ValueError(f"Invalid GitHub PR URL: {url}")
    owner, repo, number = match.groups()
    return f"{owner}/{repo}", int(number)
