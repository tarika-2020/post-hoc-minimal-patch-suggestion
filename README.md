# Post-Hoc Minimal Patch Suggestion via Execution Intervention

This repository is a working research prototype for post-hoc debugging of
LLM-agent trajectories on real `tau2` / tau3-style benchmark environments.
The core idea is simple: given a failed trajectory, we restore the exact
environment state at an intermediate step, apply a small patch, replay from
there, and check whether the benchmark reward flips from failure to success.

This README is also the project memory. It is written so future work can resume
from the repository alone even if chat context is gone.

## Current Status

What is already implemented:

- Real `tau2` domain integration for `retail` and `airline`.
- Snapshot and restore over environment DB state plus message history.
- Structured trajectory logging with per-step pre/post snapshots.
- Synthetic corruption failure collection for controlled recovery tests.
- Natural failure import from saved `tau2` result JSON files.
- Natural-failure replay validation that excludes saved failures which already
  succeed under exact replay, plus `default -> base` task-split normalization
  for saved tau result files.
- Mixed-domain corpus building across saved `domain::task_split::results_path`
  specs, with per-failure `task_split` tracking through search and reporting.
- Patch search baselines over failed trajectories.
- Richer patch families including replacement, insertion, deletion, context edit, and continuation replacement.
- Non-oracle `tool_deletion` recovery for successful-but-bad mutating actions.
- Deterministic and OpenRouter-ready proposer backends.
- Corpus manifests, batch experiment configs, budget sweeps, model sweeps, and figure-data generation.
- Paper-table generation from saved experiment directories.
- Simple rerun baselines for workshop comparisons:
  `retry_from_scratch`, `retry_from_localized_snapshot`, and
  `raw_continuation_from_snapshot`.
- Synthetic localization metrics and exports:
  top-1/top-3 fault localization accuracy, MRR, fault-rank stats, and
  true-fault recovery alignment in both summaries and paper tables.
- Autopsy report generation for recovered and unrecovered cases.
- Reviewer-facing artifact guide generation with environment metadata and a
  manifest over saved experiment directories.
- An explicit oracle-continuation upper-bound ablation for natural failures.
- A one-command paper bundle path that builds a corpus, runs strict search,
  runs the oracle upper bound, emits autopsies, generates figure data, and
  writes paper tables.
- A one-command workshop bundle path that also builds a synthetic corpus, runs
  the workshop retry baselines, exports case studies, and writes a
  `WORKSHOP_RELEASE.md` artifact map.

What is not implemented yet:

- Broad multi-domain continuation generation beyond the current deterministic retail repair path.
- Context or scratchpad edits as a real patch family.
- Missing-tool insertion and broader deletion coverage beyond the current mutating-step heuristic.
- Model-based localization or proposal as a main evaluated method rather than
  an interface-only optional path.
- Large-scale experiments across many tasks and multiple domains.
- Publication-grade plotting, large-sweep orchestration, and final camera-ready tables.

## Honest Research Claim Right Now

The current paper-safe claim is:

> On replayable tau-style environments, execution-intervention search can
> produce reproducible autopsies and recover controlled failures with minimal
> tool-call patches. On imported natural failures, the current system now
> supports strict non-oracle continuation from the replayed state and can
> recover real saved failures both by continuation-based retail repair and by
> deleting bad mutating airline actions, without oracle suffix reuse.

That wording matters. The synthetic story is strong. The natural-failure story
is now real but still limited: we have a dedicated retail continuation
recovery, plus a clean multi-model `32`-case mixed-domain bundle with
`13 / 32` strict recoveries. That bundle is imported from saved failures
originally produced by `claude-3-7-sonnet-20250219`, `gpt-4.1-2025-04-14`,
`gpt-4.1-mini-2025-04-14`, and `o4-mini-2025-04-16`, and all `32` cases are
verified replay failures before recovery search. Current multi-case lift is
still dominated by `airline` deletion repairs, with per-domain strict recovery
`airline = 10 / 16` and `retail = 3 / 16`. The repo is now ready to run
mixed-domain bundles and paper-facing exports, but not yet broad enough to
claim benchmark-wide natural recovery.

