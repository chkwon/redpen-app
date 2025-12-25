const crypto = require("crypto");
const jsonwebtoken = require("jsonwebtoken"); // bundled via Netlify Node runtime

const GITHUB_APP_ID = process.env.GITHUB_APP_ID;
const GITHUB_PRIVATE_KEY = process.env.GITHUB_PRIVATE_KEY; // PEM, newline-escaped
const GITHUB_WEBHOOK_SECRET = process.env.GITHUB_WEBHOOK_SECRET; // same as in App settings

// Support multiple trigger phrases
const TRIGGER_PHRASES = [
  "@redpenapp review",
  "@red-pen-app review",
  "@red-pen-app[bot] review",
];

// Language code to flag emoji mapping
const LANGUAGE_FLAGS = {
  en: "🇺🇸",
  ko: "🇰🇷",
  zh: "🇨🇳",
  ja: "🇯🇵",
  vi: "🇻🇳",
};

const LANGUAGE_NAMES = {
  en: "English",
  ko: "Korean",
  zh: "Chinese",
  ja: "Japanese",
  vi: "Vietnamese",
};

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

// Exchange for installation token using the installation ID from the webhook payload
async function installationToken(installationId) {
  const jwt = appJwt();
  const res = await fetch(
    `https://api.github.com/app/installations/${installationId}/access_tokens`,
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

// Add emoji reaction to a comment
async function addReaction(token, repoFullName, commentId, emoji) {
  const res = await fetch(
    `https://api.github.com/repos/${repoFullName}/comments/${commentId}/reactions`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({ content: emoji }),
    }
  );
  return res.ok;
}

// Find which trigger phrase is used and return its index and length
function findTrigger(commentBody) {
  const lowerBody = commentBody.toLowerCase();
  for (const phrase of TRIGGER_PHRASES) {
    const index = lowerBody.indexOf(phrase);
    if (index !== -1) {
      return { index, length: phrase.length };
    }
  }
  return null;
}

// Check if comment contains any trigger phrase
function hasTrigger(commentBody) {
  return findTrigger(commentBody) !== null;
}

// Parse options from trigger comment
// Supports: "@RedPenApp review", "@red-pen-app[bot] review", "review full", "review ko",
// "review full ko", "review 5" (review last 5 commits)
function parseOptions(commentBody) {
  const trigger = findTrigger(commentBody);

  let reviewMode = "diff"; // default: only review changed lines
  let language = "en";
  let numCommits = 1; // default: only current commit

  if (!trigger) return { reviewMode, language, numCommits };

  // Get words after the trigger phrase
  const lowerBody = commentBody.toLowerCase();
  const afterTrigger = lowerBody.slice(trigger.index + trigger.length).trim();
  const words = afterTrigger.split(/\s+/).filter(w => w.length > 0);

  for (const word of words) {
    if (word === "full") {
      reviewMode = "full";
    } else if (LANGUAGE_FLAGS[word]) {
      language = word;
    } else if (/^\d+$/.test(word)) {
      // Parse number of commits (e.g., "5" means last 5 commits)
      const n = parseInt(word, 10);
      if (n > 0 && n <= 50) { // Cap at 50 commits for safety
        numCommits = n;
      }
    }
  }

  return { reviewMode, language, numCommits };
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
  const comment_id = payload.comment.id;
  if (!commit_sha) return { statusCode: 200, body: "ignored: no commit" };

  // Avoid loops on bot-authored comments.
  if (comment_author && comment_author.endsWith("[bot]")) {
    return { statusCode: 200, body: "ignored: bot comment" };
  }

  if (!hasTrigger(comment_body)) {
    return { statusCode: 200, body: "ignored: trigger not found" };
  }

  // Get installation ID from the webhook payload
  const installationId = payload.installation?.id;
  if (!installationId) {
    return { statusCode: 400, body: "missing installation id in payload" };
  }

  const token = await installationToken(installationId);

  // Add :eyes: reaction to acknowledge the trigger comment
  if (comment_id) {
    await addReaction(token, payload.repository.full_name, comment_id, "eyes");
  }

  // Parse options from the trigger comment
  const { reviewMode, language, numCommits } = parseOptions(comment_body);
  const flag = LANGUAGE_FLAGS[language] || "🇺🇸";
  const langName = LANGUAGE_NAMES[language] || "English";
  const modeLabel = reviewMode === "full"
    ? "Full file review"
    : numCommits > 1
      ? `Changed lines (last ${numCommits} commits)`
      : "Changed lines only";

  // Acknowledge receipt to the commit thread with language flag
  const pending = await fetch(
    `https://api.github.com/repos/${payload.repository.full_name}/commits/${commit_sha}/comments`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: "application/vnd.github+json",
      },
      body: JSON.stringify({
        body: `${flag} Review request received! Analyzing \`.tex\` files...\n\n` +
          `**Mode:** ${modeLabel}\n` +
          `**Language:** ${langName}\n` +
          `**Commit:** \`${commit_sha.slice(0, 7)}\`\n\n` +
          `_Check the Actions tab for progress._`,
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
          comment_id,
          language,
          review_mode: reviewMode,
          num_commits: numCommits,
        },
      }),
    }
  );

  if (!res.ok) {
    const text = await res.text();
    return { statusCode: 500, body: `dispatch failed ${res.status}: ${text}` };
  }
  return { statusCode: 200, body: `review dispatched (lang: ${language})` };
};
