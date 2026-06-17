# Paper Source

This directory now contains a real manuscript scaffold for the project, not
just free-form notes.

## Files

- `paper_draft.md`
  Working long-form prose and project memory.
- `neurips_paper.tex`
  Submission-oriented LaTeX manuscript scaffold built from the current draft
  and current saved artifact numbers.
- `workshop_paper.tex`
  Separate short-paper manuscript source for the workshop-first submission
  path. This is where the 4-8 page version can diverge cleanly from the long
  paper while sharing the same bibliography file.
- `references.bib`
  Bibliography file with concrete benchmark and repair/search references.
- `submission_checklist.md`
  Paper-readiness tracker tied to repo evidence.
- `neurips_outline.md`
  Earlier outline and claim-shaping notes.

## Build

If the official `neurips_2024.sty` file is present in this directory,
`neurips_paper.tex` will use it automatically. Otherwise it falls back to a
plain article layout so the manuscript source remains locally buildable.

Typical build commands:

```text
pdflatex neurips_paper.tex
bibtex neurips_paper
pdflatex neurips_paper.tex
pdflatex neurips_paper.tex
```

For the workshop manuscript:

```text
pdflatex workshop_paper.tex
bibtex workshop_paper
pdflatex workshop_paper.tex
pdflatex workshop_paper.tex
```

## What Is Grounded Right Now

The current LaTeX manuscript uses repository-backed numbers from:

- `artifacts/search/patch_summary.json`
- `artifacts/synthetic_strategy_tables_3/paper_tables.json`
- `artifacts/natural_search/patch_summary.json`
- `artifacts/natural_runtime_smoke_search/patch_summary.json`
- `artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json`
- `artifacts/paper_bundle_multimodel_32/oracle_upper_bound/patch_summary.json`

The workshop manuscript is intentionally more conservative. It is grounded in
the current methodology and artifact-backed early evidence, while the final
frozen workshop counts should come from the new `make-workshop-bundle` path.

## Still Required Before Submission

- Verify the final venue choices for each bibliography entry and add any extra
  citations needed for later baseline expansions.
- Compile with the official NeurIPS style file and resolve any style issues.
- Swap smoke-scale result tables for final large-run tables and figures.
- Freeze the workshop corpora and run `make-workshop-bundle` for the short
  paper artifact release.
- Add final author metadata or anonymization details, depending on submission
  stage.
- Convert case-study markdown artifacts into final figure panels.
