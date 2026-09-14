/// <reference types="vitest/config" />
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vitest/config'

const FRONTEND_DIR = path.dirname(fileURLToPath(import.meta.url))
const PACKAGES_DIR = path.resolve(FRONTEND_DIR, '../packages')

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx,js,jsx}'],
    css: false,
  },
  // This has to match vite.config.ts, and it did not.
  //
  // The source tree still carries stale `.js`/`.jsx` mirrors of files that have since become
  // `.ts`/`.tsx` — `voice/useVoiceController.js` is from the first commit and has not been
  // touched since. Vite's default extension order puts `.js` before `.ts`, so a bare import
  // like `./voice/useVoiceController` resolves to the mirror. vite.config.ts flips the order
  // for exactly that reason; this file did not, so **the app was built from the TypeScript
  // and the tests were run against the dead JavaScript**.
  //
  // That is the worst possible shape for a test suite: it passes, and it is measuring
  // something nobody ships. It is also the explanation for a jsdom harness written during the
  // voice work that passed against code known to be broken — it was importing the mirror,
  // which did not contain the bug.
  //
  // Once the duplicate source tree is gone, both overrides become no-ops and can go with it.
  resolve: {
    alias: [
      { find: /^@homepilot\/(.*)$/, replacement: `${PACKAGES_DIR}/$1/src` },
    ],
    extensions: ['.tsx', '.ts', '.mts', '.jsx', '.js', '.mjs', '.json'],
  },
})
