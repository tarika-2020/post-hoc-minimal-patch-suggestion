# Submission Checklist

This file is the paper-readiness tracker for turning the current prototype into
a NeurIPS-grade submission. It is intentionally concrete and tied to files,
artifacts, and commands already present in the repository.

## Status Key

- `done`: exists now and has direct evidence in the repo
- `in_progress`: partially implemented or partially evidenced
- `missing`: not yet present at a submission-ready level

## Manuscript

| Item | Status | Evidence / Path | Remaining Work |
| --- | --- | --- | --- |
| Workshop manuscript scaffold | `done` | [workshop_paper.tex](./workshop_paper.tex), [README.md](./README.md) | Minor wording polish only |
| Abstract | `done` | [paper_draft.md](./paper_draft.md) | Tighten wording after full experiments |
| Introduction | `done` | [paper_draft.md](./paper_draft.md), [neurips_paper.tex](./neurips_paper.tex) | Final motivation polish after full experiments |
| Problem setup | `done` | [paper_draft.md](./paper_draft.md) | Convert informal notation into final paper notation |
| Method | `done` | [paper_draft.md](./paper_draft.md) | Add algorithm box / pseudocode |
| Related work | `done` | [paper_draft.md](./paper_draft.md), [neurips_paper.tex](./neurips_paper.tex), [references.bib](./references.bib) | Expand only if later experiments require more comparison baselines |
| Preliminary experiments/results | `done` | [paper_draft.md](./paper_draft.md) | Replace smoke framing with full main results once larger runs finish |
| Limitations | `done` | [paper_draft.md](./paper_draft.md) | Update after final experiments |
| Conclusion/future work | `done` | [paper_draft.md](./paper_draft.md) | Minor revision after final tables |
| Final paper formatting | `in_progress` | [neurips_paper.tex](./neurips_paper.tex), [workshop_paper.tex](./workshop_paper.tex), [references.bib](./references.bib), [README.md](./README.md) | Local MiKTeX toolchain is installed and both manuscripts compile (`workshop_paper.pdf`, `neurips_paper.pdf`); remaining work is to compile against the final official workshop/NeurIPS style bundle and swap smoke tables for final large-run tables/figures |

## Core Method Evidence

| Item | Status | Evidence / Path | Remaining Work |
| --- | --- | --- | --- |
| Replayable real benchmark environment | `done` | [README.md](../README.md), [main.py](../main.py) | Keep stable while scaling |
| Snapshot and restore per step | `done` | [main.py](../main.py), [test_main.py](../test_main.py) | None beyond regression protection |
| Structured trajectory logging | `done` | [main.py](../main.py) | None beyond scale testing |
| Synthetic corruption pipeline | `done` | [artifacts/search/patch_summary.json](../artifacts/search/patch_summary.json) | Scale beyond smoke size |
| Natural failure import | `done` | [artifacts/natural/summary.json](../artifacts/natural/summary.json) | Expand to larger multi-domain corpus |
| Structured patch families | `done` | [README.md](../README.md), [main.py](../main.py) | Improve proposer quality for each family |
| Strict non-oracle natural recovery | `in_progress` | [artifacts/natural_runtime_smoke_autopsy.json](../artifacts/natural_runtime_smoke_autopsy.json), [artifacts/paper_bundle_smoke_cli/strict_autopsy_report.json](../artifacts/paper_bundle_smoke_cli/strict_autopsy_report.json), [artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json](../artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json) | Demonstrate on a much larger natural corpus |
| Oracle continuation upper bound | `done` | [artifacts/natural_oracle_suffix_search/patch_summary.json](../artifacts/natural_oracle_suffix_search/patch_summary.json) | Keep explicitly separate from main claim |
| Synthetic localization metrics | `done` | [artifacts/synthetic_strategy_tables_3/synthetic_localization_results.csv](../artifacts/synthetic_strategy_tables_3/synthetic_localization_results.csv) | Scale beyond the current three-case controlled corpus |
| Frozen workshop natural corpus (`80`) | `done` | [corpus_manifest.json](../artifacts/workshop_bundle_release/natural_corpus/corpus_manifest.json), [failures.json](../artifacts/workshop_bundle_release/natural_corpus/failures.json) | Optional cleanup: finish the JSONL/shard migration for this specific corpus directory |
| Frozen workshop synthetic corpus (`24`) | `done` | [summary.json](../artifacts/workshop_bundle_release/synthetic_corpus/summary.json) | None beyond archival cleanup |
| Secret hygiene for hosted runs | `in_progress` | [submission_checklist.md](./submission_checklist.md) | Keep `OPENROUTER_API_KEY` out of tracked files and load it only from the environment |

## Main Experimental Claims Needed For Submission

