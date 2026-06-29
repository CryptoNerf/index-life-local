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

const MONTHS_RU_SHORT = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн',
  'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

export function shortDate(iso) {
  const [, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTHS_RU_SHORT[m - 1]}`;
}

export function timeAgo(ts) {
  if (!ts) return 'ещё не было';
  const s = Math.floor((Date.now() - ts) / 1000);
  if (s < 60) return 'только что';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} мин назад`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} ч назад`;
  return `${Math.floor(h / 24)} дн назад`;
}
