COLM 2026 paper bundle

Files in this directory are a self-contained COLM 2026 submission package derived from the workshop manuscript.

Main source:
- `colm2026_submission.tex`

Included local template assets:
- `colm2026_conference.sty`
- `colm2026_conference.bst`
- `fancyhdr.sty`
- `natbib.sty`
- `math_commands.tex`

Bibliography:
- `references.bib`

Compile locally:

```powershell
cd paper\colm2026
pdflatex -interaction=nonstopmode -halt-on-error colm2026_submission.tex
bibtex colm2026_submission
pdflatex -interaction=nonstopmode -halt-on-error colm2026_submission.tex
pdflatex -interaction=nonstopmode -halt-on-error colm2026_submission.tex
```

Official template source used for this conversion:
- `external/colm-template-2026/`
