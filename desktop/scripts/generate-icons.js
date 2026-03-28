#!/usr/bin/env node
/**
 * Generate all platform icons from the HomePilot SVG logo.
 * Produces proper 256x256 PNG (Linux/fallback), 16x16 tray PNG.
 *
 * For .ico (Windows) and .icns (Mac), electron-builder auto-converts
 * from the 256x256 PNG at build time — no ImageMagick needed.
 *
 * Run: node scripts/generate-icons.js
 */

const fs = require("fs");
const path = require("path");
const zlib = require("zlib");

const ICONS_DIR = path.join(__dirname, "..", "icons");

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
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  return Buffer.concat([
    sig,
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", compressed),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

// ── HomePilot logo renderer ──────────────────────────────────────────────

function renderLogo(x, y, W, H) {
  const nx = (x - W / 2) / (W / 2); // -1..1
  const ny = (y - H / 2) / (H / 2);

  let r = 0,
    g = 0,
    b = 0,
    a = 255;

  // Rounded-rect mask (app icon shape)
  const cornerR = 0.22;
  const edgeX = Math.abs(nx) - (1 - cornerR);
  const edgeY = Math.abs(ny) - (1 - cornerR);
  if (edgeX > 0 && edgeY > 0) {
    const cd = Math.sqrt(edgeX * edgeX + edgeY * edgeY);
    if (cd > cornerR) return [0, 0, 0, 0];
    if (cd > cornerR - 0.02) {
      a = Math.round(255 * ((cornerR - cd) / 0.02));
    }
  }
  if (Math.abs(nx) > 1 || Math.abs(ny) > 1) return [0, 0, 0, 0];

  // Background gradient (top-left blue → bottom-right purple)
  const gt = (nx + ny + 2) / 4; // 0..1 diagonal
  r = Math.round(37 + gt * 87);  // #2563eb → #7c3aed
  g = Math.round(99 - gt * 41);
  b = Math.round(235 - gt * (235 - 237));

  // House roof (triangle)
  const roofTop = -0.55;
  const roofBot = -0.05;
  if (ny >= roofTop && ny <= roofBot) {
    const progress = (ny - roofTop) / (roofBot - roofTop);
    const halfW = 0.08 + progress * 0.36;
    if (Math.abs(nx) <= halfW) {
      // White with subtle gradient
      const shade = 240 + Math.round(15 * (1 - progress));
      r = shade;
      g = shade;
      b = shade;
    }
  }

  // House body
  if (ny > roofBot && ny <= 0.44 && Math.abs(nx) <= 0.30) {
    const shade = 240 + Math.round(15 * (1 - (ny - roofBot) / 0.49));
    r = shade;
    g = shade;
    b = shade;
  }

  // Door
  if (ny > 0.08 && ny <= 0.44 && Math.abs(nx) <= 0.10) {
    r = 37;
    g = 99;
    b = 235;
  }

  // Window (eye) — outer
  const wd = Math.sqrt(nx * nx + (ny + 0.08) * (ny + 0.08));
  if (wd < 0.07) {
    r = 37;
    g = 99;
    b = 235;
  }

  // Window — inner glow
  if (wd < 0.035) {
    r = 96;
    g = 165;
    b = 250;
  }

  return [r, g, b, a];
}

// ── Tray icon (solid blue square) ────────────────────────────────────────

function renderTray(x, y, W, H) {
  const nx = (x - W / 2) / (W / 2);
  const ny = (y - H / 2) / (H / 2);

  // Simple rounded rect
  const cr = 0.2;
  const ex = Math.abs(nx) - (1 - cr);
  const ey = Math.abs(ny) - (1 - cr);
  if (ex > 0 && ey > 0 && Math.sqrt(ex * ex + ey * ey) > cr) {
    return [0, 0, 0, 0];
  }

  // Blue with white house silhouette
  let r = 59, g = 130, b = 246, a = 255;

  // Simplified house shape for tiny icon
  const roofTop = -0.5, roofBot = 0.0;
  if (ny >= roofTop && ny <= roofBot) {
    const p = (ny - roofTop) / (roofBot - roofTop);
    if (Math.abs(nx) <= 0.1 + p * 0.35) {
      r = 255; g = 255; b = 255;
    }
  }
  if (ny > roofBot && ny <= 0.45 && Math.abs(nx) <= 0.3) {
    r = 255; g = 255; b = 255;
  }

  return [r, g, b, a];
}

// ── Generate ─────────────────────────────────────────────────────────────

if (!fs.existsSync(ICONS_DIR)) fs.mkdirSync(ICONS_DIR, { recursive: true });

// Main icon — 256x256 (electron-builder converts to .ico/.icns automatically)
const icon256 = createPNG(256, 256, renderLogo);
fs.writeFileSync(path.join(ICONS_DIR, "icon.png"), icon256);
console.log(`  icon.png     (256x256, ${icon256.length} bytes)`);

// 512x512 for higher-DPI displays
const icon512 = createPNG(512, 512, renderLogo);
fs.writeFileSync(path.join(ICONS_DIR, "512x512.png"), icon512);
console.log(`  512x512.png  (512x512, ${icon512.length} bytes)`);

// Tray icon — 16x16
const tray16 = createPNG(16, 16, renderTray);
fs.writeFileSync(path.join(ICONS_DIR, "tray-icon.png"), tray16);
console.log(`  tray-icon.png (16x16, ${tray16.length} bytes)`);

// Also generate common sizes for Linux hicolor theme
for (const size of [16, 32, 48, 64, 128]) {
  const buf = createPNG(size, size, renderLogo);
  fs.writeFileSync(path.join(ICONS_DIR, `${size}x${size}.png`), buf);
  console.log(`  ${size}x${size}.png  (${buf.length} bytes)`);
}

// ── ICO generation (Windows) ─────────────────────────────────────────────
// ICO format: header + directory entries + PNG image data for each size.
// Modern ICO files can embed PNG data directly (Vista+), which is what we do.

function createICO(pngBuffers) {
  const count = pngBuffers.length;
  const headerSize = 6;
  const dirEntrySize = 16;
  const dirSize = dirEntrySize * count;
  let dataOffset = headerSize + dirSize;

  // ICO header: reserved(2) + type(2, 1=icon) + count(2)
  const header = Buffer.alloc(headerSize);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type = icon
  header.writeUInt16LE(count, 4);

  const dirEntries = [];
  const imageDataParts = [];

  for (const { width, png } of pngBuffers) {
    const entry = Buffer.alloc(dirEntrySize);
    entry[0] = width >= 256 ? 0 : width; // width (0 = 256)
    entry[1] = width >= 256 ? 0 : width; // height
    entry[2] = 0; // color palette
    entry[3] = 0; // reserved
    entry.writeUInt16LE(1, 4); // color planes
    entry.writeUInt16LE(32, 6); // bits per pixel
    entry.writeUInt32LE(png.length, 8); // image data size
    entry.writeUInt32LE(dataOffset, 12); // offset to image data

    dirEntries.push(entry);
    imageDataParts.push(png);
    dataOffset += png.length;
  }

  return Buffer.concat([header, ...dirEntries, ...imageDataParts]);
}

const icoSizes = [16, 32, 48, 64, 128, 256];
const icoPngs = icoSizes.map((size) => ({
  width: size,
  png: createPNG(size, size, renderLogo),
}));
const ico = createICO(icoPngs);
fs.writeFileSync(path.join(ICONS_DIR, "icon.ico"), ico);
console.log(`  icon.ico     (${icoSizes.join("+")}px, ${ico.length} bytes)`);

// ── ICNS generation (macOS) ──────────────────────────────────────────────
// ICNS format: 4-byte magic + 4-byte total size + entries.
// Each entry: 4-byte OSType + 4-byte size (incl header) + PNG data.
// Modern macOS reads PNG-in-ICNS for ic07 (128), ic08 (256), ic09 (512), ic10 (1024).

function createICNS(entries) {
  const magic = Buffer.from("icns");
  let totalSize = 8; // magic + size field
  const parts = [];

  for (const { osType, png } of entries) {
    const entrySize = 8 + png.length;
    const header = Buffer.alloc(8);
    header.write(osType, 0, 4, "ascii");
    header.writeUInt32BE(entrySize, 4);
    parts.push(header, png);
    totalSize += entrySize;
  }

  const sizeBuffer = Buffer.alloc(4);
  sizeBuffer.writeUInt32BE(totalSize);

  return Buffer.concat([magic, sizeBuffer, ...parts]);
}

const icnsEntries = [
  { osType: "ic07", png: createPNG(128, 128, renderLogo) },
  { osType: "ic08", png: createPNG(256, 256, renderLogo) },
  { osType: "ic09", png: createPNG(512, 512, renderLogo) },
  { osType: "ic10", png: createPNG(1024, 1024, renderLogo) },
];
const icns = createICNS(icnsEntries);
fs.writeFileSync(path.join(ICONS_DIR, "icon.icns"), icns);
console.log(`  icon.icns    (128+256+512+1024px, ${icns.length} bytes)`);

console.log("\nDone! Icons written to desktop/icons/");
