<script>
  import RatingCubes from '../components/RatingCubes.svelte';
  import MoodFace from '../components/MoodFace.svelte';
  import { getEntry } from '../lib/db.js';
  import { moodStore, saveEntry } from '../lib/store.svelte.js';
  import { scheduleSync } from '../lib/sync-state.svelte.js';
  import { loadDraft, saveDraft, clearDraft, editorStateFor } from '../lib/drafts.js';
  import { currentStreak } from '../lib/stats.js';
  import { todayISO, prettyDate, isToday, addDays, pluralDays } from '../lib/mood.js';

  // Bindable so date navigation here propagates to the app (and "День" in the
  // nav resets it to today). Any past day can be opened to backfill it.
  let { date = $bindable(todayISO()) } = $props();

  let rating = $state(0);
  let note = $state('');
  let saved = $state(false);
  // The day exists here only as a tombstone: it was deleted on another
  // device. A tombstone keeps its old text (that is how the deletion travels
  // to devices that still hold the entry), so loading it into the editor
  // would show content the user deliberately deleted — and any save would
  // push it back to the desktop, resurrecting it.
  let deletedElsewhere = $state(false);

  const TODAY = todayISO();
  function step(n) {
    const next = addDays(date, n);
    date = next > TODAY ? TODAY : next; // never log a future day
  }

  // Logging streak — the little daily-habit reward. Reactive off the shared
  // store, so it bumps the moment today's entry is saved.
  const streak = $derived(currentStreak(moodStore.entries, TODAY));

  // Load whenever the target day changes. An unsaved draft (from a previous
  // visit where the user typed but didn't save) takes priority over the saved
  // entry — but only while it's the fresher of the two: an entry edited on
  // another device and synced later must not be hidden behind a stale draft
  // (see draftIsFresh).
  $effect(() => {
    const d = date;
    getEntry(d).then((e) => {
      const view = editorStateFor(e, loadDraft(d));
      rating = view.rating;
      note = view.note;
      deletedElsewhere = view.deletedElsewhere;
    });
  });

  // Persist every edit immediately so leaving this screen never drops text.
  function touch() {
    saveDraft(date, { rating, note });
  }

  function setRating(v) {
    rating = v;
    deletedElsewhere = false;   // writing again is a deliberate revival
    touch();
  }

  async function save() {
    if (!rating) return;
    await saveEntry({ date, rating, note });
    clearDraft(date);
    scheduleSync(); // push to the cloud shortly after (debounced)
    saved = true;
    setTimeout(() => (saved = false), 1500);
  }
</script>

<section class="screen capture">
  <header class="cap-head">
    <div class="cap-nav">
      <button class="cap-arrow" onclick={() => step(-1)} aria-label="Предыдущий день">‹</button>
      <label class="cap-date">
        {prettyDate(date)}<span class="cap-date-caret">▾</span>
        <input type="date" class="cap-date-input" bind:value={date} max={TODAY} />
      </label>
      <button class="cap-arrow" onclick={() => step(1)} disabled={date >= TODAY}
              aria-label="Следующий день">›</button>
    </div>
    {#if isToday(date)}<div class="cap-today">сегодня</div>{/if}
    {#if streak >= 2 && isToday(date)}
      <div class="cap-streak">▪ {streak} {pluralDays(streak)} подряд</div>
    {/if}
    <MoodFace {rating} size={92} />
  </header>

  {#if deletedElsewhere}
    <p class="cap-deleted">
      Эта запись удалена на другом устройстве. Поставьте оценку, чтобы завести
      день заново.
    </p>
  {/if}

  <RatingCubes value={rating} onchange={setRating} />

  <textarea class="note" bind:value={note} oninput={() => { deletedElsewhere = false; touch(); }}
            placeholder="Как прошёл день?"></textarea>

  <button class="save-btn" class:is-saved={saved} disabled={!rating} onclick={save}>
    {saved ? 'Сохранено ✓' : 'Сохранить'}
  </button>
</section>
