<script>
  import { shortDate } from '../lib/mood.js';

  // entries: ascending by date, each { date, rating }
  let { entries = [] } = $props();

  const W = 320, H = 200;
  const padL = 14, padR = 14, padT = 16, padB = 28;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const xy = (i, n, r) => ({
    x: n === 1 ? padL + plotW / 2 : padL + (i / (n - 1)) * plotW,
    y: padT + ((10 - r) / 9) * plotH
  });

  const pts = $derived.by(() =>
    entries.map((e, i) => ({ ...xy(i, entries.length, e.rating), rating: e.rating }))
  );

  // River = a centered moving average so the trend reads through the noise.
  const smoothPts = $derived.by(() => {
    const n = entries.length;
    if (n < 5) return [];
    const win = Math.max(2, Math.round(n / 12)); // half-window, scales with data
    return entries.map((_, i) => {
      let s = 0, c = 0;
      for (let k = i - win; k <= i + win; k++) {
        if (k >= 0 && k < n) { s += entries[k].rating; c++; }
      }
      return xy(i, n, s / c);
    });
  });

  const toPath = (p) => p.map((q, i) => `${i ? 'L' : 'M'}${q.x.toFixed(1)},${q.y.toFixed(1)}`).join(' ');
  const rawPath = $derived(toPath(pts));
  const smoothPath = $derived(toPath(smoothPts));
  const avg = $derived(entries.length ? entries.reduce((s, e) => s + e.rating, 0) / entries.length : 0);
</script>

{#if entries.length < 2}
  <p class="empty-sm">Нужно хотя бы два дня, чтобы построить график.</p>
{:else}
  <svg class="mood-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
       role="img" aria-label="График настроения по дням">
    <line class="ch-axis" x1={padL} y1={padT} x2={padL} y2={padT + plotH} />
    <line class="ch-axis" x1={padL} y1={padT + plotH} x2={padL + plotW} y2={padT + plotH} />
    <line class="ch-grid" x1={padL} y1={padT + plotH / 2} x2={padL + plotW} y2={padT + plotH / 2} />

    <!-- raw series: faint when a smoothed trend is shown -->
    <path class="ch-line" class:ch-line-faint={smoothPts.length} d={rawPath} />
    {#if smoothPts.length}
      <path class="ch-trend" d={smoothPath} />
    {:else}
      {#each pts as p}<circle class="ch-dot" cx={p.x} cy={p.y} r="3" />{/each}
    {/if}

    <text class="ch-lbl" x={padL + 3} y={padT + 8} text-anchor="start">10</text>
    <text class="ch-lbl" x={padL + 3} y={padT + plotH - 3} text-anchor="start">1</text>
    <text class="ch-lbl" x={padL} y={H - 8} text-anchor="start">{shortDate(entries[0].date)}</text>
    <text class="ch-lbl" x={padL + plotW} y={H - 8} text-anchor="end">
      {shortDate(entries[entries.length - 1].date)}
    </text>
  </svg>
  <div class="ch-stat">Среднее: {avg.toFixed(1)} · дней: {entries.length}</div>
{/if}
