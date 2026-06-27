import { defineConfig } from 'vitest/config';

// Standalone test config (no Svelte/PWA plugins needed — the libs under test
// are plain JS). Runs in Node so tests can read the shared sync-spec fixtures.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.js']
  }
});
