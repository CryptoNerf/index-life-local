<script>
  // Year-at-a-glance grid — the phone twin of the desktop's mood_grid
  // (the app's "face"). 12 month rows × 31 day cells; a logged day is an
  // ink square whose opacity scales with the rating, so the year reads as
  // a monochrome mood texture. Visual overview only: the cells are too
  // small for reliable tapping — days are opened via the Feed or the
  // Capture date picker.
  import { moodStore, refreshEntries } from '../lib/store.svelte.js';
  import { todayISO } from '../lib/mood.js';

  $effect(() => {
    if (!moodStore.loaded) refreshEntries();
  });

  const TODAY = todayISO();
  const CURRENT_YEAR = Number(TODAY.slice(0, 4));
  let year = $state(CURRENT_YEAR);

  const rated = $derived(
    moodStore.entries.filter((e) => !e.deleted && e.rating >= 1)
  );
  const byDate = $derived(new Map(rated.map((e) => [e.date, e.rating])));

  // Years with data (plus the current one), for the ‹ › switcher bounds.
  const years = $derived.by(() => {
    const ys = new Set(rated.map((e) => Number(e.date.slice(0, 4))));
    ys.add(CURRENT_YEAR);
    return [...ys].sort((a, b) => a - b);
  });

  const yearEntries = $derived(rated.filter((e) => Number(e.date.slice(0, 4)) === year));
  const yearAvg = $derived(
    yearEntries.length
      ? (yearEntries.reduce((s, e) => s + e.rating, 0) / yearEntries.length).toFixed(1)
      : null
  );

  const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

  const daysIn = (y, m) => new Date(y, m + 1, 0).getDate();
  const p2 = (n) => String(n).padStart(2, '0');
  const iso = (y, m, d) => `${y}-${p2(m + 1)}-${p2(d)}`;

  // Monochrome intensity: 1/10 is barely-there ink, 10/10 is solid.
  const cellOpacity = (rating) => 0.15 + 0.85 * (rating / 10);

  function step(n) {
    const idx = years.indexOf(year);
    const next = years[idx + n];
    if (next !== undefined) year = next;
  }
</script>

<section class="screen year">
  <h2 class="screen-title">Год</h2>

  <div class="year-nav">
    <button class="cap-arrow" onclick={() => step(-1)}
            disabled={years.indexOf(year) === 0} aria-label="Предыдущий год">‹</button>
    <span class="year-label">{year}</span>
    <button class="cap-arrow" onclick={() => step(1)}
            disabled={years.indexOf(year) === years.length - 1}
            aria-label="Следующий год">›</button>
  </div>

  <div class="year-grid">
    {#each MONTHS as label, m}
      <div class="year-row">
        <span class="year-month">{label}</span>
        <div class="year-cells">
          {#each Array(31) as _, i}
            {@const day = i + 1}
            {#if day <= daysIn(year, m)}
              {@const rating = byDate.get(iso(year, m, day))}
              <span class="year-cell"
                    class:is-today={iso(year, m, day) === TODAY}
                    style={rating ? `background: var(--ink); opacity: ${cellOpacity(rating)}` : ''}
                    title="{iso(year, m, day)}{rating ? ` — ${rating}/10` : ''}"></span>
            {:else}
              <span class="year-cell year-cell-void"></span>
            {/if}
          {/each}
        </div>
      </div>
    {/each}
  </div>

  {#if yearEntries.length}
    <p class="ch-stat">записей: {yearEntries.length} · средняя оценка: {yearAvg}/10</p>
  {:else}
    <p class="empty">За {year} год записей пока нет.</p>
  {/if}
</section>
