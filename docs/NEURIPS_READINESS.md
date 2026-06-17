# NeurIPS Readiness Notes

This project implements execution-intervention search for post-hoc debugging of
LLM agent trajectories on real `tau2` / tau3-style benchmark environments.

## Current Claim

Given a failed trajectory with replayable environment state, the system can fork
execution at intermediate tool-call states, apply a minimal tool patch, roll out
the remaining trajectory, and emit an autopsy report when the patch flips the
downstream environment reward. The repo now also supports staged strict
continuation from the replayed state and has verified natural-failure recovery
without oracle suffix reuse in two forms: retail continuation repair and
airline mutating-step deletion. A clean multi-model deterministic bundle over
`32` replay-failing natural cases now recovers `13 / 32` strict natural cases,
with per-domain strict recovery `airline = 10 / 16` and `retail = 3 / 16`.

Important grounding note:

- The current headline natural bundle uses `proposer_backend = deterministic`
  and `model_slug = null`.
- The saved failures inside that bundle were originally produced by multiple
  benchmark-run models, namely `claude-3-7-sonnet-20250219`,
  `gpt-4.1-2025-04-14`, `gpt-4.1-mini-2025-04-14`, and
  `o4-mini-2025-04-16`.
- The concrete retail continuation recovery is
  `retail:35:natural:0:39d2c249-6e85-4db3-8f36-049be2744cf3` from the saved
  `gpt-4.1-mini-2025-04-14` retail results, while representative airline
  deletion recoveries appear in saved failures from both `gpt-4.1-2025-04-14`
  and `claude-3-7-sonnet-20250219`.

## What Is Paper-Grade Now

- Real `tau2` domain environments are used for `retail` and `airline`.
- Every trajectory step records pre- and post-tool-call snapshots.
- Patch evaluation resumes from the saved `pre_snapshot` for the target step.
- Synthetic corruption failures are supported for controlled root-cause tests.
- Natural failed trajectories can be imported from saved benchmark result JSON.
- Imported natural failures are now filtered so replay-success cases are
  excluded from the failure corpus, and saved `default` split names are
  normalized to the benchmark loader's `base` split.
- Mixed-domain corpora can be built from multiple `domain::task_split::path`
  specs and searched without assuming a single adapter for the whole batch.
- Search baselines can be compared over the same failure corpus.
- Natural failures use structured non-oracle patch candidates for lookup-style
  repairs, while reference-argument restoration is limited to controlled
  synthetic corruptions.
- Patch search now supports a broader family taxonomy:
  `tool_args`, `tool_call_replace`, `tool_insertion`, `tool_deletion`,
  `context_edit`, and `continuation_replace`.
- `tool_deletion` now applies to successful-but-bad mutating assistant actions,
  which makes policy-violation failures recoverable even when the tool itself
  returned no explicit error.
- The repo now has an experiment harness for corpus manifests, saved batch
  configs, budget sweeps, model sweeps, and figure-data generation.
- Saved experiment directories can now be exported into paper-facing CSV and
  Markdown tables through a dedicated table-generation command.
- Saved autopsy reports can now be rendered into paper-facing case-study
  panels in both JSON and Markdown form.
- Synthetic controlled failures now also export localization-quality metrics:
  top-1/top-3 fault accuracy, MRR, fault-rank summaries, and true-fault
  recovery alignment.
- A saved three-failure synthetic strategy suite now exists, showing that
  recovery and localization diverge across strategies even beyond the original
  single-failure smoke run.
- The repo can now generate a reviewer-facing artifact guide and environment
  manifest directly from saved experiment directories.
- The repo now also emits a pinned dependency snapshot artifact consisting of a
  selected package snapshot, a full local requirements lock, and a short
  reproducibility note.
- A one-command paper bundle path now exists for smoke runs:
  build corpus, run strict search, run oracle upper bound, aggregate autopsies,
  export figure data, and render paper tables from one CLI entrypoint.
- Paper-bundle and batch runs now default to compact `patch_results.json`
  serialization, dropping per-candidate `patched_trajectory` payloads unless
  full debug output is explicitly requested.
