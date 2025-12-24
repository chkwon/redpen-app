# Redpen Commit Timestamp App

Minimal GitHub App behavior implemented via a Netlify Function: mention `@RedPenApp check` on any commit comment and the App replies with the current UTC date and time.

## How it works
- A GitHub App listens for `commit_comment` webhooks and calls a Netlify Function (`netlify/functions/webhook.js`).
- The function verifies the webhook signature, checks for the trigger phrase, and posts a new commit comment with the timestamp using the installation token.

## Setup
1. Push this repository to GitHub.
2. Create a lightweight GitHub App:
   - App permissions: **Metadata: read** and **Contents: write**.
   - Subscribe to the **Commit comment** webhook event.
   - Set the Webhook URL to your deployed Netlify Function URL and the Webhook Secret to a random string (also set as `GITHUB_WEBHOOK_SECRET` in Netlify).
   - Install the App on the target repository.
3. Deploy the Netlify Function (or any HTTPS endpoint) from `netlify/functions/webhook.js` and configure environment variables:
   - `GITHUB_APP_ID`, `GITHUB_INSTALLATION_ID`, `GITHUB_PRIVATE_KEY` (PEM with `\\n` escapes), `GITHUB_WEBHOOK_SECRET`, optional `TRIGGER_PHRASE`.
   - Install dependencies (`npm install`) so Netlify bundles `jsonwebtoken` for the function.
4. Comment on any commit with `@RedPenApp check`; the App will reply with the current UTC timestamp.

Notes:
- The GitHub Actions workflow path was removed for simplicity; everything runs inside the Netlify Function via the App installation token.
- Adjust the trigger phrase by setting `TRIGGER_PHRASE` in the Netlify environment (default: `@RedPenApp check`).
