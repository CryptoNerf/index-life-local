<script>
  import { wordStats } from '../lib/words.js';

  let { entries = [] } = $props();

  const stats = $derived(wordStats(entries));
  const good = $derived(stats.slice(0, 7));
  const bad = $derived(stats.slice(-7).reverse().filter((w) => !good.includes(w)));
</script>

{#if stats.length === 0}
  <p class="empty-sm">Слова появятся, когда наберётся больше заметок (нужно слово в ≥3 днях).</p>
{:else}
  <div class="words-cols">
    <div class="words-col">
      <div class="words-head good">Хорошие дни</div>
      {#each good as w}
        <div class="word-row"><span class="word">{w.word}</span><span class="word-avg">{w.avg.toFixed(1)}</span></div>
      {/each}
    </div>
    <div class="words-col">
      <div class="words-head bad">Трудные дни</div>
      {#each bad as w}
        <div class="word-row"><span class="word">{w.word}</span><span class="word-avg">{w.avg.toFixed(1)}</span></div>
      {/each}
    </div>
  </div>
{/if}
