<script>
  import CloudSync from '../components/CloudSync.svelte';
  import Durability from '../components/Durability.svelte';
  import { loadAppearance, saveAppearance, applyAppearance } from '../lib/theme.js';

  let look = $state(loadAppearance());

  function update(patch) {
    look = { ...look, ...patch };
    saveAppearance(look);
    applyAppearance(look);
  }

  const THEMES = [['system', 'Системная'], ['light', 'Светлая'], ['dark', 'Тёмная']];
  const FONTS = [['serif', 'Засечки'], ['sans', 'Без засечек']];
</script>

<section class="screen settings">
  <h2>Синхронизация</h2>
  <CloudSync />

  <h2>Сохранность данных</h2>
  <Durability />

  <h2>Оформление</h2>

  <div class="opt-label">Тема</div>
  <div class="seg">
    {#each THEMES as [val, label]}
      <button class="seg-btn" class:on={look.theme === val} onclick={() => update({ theme: val })}>
        {label}
      </button>
    {/each}
  </div>

  <div class="opt-label">Шрифт заметок</div>
  <div class="seg">
    {#each FONTS as [val, label]}
      <button class="seg-btn" class:on={look.font === val} onclick={() => update({ font: val })}>
        {label}
      </button>
    {/each}
  </div>

  <h2>О приложении</h2>
  <p class="hint">
    index.life — локальный дневник настроения. Данные хранятся на этом устройстве и
    зашифрованно синхронизируются в ваше облако. ИИ-психолог работает в десктоп-версии —
    телефон его пока не тянет.
  </p>
</section>
