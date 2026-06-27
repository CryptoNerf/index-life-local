// Mood model + date helpers shared across screens.

// Rating is 1..10. The brand mood-face mouth is a quadratic curve whose
// control-point offset `m` runs from -11 (frown) to +11 (smile); same geometry
// as the desktop chart's mood_face. An unset day shows a neutral face.
export function moodMouth(rating) {
  const r = rating >= 1 ? rating : 5.5;
  const m = ((r - 1) / 9) * 22 - 11;
  return Math.max(-11, Math.min(11, m));
}

export function todayISO() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

const MONTHS_RU = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];

export function prettyDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTHS_RU[m - 1]} ${y}`;
}

export function isToday(iso) {
  return iso === todayISO();
}