## Exact Natural Evidence

The safest concrete statement today is:

- The saved natural-failure bundle at
  `artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json` uses the
  `deterministic` proposer backend with `model_slug = null`. The current
  headline natural result does not depend on an OpenRouter model call.
- The `32` imported failures in that bundle came from saved benchmark outputs
  originally produced by `claude-3-7-sonnet-20250219`,
  `gpt-4.1-2025-04-14`, `gpt-4.1-mini-2025-04-14`, and
  `o4-mini-2025-04-16`.
- The strongest retail continuation example is
  `retail:35:natural:0:39d2c249-6e85-4db3-8f36-049be2744cf3`, saved in
  [artifacts/natural_runtime_smoke_autopsy.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/natural_runtime_smoke_autopsy.json:1).
  It comes from
  `external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json`
  and recovers under `strict_replay` by changing the first
  `find_user_id_by_email` argument from `aarav.santos8321@example.com` to
  `aarav.santos8320@example.com`, then synthesizing a bounded continuation from
  the patched replay state.
- A representative airline deletion example is
  `airline:48:natural:0:830f1ac4-f6d3-4d6b-95b1-f52045527e10`, shown in
  [artifacts/paper_case_studies_multimodel_32/case_studies.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_case_studies_multimodel_32/case_studies.md:1).
  It comes from
  `external/tau2-bench/data/tau2/results/final/gpt-4.1-2025-04-14_airline_default_gpt-4.1-2025-04-14_4trials.json`
  and recovers by deleting a `cancel_reservation` action at the localized bad
  step.
- Another recovered airline deletion case comes from the Claude-generated saved
  failures:
  `airline:1:natural:0:024ecc62-7ee5-476e-9c2b-3f8e6fda8ab3` in
  [artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json:1),
  where deleting a late `cancel_reservation` call recovers reward.

## Repository Map

- [main.py](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/main.py:1)
  Main prototype: adapters, replay, failure import, patch search, CLI.
- [test_main.py](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/test_main.py:1)
  End-to-end tests over the real benchmark-shaped pipeline.
- [docs/NEURIPS_READINESS.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/docs/NEURIPS_READINESS.md:1)
  Shorter paper-readiness notes.
- [docs/ARTIFACT_MAP.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/docs/ARTIFACT_MAP.md:1)
  Artifact glossary and current contribution snapshot.
- [paper/README.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/paper/README.md:1)
  Manuscript-source map and paper build notes.
- [paper/neurips_paper.tex](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/paper/neurips_paper.tex:1)
  Submission-oriented LaTeX manuscript scaffold grounded in current artifacts.
- `artifacts/`
  Saved failures, patch search outputs, and autopsy reports.
- `external/tau2-bench/`
  Benchmark dependency and data source used by the prototype.

For GitHub, only the curated paper-facing summaries, tables, autopsies, and
case-study artifacts are intended to be tracked. The multi-GB raw replay dumps
and imported benchmark data stay local and are excluded via `.gitignore`.
Paper-bundle and batch runs now also support compact `patch_results.json`
serialization so we do not save full per-candidate patched trajectories unless
we explicitly request full debug output.

## Implemented Method

The current pipeline is:

1. Build or import a failed trajectory.
2. Save structured per-step state:
   pre-snapshot, action, tool result, post-snapshot.
3. Rank suspicious steps with a deterministic heuristic or alternative search
   order.
4. Generate candidate patches for one target step.
5. Restore the saved pre-step snapshot.
6. Apply the patch and replay the remainder.
7. Evaluate the patched rollout with the real benchmark evaluator.
8. Emit an autopsy report with the winning patch or a clean non-recovery result.

