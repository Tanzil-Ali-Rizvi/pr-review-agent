"""The GitHub REST calls the Action needs: read a PR, read file contents at its head, post one review."""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx

KEY = re.compile(r"pr-review-agent:key=([0-9a-f]{12})")
SHA = re.compile(r"pr-review-agent:sha=([0-9a-f]+)")


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


class GitHub:
    def __init__(self, token: str, repo: str, api: str = "https://api.github.com", client: httpx.Client | None = None):
        self.repo = repo
        self.c = client or httpx.Client(
            base_url=api,
            timeout=30,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def _get(self, path: str, **params: Any) -> Any:
        r = self.c.get(path, params=params)
        if r.status_code >= 400:
            raise GitHubError(r.status_code, r.text[:300])
        return r.json()

    def _pages(self, path: str) -> list[dict]:
        out, page = [], 1
        while True:
            rows = self._get(path, per_page=100, page=page)
            out += rows
            if len(rows) < 100 or page >= 30:
                return out
            page += 1

    def pull(self, n: int) -> dict:
        return self._get(f"/repos/{self.repo}/pulls/{n}")

    def files(self, n: int) -> list[dict]:
        return self._pages(f"/repos/{self.repo}/pulls/{n}/files")

    def content(self, path: str, ref: str) -> str | None:
        try:
            data = self._get(f"/repos/{self.repo}/contents/{path}", ref=ref)
        except GitHubError as e:
            if e.status == 404:
                return None
            raise
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", "replace")
        return None

    def posted_keys(self, n: int) -> set[str]:
        """Findings already posted on this PR (by any earlier run), so a new push doesn't repeat them."""
        keys: set[str] = set()
        for c in self._pages(f"/repos/{self.repo}/pulls/{n}/comments"):
            keys.update(KEY.findall(c.get("body") or ""))
        return keys

    def reviewed_shas(self, n: int) -> set[str]:
        shas: set[str] = set()
        for r in self._pages(f"/repos/{self.repo}/pulls/{n}/reviews"):
            shas.update(SHA.findall(r.get("body") or ""))
        return shas

    def post_review(self, n: int, sha: str, body: str, comments: list[dict]) -> dict:
        """Always event=COMMENT: the agent never approves or blocks a PR by itself."""
        payload = {"commit_id": sha, "event": "COMMENT", "body": body, "comments": comments}
        r = self.c.post(f"/repos/{self.repo}/pulls/{n}/reviews", json=payload)
        if r.status_code == 422 and comments:
            # One comment on a line GitHub won't accept fails the whole review; fall back to the summary only,
            # with the comments listed in the body.
            extra = "\n\n".join(f"**`{c['path']}` line {c['line']}**\n\n{c['body']}" for c in comments)
            payload = {"commit_id": sha, "event": "COMMENT", "body": body + "\n\n---\n\n" + extra, "comments": []}
            r = self.c.post(f"/repos/{self.repo}/pulls/{n}/reviews", json=payload)
        if r.status_code >= 400:
            raise GitHubError(r.status_code, r.text[:300])
        return r.json()
