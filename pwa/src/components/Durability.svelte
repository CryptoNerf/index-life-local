<script>
  import { exportMarkdown } from '../lib/markdown.js';
  import { moodStore } from '../lib/store.svelte.js';
  import { isUnlocked } from '../lib/vault.js';
  import { syncState } from '../lib/sync-state.svelte.js';
  import { durability, refreshPersisted, enablePersist } from '../lib/durability.svelte.js';

  $effect(() => {
    refreshPersisted();
  });

  const cloud = $derived(isUnlocked() && syncState.lastSyncedAt > 0);
  const count = $derived(moodStore.entries.filter((e) => !e.deleted).length);
</script>

<div class="durability">
  <div class="dur-row" class:ok={cloud}>
    <span class="dur-ico">{cloud ? '✓' : '○'}</span>
    <div>
      <div class="dur-title">Резервная копия в облаке</div>
      <div class="dur-sub">
        {#if cloud}
          Дневник зашифрованно дублируется в Google Drive — восстановится на новом
          устройстве по пароль-фразе.
        {:else}
          Главная защита от потери. Подключите облако в разделе «Синхронизация» выше.
        {/if}
      </div>
    </div>
  </div>

  <div class="dur-row" class:ok={durability.persisted === true}>
    <span class="dur-ico">{durability.persisted === true ? '✓' : '○'}</span>
    <div>
      <div class="dur-title">Защита хранилища от очистки</div>
      <div class="dur-sub">
        {#if durability.persisted === true}
          Браузер не вытеснит ваш дневник при нехватке места.
        {:else}
          <button class="link-btn" onclick={enablePersist}>Попросить браузер сохранять данные</button>
        {/if}
      </div>
    </div>
  </div>

  <div class="dur-row">
    <span class="dur-ico">⬇</span>
    <div>
      <div class="dur-title">Экспорт в Markdown</div>
      <div class="dur-sub">
        Человекочитаемая копия, не зависящая от приложения.
        <button class="link-btn" onclick={exportMarkdown}>Скачать ({count})</button>
      </div>
    </div>
  </div>
</div>