The implemented patch families are:

- `tool_args`
  Replace the arguments of an observed tool call.
- `tool_call_replace`
  Replace the tool name and/or arguments for a single observed step.
- `tool_insertion`
  Insert a new tool call before the failing step.
- `tool_deletion`
  Remove the failing step and replay the suffix.
- `context_edit`
  Edit replay context at the saved snapshot boundary.
- `continuation_replace`
  Replace the downstream suffix with a bounded continuation proposal.
- `tool_call_with_oracle_suffix`
  Replace a single step, then continue with the benchmark reference suffix.
  This is an explicit upper-bound ablation, not the main deployable method.

## Search Strategies

The code currently supports:

- `heuristic`
- `reverse`
- `chronological`
- `latest_only`
- `oracle_fault_step`
- `random_candidate`
- `no_repair`

These can be run through the CLI for both synthetic and imported natural
failure corpora.

## Current Results

### Synthetic Controlled Failure Smoke Test

Artifact:

- [artifacts/search/patch_summary.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/search/patch_summary.json:1)

Saved artifact result:

- `failure_count`: `1`
- `recovered_count`: `1`
- `success_recovery_rate`: `1.0`
- `total_token_cost`: `28`
- `evaluated_candidate_count`: `1`
- `known_fault_count`: `1`
- `localization_top1_accuracy`: `1.0`
- `localization_mrr`: `1.0`
- `winning patch family`: `tool_args`

Interpretation:

- Controlled single-bad-step repair works end to end.
- Snapshot restore, replay, patch application, and evaluation are functioning.

### Synthetic Strategy And Localization Comparison

Artifacts:

- [artifacts/synthetic_strategy_tables_3/paper_tables.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/synthetic_strategy_tables_3/paper_tables.md:1)
- [artifacts/synthetic_strategy_tables_3/synthetic_localization_results.csv](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/synthetic_strategy_tables_3/synthetic_localization_results.csv:1)
- [artifacts/synthetic_strategy_figures_3/figure_data.csv](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/synthetic_strategy_figures_3/figure_data.csv:1)

Saved artifact result:

- `controlled failures`: `3`
- `strategies`: `heuristic`, `reverse`, `chronological`, `latest_only`,
  `oracle_fault_step`, `random_candidate`, `no_repair`
- `heuristic`, `reverse`, `latest_only`, and `oracle_fault_step` each recover
  `3 / 3` failures with perfect localization on this slice.
- `latest_only` had the lowest search cost among the successful repair
  strategies: `3165` total token cost across `3` failures, with median token
  cost `866`
- `chronological` drops to `2 / 3` recovery and has poor localization:
  `localization_top1_accuracy = 0.0`, `localization_top3_accuracy = 0.0`,
  `localization_mrr = 0.164`, `mean_fault_rank = 7.0`
- `random_candidate` also drops to `2 / 3` recovery with weaker localization:
  `localization_top1_accuracy = 0.0`, `localization_top3_accuracy = 0.667`,
  `localization_mrr = 0.264`
- `no_repair` cleanly stayed at `success_recovery_rate = 0.0`

Interpretation:

- Recovery alone is not enough as the synthetic headline metric.
- The repo now has a controlled-fault evaluation story where localization
  quality and recovery quality can diverge and be measured separately.
- That divergence is no longer a one-off anecdote: it now appears across a
  saved three-failure synthetic suite.
- This is the right substrate for a synthetic table in a paper:
  recovery, cost, and localization accuracy all come from saved JSON/CSV
  instead of notebook-only analysis.

### Natural Failure Strict Replay

Artifact:

- [artifacts/natural_search/patch_summary.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/natural_search/patch_summary.json:1)

Current result:

- `failure_count`: `3`
- `recovered_count`: `0`
- `success_recovery_rate`: `0.0`
- `total_token_cost`: `280`
- `evaluated_family_counts`: `{"tool_call_replace": 8}`

