# RedPen LaTeX Reviewer

GitHub App + Netlify Function + GitHub Actions that reviews LaTeX files with OpenAI. Mention `@RedPenApp review` on a commit comment; the App dispatches a workflow that reviews all `.tex` files at that commit and comments back with feedback.

**Website:** https://redpen-app.netlify.app
**Webhook URL:** https://redpen-app.netlify.app/.netlify/functions/webhook

## Architecture

```
User comments "@RedPenApp review" on a commit
        │
        ▼
┌─────────────────────────────────────────┐
│  GitHub App (RedPenApp)                 │
│  - Listens to commit_comment events     │
│  - Sends webhook to Netlify             │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  Netlify Function (webhook.js)          │
│  - Verifies webhook signature           │
│  - Posts "received" acknowledgement     │
│  - Dispatches repository_dispatch event │
└─────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────┐
│  GitHub Actions (redpen-review.yml)     │
│  - Runs in the user's repository        │
│  - Fetches .tex files at commit         │
│  - Calls OpenAI API (repo's own key)    │
│  - Posts review as commit comment       │
└─────────────────────────────────────────┘
```

## Key Files

| File | Purpose |
|------|---------|
| `netlify/functions/webhook.js` | Webhook handler - verifies signature, posts ack, dispatches workflow |
| `.github/workflows/redpen-review.yml` | GitHub Actions workflow template for users |
| `scripts/openai_review.py` | Python script that fetches .tex files and calls OpenAI |
| `prompts/review_prompt.md` | System prompt for the LaTeX reviewer |
| `index.html` | Landing page at https://redpen-app.netlify.app |

## Environment Variables (Netlify)

| Variable | Description |
|----------|-------------|
| `GITHUB_APP_ID` | The App ID from GitHub App settings |
| `GITHUB_INSTALLATION_ID` | Installation ID (found in URL when viewing installed app) |
| `GITHUB_PRIVATE_KEY` | Private key PEM (replace newlines with `\n`) |
| `GITHUB_WEBHOOK_SECRET` | Secret string for webhook signature verification |
| `TRIGGER_PHRASE` | Optional, default: `@RedPenApp review` |

## GitHub App Configuration

When creating/editing the GitHub App at https://github.com/settings/apps:

**Permissions:**
- Repository permissions → Contents: **Read and write**
- Repository permissions → Metadata: **Read-only**

**Subscribe to events:**
- [x] Commit comment

**Webhook:**
- Webhook URL: `https://redpen-app.netlify.app/.netlify/functions/webhook`
- Webhook secret: (same as `GITHUB_WEBHOOK_SECRET` in Netlify)

## For Users: How to Use RedPenApp

### Step 1: Install the GitHub App
Go to the GitHub App page and click "Install" on your repository.

### Step 2: Add the Workflow File
Copy `.github/workflows/redpen-review.yml` to your repository:

```yaml
name: RedPen LaTeX Review

on:
  repository_dispatch:
    types: [redpen-review]
  workflow_dispatch:

jobs:
  review:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          ref: ${{ github.event.client_payload.commit_sha || github.sha }}

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: python -m pip install --upgrade pip

      - name: Run OpenAI LaTeX review
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          GITHUB_EVENT_PATH: ${{ github.event_path }}
          GITHUB_SHA: ${{ github.event.client_payload.commit_sha || github.sha }}
        run: |
          curl -sO https://raw.githubusercontent.com/chkwon/redpen-app/main/scripts/openai_review.py
          curl -sO https://raw.githubusercontent.com/chkwon/redpen-app/main/prompts/review_prompt.md
          python openai_review.py
```

### Step 3: Add Repository Secret
Add `OPENAI_API_KEY` as a repository secret (Settings → Secrets and variables → Actions).

### Step 4: Trigger a Review
Comment `@RedPenApp review` on any commit to get a review of all `.tex` files.

## Notes

- Each repository uses its own `OPENAI_API_KEY` - Netlify never sees this key
- The workflow can also be triggered manually from the Actions tab
- Adjust the trigger phrase via `TRIGGER_PHRASE` in Netlify env vars
