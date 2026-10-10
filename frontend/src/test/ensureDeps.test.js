/**
 * `npm run dev` first checks that node_modules has what package.json asks for
 * (scripts/ensure-deps.mjs). A dependency added by a pull — react-easy-crop for
 * Edit Profile Picture — used to stop Vite with "Failed to resolve import"
 * because the start commands only installed when node_modules was missing.
 */
import { afterEach, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { staleDependencies } from '../../scripts/ensure-deps.mjs'

const dirs = []
afterEach(() => { for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true }) })

function project({ deps = {}, devDeps = {}, lock = {}, installed = {} }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hp-deps-'))
  dirs.push(root)
  const write = (rel, data) => {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true })
    fs.writeFileSync(path.join(root, rel), JSON.stringify(data))
  }
  write('package.json', { name: 'x', dependencies: deps, devDependencies: devDeps })
  if (lock) {
    const packages = { '': {} }
    for (const [name, version] of Object.entries(lock)) packages[`node_modules/${name}`] = { version }
    write('package-lock.json', { lockfileVersion: 3, packages })
  }
  for (const [name, version] of Object.entries(installed)) write(`node_modules/${name}/package.json`, { name, version })
  return root
}

describe('the dependency check before npm run dev', () => {
  it('is quiet when everything is installed at the pinned versions', () => {
    const root = project({
      deps: { react: '^18.3.1', 'react-easy-crop': '6.2.3' },
      devDeps: { vite: '^5.0.0' },
      lock: { react: '18.3.1', 'react-easy-crop': '6.2.3', vite: '5.4.0' },
      installed: { react: '18.3.1', 'react-easy-crop': '6.2.3', vite: '5.4.0' },
    })
    expect(staleDependencies(root)).toEqual([])
  })

  it('finds a dependency a pull added but nobody installed', () => {
    const root = project({
      deps: { react: '^18.3.1', 'react-easy-crop': '6.2.3' },
      lock: { react: '18.3.1', 'react-easy-crop': '6.2.3' },
      installed: { react: '18.3.1' },
    })
    expect(staleDependencies(root)).toEqual([{ name: 'react-easy-crop', reason: 'not installed' }])
  })

  it('finds one installed at a different version from the lockfile', () => {
    const root = project({
      devDeps: { vite: '^5.0.0' },
      lock: { vite: '5.4.0' },
      installed: { vite: '5.1.0' },
    })
    expect(staleDependencies(root)).toEqual([{ name: 'vite', reason: '5.1.0 installed, 5.4.0 expected' }])
  })

  it('without a lockfile, only checks that each one is there', () => {
    const root = project({ deps: { a: '^1.0.0', b: '^2.0.0' }, lock: null, installed: { a: '1.9.0' } })
    expect(staleDependencies(root).map((s) => s.name)).toEqual(['b'])
  })

  it('npm run dev runs the check first, and it reads the real frontend files', () => {
    const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
    expect(Array.isArray(staleDependencies(frontend))).toBe(true)
    const pkg = JSON.parse(fs.readFileSync(path.join(frontend, 'package.json'), 'utf8'))
    expect(pkg.scripts.predev).toBe('node scripts/ensure-deps.mjs')
  })
})
