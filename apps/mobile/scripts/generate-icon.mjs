#!/usr/bin/env node
/**
 * Generate the HomePilot mobile app icons — zero dependencies.
 *
 * Reuses the exact gradient + house renderer from the desktop generator
 * (`desktop/scripts/generate-icons.js`) so mobile branding matches desktop and
 * web. Produces 1024×1024 PNGs that Expo prebuild consumes:
 *   - assets/icon.png          (iOS + Android legacy launcher)
 *   - assets/adaptive-icon.png (Android adaptive foreground)
 *
 * Run: node scripts/generate-icon.mjs   (also runs via the `prebuild` script)
 */

import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ASSETS_DIR = path.join(__dirname, "..", "assets");

// ── PNG encoder (zero dependencies) ──────────────────────────────────────
function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i];
    for (let j = 0; j < 8; j++) c = (c >>> 1) ^ (c & 1 ? 0xedb88320 : 0);
  }
  return (c ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const t = Buffer.from(type);
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length);
  const body = Buffer.concat([t, data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([len, body, crc]);
}

function createPNG(width, height, renderFn) {
  const raw = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y++) {
    const rowOff = y * (width * 4 + 1);
    raw[rowOff] = 0; // filter: None
    for (let x = 0; x < width; x++) {
      const [r, g, b, a] = renderFn(x, y, width, height);
      const px = rowOff + 1 + x * 4;
      raw[px] = r;
      raw[px + 1] = g;
      raw[px + 2] = b;
      raw[px + 3] = a;
    }
  }
  const compressed = zlib.deflateSync(raw);
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  return Buffer.concat([
    sig,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", compressed),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

// ── HomePilot logo renderer (gradient + house) ───────────────────────────
// `mask` = true draws the rounded-rect app-icon shape (icon.png); false keeps
// the gradient full-bleed (adaptive foreground, Android masks it itself).
function makeRenderLogo(mask) {
  return function renderLogo(x, y, W, H) {
    const nx = (x - W / 2) / (W / 2); // -1..1
    const ny = (y - H / 2) / (H / 2);
    let r = 0, g = 0, b = 0, a = 255;

    if (mask) {
      const cornerR = 0.22;
      const edgeX = Math.abs(nx) - (1 - cornerR);
      const edgeY = Math.abs(ny) - (1 - cornerR);
      if (edgeX > 0 && edgeY > 0) {
        const cd = Math.sqrt(edgeX * edgeX + edgeY * edgeY);
        if (cd > cornerR) return [0, 0, 0, 0];
        if (cd > cornerR - 0.02) a = Math.round(255 * ((cornerR - cd) / 0.02));
      }
      if (Math.abs(nx) > 1 || Math.abs(ny) > 1) return [0, 0, 0, 0];
    }

    // Background gradient (top-left blue → bottom-right purple)
    const gt = (nx + ny + 2) / 4;
    r = Math.round(37 + gt * 87);
    g = Math.round(99 - gt * 41);
    b = Math.round(235 - gt * (235 - 237));

    // House roof (triangle)
    const roofTop = -0.55, roofBot = -0.05;
    if (ny >= roofTop && ny <= roofBot) {
      const progress = (ny - roofTop) / (roofBot - roofTop);
      const halfW = 0.08 + progress * 0.36;
      if (Math.abs(nx) <= halfW) {
        const shade = 240 + Math.round(15 * (1 - progress));
        r = shade; g = shade; b = shade;
      }
    }
    // House body
    if (ny > roofBot && ny <= 0.44 && Math.abs(nx) <= 0.3) {
      const shade = 240 + Math.round(15 * (1 - (ny - roofBot) / 0.49));
      r = shade; g = shade; b = shade;
    }
    // Door
    if (ny > 0.08 && ny <= 0.44 && Math.abs(nx) <= 0.1) { r = 37; g = 99; b = 235; }
    // Window (eye)
    const wd = Math.sqrt(nx * nx + (ny + 0.08) * (ny + 0.08));
    if (wd < 0.07) { r = 37; g = 99; b = 235; }
    if (wd < 0.035) { r = 96; g = 165; b = 250; }

    return [r, g, b, a];
  };
}

if (!fs.existsSync(ASSETS_DIR)) fs.mkdirSync(ASSETS_DIR, { recursive: true });

const icon = createPNG(1024, 1024, makeRenderLogo(true));
fs.writeFileSync(path.join(ASSETS_DIR, "icon.png"), icon);
console.log(`  icon.png          (1024x1024, ${icon.length} bytes)`);

const adaptive = createPNG(1024, 1024, makeRenderLogo(false));
fs.writeFileSync(path.join(ASSETS_DIR, "adaptive-icon.png"), adaptive);
console.log(`  adaptive-icon.png (1024x1024, ${adaptive.length} bytes)`);
