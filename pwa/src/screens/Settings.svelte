<script>
  import { exportMarkdown } from '../lib/markdown.js';
  import { requestPersist, isPersisted } from '../lib/db.js';

  let persisted = $state(null);

  $effect(() => {
    isPersisted().then((v) => (persisted = v));
  });

  async function protect() {
    persisted = await requestPersist();
  }
</script>

<section class="screen settings">
  <h2>Данные</h2>
  <button class="row-btn" onclick={exportMarkdown}>⬇️ Экспортировать в Markdown</button>
  <p class="hint">
    Человекочитаемая копия всех записей. Храните её где угодно — данные не
    заперты в приложении.
  </p>

  {#if persisted === false}
    <button class="row-btn" onclick={protect}>🛡 Защитить хранилище от очистки</button>
    <p class="hint">
      Браузер может вытеснять данные сайтов. Эта настройка просит ОС сохранять
      ваш дневник. Скоро добавим синхронизацию в ваше облако — тогда копия будет
      всегда и на новом телефоне восстановится по паролю.
    </p>
  {:else if persisted === true}
    <p class="hint">🛡 Хранилище защищено от автоматической очистки.</p>
  {/if}

  <h2>О приложении</h2>
  <p class="hint">
    index.life — локальный дневник настроения. Данные хранятся только на этом
    устройстве. Синхронизация с компьютером через зашифрованное облако появится
    в следующих версиях. ИИ-психолог работает в десктоп-версии — телефон его
    пока не тянет.
  </p>
</section>
