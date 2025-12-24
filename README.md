# Redpen Commit Timestamp App

Minimal GitHub App behavior implemented via a workflow. Mention `@redpen check` on any commit comment and the workflow responds with the current UTC date and time.

## How it works
- The workflow at `.github/workflows/redpen-check.yml` listens to the `commit_comment` event.
- When the trigger phrase is detected, it runs `scripts/timestamp_comment.py`.
- The script reads the event payload from `GITHUB_EVENT_PATH`, builds a timestamp response, and posts a new commit comment via the `GITHUB_TOKEN`.

## Setup
1. Push this repository to GitHub.
2. Create a lightweight GitHub App that forwards `commit_comment` webhooks to a `repository_dispatch`:
   - App permissions: **Metadata: read** and **Contents: write** (required for `repository_dispatch`).
   - Subscribe to the **Commit comment** webhook event.
   - In the webhook handler, POST to `https://api.github.com/repos/{owner}/{repo}/dispatches` with headers `Authorization: Bearer <installation_token>`, `Accept: application/vnd.github+json`, and JSON body:
     ```json
     { "event_type": "redpen-commit-comment",
       "client_payload": {
         "commit_sha": "<commit sha>",
         "comment_body": "<comment body>",
         "comment_author": "<comment author login>"
       }
     }
     ```
   - The installation token scopes are handled by the App; no personal tokens needed.
3. Comment on any commit with `@redpen check`.
4. The workflow triggered via `repository_dispatch` will reply with the current UTC timestamp.

Use the optional `TRIGGER_PHRASE` environment variable on the workflow step to customize the trigger text.
