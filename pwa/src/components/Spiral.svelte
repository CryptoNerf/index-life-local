<script>
  // Spiral of the year: one turn per month, day mapped outward; each day a dot
  // sized + shaded by its rating. Current year only. Ported from desktop spiral.
  let { entries = [] } = $props();

  const SIZE = 320, cx = 160, cy = 160, rMin = 30, rMax = 140, turns = 12;
  const year = new Date().getFullYear();
  const daysInYear = (year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)) ? 366 : 365;

  function dayOfYear(iso) {
    const d = new Date(iso + 'T00:00:00');
    const start = new Date(d.getFullYear(), 0, 0);
    return Math.floor((d - start) / 86400000);
  }
  function point(day) {
    const t = (day - 1) / Math.max(daysInYear - 1, 1);
    const angle = -Math.PI / 2 + 2 * Math.PI * turns * t;
    const r = rMin + t * (rMax - rMin);
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  }

  const guide = $derived.by(() => {
    let d = '';
    for (let day = 1; day <= daysInYear; day += 3) {
      const p = point(day);
      d += `${day === 1 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    }
    return d;
  });

  const dots = $derived.by(() =>
    entries
      .filter((e) => e.rating >= 1 && e.date.startsWith(String(year)))
      .map((e) => {
        const p = point(dayOfYear(e.date));
        return {
          ...p,
          r: 2.5 + ((e.rating - 1) / 9) * 4,
          op: (1 - ((e.rating - 1) / 9) * 0.7).toFixed(2)
        };
      })
  );
</script>

{#if dots.length === 0}
  <p class="empty-sm">В этом году ({year}) пока нет записей для спирали.</p>
{:else}
  <svg class="spiral" viewBox={`0 0 ${SIZE} ${SIZE}`} preserveAspectRatio="xMidYMid meet"
       role="img" aria-label="Спираль года">
    <path class="ch-grid" d={guide} fill="none" />
    {#each dots as d}
      <circle cx={d.x} cy={d.y} r={d.r} fill="var(--ink)" fill-opacity={d.op} />
    {/each}
    <text class="ch-lbl" x={cx} y={cy + 3} text-anchor="middle">{year}</text>
  </svg>
{/if}
