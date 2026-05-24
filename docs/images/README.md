# Documentation screenshots

Screenshots live in the repository-root [`images/`](../../images/) folder.
From a doc under `docs/en/` or `docs/ru/`, reference them as
`../../images/<name>.png`.

The page-level screenshots are already wired into the guides:
`index.life.png`, `lifeinweeks.png`, `account.png`, `sync.png`,
`modules.png`, `ai-chat.png`, `graphics.png`, `customize.png`.

## Placeholders still open

Some spots still have a placeholder comment instead of an image:

```
<!-- SCREENSHOT: day editor with a Markdown note | ../../images/edit-day.png -->
```

To fill one in, drop the image into `images/` and replace the comment
with a normal Markdown image:

```
![Day editor with a Markdown note](../../images/edit-day.png)
```

Find every remaining spot:

```
grep -rn "SCREENSHOT:" docs/
```

| Suggested file | Screenshot still needed |
|---|---|
| `edit-day.png` | Day editor with a Markdown note |
| `ai-tools.png` | Tool chips while the assistant pulls diary data |
| `neural-map.png` | Neural map — entries clustered into topics |
| `customization-before-after.png` | Before / after a theme change |
| `chart-*.png` | One per chart: overview, river, spiral, rose, ridgeline, rhythm, words, activities, people |

## Conventions

- **Format:** PNG (or WebP for large shots). Keep files reasonably small.
- **Filenames:** reuse the name suggested in each placeholder so the
  English and Russian docs can share one image.
- **Localized UI:** for language-specific captures, add a suffix
  (`ai-chat-en.png` / `ai-chat-ru.png`) and point each doc at its own file.
- **Privacy:** these ship in a public repo — use sample/placeholder
  diary text, not real personal entries.