Interpretation:

- Single-step lookup/tool-call repairs alone are not enough when the rest of
  the observed suffix stays unchanged.
- This is an important negative result, not a bug to hide.

### Natural Failure Strict Replay With Staged Continuation

Artifacts:

- [artifacts/natural_runtime_smoke_search/patch_summary.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/natural_runtime_smoke_search/patch_summary.json:1)
- [artifacts/natural_runtime_smoke_autopsy.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/natural_runtime_smoke_autopsy.json:1)

Current result:

- `failure_count`: `1`
- `recovered_count`: `1`
- `success_recovery_rate`: `1.0`
- `total_token_cost`: `483`
- `winning patch family`: `continuation_replace`
- `patch_size`: `3`

Interpretation:

- Strict replay is no longer limited to replaying the stale observed suffix.
- The system can patch a real failed lookup, run that patched tool call,
  inspect the replayed tau state, synthesize a bounded continuation, and flip
  the true benchmark reward without oracle suffix reuse.
- This is the current strongest natural-failure evidence in the repo.

### Natural Failure Oracle-Continuation Upper Bound

Artifact:

- [artifacts/natural_oracle_suffix_search/patch_summary.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/natural_oracle_suffix_search/patch_summary.json:1)

Current result:

- `failure_count`: `3`
- `recovered_count`: `1`
- `success_recovery_rate`: `0.3333333333333333`
- `total_token_cost`: `443`
- `evaluated_family_counts`:
  `{"tool_call_replace": 3, "tool_call_with_oracle_suffix": 3}`

Interpretation:

- At least one imported natural failure is recoverable once the localized fix is
  paired with a correct continuation.
- This means the bottleneck is no longer only fault localization; continuation
  generation is now a real research target.

### Current Autopsy Examples

Artifact:

- [artifacts/natural_oracle_suffix_autopsy_report.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/natural_oracle_suffix_autopsy_report.json:1)

Strict non-oracle recovered case:

- Failure: `retail:35:natural:0:39d2c249-6e85-4db3-8f36-049be2744cf3`
- Root-cause step: `0`
- Original action:
  `find_user_id_by_email(email="aarav.santos8321@example.com")`
- Patched action:
  `find_user_id_by_email(email="aarav.santos8320@example.com")`
- Recovery mode:
  `continuation_replace`

Oracle-upper-bound recovered case:

- Failure: `retail:35:natural:0:39d2c249-6e85-4db3-8f36-049be2744cf3`
- Root-cause step: `2`
- Original action:
  `find_user_id_by_name_zip(first_name="Aarav", last_name="Santos", zip="94109")`
- Patched action:
  `get_user_details(user_id="aarav_santos_2259")`
- Recovery mode:
  `tool_call_with_oracle_suffix`

Interpretation:

- The system can now produce concrete, reproducible autopsies for real saved
  benchmark failures in both strict and oracle-upper-bound settings.

### Mixed-Domain Paper Bundle Smoke Run

Artifacts:

- [artifacts/paper_bundle_smoke_cli/paper_bundle_summary.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_bundle_smoke_cli/paper_bundle_summary.json:1)
- [artifacts/paper_bundle_smoke_cli/corpus/corpus_manifest.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_bundle_smoke_cli/corpus/corpus_manifest.json:1)
- [artifacts/paper_bundle_smoke_cli/paper_tables/paper_tables.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_bundle_smoke_cli/paper_tables/paper_tables.md:1)

Saved artifact result:

- `domains`: `["airline", "retail"]`
- `task_splits`: `["base"]`
- `failure_count`: `2`
- `strict recovered_count`: `1`
- `strict success_recovery_rate`: `0.5`
- `oracle recovered_count`: `1`
- `winning strict patch family`: `tool_deletion`
- `figure_count`: `2`

Interpretation:

