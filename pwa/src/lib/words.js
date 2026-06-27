// Words that go with good / bad days — ported from the desktop "words" chart.
// For each word seen on >= 3 different days, the average rating of those days.
// Pure text stats from local notes, no AI.

const STOPWORDS = new Set(`
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы
по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг
ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без
будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой
совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех
никогда можно при наконец два об другой хоть после над больше тот через эти нас
про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда
лучше чуть том нельзя такой им более всегда конечно всю между этом этих этим
была было были быть буду будешь будет будем будете будут есть быть будучи
день дня дни днями сегодня вчера завтра утром вечером ночью днём очень просто
the a an and or but of to in on at for with by from is are was were be been
being have has had do does did not no yes this that these those it its i you he
she we they me him her us them my your his our their as so if then than also just
very too can will would should could about into out up down over under again
still now here there when where why how what who which because while during before
after some any all each every other another own same such of
`.split(/\s+/).filter(Boolean));

export function wordStats(entries) {
  const stat = new Map(); // word -> { sum, count }
  for (const e of entries) {
    if (e.rating < 1 || !e.note) continue;
    const seen = new Set(
      (e.note.toLowerCase().match(/[\p{L}]+/gu) || [])
        .filter((w) => w.length >= 3 && !STOPWORDS.has(w))
    );
    for (const w of seen) {
      const s = stat.get(w) || { sum: 0, count: 0 };
      s.sum += e.rating;
      s.count += 1;
      stat.set(w, s);
    }
  }
  return [...stat.entries()]
    .filter(([, s]) => s.count >= 3)
    .map(([word, s]) => ({ word, avg: s.sum / s.count, count: s.count }))
    .sort((a, b) => b.avg - a.avg);
}