- A clean saved bundle now exists at `artifacts/paper_bundle_multimodel_32`,
  giving a stronger mixed-domain natural evidence point than the older
  one-plus-one smoke, six-case, and sixteen-case bundles.
- A proposer backend abstraction is in place, with deterministic offline
  continuation and an optional OpenRouter backend.
- Deterministic runtime continuation now supports a staged replay path:
  patch one step, execute it, inspect the patched tool result and replayed DB
  snapshot, then propose the bounded follow-up actions from that exact state.
- Deletion-aware autopsy reporting is now in place, so recovered cases that
  remove the root-cause step serialize cleanly into paper artifacts.
- Natural-failure searches now support an explicit opt-in oracle-continuation
  ablation. This keeps strict replay as the default while measuring an upper
  bound for whether a localized patch could recover if the downstream suffix
  were regenerated correctly.

## Core Commands

Collect controlled corruption failures:

```powershell
python main.py collect-failures --domain retail --limit 10 --output-dir artifacts/collect
```

Import natural failures from saved tau2 result files:

```powershell
python main.py import-natural-failures `
  --domain retail `
  --results-path external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json `
  --limit 25 `
  --output-dir artifacts/natural
```

Search for recovery patches:

```powershell
python main.py search-patches --input-dir artifacts/collect --output-dir artifacts/search
```

Build a normalized paper corpus:

```powershell
python main.py build-corpus --name paper_corpus --domain-specs retail::base::... airline::base::... --output-dir artifacts/corpus
```

Run a one-command mixed-domain paper bundle:

```powershell
python main.py make-paper-bundle `
  --name paper_bundle_smoke_cli `
  --domain-specs `
    retail::base::external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json `
    airline::base::external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json `
  --limit-per-domain 1 `
  --output-dir artifacts/paper_bundle_smoke_cli `
  --strict-strategy heuristic `
  --strict-max-evaluations 1 `
  --oracle-max-evaluations 1 `
  --continuation-horizon 2 `
  --beam-width 1 `
  --max-candidates-per-step 1
```

Run a saved batch experiment:

```powershell
python main.py run-batch --config configs/paper_batch_template.json
```

The provided paper batch template enables `compact_results` by default.

Run the natural-failure oracle-continuation upper bound:

```powershell
python main.py search-patches `
  --input-dir artifacts/natural `
  --output-dir artifacts/natural_oracle_suffix_search `
  --include-oracle-suffix
