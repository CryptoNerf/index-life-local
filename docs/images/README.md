# Documentation screenshots

This folder holds the screenshots used in the guides. A doc under
`docs/en/` or `docs/ru/` references them as `../images/<name>.png`; the
repo-root README uses `docs/images/<name>.png`.

Most pages and charts are already wired in. Two spots still have a
placeholder comment instead of an image:

```text
<!-- SCREENSHOT: the people chart | ../images/chart-people.png -->
<!-- SCREENSHOT: before / after a theme change | ../images/customization-before-after.png -->
```

To fill one in, drop the image into this folder and replace the comment
with a normal Markdown image:

```text
![The people chart](../images/chart-people.png)
```

Find any remaining spots:

```text
grep -rn "SCREENSHOT:" docs/
```

| Suggested file | Screenshot still needed |
|---|---|
| `chart-people.png` | The "people" chart (Graphics → People) |
| `customization-before-after.png` | Before / after a theme change |

## Conventions

- **Format:** PNG (or WebP for large shots). Keep files reasonably small.
- **Filenames:** the English and Russian docs share one image per shot.
- **Privacy:** these ship in a public repo — use sample/placeholder
  diary text, not real personal entries.