- The full paper bundle path works from the CLI, not only via test helpers.
- Mixed-domain corpora now round-trip through collection, search, autopsy, and
  table-generation without assuming a single adapter or task split.
- The bundle now includes a verified strict natural-failure recovery in
  `airline`, where deleting a bad mutating cancellation step flips the true
  benchmark reward.

### Clean Multi-Model Mixed-Domain Bundle

Artifacts:

- [artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json:1)
- [artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json:1)
- [artifacts/paper_bundle_multimodel_32/paper_tables/paper_tables.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_bundle_multimodel_32/paper_tables/paper_tables.md:1)

Saved artifact result:

- `domains`: `["airline", "retail"]`
- `source model families`: `claude-3.7-sonnet`, `gpt-4.1`, `gpt-4.1-mini`,
  `o4-mini`
- `failure_count`: `32`
- `strict recovered_count`: `13`
- `strict success_recovery_rate`: `0.40625`
- `strict per-domain recovery`: `airline = 10 / 16`, `retail = 3 / 16`
- `strict total_token_cost`: `2000`
- `strict oracle gap on this slice`: `0.0`
- `winning strict patch family`: `tool_deletion`
- `replay reward histogram before search`: `32` cases at `0.0`, `0` replay
  successes

Interpretation:

- We now have a larger clean multi-model mixed-domain bundle beyond the earlier
  smoke, six-case, and sixteen-case artifacts.
- Strict natural recovery is no longer only a single-case anecdote.
- The current deterministic method is strongest on short harmful-mutation
  `airline` failures, while `retail` still needs a stronger continuation
  policy.
- On this bundle, oracle continuation does not add lift over strict replay,
  which suggests the current recoveries are mostly deletion-style rather than
  continuation-limited.

### Paper Case Studies

Artifacts:

- [artifacts/paper_case_studies_multimodel_32/case_studies.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_case_studies_multimodel_32/case_studies.md:1)
- [artifacts/paper_case_studies_multimodel_32/case_studies.json](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/paper_case_studies_multimodel_32/case_studies.json:1)

Saved artifact result:

- `selected_case_count`: `6`
- `selected_domains`: `["airline", "retail"]`
- `selected_patch_families`: `["continuation_replace", "tool_deletion"]`

Interpretation:

- The repo now has a paper-facing case-study panel artifact rather than only raw
  autopsy JSON.
- The current panel now explicitly covers both main natural repair mechanisms
  we have so far: retail staged continuation and airline mutating-step
  deletion.

### Reproducibility Snapshot

Artifacts:

- [artifacts/reproducibility_snapshot/REPRODUCIBILITY.md](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/reproducibility_snapshot/REPRODUCIBILITY.md:1)
- [artifacts/reproducibility_snapshot/requirements-selected.txt](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/reproducibility_snapshot/requirements-selected.txt:1)
- [artifacts/reproducibility_snapshot/requirements-lock.txt](/c:/Users/Admin/VSCodeProjects/Post-Hoc%20Minimal%20Patch%20Suggestion%20via%20Execution%20Intervention/artifacts/reproducibility_snapshot/requirements-lock.txt:1)

Saved artifact result:

- `distribution_count`: `144`
- `selected_distribution_count`: `5`
- upstream `tau2` lockfiles detected:
  `external/tau2-bench/pyproject.toml` and `external/tau2-bench/uv.lock`

Interpretation:

- The repo now has a pinned dependency snapshot that is stronger than the older
  environment manifest alone.
- This is not yet a validated clean-room reproduction, but it closes one of the
  biggest paper-readiness bookkeeping gaps.

## What To Run

Collect controlled failures:

```powershell
python main.py collect-failures --domain retail --limit 10 --output-dir artifacts/collect
```

Search patches on the controlled corpus:

```powershell
python main.py search-patches --input-dir artifacts/collect --output-dir artifacts/search
```

Build a reusable natural-failure corpus manifest:

