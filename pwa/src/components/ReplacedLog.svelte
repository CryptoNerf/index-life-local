<script>
  // What a sync overwrote here, and a way to take it back.
  //
  // Last-write-wins means one side loses when the same day was edited in two
  // places. Losing silently is unacceptable for a diary, so every replaced
  // local version is kept for 30 days and shown here with its text.
  import { listConflicts, markSeen, forgetConflict } from '../lib/conflicts.js';
  import { saveEntry } from '../lib/store.svelte.js';
  import { scheduleSync } from '../lib/sync-state.svelte.js';
  import { prettyDate } from '../lib/mood.js';

  let rows = $state(listConflicts());
  let open = $state(false);

  function toggle() {
    open = !open;
    if (open) {
      rows = listConflicts();
      markSeen();
    }
  }

  // Write the old text back as a fresh edit: a newer updated_at makes it win
  // the next merge, so the restore reaches the other devices too.
  async function restore(row) {
    await saveEntry({ date: row.date, rating: row.rating, note: row.note ?? '' });
    forgetConflict(row.at, row.date);
    rows = listConflicts();
    scheduleSync();
  }

  function dismiss(row) {
    forgetConflict(row.at, row.date);
    rows = listConflicts();
  }
</script>

{#if rows.length}
  <button class="link-btn" onclick={toggle}>
    {open ? 'Скрыть' : `Заменённые записи (${rows.length})`}
  </button>

  {#if open}
    <p class="hint">
      Эти дни правились и здесь, и на другом устройстве. Осталась версия, которая
      была сохранена позже — ваша прежняя версия хранится тут 30 дней.
    </p>
    {#each rows as r (r.at + r.date)}
      <div class="repl-row">
        <div class="repl-head">{prettyDate(r.date)} · было {r.rating}/10</div>
        {#if r.note}<div class="repl-note">{r.note}</div>{/if}
        <div class="repl-actions">
          <button class="row-btn repl-btn" onclick={() => restore(r)}>Вернуть эту версию</button>
          <button class="link-btn repl-btn" onclick={() => dismiss(r)}>Убрать</button>
        </div>
      </div>
    {/each}
  {/if}
{/if}

<style>
  .repl-row {
    border: 1px solid var(--line, #e0e0e0);
    padding: 10px 12px;
    margin: 8px 0;
  }
  .repl-head { font-size: 14px; margin-bottom: 4px; }
  .repl-note {
    font-size: 14px;
    line-height: 1.45;
    white-space: pre-wrap;
    color: var(--text-2, #555);
    margin-bottom: 8px;
  }
  .repl-actions { display: flex; gap: 8px; align-items: center; }
  .repl-btn { margin: 0; }
</style>
