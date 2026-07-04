// Aggregations for the chart gallery — all from local rated entries, no AI.
// Each returns [{ label, value, count }] ready for a bar chart.

export function distribution(entries) {
  const counts = Array(10).fill(0);
  for (const e of entries) {
    if (e.rating >= 1 && e.rating <= 10) counts[e.rating - 1]++;
  }
  return counts.map((c, i) => ({ label: String(i + 1), value: c, count: c }));
}

const MONTHS = ['Янв', 'Фев', 'Мар', 'Апр', 'Май', 'Июн',
  'Июл', 'Авг', 'Сен', 'Окт', 'Ноя', 'Дек'];

export function monthlyAverages(entries) {
  const sum = Array(12).fill(0), n = Array(12).fill(0);
  for (const e of entries) {
    if (e.rating < 1) continue;
    const m = Number(e.date.slice(5, 7)) - 1;
    sum[m] += e.rating;
    n[m]++;
  }
  return MONTHS.map((label, i) => ({
    label, value: n[i] ? sum[i] / n[i] : 0, count: n[i]
  }));
}

const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

export function weekdayAverages(entries) {
  const sum = Array(7).fill(0), n = Array(7).fill(0);
  for (const e of entries) {
    if (e.rating < 1) continue;
    const d = new Date(e.date + 'T00:00:00');
    const wd = (d.getDay() + 6) % 7; // Mon=0 … Sun=6
    sum[wd] += e.rating;
    n[wd]++;
  }
  return WEEKDAYS.map((label, i) => ({
    label, value: n[i] ? sum[i] / n[i] : 0, count: n[i]
  }));
}

// Current logging streak: consecutive rated days counting back from today —
// or from yesterday, so the streak doesn't read as broken before today's
// entry is made. Mirrors the desktop's proactive-note streak.
export function currentStreak(entries, today) {
  const dates = new Set();
  for (const e of entries) {
    if (!e.deleted && e.rating >= 1) dates.add(e.date);
  }
  const dayBefore = (iso) => {
    const d = new Date(iso + 'T00:00:00');
    d.setDate(d.getDate() - 1);
    const p = (x) => String(x).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  };
  let d = dates.has(today) ? today : dayBefore(today);
  let streak = 0;
  while (dates.has(d)) {
    streak++;
    d = dayBefore(d);
  }
  return streak;
}
