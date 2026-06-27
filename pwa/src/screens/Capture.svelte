<script>
  import RatingCubes from '../components/RatingCubes.svelte';
  import MoodFace from '../components/MoodFace.svelte';
  import { getEntry, putEntry } from '../lib/db.js';
  import { todayISO, prettyDate, isToday } from '../lib/mood.js';

  let { date = todayISO() } = $props();

  let rating = $state(0);
  let note = $state('');
  let saved = $state(false);

  // Reload whenever the target day changes (e.g. opened from the feed).
  $effect(() => {
    const d = date;
    getEntry(d).then((e) => {
      rating = e?.rating ?? 0;
      note = e?.note ?? '';
    });
  });

  async function save() {
    if (!rating) return;
    await putEntry({ date, rating, note });
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

  <RatingCubes value={rating} onchange={(v) => (rating = v)} />

  <textarea class="note" bind:value={note} placeholder="Как прошёл день?"></textarea>

  <button class="save-btn" class:is-saved={saved} disabled={!rating} onclick={save}>
    {saved ? 'Сохранено ✓' : 'Сохранить'}
  </button>
</section>
