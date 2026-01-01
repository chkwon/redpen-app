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


def fetch_gitignore(repo: str, ref: str, token: str) -> Optional[str]:
    """Fetch .gitignore content from the repository if it exists."""
    try:
        return fetch_file(repo, ".gitignore", ref, token)
    except Exception:
        return None


def list_tracked_pdf_files(repo: str, ref: str, token: str) -> List[str]:
    """List all PDF files tracked in the repository."""
    url = f"https://api.github.com/repos/{repo}/git/trees/{ref}?recursive=1"
    data = gh_request(url, token)
    tree = data.get("tree", [])
    return [
        entry["path"]
        for entry in tree
        if entry.get("type") == "blob" and entry.get("path", "").lower().endswith(".pdf")
    ]


def check_gitignore_for_latex(gitignore_content: Optional[str]) -> Dict[str, Any]:
    """Check if .gitignore exists and contains proper LaTeX patterns.

    Returns a dict with:
    - exists: bool - whether .gitignore exists
    - has_pdf: bool - whether *.pdf or similar is ignored
    - has_aux: bool - whether common LaTeX auxiliary files are ignored
    - has_latex_patterns: bool - whether it has general LaTeX patterns
    - missing_patterns: list - suggested patterns that are missing
    """
    result = {
        "exists": gitignore_content is not None,
        "has_pdf": False,
        "has_aux": False,
        "has_latex_patterns": False,
        "missing_patterns": [],
    }

    if not gitignore_content:
        result["missing_patterns"] = ["*.pdf", "*.aux", "*.log", "*.out", "*.bbl", "*.blg", "*.synctex.gz"]
        return result

    lines = [line.strip().lower() for line in gitignore_content.split("\n") if line.strip() and not line.strip().startswith("#")]

    # Check for PDF patterns
    pdf_patterns = ["*.pdf", "**/*.pdf", ".pdf", "pdf"]
    result["has_pdf"] = any(p in lines or any(p in line for line in lines) for p in pdf_patterns)

    # Check for common LaTeX auxiliary file patterns
    aux_patterns = ["*.aux", "*.log", "*.out", "*.toc", "*.lof", "*.lot"]
    found_aux = sum(1 for p in aux_patterns if any(p in line for line in lines))
    result["has_aux"] = found_aux >= 2  # At least 2 auxiliary patterns

    # Check for general LaTeX patterns (might use .gitignore templates)
    latex_keywords = ["latex", "tex", "*.bbl", "*.blg", "*.synctex", "*.fls", "*.fdb_latexmk"]
    result["has_latex_patterns"] = any(any(kw in line for kw in latex_keywords) for line in lines) or result["has_aux"]

    # Suggest missing important patterns
    important_patterns = {
        "*.pdf": ["*.pdf", "**/*.pdf"],
        "*.aux": ["*.aux"],
        "*.log": ["*.log"],
        "*.out": ["*.out"],
        "*.bbl": ["*.bbl"],
        "*.blg": ["*.blg"],
        "*.synctex.gz": ["*.synctex.gz", "*.synctex"],
    }

    for pattern_name, variants in important_patterns.items():
        if not any(any(v in line for v in variants) for line in lines):
            result["missing_patterns"].append(pattern_name)

    return result


