#!/usr/bin/env node
/**
 * R2 Upload Helper — Uses the Cloudflare API (api.cloudflare.com) instead of
 * the S3-compatible endpoint, which can timeout in WSL environments.
 *
 * Usage:
 *   node r2-upload.mjs <bucket> <key> <file> <content-type>
 *
 * Requires environment variables (set via wrangler login or .env):
 *   CLOUDFLARE_ACCOUNT_ID — Cloudflare account ID
 *   CLOUDFLARE_API_TOKEN  — API token with R2 write permission
 *
 * If API token is not set, falls back to extracting the OAuth token
 * from wrangler's cached config.
 */
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";
import https from "node:https";

const [bucket, key, filePath, contentType] = process.argv.slice(2);

if (!bucket || !key || !filePath) {
  console.error("Usage: node r2-upload.mjs <bucket> <key> <file> <content-type>");
  process.exit(1);
}

// Resolve account ID
let accountId = process.env.CLOUDFLARE_ACCOUNT_ID || "";
if (!accountId) {
  // Try to read from wrangler's cached config
  const cacheDir = join("node_modules", ".cache", "wrangler");
  const accountFile = join(cacheDir, "account-id");
  if (existsSync(accountFile)) {
    accountId = readFileSync(accountFile, "utf8").trim();
  }
}
if (!accountId) {
  console.error("Error: CLOUDFLARE_ACCOUNT_ID not set and not found in wrangler cache.");
  console.error("Set it via: export CLOUDFLARE_ACCOUNT_ID=<your-account-id>");
  process.exit(1);
}

// Resolve API token
let apiToken = process.env.CLOUDFLARE_API_TOKEN || "";
if (!apiToken) {
  // Try to read wrangler's OAuth token from its config
  const configPaths = [
    join(homedir(), ".wrangler", "config", "default.toml"),
    join(homedir(), ".config", ".wrangler", "config", "default.toml"),
  ];
  for (const p of configPaths) {
    if (existsSync(p)) {
      const content = readFileSync(p, "utf8");
      const match = content.match(/oauth_token\s*=\s*"([^"]+)"/);
      if (match) {
        apiToken = match[1];
        break;
      }
    }
  }
}
if (!apiToken) {
  console.error("Error: CLOUDFLARE_API_TOKEN not set and no wrangler OAuth token found.");
  console.error("Run 'wrangler login' or set CLOUDFLARE_API_TOKEN.");
  process.exit(1);
}

// Read file
const fileData = readFileSync(filePath);

// Upload via Cloudflare S3-compatible API using HTTPS directly
// The S3 PUT endpoint: https://<account_id>.r2.cloudflarestorage.com/<bucket>/<key>
// But since that times out from WSL, we use the Cloudflare API v4 endpoint instead.
//
// Cloudflare API v4 for R2:
// PUT https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket}/objects/{key}

const encodedKey = key.split("/").map(encodeURIComponent).join("/");
const path = `/client/v4/accounts/${accountId}/r2/buckets/${bucket}/objects/${encodedKey}`;

const options = {
  hostname: "api.cloudflare.com",
  port: 443,
  path,
  method: "PUT",
  headers: {
    Authorization: `Bearer ${apiToken}`,
    "Content-Type": contentType || "application/octet-stream",
    "Content-Length": fileData.length,
  },
  timeout: 30000,
};

const req = https.request(options, (res) => {
  let body = "";
  res.on("data", (chunk) => { body += chunk; });
  res.on("end", () => {
    if (res.statusCode >= 200 && res.statusCode < 300) {
      console.log(`Upload complete: ${key}`);
      process.exit(0);
    } else {
      console.error(`Upload failed (HTTP ${res.statusCode}): ${body}`);
      process.exit(1);
    }
  });
});

req.on("timeout", () => {
  console.error("Upload timed out (30s)");
  req.destroy();
  process.exit(1);
});

req.on("error", (e) => {
  console.error(`Upload error: ${e.message}`);
  process.exit(1);
});

req.write(fileData);
req.end();
