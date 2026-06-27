<script>
  // Rhythm: weekday (rows) × month (cols) average rating. Darker = lower mood,
  // scaled to the real spread so a narrow range still reads. Empty cells faint.
  let { entries = [] } = $props();

  const MONTHS = ['1','2','3','4','5','6','7','8','9','10','11','12'];
  const WD = ['пн','вт','ср','чт','пт','сб','вс'];

  const grid = $derived.by(() => {
    const sum = Array.from({ length: 7 }, () => Array(12).fill(0));
    const cnt = Array.from({ length: 7 }, () => Array(12).fill(0));
    for (const e of entries) {
      if (e.rating < 1) continue;
      const d = new Date(e.date + 'T00:00:00');
      const w = (d.getDay() + 6) % 7;
      const m = Number(e.date.slice(5, 7)) - 1;
      sum[w][m] += e.rating;
      cnt[w][m] += 1;
    }
    const avgs = [];
    const cells = sum.map((row, w) =>
      row.map((s, m) => {
        const a = cnt[w][m] ? s / cnt[w][m] : null;
        if (a !== null) avgs.push(a);
        return { avg: a, count: cnt[w][m] };
      })
    );
    const lo = avgs.length ? Math.min(...avgs) : 0;
    const hi = avgs.length ? Math.max(...avgs) : 1;
    return { cells, lo: lo - 0.05, hi: hi + 0.05 };
  });

  const padL = 22, padT = 14, cellH = 17;
  const W = 320, padR = 4;
  const cellW = $derived((W - padL - padR) / 12);
  const H = padT + 7 * cellH + 6;

  function opacity(avg) {
    const { lo, hi } = grid;
    if (avg === null || hi <= lo) return null;
    const t = Math.max(0, Math.min(1, (avg - lo) / (hi - lo)));
    return (1 - t * 0.85).toFixed(3); // worst day → dark, best → light
  }
</script>

<svg class="heatmap" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
     role="img" aria-label="Ритм: дни недели по месяцам">
  {#each MONTHS as label, m}
    <text class="ch-lbl" x={padL + m * cellW + cellW / 2} y={padT - 4} text-anchor="middle">{label}</text>
  {/each}
  {#each WD as wlabel, w}
    <text class="ch-lbl" x={padL - 5} y={padT + w * cellH + cellH / 2 + 3} text-anchor="end">{wlabel}</text>
    {#each grid.cells[w] as cell, m}
      {@const op = opacity(cell.avg)}
      <rect x={padL + m * cellW + 0.6} y={padT + w * cellH + 0.6}
            width={cellW - 1.2} height={cellH - 1.2} rx="2"
            fill={op !== null ? 'var(--ink)' : 'none'}
            fill-opacity={op !== null ? op : 1}
            stroke={op === null ? '#e6e6e6' : 'none'} stroke-width="1" />
    {/each}
  {/each}
</svg>