```powershell
python main.py build-corpus `
  --name retail_airline_corpus `
  --domain-specs `
    retail::base::external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json `
    airline::base::external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json `
  --limit-per-domain 100 `
  --output-dir artifacts/corpus
```

Build a synthetic mixed-domain corpus for workshop localization experiments:

```powershell
python main.py build-synthetic-corpus `
  --name retail_airline_synthetic `
  --domains retail airline `
  --limit-per-domain 12 `
  --output-dir artifacts/workshop_synthetic
```

Import natural failures from saved `tau2` results:

```powershell
python main.py import-natural-failures `
  --domain retail `
  --task-split base `
  --results-path external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json `
  --limit 25 `
  --output-dir artifacts/natural
```

Run strict natural replay:

```powershell
python main.py search-patches `
  --input-dir artifacts/natural `
  --output-dir artifacts/natural_search `
  --strategy heuristic
```

Run a synthetic strategy comparison with localization outputs:

```powershell
python main.py compare-strategies `
  --input-dir artifacts/collect `
  --output-dir artifacts/synthetic_strategy_comparison_smoke `
  --strategies heuristic reverse chronological latest_only oracle_fault_step random_candidate no_repair `
  --max-evaluations 4
```

Run the strict staged-continuation smoke path:

```powershell
python main.py import-natural-failures `
  --domain retail `
  --task-split base `
  --results-path external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json `
  --limit 1 `
  --output-dir artifacts/natural_runtime_smoke_collect

python main.py search-patches `
  --input-dir artifacts/natural_runtime_smoke_collect `
  --output-dir artifacts/natural_runtime_smoke_search `
  --strategy chronological `
  --max-evaluations 10

python main.py report-autopsy `
  --input-dir artifacts/natural_runtime_smoke_search `
  --output-path artifacts/natural_runtime_smoke_autopsy.json
```

Run the oracle-continuation upper bound:

```powershell
python main.py search-patches `
  --input-dir artifacts/natural `
  --output-dir artifacts/natural_oracle_suffix_search `
  --strategy heuristic `
  --include-oracle-suffix
```

Generate an aggregated autopsy report:

```powershell
python main.py report-autopsy `
  --input-dir artifacts/natural_oracle_suffix_search `
  --output-path artifacts/natural_oracle_suffix_autopsy_report.json
```

Run a saved experiment config:

```powershell
python main.py run-batch --config configs/paper_batch_template.json
```

The default paper batch template sets `compact_results = true`.

Run the workshop retry baselines on a saved corpus:

```powershell
python main.py run-baselines `
  --input-dir artifacts/corpus `
  --output-dir artifacts/workshop_retry_baselines `
  --method-variants retry_from_scratch retry_from_localized_snapshot raw_continuation_from_snapshot `
  --strategy heuristic `
  --proposer-backend openrouter `
  --model-slug openai/gpt-4.1-mini
```

Sweep budget or model settings:

```powershell
python main.py sweep-budget `
  --input-dir artifacts/corpus `
  --output-dir artifacts/budget_sweep `
  --strategy heuristic `
  --evaluation-budgets 1 2 4 8

python main.py sweep-models `
  --input-dir artifacts/corpus `
  --output-dir artifacts/model_sweep `
  --strategy heuristic `
  --model-slugs openai/gpt-4.1-mini openai/o4-mini
```

Generate paper-facing figure data:

```powershell
python main.py make-figures `
  --input-dirs artifacts/search artifacts/natural_search artifacts/natural_oracle_suffix_search `
  --output-dir artifacts/figures
```

Generate paper-facing result tables:

```powershell
python main.py make-paper-tables `
  --input-dirs artifacts/search artifacts/natural_search artifacts/natural_oracle_suffix_search artifacts/natural_runtime_smoke_search `
  --output-dir artifacts/paper_tables