| Claim | Status | Current Evidence | What Still Needs To Happen |
| --- | --- | --- | --- |
| Controlled failures can be causally localized and repaired | `done` | [artifacts/search/patch_summary.json](../artifacts/search/patch_summary.json), [artifacts/synthetic_strategy_tables_3/paper_tables.json](../artifacts/synthetic_strategy_tables_3/paper_tables.json) | Increase corpus size and confidence intervals |
| Recovery and localization should be measured separately | `done` | [artifacts/synthetic_strategy_tables_3/paper_tables.json](../artifacts/synthetic_strategy_tables_3/paper_tables.json) | Scale beyond the current three-case controlled suite |
| Naive single-step repair is insufficient on natural failures | `done` | [artifacts/natural_search/patch_summary.json](../artifacts/natural_search/patch_summary.json) | Confirm on larger natural corpus |
| Oracle continuation reveals a continuation bottleneck | `done` | [artifacts/natural_oracle_suffix_search/patch_summary.json](../artifacts/natural_oracle_suffix_search/patch_summary.json) | Measure gap at larger scale |
| Strict non-oracle recovery is possible on real failures | `in_progress` | [artifacts/natural_runtime_smoke_autopsy.json](../artifacts/natural_runtime_smoke_autopsy.json), [artifacts/paper_bundle_smoke_cli/paper_bundle_summary.json](../artifacts/paper_bundle_smoke_cli/paper_bundle_summary.json), [artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json](../artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json) | Show non-trivial lift on hundreds of failures |
| Minimal successful patches provide useful autopsies | `in_progress` | [artifacts/natural_oracle_suffix_autopsy_report.json](../artifacts/natural_oracle_suffix_autopsy_report.json), [artifacts/paper_case_studies_multimodel_32/case_studies.md](../artifacts/paper_case_studies_multimodel_32/case_studies.md) | Add human validation and final camera-ready figure layout |

## Required Tables And Figures

| Artifact | Status | Current Evidence / Path | Remaining Work |
| --- | --- | --- | --- |
| Workshop short-paper tables and figure CSVs | `done` | [paper_tables.json](../artifacts/workshop_bundle_release/paper_tables/paper_tables.json), [paper_tables.md](../artifacts/workshop_bundle_release/paper_tables/paper_tables.md), [figure_data.csv](../artifacts/workshop_bundle_release/figures/figure_data.csv), [figure_report.md](../artifacts/workshop_bundle_release/figures/figure_report.md) | None beyond final visual styling in the paper |
| Synthetic localization table | `done` | [synthetic_localization_results.csv](../artifacts/synthetic_strategy_tables_3/synthetic_localization_results.csv) | Scale to larger synthetic corpus |
| Main smoke result tables | `done` | [paper_tables.md](../artifacts/synthetic_strategy_tables_3/paper_tables.md), [paper_tables.md](../artifacts/paper_bundle_smoke_cli/paper_tables/paper_tables.md) | Produce final paper tables from full runs |
| Figure-ready CSV data | `done` | [figure_data.csv](../artifacts/synthetic_strategy_figures_3/figure_data.csv) | Turn into camera-ready plots |
| Natural recovery table at scale | `in_progress` | [paper_tables.md](../artifacts/paper_bundle_multimodel_32/paper_tables/paper_tables.md) | Scale beyond the current clean thirty-two-case mixed-domain bundle |
| Budget sweep figure at scale | `in_progress` | CLI exists in [main.py](../main.py) | Execute and save larger sweeps |
| Patch-family ablation figure | `in_progress` | Patch-family exports exist | Run on larger corpora |
| Case-study figure panels | `in_progress` | [case_studies.md](../artifacts/paper_case_studies_multimodel_32/case_studies.md) | Turn the markdown panels into final figure layouts |

## Reproducibility

