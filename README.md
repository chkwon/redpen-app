# Redpen Commit Timestamp App

Minimal GitHub App behavior implemented via a workflow. Mention `@redpen check` on any commit and the workflow responds with the current UTC date and time.

## How it works
- The workflow at `.github/workflows/redpen-check.yml` listens to the `commit_comment` event.
- When the trigger phrase is detected, it runs `scripts/timestamp_comment.py`.
- The script reads the event payload from `GITHUB_EVENT_PATH`, builds a timestamp response, and posts a new commit comment via the `GITHUB_TOKEN`.

## Setup
1. Push this repository to GitHub.
2. Ensure workflows are enabled (default on public repos).
3. Comment on any commit with `@redpen check`.
4. The `github-actions` bot will reply with the current UTC timestamp.

Use the optional `TRIGGER_PHRASE` environment variable on the workflow step to customize the trigger text.
