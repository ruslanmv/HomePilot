#!/usr/bin/env node
/**
 * Write the release version into app.json — mirrors the desktop workflow's
 * "set version in package.json" step.
 *
 * Usage: node scripts/set-version.mjs <semver> [buildNumber]
 *   <semver>      e.g. 1.0.0 (from the release tag, `v` stripped by CI)
 *   [buildNumber] integer for android.versionCode / ios.buildNumber
 *                 (defaults to a monotonic value derived from the semver)
 *
 * versionCode must strictly increase for every store/sideload update, so CI
 * passes the run number; locally we derive MAJOR*10000 + MINOR*100 + PATCH.
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_JSON = path.join(__dirname, "..", "app.json");

const semver = (process.argv[2] || "").replace(/^v/, "").trim();
if (!/^\d+\.\d+\.\d+/.test(semver)) {
  console.error(`set-version: invalid semver "${process.argv[2]}". Expected e.g. 1.0.0`);
  process.exit(1);
}

const [maj, min, pat] = semver.split(".").map((n) => parseInt(n, 10) || 0);
const derived = maj * 10000 + min * 100 + pat;
const buildNumber = parseInt(process.argv[3], 10) || derived;

const cfg = JSON.parse(fs.readFileSync(APP_JSON, "utf8"));
cfg.expo.version = semver;
cfg.expo.ios = { ...(cfg.expo.ios || {}), buildNumber: String(buildNumber) };
cfg.expo.android = { ...(cfg.expo.android || {}), versionCode: buildNumber };

fs.writeFileSync(APP_JSON, JSON.stringify(cfg, null, 2) + "\n");
console.log(`set-version: ${semver} (versionCode/buildNumber=${buildNumber})`);