def format_gitignore_review(gitignore_check: Dict[str, Any], tracked_pdfs: List[str] = None) -> str:
    """Format the .gitignore check results as a markdown section."""
    if tracked_pdfs is None:
        tracked_pdfs = []

    lines = ["### 📋 Repository Hygiene: `.gitignore` Check\n"]

    if not gitignore_check["exists"]:
        lines.append("⚠️ **No `.gitignore` file found!**\n")
        lines.append("LaTeX projects generate many auxiliary files that should not be tracked in git.\n")
        lines.append("\n**Recommended:** Create a `.gitignore` file with these patterns:\n")
        lines.append("```")
        lines.append("# LaTeX auxiliary files")
        lines.append("*.aux")
        lines.append("*.log")
        lines.append("*.out")
        lines.append("*.toc")
        lines.append("*.lof")
        lines.append("*.lot")
        lines.append("*.bbl")
        lines.append("*.blg")
        lines.append("*.synctex.gz")
        lines.append("")
        lines.append("# Output files")
        lines.append("*.pdf")
        lines.append("```")
    else:
        issues = []

        if not gitignore_check["has_pdf"]:
            issues.append("- ⚠️ **PDF files are not ignored.** Add `*.pdf` to prevent tracking compiled output.")

        if not gitignore_check["has_latex_patterns"]:
            issues.append("- ⚠️ **LaTeX auxiliary files may not be properly ignored.** Consider adding patterns for `.aux`, `.log`, `.out`, `.bbl`, `.blg`, `.synctex.gz` files.")

        if issues:
            lines.append("The `.gitignore` file exists but may be missing some important patterns:\n")
            lines.extend(issues)
            if gitignore_check["missing_patterns"]:
                lines.append("\n**Suggested additions:**")
                lines.append("```")
                for pattern in gitignore_check["missing_patterns"]:
                    lines.append(pattern)
                lines.append("```")
        else:
            lines.append("✅ `.gitignore` file exists and includes proper LaTeX patterns.\n")

    # Check for tracked PDF files
    if tracked_pdfs:
        lines.append("\n---\n")
        lines.append("⚠️ **PDF files are tracked in this repository!**\n")
        lines.append("Compiled PDF output files should typically not be tracked in git. Found:\n")
        for pdf in tracked_pdfs[:10]:  # Limit to first 10
            lines.append(f"- `{pdf}`")
        if len(tracked_pdfs) > 10:
            lines.append(f"- ... and {len(tracked_pdfs) - 10} more")

        lines.append("\n**To remove tracked PDF files and update `.gitignore`:**\n")
        lines.append("```bash")
        lines.append("# 1. Add *.pdf to .gitignore (if not already present)")
        lines.append("echo '*.pdf' >> .gitignore")
        lines.append("")
        lines.append("# 2. Remove PDF files from git tracking (keeps local files)")
        for pdf in tracked_pdfs[:5]:
            lines.append(f"git rm --cached \"{pdf}\"")
        if len(tracked_pdfs) > 5:
            lines.append("# ... repeat for other PDF files, or use:")
            lines.append("git rm --cached \"*.pdf\"")
        lines.append("")
        lines.append("# 3. Commit the changes")
        lines.append("git add .gitignore")
        lines.append("git commit -m \"Remove tracked PDF files and update .gitignore\"")
        lines.append("```")
        lines.append("\n> **Note:** `git rm --cached` removes files from git tracking but keeps them in your local directory.")

    return "\n".join(lines)


def fetch_commit_diff(repo: str, sha: str, token: str) -> Dict[str, List[tuple[int, int]]]:
    """Fetch the diff for a commit and return changed line ranges per file.

    Returns dict mapping file paths to list of (start_line, end_line) tuples for changed regions.
    """
    url = f"https://api.github.com/repos/{repo}/commits/{sha}"
    data = gh_request(url, token)

    changed_files: Dict[str, List[tuple[int, int]]] = {}

    for file_info in data.get("files", []):
        filename = file_info.get("filename", "")
        if not filename.lower().endswith(".tex"):
            continue

        # Parse the patch to extract changed line numbers
        patch = file_info.get("patch", "")
        if not patch:
            # File was added/deleted without patch info - mark entire file
            changed_files[filename] = [(1, 999999)]
            continue

        line_ranges = parse_diff_hunks(patch)
        if line_ranges:
            changed_files[filename] = line_ranges

    return changed_files


def fetch_multi_commit_diff(repo: str, sha: str, num_commits: int, token: str) -> Dict[str, List[tuple[int, int]]]:
    """Fetch the combined diff across multiple commits.

    Returns dict mapping file paths to list of (start_line, end_line) tuples for changed regions.
    """
    # First, get the list of commits to analyze
    url = f"https://api.github.com/repos/{repo}/commits?sha={sha}&per_page={num_commits}"
    commits = gh_request(url, token)

    if not commits or len(commits) == 0:
        return {}

    # Get the oldest commit's parent as the base for comparison
    oldest_commit = commits[-1]
    oldest_sha = oldest_commit.get("sha", "")

    # Get the parent of the oldest commit
    oldest_url = f"https://api.github.com/repos/{repo}/commits/{oldest_sha}"
    oldest_data = gh_request(oldest_url, token)
    parents = oldest_data.get("parents", [])

    if not parents:
        # No parent means this is the initial commit, compare against empty tree
        base_sha = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # Git's empty tree SHA
    else:
        base_sha = parents[0].get("sha", "")

    # Compare base to current sha
    compare_url = f"https://api.github.com/repos/{repo}/compare/{base_sha}...{sha}"
    compare_data = gh_request(compare_url, token)

    changed_files: Dict[str, List[tuple[int, int]]] = {}

    for file_info in compare_data.get("files", []):
        filename = file_info.get("filename", "")
        if not filename.lower().endswith(".tex"):
            continue

        # Parse the patch to extract changed line numbers
        patch = file_info.get("patch", "")
        if not patch:
            # File was added/deleted without patch info - mark entire file
            changed_files[filename] = [(1, 999999)]
            continue

        line_ranges = parse_diff_hunks(patch)
        if line_ranges:
            changed_files[filename] = line_ranges

    return changed_files


