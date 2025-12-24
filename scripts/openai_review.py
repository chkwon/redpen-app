#!/usr/bin/env python3
"""Fetch a LaTeX file at a commit, ask OpenAI to review it, and post the JSON result as a commit comment."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict


API_URL = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def gh_request(url: str, token: str, data: Dict[str, Any] | None = None, method: str = "GET") -> Any:
    payload = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    if data is not None:
        payload = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=payload, method=method, headers=headers)
    with urllib.request.urlopen(request) as response:  # noqa: S310 - GitHub API call
        body = response.read().decode("utf-8")
        if response.status >= 400:
            raise RuntimeError(f"GitHub API error {response.status}: {body}")
        return json.loads(body) if body else None


def fetch_file(repo: str, path: str, ref: str, token: str) -> str:
    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    data = gh_request(url, token)
    if data.get("encoding") != "base64" or "content" not in data:
        raise RuntimeError(f"Unexpected content encoding for {path}")
    decoded = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return decoded


def call_openai(api_key: str, file_path: str, file_text: str) -> str:
    system_prompt = """
You are an expert academic writing reviewer. Your task is to review LaTeX manuscripts and provide constructive feedback.

Priority 1: Grammar and Spelling
This is your PRIMARY focus. Check for spelling, subject-verb agreement, articles, run-ons, dangling modifiers, fragments, wrong prepositions.

Priority 2: LaTeX Best Practices
- No `\\\\` for new paragraphs; use blank lines.
- No empty line before equations or before "where" clauses.
- No `\\\\` after the last line of multi-line equations.
- Use proper quotes: ``text''.
- Emphasis: \\emph{} not \\textit{}.
- Dashes: -- for ranges, --- for breaks.
- Use \\ref/\\eqref, non-breaking spaces before refs/cites.
- Citations: \\citet vs \\citep; non-breaking space before parenthetical.
- Math: avoid bare words as variables.
- Tables: captions above, booktabs, left-align text, right-align numbers, avoid [h]/[H].
- Figures: captions below, avoid [h]/[H].

Priority 3: Academic Style
- Flag informal or vague language.
- Avoid weak hedging.
- Define acronyms before use; space before parentheses for acronyms.
- Avoid starting sentences with symbols/numbers.

Priority 4: Repository Hygiene
- If .gitignore missing LaTeX ignores, suggest TeX.gitignore.
- If PDFs are tracked, tell user to delete and gitignore them.

Output JSON only:
{
  "summary": "...",
  "comments": [
    {
      "line": 42,
      "severity": "error|warning|suggestion",
      "category": "grammar|spelling|latex|style",
      "issue": "...",
      "suggestion": "...",
      "explanation": "..."
    }
  ]
}
Limit to the 5-7 most important issues.
"""

    user_prompt = (
        f"Review the LaTeX file `{file_path}` using the instructions. "
        "Return valid JSON only. Use 1-based line numbers.\n\n"
        f"Content:\n{file_text}"
    )

    body = json.dumps(
        {
          "model": MODEL,
          "messages": [
              {"role": "system", "content": system_prompt.strip()},
              {"role": "user", "content": user_prompt},
          ],
          "temperature": 0.2,
          "response_format": {"type": "json_object"},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:  # noqa: S310
            result = response.read().decode("utf-8")
            parsed = json.loads(result)
            return parsed["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as exc:  # pragma: no cover - best-effort logging
        detail = exc.read().decode()
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail}") from exc


def post_commit_comment(repo: str, sha: str, token: str, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/commits/{sha}/comments"
    gh_request(url, token, data={"body": body}, method="POST")


def main() -> int:
    openai_key = require_env("OPENAI_API_KEY")
    github_token = require_env("GITHUB_TOKEN")
    repo = require_env("GITHUB_REPOSITORY")

    with open(require_env("GITHUB_EVENT_PATH"), "r", encoding="utf-8") as handle:
        event = json.load(handle)

    payload = event.get("client_payload") or {}
    commit_sha = payload.get("commit_sha") or os.getenv("GITHUB_SHA")
    target_file = (
        payload.get("target_file")
        or os.getenv("TARGET_FILE")
        or "main.tex"
    )
    if not commit_sha:
        raise RuntimeError("Missing commit SHA in dispatch payload")

    file_text = fetch_file(repo, target_file, commit_sha, github_token)
    # Clip very long files to keep request size manageable.
    max_chars = int(os.getenv("MAX_REVIEW_CHARS", "20000"))
    if len(file_text) > max_chars:
        file_text = file_text[:max_chars]

    review_json = call_openai(openai_key, target_file, file_text)
    comment_body = f"OpenAI review for `{target_file}`:\n\n```json\n{review_json}\n```"
    post_commit_comment(repo, commit_sha, github_token, comment_body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