```

Generate a reviewer-facing artifact guide:

```powershell
python main.py make-artifact-guide `
  --input-dirs `
    artifacts/search `
    artifacts/synthetic_strategy_tables_smoke `
    artifacts/synthetic_strategy_figures_smoke `
    artifacts/natural_search `
    artifacts/natural_oracle_suffix_search `
    artifacts/natural_runtime_smoke_search `
    artifacts/paper_bundle_smoke_cli `
    artifacts/paper_bundle_smoke_cli/paper_tables `
  --output-dir artifacts/reviewer_artifact_guide_smoke `
  --title "Reviewer Artifact Guide (Smoke)" `
  --paper-draft-path paper/paper_draft.md `
  --checklist-path paper/submission_checklist.md
```

Generate paper-facing case studies from saved autopsies:

```powershell
python main.py make-case-studies `
  --input-paths `
    artifacts/natural_runtime_smoke_autopsy.json `
    artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json `
  --output-dir artifacts/paper_case_studies_multimodel_32 `
  --title "Paper Case Studies (Multi-Model 32)" `
  --max-cases 6
```

Freeze the current local dependency environment:

```powershell
python main.py freeze-deps --output-dir artifacts/reproducibility_snapshot
```

Run the full mixed-domain paper bundle in one command:

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

`make-paper-bundle` now writes compact search results by default. Pass
`--full-results` only when you need every evaluated candidate's full patched
trajectory for debugging.

The bundle writes:

- `corpus/corpus_manifest.json` and `corpus/failures.json`
- `strict_search/patch_summary.json`
- `strict_search/patch_results.json` in compact mode by default
- `oracle_upper_bound/patch_summary.json`
- `strict_autopsy_report.json` and `oracle_autopsy_report.json`
- `figures/figure_manifest.json`
- `paper_tables/paper_tables.json` and `paper_tables/paper_tables.md`
- `paper_bundle_summary.json`

Run the workshop-first bundle in one command:

```powershell
python main.py make-workshop-bundle `
  --name workshop_bundle_smoke `
  --natural-domain-specs `
    retail::base::external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json `
    airline::base::external/tau2-bench/data/tau2/results/final/gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json `
  --natural-limit-per-domain 1 `
  --synthetic-domains retail airline `
  --synthetic-limit-per-domain 1 `
  --output-dir artifacts/workshop_bundle_smoke `
  --strict-max-evaluations 1 `
  --oracle-max-evaluations 1 `
  --continuation-horizon 2 `
  --beam-width 1 `
  --max-candidates-per-step 1