def parse_diff_hunks(patch: str) -> List[tuple[int, int]]:
    """Parse unified diff patch and extract changed line ranges in the new file.

    Returns list of (start_line, end_line) tuples.
    """
    import re

    ranges = []
    # Match hunk headers like @@ -10,5 +12,8 @@
    hunk_pattern = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for match in hunk_pattern.finditer(patch):
        start_line = int(match.group(1))
        count = int(match.group(2)) if match.group(2) else 1
        end_line = start_line + count - 1
        ranges.append((start_line, end_line))

    return ranges


def extract_changed_regions(file_text: str, line_ranges: List[tuple[int, int]], context_lines: int = 5) -> tuple[str, List[int]]:
    """Extract text around changed line ranges with context.

    Returns (extracted_text, line_number_mapping) where line_number_mapping
    maps extracted line index to original line number.
    """
    lines = file_text.split("\n")
    total_lines = len(lines)

    # Expand ranges with context and merge overlapping
    expanded_ranges = []
    for start, end in line_ranges:
        exp_start = max(1, start - context_lines)
        exp_end = min(total_lines, end + context_lines)
        expanded_ranges.append((exp_start, exp_end))

    # Sort and merge overlapping ranges
    expanded_ranges.sort()
    merged = []
    for start, end in expanded_ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    # Extract lines with line number prefixes
    extracted_lines = []
    original_line_numbers = []
    for start, end in merged:
        if extracted_lines:
            extracted_lines.append("...")  # Separator between non-contiguous regions
            original_line_numbers.append(-1)
        for line_num in range(start, end + 1):
            if line_num <= total_lines:
                extracted_lines.append(f"L{line_num}: {lines[line_num - 1]}")
                original_line_numbers.append(line_num)

    return "\n".join(extracted_lines), original_line_numbers


def add_reaction(repo: str, comment_id: int, token: str, emoji: str) -> bool:
    """Add an emoji reaction to a comment."""
    url = f"https://api.github.com/repos/{repo}/comments/{comment_id}/reactions"
    try:
        gh_request(url, token, data={"content": emoji}, method="POST")
        return True
    except Exception:
        return False


def chunk_file_by_lines(file_text: str, max_chars: int) -> List[tuple[str, int]]:
    """Split file into chunks that respect line boundaries.

    Returns list of (chunk_text, start_line_number) tuples.
    """
    lines = file_text.split("\n")
    chunks = []
    current_chunk_lines = []
    current_chunk_size = 0
    chunk_start_line = 1

    for i, line in enumerate(lines):
        line_with_newline = line + "\n"
        line_size = len(line_with_newline)

        # If adding this line would exceed max_chars, start a new chunk
        if current_chunk_size + line_size > max_chars and current_chunk_lines:
            chunk_text = "\n".join(current_chunk_lines)
            chunks.append((chunk_text, chunk_start_line))
            current_chunk_lines = []
            current_chunk_size = 0
            chunk_start_line = i + 1  # 1-based line number

        current_chunk_lines.append(line)
        current_chunk_size += line_size

    # Don't forget the last chunk
    if current_chunk_lines:
        chunk_text = "\n".join(current_chunk_lines)
        chunks.append((chunk_text, chunk_start_line))

    return chunks


