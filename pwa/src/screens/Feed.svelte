<script>
  import MoodFace from '../components/MoodFace.svelte';
  import { moodStore, refreshEntries } from '../lib/store.svelte.js';
  import { prettyDate } from '../lib/mood.js';

  let { onopen } = $props();

  $effect(() => {
    if (!moodStore.loaded) refreshEntries();
  });

  const entries = $derived(
    moodStore.entries
      .filter((e) => !e.deleted)
      .sort((a, b) => b.date.localeCompare(a.date))
  );
</script>

<section class="screen feed">
  {#if entries.length === 0}
    <p class="empty">Пока нет записей.<br />Откройте «День» и оцените сегодняшний.</p>
  {:else}
    {#each entries as e (e.date)}
      <button class="feed-row" onclick={() => onopen(e.date)}>
        <MoodFace rating={e.rating} size={40} />
        <span class="feed-date">{prettyDate(e.date)}</span>
        <span class="feed-rating">{e.rating}/10</span>
        {#if e.note}<span class="feed-note">{e.note}</span>{/if}
      </button>
    {/each}
  {/if}
</section>
