<script>
  // Polar rose: one petal per weekday; the petal's shape is the smoothed
  // distribution (Gaussian KDE) of that weekday's ratings, coloured by the
  // weekday's average (dark = lower mood). Ported from the desktop rose chart.
  let { entries = [] } = $props();

  const SIZE = 320, cx = 160, cy = 160;
  const innerR = 26, outerR = 120;
  const SAMPLES = 40, SIGMA = 0.9;
  const NAMES = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];
  const gap = (4 * Math.PI) / 180;
  const sector = (2 * Math.PI) / 7 - gap;
  const firstAlpha = -Math.PI / 2 - sector / 2; // Monday centred at top

  const data = $derived.by(() => {
    const byWd = Array.from({ length: 7 }, () => []);
    for (const e of entries) {
      if (e.rating < 1) continue;
      const d = new Date(e.date + 'T00:00:00');
      byWd[(d.getDay() + 6) % 7].push(e.rating);
    }
    const avgs = byWd.map((r) => (r.length ? r.reduce((a, b) => a + b, 0) / r.length : null));
    const valid = avgs.filter((a) => a !== null);
    let lo = valid.length ? Math.min(...valid) : 0;
    let hi = valid.length ? Math.max(...valid) : 1;
    const pad = Math.max(0.1, (hi - lo) * 0.05);
    lo -= pad; hi += pad;
    if (hi - lo < 0.01) { lo -= 0.5; hi += 0.5; }

    return NAMES.map((name, i) => {
      const ratings = byWd[i];
      const dens = Array(SAMPLES).fill(0);
      for (const r of ratings) {
        for (let k = 0; k < SAMPLES; k++) {
          const pos = 1 + (k / (SAMPLES - 1)) * 9;
          const z = (pos - r) / SIGMA;
          dens[k] += Math.exp(-0.5 * z * z);
        }
      }
      const md = Math.max(...dens, 0);
      const norm = dens.map((v) => (md > 0 ? v / md : 0));
      const a0 = firstAlpha + i * (sector + gap);

      const pts = [];
      for (let k = 0; k < SAMPLES; k++) {
        const alpha = a0 + (k / (SAMPLES - 1)) * sector;
        const r = innerR + norm[k] * (outerR - innerR);
        pts.push(`${(cx + r * Math.cos(alpha)).toFixed(1)},${(cy + r * Math.sin(alpha)).toFixed(1)}`);
      }
      for (let k = SAMPLES - 1; k >= 0; k--) {
        const alpha = a0 + (k / (SAMPLES - 1)) * sector;
        pts.push(`${(cx + innerR * Math.cos(alpha)).toFixed(1)},${(cy + innerR * Math.sin(alpha)).toFixed(1)}`);
      }

      const mid = a0 + sector / 2;
      const lr = outerR + 16;
      const avg = avgs[i];
      let op = 0.06;
      if (avg !== null && hi > lo) {
        const t = Math.max(0, Math.min(1, (avg - lo) / (hi - lo)));
        op = 1 - t * 0.85;
      }
      return {
        name, count: ratings.length, points: pts.join(' '),
        lx: cx + lr * Math.cos(mid), ly: cy + lr * Math.sin(mid) + 3,
        opacity: op.toFixed(3)
      };
    });
  });
</script>

<svg class="rose" viewBox={`0 0 ${SIZE} ${SIZE}`} preserveAspectRatio="xMidYMid meet"
     role="img" aria-label="Роза настроения по дням недели">
  <circle class="ch-grid" cx={cx} cy={cy} r={innerR} fill="none" />
  <circle class="ch-grid" cx={cx} cy={cy} r={(innerR + outerR) / 2} fill="none" />
  <circle class="ch-grid" cx={cx} cy={cy} r={outerR} fill="none" />
  {#each data as p}
    <polygon points={p.points} fill="var(--ink)" fill-opacity={p.opacity}
             stroke="var(--ink)" stroke-width="0.6" stroke-opacity="0.5" />
    <text class="ch-lbl" x={p.lx} y={p.ly} text-anchor="middle">{p.name}</text>
  {/each}
</svg>
