<script>
  // Monochrome vertical bars. `max` is the value mapped to full height
  // (10 for averages, the peak count for distributions). Bars with no data
  // (count 0) render as a faint outline so empty months/weekdays still read.
  let { bars = [], max = 10 } = $props();

  const W = 320, H = 150;
  const padT = 8, padB = 22, padX = 6;
  const plotH = H - padT - padB;

  const bw = $derived(bars.length ? (W - padX * 2) / bars.length : 0);
</script>

<svg class="bar-chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
     role="img" aria-label="Столбчатый график">
  <line class="ch-axis" x1={padX} y1={padT + plotH} x2={W - padX} y2={padT + plotH} />
  {#each bars as b, i}
    {@const h = max > 0 ? Math.max(0, Math.min(1, b.value / max)) * plotH : 0}
    {@const x = padX + i * bw + bw * 0.16}
    {@const w = bw * 0.68}
    {#if (b.count ?? b.value) > 0}
      <rect class="bar" x={x} y={padT + plotH - h} width={w} height={Math.max(h, 1)} rx="2" />
    {:else}
      <rect class="bar-empty" x={x} y={padT + plotH - 3} width={w} height="3" rx="1.5" />
    {/if}
    <text class="ch-lbl" x={padX + i * bw + bw / 2} y={H - 7} text-anchor="middle">{b.label}</text>
  {/each}
</svg>
