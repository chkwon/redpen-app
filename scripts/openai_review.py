#!/usr/bin/env python3
"""Fetch LaTeX files at a commit, ask OpenAI to review them, and post the result as a commit comment."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# API Configuration
API_URL = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions")
DEFAULT_MODEL = "gpt-5-mini"
DEFAULT_LANGUAGE = "en"
DEFAULT_MAX_CHARS = 20000
PROMPT_PATH = Path(os.getenv("REVIEW_PROMPT_PATH", "prompts/review_prompt.md"))
CONFIG_PATH = Path(os.getenv("REDPEN_CONFIG_PATH", "config.yml"))

# Language configuration
LANGUAGE_FLAGS = {
    "en": "🇺🇸",
    "ko": "🇰🇷",
    "zh": "🇨🇳",
    "ja": "🇯🇵",
    "vi": "🇻🇳",
}

LANGUAGE_NAMES = {
    "en": "English",
    "ko": "Korean",
    "zh": "Chinese",
    "ja": "Japanese",
    "vi": "Vietnamese",
}

LANGUAGE_INSTRUCTIONS = {
    "en": "Write all feedback, explanations, and suggestions in English.",
    "ko": "모든 피드백, 설명, 제안을 한국어로 작성하세요. Write all feedback, explanations, and suggestions in Korean.",
    "zh": "请用中文撰写所有反馈、解释和建议。Write all feedback, explanations, and suggestions in Chinese.",
    "ja": "すべてのフィードバック、説明、提案を日本語で記述してください。Write all feedback, explanations, and suggestions in Japanese.",
    "vi": "Viết tất cả phản hồi, giải thích và đề xuất bằng tiếng Việt. Write all feedback, explanations, and suggestions in Vietnamese.",
}


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_config() -> Dict[str, Any]:
    """Load configuration from config.yml if it exists."""
    config = {
        "model": DEFAULT_MODEL,
        "language": DEFAULT_LANGUAGE,
        "max_chars": DEFAULT_MAX_CHARS,
    }

    if CONFIG_PATH.exists():
        try:
            content = CONFIG_PATH.read_text(encoding="utf-8")
            # Simple YAML parsing for our flat config (no external dependency)
            for line in content.split("\n"):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()
                    # Remove quotes if present
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    # Convert numeric values
                    if key == "max_chars":
                        try:
                            value = int(value)
                        except ValueError:
                            pass
                    elif key == "temperature":
                        try:
                            value = float(value)
                        except ValueError:
                            pass
                    config[key] = value
        except Exception as e:
            print(f"Warning: Could not parse config.yml: {e}", file=sys.stderr)

    return config


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


def list_tex_files(repo: str, ref: str, token: str) -> List[str]:
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    data = gh_request(url, token)
    tree = data.get("tree", [])
    return [
        entry["path"]
        for entry in tree
        if entry.get("type") == "blob" and entry.get("path", "").lower().endswith(".tex")
    ]


def add_reaction(repo: str, comment_id: int, token: str, emoji: str) -> bool:
    """Add an emoji reaction to a comment."""
    url = f"https://api.github.com/repos/{repo}/comments/{comment_id}/reactions"
    try:
        gh_request(url, token, data={"content": emoji}, method="POST")
        return True
    except Exception:
        return False


def call_openai(api_key: str, system_prompt: str, file_path: str, file_text: str, model: str, language: str, temperature: Optional[float] = None) -> str:
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])

    user_prompt = (
        f"Review the LaTeX file `{file_path}` using the instructions.\n\n"
        f"**IMPORTANT**: {lang_instruction}\n\n"
        "Return valid JSON only. Use 1-based line numbers.\n\n"
        f"Content:\n{file_text}"
    )

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    # Add temperature if specified
    if temperature is not None:
        request_body["temperature"] = temperature
    elif os.getenv("OPENAI_TEMPERATURE"):
        request_body["temperature"] = float(os.getenv("OPENAI_TEMPERATURE"))

    body = json.dumps(request_body).encode("utf-8")

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


def format_review_as_markdown(file_path: str, review_json: str, file_content: str = "") -> str:
    """Convert JSON review output to readable markdown."""
    try:
        data = json.loads(review_json)
    except json.JSONDecodeError:
        return f"**{file_path}**\n\n```\n{review_json}\n```"

    # Build line lookup for quoting source
    source_lines = file_content.split("\n") if file_content else []

    lines = [f"### 📄 {file_path}"]

    summary = data.get("summary", "")
    if summary:
        lines.append(f"\n{summary}\n")

    comments = data.get("comments", [])
    if not comments:
        lines.append("\n✅ No issues found.\n")
        return "\n".join(lines)

    severity_icons = {
        "error": "🔴",
        "warning": "🟡",
        "suggestion": "💡",
    }

    for comment in comments:
        line_num = comment.get("line", "?")
        severity = comment.get("severity", "suggestion")
        icon = severity_icons.get(severity, "💡")
        category = comment.get("category", "")
        original = comment.get("original", "")
        issue = comment.get("issue", "")
        suggestion = comment.get("suggestion", "")
        explanation = comment.get("explanation", "")

        # Try to find the correct line using the original text if provided
        actual_line_num = line_num
        if original and source_lines and isinstance(line_num, int):
            # Search for the original text in source lines
            original_stripped = original.strip()
            for i, src_line in enumerate(source_lines):
                if original_stripped in src_line or src_line.strip() == original_stripped:
                    actual_line_num = i + 1
                    break

        lines.append(f"\n---\n\n{icon} **Line {actual_line_num}** · `{category}`")

        # Quote context around the problematic line (2 lines before, target line, 2 lines after)
        if isinstance(actual_line_num, int) and 1 <= actual_line_num <= len(source_lines):
            context_start = max(0, actual_line_num - 3)  # 2 lines before (0-indexed)
            context_end = min(len(source_lines), actual_line_num + 2)  # 2 lines after
            context_lines = []
            for i in range(context_start, context_end):
                line_number = i + 1
                line_text = source_lines[i].rstrip()
                prefix = "→" if line_number == actual_line_num else " "
                context_lines.append(f"{prefix} {line_number:4d} │ {line_text}")
            if context_lines:
                lines.append("\n```latex")
                lines.extend(context_lines)
                lines.append("```")

        if issue:
            lines.append(f"\n**Issue:** {issue}")
        if suggestion:
            lines.append(f"\n**Suggestion:** {suggestion}")
        if explanation:
            lines.append(f"\n> 💬 {explanation}")

    return "\n".join(lines)


def load_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise RuntimeError(f"Review prompt not found at {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def main() -> int:
    openai_key = require_env("OPENAI_API_KEY")
    github_token = require_env("GITHUB_TOKEN")
    repo = require_env("GITHUB_REPOSITORY")

    # Load configuration
    config = load_config()
    model = os.getenv("OPENAI_MODEL") or config.get("model", DEFAULT_MODEL)
    max_chars = int(os.getenv("MAX_REVIEW_CHARS", config.get("max_chars", DEFAULT_MAX_CHARS)))
    temperature = config.get("temperature")

    with open(require_env("GITHUB_EVENT_PATH"), "r", encoding="utf-8") as handle:
        event = json.load(handle)

    payload = event.get("client_payload") or {}
    commit_sha = payload.get("commit_sha") or os.getenv("GITHUB_SHA")
    if not commit_sha:
        raise RuntimeError("Missing commit SHA in dispatch payload")

    # Get language from payload (set by webhook) or config
    language = payload.get("language") or config.get("language", DEFAULT_LANGUAGE)
    if language not in LANGUAGE_FLAGS:
        language = DEFAULT_LANGUAGE

    # Get comment ID for adding rocket reaction on success
    trigger_comment_id = payload.get("comment_id")

    prompt_text = load_prompt()
    tex_paths = list_tex_files(repo, commit_sha, github_token)
    if not tex_paths:
        post_commit_comment(
            repo,
            commit_sha,
            github_token,
            "📭 No `.tex` files found to review at this commit.",
        )
        return 0

    results = []
    for path in tex_paths:
        file_text = fetch_file(repo, path, commit_sha, github_token)
        original_text = file_text  # Keep original for quoting
        if len(file_text) > max_chars:
            file_text = file_text[:max_chars]
        review_json = call_openai(openai_key, prompt_text, path, file_text, model, language, temperature)
        results.append((path, review_json, original_text))

    # Build the review comment
    flag = LANGUAGE_FLAGS.get(language, "🇺🇸")
    lang_name = LANGUAGE_NAMES.get(language, "English")

    header = f"## 🖊️ RedPen Review {flag}\n\n"
    header += f"Reviewed **{len(results)}** `.tex` file(s) at commit `{commit_sha[:7]}`\n"
    header += f"**Model:** `{model}` · **Language:** {lang_name}\n"

    parts = [header]
    for path, review_json, file_content in results:
        parts.append(format_review_as_markdown(path, review_json, file_content))

    comment_body = "\n---\n".join(parts)
    post_commit_comment(repo, commit_sha, github_token, comment_body)

    # Add rocket reaction to the original trigger comment to indicate success
    if trigger_comment_id:
        add_reaction(repo, trigger_comment_id, github_token, "rocket")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