| Item | Status | Evidence / Path | Remaining Work |
| --- | --- | --- | --- |
| Workshop bundle CLI path | `done` | [main.py](../main.py), [workshop_paper.tex](./workshop_paper.tex) | None beyond final artifact completion |
| Workshop release resume path | `done` | [resume_workshop_release.py](../scripts/resume_workshop_release.py) | None beyond keeping the utility available |
| Streaming large-corpus failure loading | `done` | [main.py](../main.py) | None beyond long-run monitoring |
| JSONL + sharded corpus artifacts | `in_progress` | [main.py](../main.py), [artifacts/collect/failures.jsonl](../artifacts/collect/failures.jsonl) | Finish the interrupted migration for `artifacts/workshop_bundle_release/natural_corpus` and remove temp files |
| Incremental resumable patch-result writes | `done` | [patch_results.jsonl](../artifacts/workshop_bundle_release/oracle_upper_bound/patch_results.jsonl), [patch_summary.progress.json](../artifacts/workshop_bundle_release/oracle_upper_bound/patch_summary.progress.json), [patch_summary.json](../artifacts/workshop_bundle_release/oracle_upper_bound/patch_summary.json), [main.py](../main.py) | None; canonical workshop oracle run completed |
| One-command smoke bundle | `done` | [paper_bundle_summary.json](../artifacts/paper_bundle_smoke_cli/paper_bundle_summary.json) | Keep stable while scaling |
| Saved paper-facing tables | `done` | [artifacts/paper_bundle_smoke_cli/paper_tables/paper_tables.json](../artifacts/paper_bundle_smoke_cli/paper_tables/paper_tables.json) | Produce full-run versions |
| Saved autopsy reports | `done` | [artifacts/paper_bundle_smoke_cli/strict_autopsy_report.json](../artifacts/paper_bundle_smoke_cli/strict_autopsy_report.json) | Curate final examples |
| Full dependency freeze | `in_progress` | [dependency_snapshot.json](../artifacts/reproducibility_snapshot/dependency_snapshot.json), [requirements-lock.txt](../artifacts/reproducibility_snapshot/requirements-lock.txt), [requirements-selected.txt](../artifacts/reproducibility_snapshot/requirements-selected.txt) | Validate the pinned snapshot in a clean environment |
| Artifact README for reviewers | `done` | [ARTIFACT_README.md](../artifacts/reviewer_artifact_guide_smoke/ARTIFACT_README.md), [ARTIFACT_README.md](../artifacts/reviewer_artifact_guide_multimodel_32/ARTIFACT_README.md), [ARTIFACT_README.md](../artifacts/reviewer_artifact_guide_synthetic_3/ARTIFACT_README.md) | Refresh once final result paths are frozen |

## High-Priority Next Actions

1. Clean up the interrupted corpus-migration temp files under [natural_corpus](../artifacts/workshop_bundle_release/natural_corpus) and finish the JSONL/shard backfill for that directory.
2. Compile the workshop manuscript against the official workshop style bundle once it is available locally.
3. Do final short-paper wording polish around the saved workshop numbers and chosen case studies.
4. If credits and time permit, refresh the hosted retry baselines with a stronger non-free model for a sensitivity comparison.
5. Start the post-workshop scale-up path: larger natural corpus, stronger continuation, broader baselines, and human autopsy evaluation.

## Live Run Notes

- Clean workshop oracle rerun completed under [oracle_upper_bound](../artifacts/workshop_bundle_release/oracle_upper_bound).
- Old invalid oracle outputs were archived under:
  [oracle_upper_bound_invalid_pre_cf842a7_20260618_112802](../artifacts/workshop_bundle_release/oracle_upper_bound_invalid_pre_cf842a7_20260618_112802)
  and
  [oracle_autopsy_report_invalid_pre_cf842a7_20260618_112802.json](../artifacts/workshop_bundle_release/oracle_autopsy_report_invalid_pre_cf842a7_20260618_112802.json).
- Current resumable progress files are:
  [patch_results.jsonl](../artifacts/workshop_bundle_release/oracle_upper_bound/patch_results.jsonl)
  and
  [patch_summary.progress.json](../artifacts/workshop_bundle_release/oracle_upper_bound/patch_summary.progress.json).
  The finalized summary is
  [patch_summary.json](../artifacts/workshop_bundle_release/oracle_upper_bound/patch_summary.json).

## Canonical Current Artifacts

- Mixed-domain smoke bundle:
  [paper_bundle_summary.json](../artifacts/paper_bundle_smoke_cli/paper_bundle_summary.json)
- Frozen workshop bundle summary:
  [workshop_bundle_summary.json](../artifacts/workshop_bundle_release/workshop_bundle_summary.json)
- Frozen workshop oracle autopsy:
  [oracle_autopsy_report.json](../artifacts/workshop_bundle_release/oracle_autopsy_report.json)
- Frozen workshop case studies:
  [case_studies.json](../artifacts/workshop_bundle_release/case_studies/case_studies.json)
- Frozen workshop tables:
  [paper_tables.json](../artifacts/workshop_bundle_release/paper_tables/paper_tables.json)
- Strongest mixed-domain bundle:
  [paper_bundle_summary.json](../artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json)
- Strict non-oracle retail continuation recovery:
  [natural_runtime_smoke_autopsy.json](../artifacts/natural_runtime_smoke_autopsy.json)
- Paper-facing case studies:
  [case_studies.md](../artifacts/paper_case_studies_multimodel_32/case_studies.md)
- Reproducibility snapshot:
  [REPRODUCIBILITY.md](../artifacts/reproducibility_snapshot/REPRODUCIBILITY.md)
- Broader retail natural negative result:
  [patch_summary.json](../artifacts/natural_search/patch_summary.json)
- Oracle upper-bound retail result:
  [patch_summary.json](../artifacts/natural_oracle_suffix_search/patch_summary.json)
- Synthetic localization tables:
  [paper_tables.json](../artifacts/synthetic_strategy_tables_3/paper_tables.json)
