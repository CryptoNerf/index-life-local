# Внедрение дизайн-системы в index.life (VS Code + Claude Opus)

Коротко: дизайн-система — это **два правила и один файл переменных**.
Файл переменных кладётся рядом с остальными стилями, каждая страница его
импортирует, и дальше в page-стилях не остаётся ни одного «сырого» px для
размера текста и отступов.

Ничего в Python, в маршрутах, в именах полей форм и в тестах менять не нужно.
Меняются только CSS-файлы и presentational-разметка в шаблонах.

---

## Что лежит в этой папке

| Файл | Что это |
|---|---|
| `_tokens.css` | Общие переменные: роли размеров шрифта, роли отступов, форма. Это ядро. |
| `sync.css` | Готовая замена `app/static/css/sync.css` — страница синхронизации целиком на токенах. |
| `sync.partial.html` | Разметка новой страницы синхронизации. Все `name=`, `id=`, `data-*` и action'ы сохранены — JS и тесты продолжают работать. |

Живой макет всех страниц: `ui_kits/desktop-app/index.html` в этом проекте
(переключатель RU/EN внизу справа, состояния синхронизации — там же).

---

## Шаг 1. Положить токены

Скопируйте `_tokens.css` в `app/static/css/_tokens.css`.

В начало **каждого** page-стиля (`calendar.css`, `sync.css`, `account.css`,
`modules.css`, `edit_day.css`, `life_calendar.css`, `what_is_index.css`)
добавьте первой строкой:

```css
@import url("_tokens.css");
```

Проверка: страницы должны выглядеть точно так же, как до этого. Токены пока
никто не использует — просто объявлены.

## Шаг 2. Заменить страницу синхронизации

1. `handoff/sync.css` → `app/static/css/sync.css` (замена целиком).
2. Разметку в `app/templates/sync.html` привести к `sync.partial.html`.
   **Важно:** блок `{% macro settings_form() %}`, все `url_for(...)`,
   `name="sync_mode"`, `name="sync_folder"`, `name="webdav_url"`,
   `id="sync-settings-form"`, `id="advanced-setup"`, `data-goal`,
   `data-goal-panel`, `data-pane`, `id="pair-qr"` — остаются как есть.
3. Два места в инлайновом `<script>` внизу `sync.html`, где нужна правка
   (они помечены комментариями в `sync.partial.html`):
   - `renderDevices()` — вместо одной строки с эмодзи собирать
     `<span class="mark …">` + `<span class="device-name">` +
     `<span class="device-when">`;
   - убрать эмодзи из статических строк (`📱`, `💻`, `🔒`, `⚠️`, `✅`, `🔑`) —
     их роль теперь выполняет квадратный маркер `.mark`.
4. Новые строки перевода для пошаговой настройки (`sync.step_phone_1_title`
   и т.д.) добавить в `app/translations/en.json` и `ru.json`. Тексты можно
   взять из `ui_kits/desktop-app/copy.js` — там они уже написаны на обоих
   языках.

## Шаг 3. Перевести остальные страницы на роли

Для каждого page-стиля — механическая замена. Таблица соответствий:

| Было (встречается в проекте) | Стало |
|---|---|
| `font-size: 24px` / `22px` у заголовка страницы | `font-size: var(--il-text-page-title)` |
| `font-size: 20px` / `22px` / `18px` у `h2` | `font-size: var(--il-text-section-title)` |
| `font-size: 18px` у подзаголовка, статуса | `font-size: var(--il-text-subhead)` |
| `font-size: 16px` / `15px` у текста, кнопок, инпутов | `font-size: var(--il-text-body)` |
| `font-size: 14px` у мета-текста | `font-size: var(--il-text-ui)` |
| `font-size: 13px` / `12px` у подсказок | `font-size: var(--il-text-hint)` |
| `font-size: 20px` / `22px` у `.top-menu` | `font-size: var(--il-text-nav)` |
| `gap: 6px…10px` между кнопками | `gap: var(--il-inline)` |
| `margin-bottom: 8px…12px` у лейблов | `var(--il-field)` |
| `padding: 14px…16px`, `margin: 16px` | `var(--il-row)` |
| `margin-bottom: 20px…24px` | `var(--il-block)` |
| `margin-bottom: 32px…48px`, `margin-top: 40px` | `var(--il-section)` |
| `border-radius: 3px / 4px / 8px / 12px` | `border-radius: var(--il-radius)` (то есть 0) |

Дополнительно по каждой странице:

