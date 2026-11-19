"""Entry point for the GitHub Action: review the pull request that triggered the workflow."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from .github import GitHub, GitHubError
from .llm import from_env
from .render import comment, summary
from .review import SEVERITY_RANK, review_diff


def _input(name: str, default: str = "") -> str:
    return os.getenv(f"INPUT_{name.upper().replace('-', '_')}", default).strip() or default


def _step_summary(text: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")


def main() -> int:
    event_path = os.getenv("GITHUB_EVENT_PATH", "")
    event = json.loads(Path(event_path).read_text()) if event_path and os.path.exists(event_path) else {}
    pr = event.get("pull_request")
    if not pr:
        print("Not a pull_request event; nothing to review.")
        return 0
    if pr.get("draft") and _input("skip-drafts", "true") == "true":
        print("Draft PR; skipping.")
        return 0
    gh = GitHub(_input("github-token") or os.environ["GITHUB_TOKEN"], os.environ["GITHUB_REPOSITORY"])
    n, sha = pr["number"], pr["head"]["sha"]

    if sha in gh.reviewed_shas(n):
        print(f"Commit {sha[:7]} was already reviewed.")
        return 0

    files = gh.files(n)
    patches = {f["filename"]: f.get("patch", "") for f in files if f.get("status") != "removed"}
    contents = {}
    for f in files:
        if f["filename"].endswith(".py") and f.get("status") != "removed":
            text = gh.content(f["filename"], sha)
            if text is not None:
                contents[f["filename"]] = text
    # GitHub's per-file patches have hunks but no file headers; add them so the diff parser can read them.
    diff_text = "".join(f"--- a/{p}\n+++ b/{p}\n{patch}\n" for p, patch in patches.items() if patch)

    llm = from_env()
    if llm is None:
        print("No LLM key available (on a pull request from a fork, secrets are not shared). Running linters only.")
    review = asyncio.run(
        review_diff(
            diff_text,
            contents,
            llm,
            title=pr.get("title", ""),
            body=pr.get("body") or "",
            verify=_input("verify", "true") == "true",
            max_total=int(_input("max-comments", "15")),
        )
    )
    already = gh.posted_keys(n)
    new = [f for f in review.findings if f.key not in already]
    model = "gpt-oss-120b via llm-gateway" if llm else "linters only (no LLM key)"
    body = summary(review, sha, model)
    _step_summary(body)
    comments = [{"path": f.path, "line": f.line, "side": "RIGHT", "body": comment(f)} for f in new]
    try:
        gh.post_review(n, sha, body, comments)
        print(f"Posted review: {len(new)} new comment(s), {len(review.findings) - len(new)} already on the PR.")
    except GitHubError as e:
        # Fork PRs get a read-only token; the review still appears in the job summary.
        print(f"Could not post the review ({e}). The findings are in the job summary.")

    fail_on = _input("fail-on", "none")
    if fail_on in SEVERITY_RANK and any(SEVERITY_RANK[f.severity] <= SEVERITY_RANK[fail_on] for f in review.findings):
        print(f"Failing the check: findings at or above '{fail_on}'.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
