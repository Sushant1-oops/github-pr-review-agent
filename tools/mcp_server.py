"""
MCP server for this project's GitHub PR operations — built on FastMCP 2.0
(https://github.com/jlowin/fastmcp), the standalone `fastmcp` package.
This project uses ONLY that library for MCP — not the lower-level
`mcp` SDK's bundled server helpers directly.

Install:
    pip install fastmcp

Run standalone (STDIO transport, for local MCP clients like Claude Code):
    python -m tools.mcp_server

Run as an HTTP server instead (for remote clients):
    python -m tools.mcp_server --http --port 8765

Tools exposed:
  - fetch_pr_diff(repo, pr_number)   -> formatted diff text
  - get_pr_metadata(repo, pr_number) -> title/author/branches/head_sha
  - post_pr_review(repo, pr_number, review_body, approve) -> confirmation
  - parse_github_pr_url(url)         -> {repo, pr_number}

Note: post_pr_review is a WRITE operation with real-world side effects
(it posts a public comment to a real PR). MCP clients should treat it
like any other side-effecting tool call and confirm with the user before
invoking it, same as this project's own guardrails require.
"""

import argparse
import os

from fastmcp import FastMCP

from tools.github_tools import fetch_pr, format_diff_for_llm, post_review_comment, parse_pr_url

mcp = FastMCP("github-pr-review-agent")


@mcp.tool()
def fetch_pr_diff(repo: str, pr_number: int) -> str:
    """Fetch a GitHub PR's full diff, formatted for review.

    Args:
        repo: "owner/repo" (e.g. "octocat/hello-world")
        pr_number: the pull request number
    """
    ctx = fetch_pr(repo, pr_number)
    return format_diff_for_llm(ctx)


@mcp.tool()
def get_pr_metadata(repo: str, pr_number: int) -> dict:
    """Get a GitHub PR's metadata without the full diff (title, author,
    branches, file count, head commit SHA — useful for idempotency
    checks before doing a full fetch)."""
    ctx = fetch_pr(repo, pr_number)
    return {
        "title": ctx.title,
        "author": ctx.author,
        "base_branch": ctx.base_branch,
        "head_branch": ctx.head_branch,
        "head_sha": ctx.head_sha,
        "files_changed": len(ctx.files),
        "additions": ctx.total_additions,
        "deletions": ctx.total_deletions,
    }


@mcp.tool()
def post_pr_review(repo: str, pr_number: int, review_body: str, approve: bool = False) -> str:
    """Post a review comment to a GitHub PR. This is a WRITE operation
    with a real, public side effect — confirm with the user before
    calling this.

    Args:
        repo: "owner/repo"
        pr_number: the pull request number
        review_body: markdown review text to post
        approve: if true, posts as an APPROVE event; otherwise COMMENT
    """
    return post_review_comment(repo, pr_number, review_body, approve=approve)


@mcp.tool()
def parse_github_pr_url(url: str) -> dict:
    """Parse a GitHub PR URL into its repo and PR number."""
    repo, pr_number = parse_pr_url(url)
    return {"repo": repo, "pr_number": pr_number}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="Serve over HTTP (SSE transport) instead of STDIO")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.http:
        # This exact fastmcp==2.0.0 build has no "http"/"streamable-http"
        # transport yet (only "stdio" and "sse"), and run() doesn't take
        # host/port kwargs — they're read off mcp.settings instead.
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="sse")
    else:
        mcp.run()  # STDIO — for local MCP clients like Claude Code / Claude Desktop