<script>
  import { moodStore } from '../lib/store.svelte.js';
  import { isUnlocked } from '../lib/vault.js';
  import { syncState } from '../lib/sync-state.svelte.js';

  let { onfix } = $props();
  let dismissed = $state(false); // session-only: reappears next open if still at risk

  // At risk = there are entries, but no durable copy (cloud never synced).
  const atRisk = $derived(
    moodStore.entries.filter((e) => !e.deleted).length > 0 &&
    !(isUnlocked() && syncState.lastSyncedAt > 0)
  );
</script>

{#if atRisk && !dismissed}
  <div class="dur-banner">
    <span>Записи пока только на этом телефоне. Подключите облако, чтобы не потерять их.</span>
    <div class="dur-banner-actions">
      <button class="dur-banner-btn" onclick={onfix}>Подключить</button>
      <button class="dur-banner-x" onclick={() => (dismissed = true)} aria-label="Скрыть">×</button>
    </div>
  </div>
{/if}
