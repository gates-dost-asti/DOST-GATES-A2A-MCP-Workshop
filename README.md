# GATES Workshop: OneLab Laboratory Assistant — Site Source

This branch holds the **Quarto website** for the OneLab Workshop and is deployed
to GitHub Pages. For the workshop notebooks, code, and data, see the
[`training-materials`](../../tree/training-materials) branch.

## What's in this branch

- `index.qmd`, `_quarto.yml`, `styles.css`, `favicon-include.html` — the Quarto site source.
- `setup_guide.html` — the workshop setup guide, published as part of the site.
- `Exercise-1.ipynb` / `.html`, `Exercise-2.ipynb` / `.html`, `Exercise-3/` — read-only copies of the exercise notebooks and their rendered output, linked from the site as downloadable resources.
- `TESTQUERIES.md` — sample queries referenced by the site.
- `images/`, `analytics/`, `Logo Assets/` — images, charts, maps, and brand assets used by the site.

## Building locally

```bash
quarto render
open _site/index.html
```

## Deployment

Pushes to this branch are rendered and published to GitHub Pages automatically
via `.github/workflows/publish.yml`.
