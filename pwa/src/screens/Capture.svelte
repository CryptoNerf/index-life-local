<script>
  import RatingCubes from '../components/RatingCubes.svelte';
  import MoodFace from '../components/MoodFace.svelte';
  import { getEntry } from '../lib/db.js';
  import { saveEntry } from '../lib/store.svelte.js';
  import { scheduleSync } from '../lib/sync-state.svelte.js';
  import { loadDraft, saveDraft, clearDraft } from '../lib/drafts.js';
  import { todayISO, prettyDate, isToday, addDays } from '../lib/mood.js';

  // Bindable so date navigation here propagates to the app (and "День" in the
  // nav resets it to today). Any past day can be opened to backfill it.
  let { date = $bindable(todayISO()) } = $props();

  let rating = $state(0);
  let note = $state('');
  let saved = $state(false);

  const TODAY = todayISO();
  function step(n) {
    const next = addDays(date, n);
    date = next > TODAY ? TODAY : next; // never log a future day
  }

  // Load whenever the target day changes. An unsaved draft (from a previous
  // visit where the user typed but didn't save) takes priority over the saved
  // entry, so nothing is ever lost on tab switch / app restart.
  $effect(() => {
    const d = date;
    getEntry(d).then((e) => {
      const draft = loadDraft(d);
      rating = draft?.rating ?? e?.rating ?? 0;
      note = draft?.note ?? e?.note ?? '';
    });
  });

  // Persist every edit immediately so leaving this screen never drops text.
  function touch() {
    saveDraft(date, { rating, note });
  }

  function setRating(v) {
    rating = v;
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
    <MoodFace {rating} size={92} />
  </header>

  <RatingCubes value={rating} onchange={setRating} />

  <textarea class="note" bind:value={note} oninput={touch}
            placeholder="Как прошёл день?"></textarea>

  <button class="save-btn" class:is-saved={saved} disabled={!rating} onclick={save}>
    {saved ? 'Сохранено ✓' : 'Сохранить'}
  </button>
</section>