- **calendar.css** — `.calendar-title` → `--il-text-page-title`; `.top-menu` →
  `--il-text-nav`; `.year-arrow`/`.year-select` `border-radius: 8px` → 0.
- **edit_day.css** — `.header` → `--il-text-page-title`; `.format-btn`
  `border-radius: 3px` → 0; `.mode-toggle` `border-radius: 4px` → 0;
  `blockquote` `border-radius: 0 4px 4px 0` → 0.
- **account.css** — вынести инлайновые стили из `account.html` в классы;
  контент поставить в колонку `max-width: var(--il-content-width)` с
  выравниванием по левому краю (сейчас центрируется, из-за чего формы «пляшут»);
  `.archive-year-link` `border-radius` → 0.
- **modules.css** — `.module-hw-block` и `.troubleshoot-btn` `border-radius` → 0;
  точки `●`/`○` заменить на `<span class="mark">` / `.mark-on` / `.mark-attention`
  (стили маркера есть в `sync.css`, лучше перенести их в `_tokens.css`-соседа
  `_base.css`, если будете выносить общее).
- **life_calendar.css** — `.life-title` → `--il-text-page-title`;
  `.life-stats` → `--il-text-ui`; печатные стили не трогать.
- **what_is_index.css** — `body { font-size: 20px }` → `--il-text-subhead`
  (18px) и `max-width: 60ch` для колонки текста.

## Шаг 4. Проверка

- Заголовки: на всех страницах `h1` один и тот же размер, `h2` один и тот же.
- В page-стилях не осталось `border-radius`, кроме `var(--il-radius)`.
- Поиск по проекту: `grep -rn "font-size: [0-9]" app/static/css` должен
  находить только объявления внутри `_tokens.css`.
- Масштаб 200% и ширина телефона — колонка 640px не ломается, кнопки не
  обрезают русские подписи.
- Кастомизация: включите тёмный фон и авто-инверсию — всё, что должно быть
  темизируемым, по-прежнему `var(--bg-color, …)` / `var(--text-color, …)`.

---

## Как поручить это Claude Opus в VS Code

Положите папку с дизайн-системой в репозиторий (например `design-system/`),
и дайте Claude такой запрос:

> В репозитории есть папка `design-system/` с дизайн-системой index.life.
> Прочитай `design-system/readme.md` (разделы «The two rules that keep pages
> consistent» и «Visual foundations») и `design-system/handoff/README.md`.
>
> Задача — шаг 1 и шаг 3 из handoff-инструкции: скопируй
> `design-system/handoff/_tokens.css` в `app/static/css/_tokens.css`,
> добавь `@import url("_tokens.css");` в начало каждого page-стиля и переведи
> `app/static/css/calendar.css` на роли-токены по таблице соответствий.
> Не меняй Python, маршруты, имена полей форм и id элементов. Не меняй
> печатные стили в `life_calendar.css`. Каждое `var(--bg-color, …)` и другие
> темизируемые переменные оставь как есть — их пишет модуль кастомизации.
> После правки покажи diff и запусти `pytest`.

Дальше — по одному файлу за запрос: `edit_day.css`, `account.css`,
`modules.css`, `life_calendar.css`, `what_is_index.css`. По одной странице за
раз проще проверять глазами, и откатить тоже проще.

Страницу синхронизации (шаг 2) стоит делать отдельным запросом, потому что там
меняется и разметка:

> Замени `app/static/css/sync.css` на `design-system/handoff/sync.css` и
> приведи разметку `app/templates/sync.html` к
> `design-system/handoff/sync.partial.html`. Сохрани все `url_for`, `name=`,
> `id=`, `data-*` и макрос `settings_form()` без изменений. Внеси две правки в
> инлайновый JS, помеченные комментариями в partial. Новые ключи переводов
> возьми из `design-system/ui_kits/desktop-app/copy.js` и добавь в
> `app/translations/en.json` и `ru.json`. Запусти `pytest tests/test_sync_*`.

Полезно также добавить в `CLAUDE.md` репозитория короткое правило, чтобы новые
экраны сразу писались по системе:

```md
## Дизайн
Стили — только по дизайн-системе в `design-system/`.
Размеры шрифта и отступы — только через роли-токены `--il-*` из
`app/static/css/_tokens.css`. Никаких сырых px для текста и отступов.
`border-radius` всегда 0. Никаких теней, градиентов и эмодзи в интерфейсе —
для статусов используется квадратный маркер `.mark`.
Всё темизируемое пишется как `var(--token, fallback)`.
```
