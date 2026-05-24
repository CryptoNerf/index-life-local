# Documentation screenshots

Drop screenshots here, then turn the matching placeholder in the docs
into a real image.

Throughout `docs/en/` and `docs/ru/` there are placeholder markers like:

```
<!-- SCREENSHOT: main calendar — the whole year as a heatmap | ../images/calendar-year.png -->
```

To fill one in, replace the comment with a normal Markdown image using
the suggested path and a short alt text:

```
![Year calendar heatmap](../images/calendar-year.png)
```

Find every spot that still needs a screenshot:

```
grep -rn "SCREENSHOT:" docs/
```

## Conventions

- **Format:** PNG (or WebP for large shots). Keep files reasonably small.
- **Filenames:** use the name suggested in each placeholder
  (`calendar-year.png`, `ai-chat.png`, `chart-river.png`, …) so the
  English and Russian docs can share the same image.
- **Localized UI:** if you want language-specific captures, add a suffix
  (`ai-chat-en.png` / `ai-chat-ru.png`) and point each doc at its own
  file.
- **Privacy:** these ship in a public repo — use sample/placeholder
  diary text, not real personal entries.

## Suggested shots (one per placeholder)

| File | Screenshot |
|---|---|
| `calendar-year.png` | Main page — the year as a heatmap (the hero shot) |
| `edit-day.png` | Day editor with a Markdown note |
| `life-in-weeks.png` | Life-in-weeks grid |
| `sync-settings.png` | Sync page — mode, folder/WebDAV, status |
| `modules-page.png` | Modules page — install buttons + progress |
| `ai-chat.png` | AI psychologist chat grounded in entries |
| `ai-tools.png` | Tool chips while the assistant pulls diary data |
| `neural-map.png` | Neural map — entries clustered into topics |
| `customization-settings.png` | Customization settings with live preview |
| `customization-before-after.png` | Before / after a theme change |
| `chart-*.png` | One per chart (overview, river, spiral, rose, ridgeline, rhythm, words, activities, people) |