def call_openai(api_key: str, system_prompt: str, file_path: str, file_text: str, model: str, language: str, temperature: Optional[float] = None, chunk_info: str = "", diff_mode: bool = False) -> str:
    lang_instruction = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])

    chunk_note = f"\n\n**Note:** {chunk_info}" if chunk_info else ""

    if diff_mode:
        mode_note = (
            "\n\n**DIFF MODE:** You are reviewing only the changed portions of a commit. "
            "Each line is prefixed with its original line number (e.g., 'L42: text'). "
            "Use these line numbers in your JSON response. Focus only on issues in the shown lines."
        )
    else:
        mode_note = ""

    user_prompt = (
        f"Review the LaTeX file `{file_path}` using the instructions.{chunk_note}{mode_note}\n\n"
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


def log(message: str) -> None:
    """Print a timestamped log message."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def main() -> int:
    log("Starting RedPen review...")

    openai_key = require_env("OPENAI_API_KEY")
    github_token = require_env("GITHUB_TOKEN")
    repo = require_env("GITHUB_REPOSITORY")

    # Load configuration
    config = load_config()
    model = os.getenv("OPENAI_MODEL") or config.get("model", DEFAULT_MODEL)
    max_chars = int(os.getenv("MAX_REVIEW_CHARS", config.get("max_chars", DEFAULT_MAX_CHARS)))
    temperature = config.get("temperature")
    log(f"Configuration loaded: model={model}, max_chars={max_chars}")

    with open(require_env("GITHUB_EVENT_PATH"), "r", encoding="utf-8") as handle:
        event = json.load(handle)

    payload = event.get("client_payload") or {}
    commit_sha = payload.get("commit_sha") or os.getenv("GITHUB_SHA")
    if not commit_sha:
        raise RuntimeError("Missing commit SHA in dispatch payload")

    # Get language from environment, payload (set by webhook), or config
    language = os.getenv("REVIEW_LANGUAGE") or payload.get("language") or config.get("language", DEFAULT_LANGUAGE)
    if language not in LANGUAGE_FLAGS:
        language = DEFAULT_LANGUAGE

    # Get review mode: "diff" (default) reviews only changed lines, "full" reviews entire files
    review_mode = os.getenv("REVIEW_MODE") or payload.get("review_mode") or "diff"

    # Get number of commits to review (default: 1, meaning just the current commit)
    num_commits = int(os.getenv("NUM_COMMITS") or payload.get("num_commits") or 1)

    log(f"Review settings: commit={commit_sha[:7]}, language={language}, mode={review_mode}, num_commits={num_commits}")

    # Get comment ID for adding rocket reaction on success
    trigger_comment_id = payload.get("comment_id")

    prompt_text = load_prompt()
    log("Review prompt loaded")

    # In diff mode, only review files that changed
    log("Fetching changed files...")
    if review_mode == "diff":
        if num_commits > 1:
            # Review changes across multiple commits
            log(f"Comparing changes across last {num_commits} commits...")
            changed_files = fetch_multi_commit_diff(repo, commit_sha, num_commits, github_token)
        else:
            # Review only the current commit
            changed_files = fetch_commit_diff(repo, commit_sha, github_token)
        tex_paths = [p for p in changed_files.keys()]
    else:
        changed_files = {}
        tex_paths = list_tex_files(repo, commit_sha, github_token)

    log(f"Found {len(tex_paths)} .tex file(s) to review")

    # Check .gitignore for proper LaTeX patterns
    log("Checking .gitignore...")
    gitignore_content = fetch_gitignore(repo, commit_sha, github_token)
    gitignore_check = check_gitignore_for_latex(gitignore_content)
    if gitignore_check["exists"]:
        log(f".gitignore found: has_pdf={gitignore_check['has_pdf']}, has_latex_patterns={gitignore_check['has_latex_patterns']}")
    else:
        log(".gitignore not found")

    # Check for tracked PDF files
    log("Checking for tracked PDF files...")
    tracked_pdfs = list_tracked_pdf_files(repo, commit_sha, github_token)
    if tracked_pdfs:
        log(f"Found {len(tracked_pdfs)} tracked PDF file(s)")
    else:
        log("No tracked PDF files found")

    if not tex_paths:
        log("No .tex files found, posting comment and exiting")
        post_commit_comment(
            repo,
            commit_sha,
            github_token,
            "📭 No `.tex` files found to review at this commit.",
        )
        return 0

    results = []
    total_files = len(tex_paths)
    for file_idx, path in enumerate(tex_paths, 1):
        log(f"[{file_idx}/{total_files}] Processing: {path}")
        file_text = fetch_file(repo, path, commit_sha, github_token)
        original_text = file_text  # Keep original for quoting

        # In diff mode, extract only the changed regions
        is_diff_mode = review_mode == "diff" and path in changed_files
        if is_diff_mode:
            line_ranges = changed_files[path]
            file_text, _ = extract_changed_regions(file_text, line_ranges, context_lines=5)
            log(f"[{file_idx}/{total_files}] Extracted {len(line_ranges)} changed region(s), {len(file_text)} chars")

        if len(file_text) <= max_chars:
            # File fits in one chunk
            log(f"[{file_idx}/{total_files}] Sending to OpenAI ({len(file_text)} chars)...")
            review_json = call_openai(openai_key, prompt_text, path, file_text, model, language, temperature, diff_mode=is_diff_mode)
            log(f"[{file_idx}/{total_files}] Review received")
        else:
            # Split into chunks and review each
            chunks = chunk_file_by_lines(file_text, max_chars)
            all_comments = []
            summary_parts = []
            log(f"[{file_idx}/{total_files}] File too large, splitting into {len(chunks)} chunks")

            for chunk_idx, (chunk_text, start_line) in enumerate(chunks):
                log(f"[{file_idx}/{total_files}] Reviewing chunk {chunk_idx + 1}/{len(chunks)} ({len(chunk_text)} chars)...")
                chunk_info = f"This is chunk {chunk_idx + 1} of {len(chunks)}, starting at line {start_line}."
                chunk_json = call_openai(
                    openai_key, prompt_text, path, chunk_text, model, language, temperature, chunk_info, diff_mode=is_diff_mode
                )
                log(f"[{file_idx}/{total_files}] Chunk {chunk_idx + 1}/{len(chunks)} complete")

                # Parse and merge results
                try:
                    chunk_data = json.loads(chunk_json)
                    if chunk_data.get("summary"):
                        summary_parts.append(f"[Chunk {chunk_idx + 1}] {chunk_data['summary']}")
                    for comment in chunk_data.get("comments", []):
                        # Adjust line numbers - they're already relative to chunk start
                        # since the LLM sees only the chunk content (only for non-diff mode)
                        if not is_diff_mode and isinstance(comment.get("line"), int):
                            comment["line"] = comment["line"] + start_line - 1
                        all_comments.append(comment)
                except json.JSONDecodeError:
                    # If parsing fails, include raw response as a comment
                    all_comments.append({
                        "line": start_line,
                        "severity": "warning",
                        "category": "system",
                        "issue": f"Chunk {chunk_idx + 1} review parse error",
                        "suggestion": chunk_json[:500],
                    })

            # Combine into single JSON result
            merged = {
                "summary": " ".join(summary_parts) if summary_parts else "Review completed in multiple chunks.",
                "comments": all_comments,
            }
            review_json = json.dumps(merged)

        results.append((path, review_json, original_text))
        log(f"[{file_idx}/{total_files}] Done: {path}")

    log("All files reviewed, formatting results...")

    # Build the review comment
    flag = LANGUAGE_FLAGS.get(language, "🇺🇸")
    lang_name = LANGUAGE_NAMES.get(language, "English")
    if review_mode == "full":
        mode_label = "Full files"
    elif num_commits > 1:
        mode_label = f"Changed lines (last {num_commits} commits)"
    else:
        mode_label = "Changed lines"

    header = f"## 🖊️ RedPen Review {flag}\n\n"
    header += f"Reviewed **{len(results)}** `.tex` file(s) at commit `{commit_sha[:7]}`\n"
    header += f"**Model:** `{model}` · **Language:** {lang_name} · **Mode:** {mode_label}\n"

    parts = [header]
    for path, review_json, file_content in results:
        parts.append(format_review_as_markdown(path, review_json, file_content))

    # Add .gitignore check results
    parts.append(format_gitignore_review(gitignore_check, tracked_pdfs))

    comment_body = "\n---\n".join(parts)
    log(f"Posting review comment ({len(comment_body)} chars)...")
    post_commit_comment(repo, commit_sha, github_token, comment_body)
    log("Review comment posted successfully")

    # Add rocket reaction to the original trigger comment to indicate success
    if trigger_comment_id:
        add_reaction(repo, trigger_comment_id, github_token, "rocket")

    log("RedPen review complete!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
