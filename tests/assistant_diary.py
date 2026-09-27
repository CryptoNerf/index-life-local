"""A made-up two-year diary with patterns planted in it, for the analysis
tools. No real diary text: every note is assembled from the phrases below.

Planted, on top of a baseline of 6 and a little noise:
- Mondays are 1.5 lower;
- running lifts the day by 1.5, and stops in the last 30 days;
- rain takes 1 off;
- Маша is written about warmly, on better days (+1);
- Сергей is neutral until June 2026 and negative after (−1.5 then);
- the theme "дедлайн" comes with hard days (−2);
- every February is a slump (−2), in both years;
- the theme "переезд" appears only in the last 60 days.
"""
import random
from datetime import date, timedelta

from app.modules.assistant.daybook import Day

TODAY = date(2026, 9, 27)
START = date(2024, 9, 28)
RUNNING_STOPS = TODAY - timedelta(days=29)
SERGEY_TURNS = date(2026, 6, 1)
MASHA_FIRST = date(2024, 10, 5)


def make_diary(seed: int = 7) -> list[Day]:
    rng = random.Random(seed)
    days = []
    d = START
    while d <= TODAY:
        score = 6.0 + rng.uniform(-0.6, 0.6)
        notes, acts, themes, people = [], [], [], {}
        weather = 'Rain' if rng.random() < 0.3 else rng.choice(['Clear', 'Clouds'])

        if d.weekday() == 0:
            score -= 1.5
            notes.append('Понедельник, тяжело раскачаться.')
        if d < RUNNING_STOPS and rng.random() < 0.45:
            score += 1.5
            acts.append('бег')
            notes.append('Бегал утром в парке.')
        if weather == 'Rain':
            score -= 1
            notes.append('Дождь весь день, сидел дома.')
        if d.weekday() < 5 and rng.random() < 0.6:
            themes.append('работа')
            acts.append('работа')
            notes.append('На работе обычный день.')
            if rng.random() < 0.25:
                score -= 2
                themes.append('дедлайн')
                notes.append('Горит дедлайн, всё валится.')
        if d >= MASHA_FIRST and rng.random() < 0.18:
            score += 1
            people['Маша'] = ('positive',)
            themes.append('отношения')
            notes.append('Вечером гуляли с Машей, долго говорили.')
        if rng.random() < 0.12:
            if d >= SERGEY_TURNS:
                score -= 1.5
                people['Сергей'] = ('negative',)
                notes.append('Сергей опять придирался на встрече.')
            else:
                people['Сергей'] = ('neutral',)
                notes.append('Созвонился с Сергеем по делу.')
            acts.append('встреча')
        if d.month == 2:
            score -= 2
            notes.append('Нет сил, всё серое.')
        if d >= TODAY - timedelta(days=59) and rng.random() < 0.5:
            themes.append('переезд')
            notes.append('Думаю о переезде в другой город.')
        if not notes:
            notes.append('Обычный день.')

        rating = max(1, min(10, round(score)))
        days.append(Day(
            date=d, rating=rating, note=' '.join(notes),
            summary=notes[0], themes=tuple(dict.fromkeys(themes)),
            activities=tuple(dict.fromkeys(acts)), people=people,
            weather=weather, temp=rng.uniform(-10, 25),
        ))
        d += timedelta(days=1)
    return days
