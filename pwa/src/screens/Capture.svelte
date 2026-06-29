<script>
  import RatingCubes from '../components/RatingCubes.svelte';
  import MoodFace from '../components/MoodFace.svelte';
  import { getEntry } from '../lib/db.js';
  import { saveEntry } from '../lib/store.svelte.js';
  import { scheduleSync } from '../lib/sync-state.svelte.js';
  import { loadDraft, saveDraft, clearDraft } from '../lib/drafts.js';
  import { todayISO, prettyDate, isToday } from '../lib/mood.js';

  let { date = todayISO() } = $props();

  let rating = $state(0);
  let note = $state('');
  let saved = $state(false);

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
    <div class="cap-date">{prettyDate(date)}</div>
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
