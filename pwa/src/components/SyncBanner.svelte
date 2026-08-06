<script>
  // Says out loud when a configured sync has stopped working.
  //
  // A cloud session can end while the app looks perfectly connected: Google
  // access tokens last about an hour and a browser PWA cannot renew one
  // without a tap. Before this banner the failure was invisible — background
  // syncs are silent by design, and the settings screen still read
  // "encrypted · Google Drive". The phone quietly drifted out of sync.
  import { syncState, reconnectAndSync, syncIsStale } from '../lib/sync-state.svelte.js';
  import { timeAgo } from '../lib/mood.js';

  let busy = $state(false);
  let dismissed = $state(false); // session-only: comes back next open if still broken

  const expired = $derived(syncState.status === 'auth');
  // Staleness is re-evaluated whenever a sync finishes (lastSyncedAt is
  // reactive), which is the only moment it can change in practice.
  const stale = $derived(syncState.lastSyncedAt >= 0 && syncIsStale());
  const show = $derived((expired || stale) && !dismissed);

  async function fix() {
    busy = true;
    try {
      await reconnectAndSync();
    } finally {
      busy = false;
    }
  }
</script>

{#if show}
  <div class="sync-banner" class:warn={expired}>
    <span>
      {#if expired}
        Сессия облака истекла — записи с телефона пока не уходят.
      {:else}
        Последняя синхронизация: {timeAgo(syncState.lastSyncedAt)}.
      {/if}
    </span>
    <div class="sync-banner-actions">
      <button class="sync-banner-btn" onclick={fix} disabled={busy}>
        {busy ? 'Минуту…' : expired ? 'Войти' : 'Обновить'}
      </button>
      <button class="sync-banner-x" onclick={() => (dismissed = true)} aria-label="Скрыть">×</button>
    </div>
  </div>
{/if}

<style>
  .sync-banner {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    font-size: 14px;
    line-height: 1.4;
    background: var(--surface-2, #f2f2f2);
    color: var(--text, #222);
    border-bottom: 1px solid var(--line, #e0e0e0);
  }
  .sync-banner.warn {
    background: #fdf6e3;
    color: #6a5d2a;
    border-bottom-color: #e0c14a;
  }
  .sync-banner span { flex: 1; min-width: 0; }
  .sync-banner-actions { display: flex; align-items: center; gap: 4px; flex: none; }
  .sync-banner-btn {
    background: transparent;
    border: 1px solid currentColor;
    color: inherit;
    font: inherit;
    font-size: 13px;
    padding: 4px 10px;
    cursor: pointer;
  }
  .sync-banner-btn:disabled { opacity: 0.6; }
  .sync-banner-x {
    background: none;
    border: none;
    color: inherit;
    font-size: 20px;
    line-height: 1;
    padding: 0 4px;
    cursor: pointer;
    opacity: 0.6;
  }
</style>
