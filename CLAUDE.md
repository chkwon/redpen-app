# RedPen LaTeX Reviewer - Claude Code Context

This document provides context for Claude Code to understand the RedPen application.

## Overview

RedPen is an AI-powered LaTeX academic writing reviewer that integrates with GitHub as a GitHub App. Users trigger reviews by commenting `@RedPenApp review` on commits, and the app analyzes `.tex` files for grammar, spelling, style issues, and LaTeX best practices.

## Architecture

```
User Comment → GitHub Webhook → Netlify Function → GitHub Actions → OpenAI API → Commit Comment
```

### Components

| Component | Location | Technology | Purpose |
|-----------|----------|------------|---------|
| Landing Page | `index.html` | HTML/CSS/JS | User documentation |
| Webhook Handler | `netlify/functions/webhook.js` | Node.js | Receives GitHub webhooks, dispatches workflows |
| Review Workflow | `.github/workflows/redpen-review.yml` | GitHub Actions | Orchestrates the review process |
| Review Engine | `scripts/openai_review.py` | Python 3.11 | Core logic: fetches files, calls OpenAI, posts results |
| System Prompt | `prompts/review_prompt.md` | Markdown | Instructions for the AI reviewer |
| Configuration | `config.yml` | YAML | Default settings (model, language, max_chars) |

## Key Files

- **`netlify/functions/webhook.js`** - Verifies webhook signatures, parses trigger phrases, posts acknowledgement comments, dispatches `repository_dispatch` events
- **`scripts/openai_review.py`** - 630+ lines of Python handling file fetching, diff parsing, chunking, OpenAI calls, and result formatting
- **`prompts/review_prompt.md`** - Detailed system prompt defining review priorities (grammar, LaTeX best practices, academic style)
- **`.github/workflows/redpen-review.yml`** - Supports 3 triggers: `repository_dispatch`, `workflow_dispatch`, `workflow_call`
- **`config.yml`** - Defaults: `model: gpt-5-mini`, `language: en`, `max_chars: 20000`

## User Trigger Syntax

Users comment on commits with variations of:
- `@redpenapp review` - Default (diff mode, English)
- `@redpenapp review full` - Review entire files
- `@redpenapp review ko` - Korean language feedback
- `@redpenapp review 5` - Review last 5 commits
- `@redpenapp review full ko 3` - Combined options

Supported languages: `en`, `ko`, `zh`, `ja`, `vi`

## Review Modes

- **Diff Mode** (default): Reviews only changed lines with 5 lines of context
- **Full Mode**: Reviews entire `.tex` files
- **Multi-Commit Mode**: Reviews changes across multiple commits (up to 50)

## External APIs

### GitHub API
- JWT-based app authentication + installation tokens
- Endpoints: contents, git trees, commits, comments, reactions, dispatches

### OpenAI API
- Endpoint: `https://api.openai.com/v1/chat/completions` (configurable)
- Uses structured JSON response format
- Model configurable via `config.yml`

## Environment Variables

### Netlify (webhook.js)
- `GITHUB_APP_ID` - GitHub App ID
- `GITHUB_PRIVATE_KEY` - App private key (PEM with `\n` escapes)
- `GITHUB_INSTALLATION_ID` - Installation ID
- `GITHUB_WEBHOOK_SECRET` - Webhook signature secret

### GitHub Actions (openai_review.py)
- `OPENAI_API_KEY` - User's OpenAI API key
- `GITHUB_TOKEN` - GitHub's default token
- `GITHUB_REPOSITORY`, `GITHUB_SHA` - Context from event
- `REVIEW_LANGUAGE`, `NUM_COMMITS` - Parsed from trigger

## Processing Flow

1. **Webhook receives** commit comment event
2. **Verifies signature** using HMAC-SHA256
3. **Parses trigger** for mode, language, commit count
4. **Posts acknowledgement** comment with language flag
5. **Dispatches** `repository_dispatch` to trigger workflow
6. **Workflow** checks out code, runs Python script
7. **Python script**:
   - Fetches `.tex` files and diffs via GitHub API
   - Checks `.gitignore` for proper LaTeX patterns
   - Checks for tracked PDF files in the repository
   - Chunks large files (>20,000 chars)
   - Calls OpenAI for each chunk with system prompt
   - Formats results as markdown with line numbers
   - Appends `.gitignore` check results with actionable recommendations
   - Posts review as commit comment
8. **Adds reactions** (👀 received, 🚀 success, 😕 failure)

## Review Categories

The AI checks for:
- **Grammar**: Subject-verb agreement, articles, spelling, tense consistency
- **LaTeX**: Paragraph spacing, equation formatting, cross-references, quotation marks, dashes
- **Academic Style**: Informal language, weak hedging, vague claims, undefined acronyms

## Repository Hygiene Check

Each review automatically includes a `.gitignore` check that:
- Verifies `.gitignore` exists
- Checks for proper LaTeX patterns (`*.aux`, `*.log`, `*.out`, `*.bbl`, `*.blg`, `*.synctex.gz`)
- Checks if `*.pdf` is ignored
- Lists any tracked PDF files in the repository
- Provides step-by-step instructions to remove tracked PDFs and update `.gitignore`

The check reports:
- ✅ If `.gitignore` is properly configured
- ⚠️ If `.gitignore` is missing or incomplete
- ⚠️ If PDF files are tracked (with `git rm --cached` removal instructions)

## Build System

- **Netlify** hosts the landing page and serverless function
- **`build.sh`** injects workflow/config content into `index.html`
- **`netlify.toml`** configures build command and functions directory

## Important Notes

- No external Python dependencies (uses only standard library)
- Bot comments are ignored to prevent loops
- Users can override `config.yml` and `prompts/review_prompt.md` in their own repos
- Large files are automatically chunked with line number tracking preserved
