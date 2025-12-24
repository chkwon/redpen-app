const crypto = require("crypto");
const jsonwebtoken = require("jsonwebtoken"); // bundled via Netlify Node runtime

const GITHUB_APP_ID = process.env.GITHUB_APP_ID;
const GITHUB_INSTALLATION_ID = process.env.GITHUB_INSTALLATION_ID;
const GITHUB_PRIVATE_KEY = process.env.GITHUB_PRIVATE_KEY; // PEM, newline-escaped
const GITHUB_WEBHOOK_SECRET = process.env.GITHUB_WEBHOOK_SECRET; // same as in App settings
const TRIGGER_PHRASE = (process.env.TRIGGER_PHRASE || "@RedPenApp review").toLowerCase();

function requireEnv(name, value) {
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

// Verify webhook signature
function verify(body, signature) {
  const hmac = crypto.createHmac("sha256", GITHUB_WEBHOOK_SECRET);
  const digest = `sha256=${hmac.update(body).digest("hex")}`;
  return crypto.timingSafeEqual(Buffer.from(digest), Buffer.from(signature || ""));
}

// Create JWT for the App
function appJwt() {
  requireEnv("GITHUB_APP_ID", GITHUB_APP_ID);
  const now = Math.floor(Date.now() / 1000);
  const payload = { iat: now - 60, exp: now + 600, iss: GITHUB_APP_ID };
  const key = requireEnv("GITHUB_PRIVATE_KEY", GITHUB_PRIVATE_KEY).replace(/\\n/g, "\n");
  const token = jsonwebtoken.sign(payload, key, {
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

module.exports.handler = async (event) => {
  const sig = event.headers["x-hub-signature-256"];
  if (!verify(event.body, sig)) return { statusCode: 401, body: "bad signature" };

  const payload = JSON.parse(event.body);
  if (payload.action !== "created" || payload.comment?.body == null) {
    return { statusCode: 200, body: "ignored" };
  }

  const commit_sha = payload.comment.commit_id;
  const comment_body = payload.comment.body;
  const comment_author = payload.comment.user?.login;
  if (!commit_sha) return { statusCode: 200, body: "ignored: no commit" };

  // Avoid loops on bot-authored comments.
  if (comment_author && comment_author.endsWith("[bot]")) {
    return { statusCode: 200, body: "ignored: bot comment" };
  }

  if (!comment_body.toLowerCase().includes(TRIGGER_PHRASE)) {
    return { statusCode: 200, body: "ignored: trigger not found" };
  }

  const token = await installationToken();

  // Acknowledge receipt to the commit thread.
  const pending = await fetch(
    `https://api.github.com/repos/${payload.repository.full_name}/commits/${commit_sha}/comments`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({
        body: "👋 Review request received. Processing all .tex files now…",
      }),
    }
  );
  if (!pending.ok) {
    const text = await pending.text();
    return { statusCode: 500, body: `pending comment failed ${pending.status}: ${text}` };
  }

  const res = await fetch(
    `https://api.github.com/repos/${payload.repository.full_name}/dispatches`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({
        event_type: "redpen-review",
        client_payload: {
          commit_sha,
          comment_body,
          comment_author,
        },
      }),
    }
  );

  if (!res.ok) {
    const text = await res.text();
    return { statusCode: 500, body: `dispatch failed ${res.status}: ${text}` };
  }
  return { statusCode: 200, body: "review dispatched" };
};
