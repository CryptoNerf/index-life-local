import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { VitePWA } from 'vite-plugin-pwa';

// base '/' — the app is served from the root of its own domain (the chosen
// static-CDN host). A relative base ('./') breaks the dev server (404 at /),
// and isn't needed now that we're not targeting a GitHub Pages subpath.
export default defineConfig({
  base: '/',
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
