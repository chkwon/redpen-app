# Redpen LaTeX Reviewer

GitHub App + Netlify Function + GitHub Actions that reviews LaTeX files with OpenAI. Mention `@RedPenApp review` on a commit comment; the App dispatches a workflow that reviews all `.tex` files at that commit and comments back with JSON feedback. A pending acknowledgement is posted immediately; results follow when the workflow completes.

## How it works
- A GitHub App listens for `commit_comment` webhooks and calls the Netlify Function (`netlify/functions/webhook.js`).
- The function verifies the signature, checks the trigger phrase, posts a “received” comment, and fires a `repository_dispatch` event (`redpen-review`) with the commit SHA.
- The workflow at `.github/workflows/redpen-review.yml` runs on that dispatch, fetches all `.tex` files at the commit, calls OpenAI (via `scripts/openai_review.py`), and posts the JSON reviews as a new commit comment.

## Setup
1. Push this repository to GitHub.
2. Create and configure a lightweight GitHub App:
   - App permissions: **Metadata: read** and **Contents: write**.
   - Subscribe to **Commit comment** webhook.
   - Webhook URL: `https://<your-site>.netlify.app/.netlify/functions/webhook`
   - Webhook Secret: random string (also set as `GITHUB_WEBHOOK_SECRET` in Netlify).
   - Install the App on the target repository.
3. Deploy the Netlify Function (or any HTTPS endpoint) from `netlify/functions/webhook.js` and configure environment variables:
   - `GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, `GITHUB_PRIVATE_KEY` (PEM with `\\n` escapes), `GITHUB_WEBHOOK_SECRET`, optional `TRIGGER_PHRASE`.
   - Install dependencies (`npm install`) so Netlify bundles `jsonwebtoken` for the function.
4. Configure GitHub Actions secret in the repository:
   - `OPENAI_API_KEY`: your OpenAI key (used by the workflow).
5. Trigger a review by commenting on a commit with `@RedPenApp review`. The workflow will reply with JSON feedback per the LaTeX reviewer instructions.

Notes:
- Adjust the trigger phrase by setting `TRIGGER_PHRASE` in Netlify (default: `@RedPenApp review`).
- The workflow can also be run manually via the Actions tab (`Run workflow`); it will process all `.tex` files at the selected commit.
