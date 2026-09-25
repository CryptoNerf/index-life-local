import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { VitePWA } from 'vite-plugin-pwa';

// Served from GitHub Pages at cryptonerf.github.io/index-life-local/ — the
// project's own subpath on a free host, after the custom domain lapsed. The
// base must be absolute: a relative one ('./') breaks the dev server. The PWA
// plugin derives the manifest's scope and start_url and the service worker's
// scope from it, so the worker stays inside this path and never answers for
// the other projects that share the cryptonerf.github.io origin.
export const BASE = '/index-life-local/';

export default defineConfig({
  base: BASE,
  // Allow cloudflared tunnel hostnames so the dev/preview server doesn't reject
  // requests whose Host is *.trycloudflare.com (used to test on a real phone).
  server: { allowedHosts: ['.trycloudflare.com'] },
  preview: { allowedHosts: ['.trycloudflare.com'] },
  plugins: [
    svelte(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icons/apple-touch-icon.png'],
      manifest: {
        name: 'index.life',
        short_name: 'index.life',
        description: 'Локальный дневник настроения',
        lang: 'ru',
        theme_color: '#ffffff',
        background_color: '#ffffff',
        display: 'standalone',
        orientation: 'portrait',
        icons: [
          { src: 'icons/android-chrome-192x192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icons/android-chrome-512x512.png', sizes: '512x512', type: 'image/png' },
          { src: 'icons/android-chrome-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' }
        ]
      }
    })
  ]
});
