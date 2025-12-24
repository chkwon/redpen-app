import crypto from "crypto";
import fetch from "node-fetch"; // Netlify bundles node-fetch v2

const GITHUB_APP_ID = process.env.GITHUB_APP_ID;
const GITHUB_INSTALLATION_ID = process.env.GITHUB_INSTALLATION_ID;
const GITHUB_PRIVATE_KEY = process.env.GITHUB_PRIVATE_KEY; // PEM, newline-escaped
const GITHUB_WEBHOOK_SECRET = process.env.GITHUB_WEBHOOK_SECRET; // same as in App settings

// Verify webhook signature
function verify(body, signature) {
  const hmac = crypto.createHmac("sha256", GITHUB_WEBHOOK_SECRET);
  const digest = `sha256=${hmac.update(body).digest("hex")}`;
  return crypto.timingSafeEqual(Buffer.from(digest), Buffer.from(signature || ""));
}

// Create JWT for the App
function appJwt() {
  const now = Math.floor(Date.now() / 1000);
  const payload = { iat: now - 60, exp: now + 600, iss: GITHUB_APP_ID };
  const token = require("jsonwebtoken").sign(payload, GITHUB_PRIVATE_KEY.replace(/\\n/g, "\n"), {
    algorithm: "RS256",
  });
  return token;
}

// Exchange for installation token
async function installationToken() {
  const jwt = appJwt();
  const res = await fetch(
    `https://api.github.com/app/installations/${GITHUB_INSTALLATION_ID}/access_tokens`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${jwt}`,
        Accept: "application/vnd.github+json",
      },
    }
  );
  if (!res.ok) throw new Error(`token exchange failed ${res.status}`);
  const json = await res.json();
  return json.token;
}

export const handler = async (event) => {
  const sig = event.headers["x-hub-signature-256"];
  if (!verify(event.body, sig)) return { statusCode: 401, body: "bad signature" };

  const payload = JSON.parse(event.body);
  if (payload.action !== "created" || payload.comment?.body == null) {
    return { statusCode: 200, body: "ignored" };
  }

  const commit_sha = payload.comment.commit_id;
  const comment_body = payload.comment.body;
  const comment_author = payload.comment.user?.login;

  const token = await installationToken();

  const dispatchRes = await fetch(
    `https://api.github.com/repos/${payload.repository.full_name}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({
        event_type: "redpen-commit-comment",
        client_payload: { commit_sha, comment_body, comment_author },
      }),
    }
  );

  if (!dispatchRes.ok) {
    const text = await dispatchRes.text();
    return { statusCode: 500, body: `dispatch failed ${dispatchRes.status}: ${text}` };
  }
  return { statusCode: 200, body: "ok" };
};
