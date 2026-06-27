<script>
  // Ridgeline: one smoothed rating distribution per month, stacked top→bottom.
  // Each ridge is per-month normalised so sparse and busy months are comparable.
  // Ported from the desktop ridgeline chart.
  let { entries = [] } = $props();

  const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн',
    'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
  const SAMPLES = 40, SIGMA = 0.9;
  const W = 320, padL = 36, padR = 10, padT = 10, padB = 20;
  const rowStep = 16, ridgeH = 26;
  const plotW = W - padL - padR;
  const H = padT + 12 * rowStep + ridgeH + padB;

  const ridges = $derived.by(() => {
    const byMonth = Array.from({ length: 12 }, () => []);
    for (const e of entries) {
      if (e.rating >= 1) byMonth[Number(e.date.slice(5, 7)) - 1].push(e.rating);
    }
    return byMonth.map((ratings, m) => {
      const dens = Array(SAMPLES).fill(0);
      for (const r of ratings) {
        for (let k = 0; k < SAMPLES; k++) {
          const pos = 1 + (k / (SAMPLES - 1)) * 9;
          const z = (pos - r) / SIGMA;
          dens[k] += Math.exp(-0.5 * z * z);
        }
      }
      const md = Math.max(...dens, 0);
      const baseline = padT + m * rowStep + ridgeH;
      let d = '';
      for (let k = 0; k < SAMPLES; k++) {
        const x = padL + (k / (SAMPLES - 1)) * plotW;
        const v = md > 0 ? dens[k] / md : 0;
        const y = baseline - v * ridgeH;
        d += `${k ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`;
      }
      d += `L${(padL + plotW).toFixed(1)},${baseline} L${padL},${baseline} Z`;
      return { label: MONTHS[m], path: d, baseline, count: ratings.length };
    });
  });
</script>

<svg class="ridgeline" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
     role="img" aria-label="Распределение настроения по месяцам">
  {#each ridges as r}
    <text class="ch-lbl" x={padL - 6} y={r.baseline - 1} text-anchor="end">{r.label}</text>
    {#if r.count > 0}
      <path d={r.path} fill="var(--surface)" stroke="var(--ink)" stroke-width="1.2"
            stroke-linejoin="round" />
    {:else}
      <line class="ch-grid" x1={padL} y1={r.baseline} x2={padL + plotW} y2={r.baseline} />
    {/if}
  {/each}
  {#each [1, 5, 10] as tick}
    <text class="ch-lbl" x={padL + ((tick - 1) / 9) * plotW} y={H - 6} text-anchor="middle">{tick}</text>
  {/each}
</svg>