```

Compare search strategies:

```powershell
python main.py compare-strategies --input-dir artifacts/collect --output-dir artifacts/strategy_comparison
```

Sweep budget or model settings:

```powershell
python main.py sweep-budget --input-dir artifacts/corpus --output-dir artifacts/budget_sweep --strategy heuristic --evaluation-budgets 1 2 4 8
python main.py sweep-models --input-dir artifacts/corpus --output-dir artifacts/model_sweep --strategy heuristic --model-slugs openai/gpt-4.1-mini openai/o4-mini
```

Create an autopsy report:

```powershell
python main.py report-autopsy --input-dir artifacts/search --output-path artifacts/autopsy_report.json
```

Generate paper-facing figure data:

```powershell
python main.py make-figures --input-dirs artifacts/search artifacts/natural_search artifacts/natural_oracle_suffix_search --output-dir artifacts/figures
```

Generate paper-facing result tables:

```powershell
python main.py make-paper-tables --input-dirs artifacts/search artifacts/natural_search artifacts/natural_oracle_suffix_search artifacts/natural_runtime_smoke_search --output-dir artifacts/paper_tables
```

Generate a reviewer-facing artifact guide:

```powershell
python main.py make-artifact-guide --input-dirs artifacts/search artifacts/paper_bundle_smoke_cli artifacts/paper_bundle_smoke_cli/paper_tables --output-dir artifacts/reviewer_artifact_guide_smoke --title "Reviewer Artifact Guide (Smoke)" --paper-draft-path paper/paper_draft.md --checklist-path paper/submission_checklist.md
```

Generate paper-facing case studies:

```powershell
python main.py make-case-studies --input-paths artifacts/natural_runtime_smoke_autopsy.json artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json --output-dir artifacts/paper_case_studies_multimodel_32 --title "Paper Case Studies (Multi-Model 32)" --max-cases 6
```

Freeze the current dependency environment:

```powershell
python main.py freeze-deps --output-dir artifacts/reproducibility_snapshot
```

The canonical bundle outputs are:

- `corpus/corpus_manifest.json`
- `strict_search/patch_summary.json`
- `strict_search/patch_results.json` in compact mode by default
- `oracle_upper_bound/patch_summary.json`
- `strict_autopsy_report.json`
- `oracle_autopsy_report.json`
- `paper_tables/paper_tables.json`
- `paper_bundle_summary.json`

The most useful saved artifact directories right now are:

- `artifacts/natural` for the broader retail natural import.
- `artifacts/natural_runtime_smoke_search` for the strict retail continuation
  recovery.
- `artifacts/paper_bundle_multimodel_32` for the strongest current mixed-domain
  bundle.
- `artifacts/paper_case_studies_multimodel_32` for the current paper-facing
  autopsy panel.
- `artifacts/synthetic_strategy_tables_3` and
  `artifacts/synthetic_strategy_figures_3` for the strongest current synthetic
  localization suite.
- `artifacts/reproducibility_snapshot` for the current dependency snapshot.
- [docs/ARTIFACT_MAP.md](./ARTIFACT_MAP.md) for a quick glossary of what each
  saved directory means.

Run verification:

```powershell
python -m unittest -v
```

## Metrics To Report

- Success Recovery Rate: recovered failures divided by total failures.
- Total search token cost: deterministic accounting for localization and patch generation.
- Average patch size: structured argument diff size for successful patches.
- Rollout count: number of candidate patches evaluated.
- Evaluated candidate count by patch family.
- Tool error rate: imported natural-failure diagnostic.
- Strategy comparison: heuristic vs reverse, chronological, latest-only, and oracle fault-step search.
- Strategy comparison now also includes `random_candidate` and `no_repair` baselines.
- Synthetic localization metrics:
  top-1 accuracy, top-3 accuracy, MRR, mean and median fault rank.
- True-fault recovery metrics:
  recovery at the known corruption step and recovered-case fault alignment.
- Strict-vs-oracle-continuation gap: how much natural recovery is blocked by
  suffix regeneration rather than root-cause localization.
- Median and p90 token cost, per-domain recovery, and per-patch-family recovery
  are all available in autopsy aggregates.
- Reviewer-facing artifact manifests can now capture the local Python/runtime
  metadata together with the canonical saved artifact directories.

## Local Model Plan

The core infrastructure does not require API credits. Hosted APIs are optional
for stronger patch proposal and critic baselines. A local-model version should
add a patch proposer interface with providers such as Ollama, vLLM, llama.cpp,
or LM Studio. The clean paper setup is:

- deterministic search baselines as the primary controlled comparison;
- local model patch generation as the main scalable method;
- hosted API models only as an optional upper-bound comparison.

## Remaining Gaps Before Submission

- Generalize the current staged non-oracle continuation proposer beyond the
  retail smoke path and beyond simple lookup-plus-terminal-repair cases,
  especially for `airline`.
- Scale synthetic localization comparisons beyond the current three-failure
  retail suite into a larger controlled corpus, ideally across multiple
  domains.
- Add stronger scratchpad-edit generation and full-regenerate baselines.
- Run experiments across larger `retail`, `airline`, and preferably `telecom`
  corpora.
- Scale beyond the current clean `16`-case mixed-domain saved bundle into a
  frozen larger corpus that is credible as a main paper result.
- Add human validation for a sampled set of autopsy reports.
- Turn figure data into publication-quality plots and final camera-ready tables.
- Validate the new dependency snapshot in a clean environment; we now have a
  lock artifact, but not yet a full clean-room reproduction report.