```

The workshop bundle writes:

- `natural_corpus/corpus_manifest.json` and `natural_corpus/failures.json`
- `synthetic_corpus/corpus_manifest.json` and `synthetic_corpus/failures.json`
- `strict_search/patch_summary.json`
- `retry_baselines/baseline_comparison.json`
- `oracle_upper_bound/patch_summary.json`
- `paper_tables/paper_tables.json`
- `case_studies/case_studies.json`
- `WORKSHOP_RELEASE.md`
- `workshop_bundle_summary.json`

Run tests:

```powershell
python -m unittest -v
```

## What Was Added Most Recently

These are the latest meaningful changes and the reason they matter:

- A reusable experiment harness:
  corpus building, batch configs, budget sweeps, model sweeps, and figure-data export.
- A reproducible paper-results path:
  saved experiment directories can now be converted directly into CSV/Markdown
  paper tables without notebook glue.
- Synthetic localization reporting:
  saved search outputs now surface fault-rank accuracy, MRR, and true-fault
  recovery alignment through both summaries and exported paper tables.
- Reviewer artifact packaging:
  the repo can now emit an `ARTIFACT_README.md` plus environment manifest for a
  set of saved experiment directories, which makes the smoke evidence easier to
  hand to reviewers or future collaborators.
- Paper case-study export:
  saved autopsy reports can now be turned directly into a human-readable
  case-study panel artifact for the manuscript.
- Dependency snapshot export:
  the repo can now emit both a selected package snapshot and a full pinned local
  requirements lock artifact.
- Mixed-domain corpus and replay support:
  search now dispatches by `(domain, task_split)` instead of assuming a single
  adapter for the whole corpus.
- A one-command bundle entrypoint:
  the repo can now build a smoke paper package end to end from raw saved
  `tau2` results.
- A workshop-first experiment path:
  the repo can now build synthetic plus natural corpora, run simple rerun
  baselines, and package a short-paper artifact bundle from the CLI.
- Mutating-step deletion recovery:
  the search can now repair natural failures where the harmful step succeeded at
  the tool level but should never have been executed.
- A richer intervention taxonomy:
  replacement, insertion, deletion, context edit, and continuation replacement.
- A proposer abstraction:
  deterministic continuation now works offline, including staged replay from a
  patched retail failure, and OpenRouter is wired as an optional backend.
- Hardened candidate evaluation:
  invalid replay candidates now fail cleanly instead of crashing the full search.

## What Future Work Should Do Next

If continuing this project, the best next steps are:

1. Generalize the current staged continuation proposer beyond the retail smoke path.
   Best version: local or hosted model proposer with constrained action decoding.
2. Strengthen the current intervention space:
   real context-edit and scratchpad-edit generation, broader missing-tool
   insertion, and less heuristic deletion coverage.
3. Expand natural-failure experiments across more tasks and domains.
4. Run serious sweeps with the existing harness:
   strict vs oracle, budget sweeps, model sweeps, and per-domain ablations.
5. Write a formal evaluation section with:
   strict replay results, oracle-continuation upper bound, synthetic
   localization tables, and search-cost comparisons.

## NeurIPS-Ready Gap

What would make this submission much stronger:

- Hundreds of natural failures, not only the current clean `16`-case bundle.
- A non-oracle continuation module that closes part of the strict-vs-upper-bound gap
  across retail and airline, not only one retail smoke case.
- At least one local-model baseline for patch proposal.
- A cleaner ablation suite over patch families and search strategies.
- Human inspection of sampled autopsies for causal plausibility.

## Notes For Future Me

If context is short and you need to restart quickly, remember:

- The repo is already on real benchmark infrastructure, not mocks.
- Synthetic repair works.
- Strict natural replay now has one verified recovered retail failure under
  `artifacts/natural_runtime_smoke_search`.
- The stronger mixed-domain bundle lives under
  `artifacts/paper_bundle_multimodel_32` and currently recovers `13 / 32`
  strict natural cases with per-domain recovery `airline = 10 / 16`,
  `retail = 3 / 16`.
- The canonical synthetic localization smoke comparison lives under
  `artifacts/synthetic_strategy_tables_3` and
  `artifacts/synthetic_strategy_figures_3`.
- The canonical reviewer-style smoke artifact guide lives under
  `artifacts/reviewer_artifact_guide_smoke`.
- The current synthetic-suite reviewer guide lives under
  `artifacts/reviewer_artifact_guide_synthetic_3`.
- The broader reviewer-facing guide lives under
  `artifacts/reviewer_artifact_guide_multimodel_32`.
- The paper-facing case-study panel lives under
  `artifacts/paper_case_studies_multimodel_32`.
- The reproducibility snapshot lives under
  `artifacts/reproducibility_snapshot`.
- Oracle continuation still matters because it exposes recoverable cases beyond
  the current deterministic strict continuation heuristic.
- The older one-plus-one CLI smoke bundle lives under
  `artifacts/paper_bundle_smoke_cli`.
- `docs/ARTIFACT_MAP.md` is the quickest way to remember what
  `natural`, `natural_collect`, and the paper bundles mean.
- Corpus manifests are saved as `corpus_manifest.json`, not `corpus_summary.json`.
- The next real bottleneck is scaling strict continuation beyond one-off domain logic.
- Do not overclaim benchmark-wide natural recovery until that broader module exists.
