<script>
  import { onMount } from 'svelte';
  import * as vault from '../lib/vault.js';
  import { getProvider, setProvider, getTransport, runSync, syncState } from '../lib/sync-state.svelte.js';
  import { timeAgo } from '../lib/mood.js';

  let provider = $state(getProvider()); // 'yandex' | 'google' | null
  let connected = $state(false);
  let busy = $state(false);
  let error = $state('');
  let st = $state({ enabled: false, unlocked: false, vaultInFolder: false });

  let pass = $state('');
  let pass2 = $state('');
  let recoveryShown = $state('');
  let recoveryInput = $state('');
  let useRecovery = $state(false);

  const providerName = $derived(
    provider === 'yandex' ? 'Яндекс.Диск' : provider === 'google' ? 'Google Drive' : 'облако'
  );

  // Rediscover persistent state on (re)mount so a tab switch doesn't forget
  // we're connected / set up.
  onMount(() => {
    provider = getProvider();
    st = { enabled: vault.isEncryptionEnabled(), unlocked: vault.isUnlocked(), vaultInFolder: false };
    if (provider) {
      connected = getTransport().isConnected();
      if (connected) refresh();
    }
  });

  async function refresh() {
    st = await vault.status(getTransport());
  }

  async function run(fn) {
    error = '';
    busy = true;
    try {
      await fn();
    } catch (e) {
      error = e?.message || String(e);
    } finally {
      busy = false;
    }
  }

  function chooseProvider(name) {
    setProvider(name);
    provider = name;
    connected = getTransport().isConnected();
  }

  const connect = () => run(async () => {
    await getTransport().connect();
    connected = true;
    await refresh();
  });

  const enable = () => run(async () => {
    if (pass.length < 8) throw new Error('Пароль-фраза минимум 8 символов');
    if (pass !== pass2) throw new Error('Пароль-фразы не совпадают');
    const r = await vault.enableEncryption(getTransport(), pass);
    recoveryShown = r.recoveryKey;
    pass = '';
    pass2 = '';
    await refresh();
  });

  const unlock = () => run(async () => {
    if (useRecovery) await vault.unlockWithRecovery(getTransport(), recoveryInput);
    else await vault.unlockWithPassphrase(getTransport(), pass);
    pass = '';
    recoveryInput = '';
    await refresh();
  });

  async function doSync() {
    error = '';
    const t = getTransport();
    if (!t.isConnected()) {
      try {
        await t.connect();
        connected = true;
      } catch (e) {
        error = e?.message || 'Не удалось подключить облако';
        return;
      }
    }
    await runSync();
  }

  function lock() {
    vault.lock();
    refresh();
  }
</script>

<div class="cloud">
  {#if recoveryShown}
    <div class="enc-recovery">
      <div class="enc-recovery-title">🔑 Запасной ключ восстановления</div>
      <code class="enc-recovery-key">{recoveryShown}</code>
      <p class="enc-recovery-hint">
        <b>Зачем он:</b> если вы забудете пароль-фразу, этот ключ — единственный способ
        вернуть доступ к зашифрованным данным.<br />
        <b>Что сделать:</b> сохраните его в надёжном месте — менеджер паролей или скриншот.
        Показывается один раз; любой, у кого он есть, сможет расшифровать дневник.
      </p>
      <button class="enc-done-btn" onclick={() => (recoveryShown = '')}>Я сохранил(а) ключ</button>
    </div>

  {:else if st.unlocked}
    <div class="cloud-status">🔒 Зашифровано · {providerName}</div>
    <button class="save-btn" onclick={doSync} disabled={syncState.status === 'syncing'}>
      {syncState.status === 'syncing' ? 'Синхронизация…' : 'Синхронизировать'}
    </button>
    <p class="hint">
      {#if syncState.status === 'error'}⚠ {syncState.error}
      {:else}Последняя синхронизация: {timeAgo(syncState.lastSyncedAt)}{/if}
    </p>
    <button class="link-btn" onclick={lock}>Заблокировать на этом устройстве</button>

  {:else if !provider}
    <div class="cloud-status">Куда синхронизировать?</div>
    <button class="row-btn" onclick={() => chooseProvider('yandex')}>🟡 Яндекс.Диск</button>
    <button class="row-btn" onclick={() => chooseProvider('google')}>☁️ Google Drive</button>
    <p class="hint">
      В России — <b>Яндекс.Диск</b> (работает без VPN). Google Drive — если он у вас
      открывается. Данные в любом случае шифруются на телефоне, облако видит только
      шифротекст.
    </p>

  {:else if !connected}
    <button class="row-btn" onclick={connect} disabled={busy}>
      ☁️ {busy ? 'Подключение…' : `Подключить ${providerName}`}
    </button>
    <p class="hint">Ключ шифрования остаётся на устройстве — облако его не видит.</p>
    <button class="link-btn" onclick={() => { provider = null; connected = false; }}>
      Выбрать другое облако
    </button>

  {:else if st.vaultInFolder}
    <div class="cloud-status">🔒 Папка зашифрована — разблокируйте</div>
    {#if !useRecovery}
      <input class="field" type="password" bind:value={pass} placeholder="Пароль-фраза" />
      <button class="save-btn" onclick={unlock} disabled={busy}>Разблокировать</button>
      <button class="link-btn" onclick={() => (useRecovery = true)}>Использовать ключ восстановления</button>
    {:else}
      <input class="field" type="text" bind:value={recoveryInput} placeholder="Ключ восстановления" />
      <button class="save-btn" onclick={unlock} disabled={busy}>Разблокировать</button>
      <button class="link-btn" onclick={() => (useRecovery = false)}>Назад к паролю</button>
    {/if}

  {:else}
    <div class="cloud-status">Придумайте пароль-фразу</div>
    <p class="hint">
      Этой фразой дневник шифруется перед отправкой в облако — без неё облачную
      синхронизацию не включить. Её же вы введёте, чтобы открыть дневник на другом
      устройстве, поэтому запомните её или сохраните в менеджере паролей.
    </p>
    <input class="field" type="password" bind:value={pass} placeholder="Пароль-фраза (мин. 8 символов)" />
    <input class="field" type="password" bind:value={pass2} placeholder="Повторите пароль-фразу" />
    <button class="save-btn" onclick={enable} disabled={busy}>Включить шифрование</button>
  {/if}

  {#if error}<p class="cloud-error">{error}</p>{/if}
</div>
