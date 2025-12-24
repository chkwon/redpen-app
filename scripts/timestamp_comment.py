#!/usr/bin/env python3
"""Respond to commit comments asking for a redpen check with the current UTC time."""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict


def _load_event_payload(event_path: str) -> Dict[str, Any]:
    with open(event_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _post_comment(repo: str, sha: str, token: str, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/comments"
    data = json.dumps({"body": body}).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("Content-Type", "application/json")

    with urllib.request.urlopen(request) as response:  # noqa: S310 - GitHub API call
        if response.status >= 400:
            raise RuntimeError(f"GitHub API responded with status {response.status}")


def main() -> int:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    repo = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")
    trigger = os.getenv("TRIGGER_PHRASE", "@redpen check").lower()
    event_name = os.getenv("GITHUB_EVENT_NAME", "")

    if not all([event_path, repo, token]):
        print("Missing required GitHub Action environment variables", file=sys.stderr)
        return 1

    payload = _load_event_payload(event_path)
    client_payload: Dict[str, Any] = payload.get("client_payload") or {}

    if event_name == "repository_dispatch":
        comment_body = (client_payload.get("comment_body") or "").lower()
        comment_author = client_payload.get("comment_author", "")
        commit_sha = client_payload.get("commit_sha")
    else:
        comment = payload.get("comment") or {}
        comment_body = (comment.get("body") or "").lower()
        comment_author = (comment.get("user") or {}).get("login", "")
        commit_sha = (
            comment.get("commit_id")
            or (payload.get("pull_request") or {}).get("head", {}).get("sha")
            or payload.get("after")
            or os.getenv("GITHUB_SHA")
        )

    # Skip comments authored by the automation to avoid infinite loops.
    if comment_author == "github-actions[bot]":
        print("Skipping comment created by github-actions bot")
        return 0

    if trigger not in comment_body:
        print("No trigger phrase detected; exiting")
        return 0

    if not commit_sha:
        print("Unable to determine commit SHA for the comment", file=sys.stderr)
        return 1

    timestamp = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")
    response_body = (
        "👋 Thanks for the ping!\n\n"
        f"Current UTC date & time: **{timestamp}**."
    )

    try:
        _post_comment(repo=repo, sha=commit_sha, token=token, body=response_body)
    except urllib.error.HTTPError as exc:  # pragma: no cover - best-effort logging
        print(f"Failed to post comment: {exc.read().decode()}" , file=sys.stderr)
        raise

    print("Comment posted successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
