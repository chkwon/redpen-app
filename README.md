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

Read the instructions at: https://redpen-app.netlify.app/

## Notes

- Each repository uses its own `OPENAI_API_KEY` - Netlify never sees this key
- The workflow can also be triggered manually from the Actions tab
- Adjust the trigger phrase via `TRIGGER_PHRASE` in Netlify env vars
