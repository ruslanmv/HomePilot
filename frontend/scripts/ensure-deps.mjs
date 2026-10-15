#!/usr/bin/env node
/**
 * Runs before `npm run dev` (the "predev" script): makes sure node_modules has
 * what package.json asks for.
 *
 * The start commands (`make start`, `make start-frontend`, `make dev`) only ran
 * `npm install` when node_modules did not exist at all, so a dependency added by
 * a `git pull` was never installed and Vite stopped with
 * "Failed to resolve import". This compares every direct dependency with the
 * version package-lock.json pins, and runs `npm install` only when one is
 * missing or different — otherwise it costs a few milliseconds.
 *
 * Set HOMEPILOT_SKIP_DEPS_CHECK=1 to skip it.
 */
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    return null
  }
}

/**
 * Direct dependencies of the package in `root` that are not installed, or not
 * at the version its package-lock.json pins. [{ name, reason }]
 */
export function staleDependencies(root) {
  const pkg = readJson(path.join(root, 'package.json'))
  if (!pkg) return []
  const pinned = readJson(path.join(root, 'package-lock.json'))?.packages || {}
  const names = Object.keys({ ...(pkg.dependencies || {}), ...(pkg.devDependencies || {}) })
  const stale = []
  for (const name of names) {
    const installed = readJson(path.join(root, 'node_modules', name, 'package.json'))
    if (!installed) {
      stale.push({ name, reason: 'not installed' })
      continue
    }
    // Linked (file:) packages have no pinned version; existence is enough.
    const want = pinned[`node_modules/${name}`]?.version
    if (want && installed.version !== want) {
      stale.push({ name, reason: `${installed.version} installed, ${want} expected` })
    }
  }
  return stale
}

function npmInstall(root) {
  // Inside `npm run`, npm_execpath is npm itself: run it with this Node, so it
  // works the same on Linux, macOS, WSL and Windows.
  const npmCli = process.env.npm_execpath
  const args = ['install', '--no-audit', '--no-fund']
  const res = npmCli && /npm-cli\.c?js$/.test(npmCli)
    ? spawnSync(process.execPath, [npmCli, ...args], { cwd: root, stdio: 'inherit' })
    : spawnSync('npm', args, { cwd: root, stdio: 'inherit', shell: process.platform === 'win32' })
  return res.status === 0
}

function main() {
  if (process.env.HOMEPILOT_SKIP_DEPS_CHECK === '1') return
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const stale = staleDependencies(root)
  if (!stale.length) return
  const shown = stale.slice(0, 5).map((s) => `${s.name} (${s.reason})`).join(', ')
  const more = stale.length > 5 ? ` and ${stale.length - 5} more` : ''
  console.log(`[homepilot] Frontend dependencies changed: ${shown}${more}. Running npm install…`)
  if (!npmInstall(root)) {
    console.error('[homepilot] npm install failed. Run it yourself, then start again:  cd frontend && npm install')
    process.exit(1)
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main()
