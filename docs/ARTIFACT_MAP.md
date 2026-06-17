# Artifact Map

This note explains the saved artifact directories that are easiest to confuse
when returning to the repo after a long break.

## Current Contribution Snapshot

The strongest paper-safe contribution claim right now is:

1. The project runs on real `tau2`-style `retail` and `airline` environments,
   not only a mock sandbox.
2. Every trajectory is replayable from saved pre-step snapshots, so patch
   search is causal rather than prompt-only.
3. The system supports structured intervention families such as
   `tool_call_replace`, `tool_deletion`, and `continuation_replace`.
4. Synthetic failures already support exact localization metrics in addition to
   recovery metrics.
5. Natural saved benchmark failures can now be recovered in strict non-oracle
   mode in two qualitatively different ways:
   retail continuation repair from replayed state, and airline mutating-step
   deletion.
6. A clean multi-model mixed-domain bundle already exists over `32` imported
   replay-failing natural cases and recovers `13 / 32` cases under a
   deterministic strict-search configuration, with per-domain recovery
   `airline = 10 / 16` and `retail = 3 / 16`.

What is still not true:

- benchmark-scale natural recovery;
- strong cross-domain continuation generation;
- final paper tables and figures from large sweeps;
- a validated clean-room reproduction.

## Artifact Names

### `artifacts/natural`

Canonical broader retail natural-failure import from the saved `tau2` result
file.

- Domain: `retail`
- Imported failures: `3`
- Main use: broader retail negative result and oracle-gap analysis
- Key file: [summary.json](../artifacts/natural/summary.json)

This is the main retail natural corpus used when we say "broader imported
retail failures."

### `artifacts/natural_collect`

Older one-case retail import used by earlier smoke commands.

- Domain: `retail`
- Imported failures: `1`
- Main use: legacy smoke input
- Key file: [summary.json](../artifacts/natural_collect/summary.json)

This is not the preferred broader retail corpus anymore.

### `artifacts/natural_runtime_smoke_collect`

Single-case retail import prepared specifically for the staged strict
continuation smoke path.

- Domain: `retail`
- Imported failures: `1`
- Main use: strict continuation replay demo
- Key file: [summary.json](../artifacts/natural_runtime_smoke_collect/summary.json)

### `artifacts/natural_search`

Patch-search output over `artifacts/natural`.

- Current role: shows that naive strict replay plus simple single-step patching
  does not recover the broader retail import
- Key file: [patch_summary.json](../artifacts/natural_search/patch_summary.json)

### `artifacts/natural_runtime_smoke_search`

Patch-search output for the single retail staged-continuation run.

- Current role: strongest strict retail continuation artifact
- Key file: [patch_summary.json](../artifacts/natural_runtime_smoke_search/patch_summary.json)

### `artifacts/synthetic_collect_3`

Three controlled synthetic corruption failures collected from the real retail
benchmark adapter.

- Domain: `retail`
- Failures: `3`
- Main use: broader synthetic localization and strategy-comparison input
- Key file: [summary.json](../artifacts/synthetic_collect_3/summary.json)

### `artifacts/synthetic_strategy_tables_3`

Current best synthetic localization table artifact.

- Controlled failures: `3`
- Strategies: `heuristic`, `reverse`, `chronological`, `latest_only`,
  `oracle_fault_step`, `random_candidate`, `no_repair`
- Key observation: `chronological` and `random_candidate` fall to `2 / 3`
  recovery with weak localization, while `heuristic`, `reverse`,
  `latest_only`, and `oracle_fault_step` stay at `3 / 3`
- Key files:
  [paper_tables.md](../artifacts/synthetic_strategy_tables_3/paper_tables.md),
  [synthetic_localization_results.csv](../artifacts/synthetic_strategy_tables_3/synthetic_localization_results.csv),
  [paper_tables.json](../artifacts/synthetic_strategy_tables_3/paper_tables.json)

### `artifacts/synthetic_strategy_figures_3`

Figure-ready CSV and markdown report for the three-failure synthetic strategy
suite.

- Figure rows: `7`
- Main use: recovery/localization plot inputs for the manuscript
- Key files:
  [figure_data.csv](../artifacts/synthetic_strategy_figures_3/figure_data.csv),
  [figure_report.md](../artifacts/synthetic_strategy_figures_3/figure_report.md)

### `artifacts/paper_bundle_smoke_cli`

Early mixed-domain smoke bundle run entirely from the CLI.

- Domains: `1` retail + `1` airline failure
- Current role: proves the full paper-bundle path works end to end
- Key file: [paper_bundle_summary.json](../artifacts/paper_bundle_smoke_cli/paper_bundle_summary.json)

### `artifacts/paper_bundle_multimodel_32`

Current best mixed-domain saved bundle for the paper narrative.

- Domains: `16` retail + `16` airline failures
- Source model families: `claude-3.7-sonnet`, `gpt-4.1`, `gpt-4.1-mini`,
  `o4-mini`
- Strict deterministic result: `13 / 32` recovered
- Per-domain result: `airline = 10 / 16`, `retail = 3 / 16`
- Oracle result on this slice: `13 / 32` recovered
- Current role: strongest clean mixed-domain natural bundle in the repo
- Search-result note: newer paper bundles default to compact
  `patch_results.json` serialization, so per-candidate
  `patched_trajectory` payloads are omitted unless full debug output is
  requested
- Key files:
  [paper_bundle_summary.json](../artifacts/paper_bundle_multimodel_32/paper_bundle_summary.json),
  [strict_autopsy_report.json](../artifacts/paper_bundle_multimodel_32/strict_autopsy_report.json),
  [paper_tables.md](../artifacts/paper_bundle_multimodel_32/paper_tables/paper_tables.md)

### `artifacts/paper_case_studies_multimodel_32`

Current paper-facing case-study panel derived from saved autopsy reports.

- Selected cases: `6`
- Domains: `airline`, `retail`
- Patch families: `tool_deletion`, `continuation_replace`
- Main use: manuscript case-study panel and qualitative examples
- Key files:
  [case_studies.md](../artifacts/paper_case_studies_multimodel_32/case_studies.md),
  [case_studies.json](../artifacts/paper_case_studies_multimodel_32/case_studies.json)

### `artifacts/reviewer_artifact_guide_multimodel_32`

Reviewer-facing guide for the clean `32`-case natural bundle and its paper
artifacts.

- Entries: `3`
- Main use: reviewer/repro handoff for the current strongest natural bundle
- Key files:
  [ARTIFACT_README.md](../artifacts/reviewer_artifact_guide_multimodel_32/ARTIFACT_README.md),
  [artifact_manifest.json](../artifacts/reviewer_artifact_guide_multimodel_32/artifact_manifest.json)

### `artifacts/reviewer_artifact_guide_synthetic_3`

Reviewer-facing guide for the broader three-failure synthetic localization
suite.

- Entries: `6`
- Main use: handoff package for the current strongest synthetic localization
  evidence
- Key files:
  [ARTIFACT_README.md](../artifacts/reviewer_artifact_guide_synthetic_3/ARTIFACT_README.md),
  [artifact_manifest.json](../artifacts/reviewer_artifact_guide_synthetic_3/artifact_manifest.json)

### `artifacts/reproducibility_snapshot`

Current pinned dependency snapshot for reproducibility packaging.

- Selected packages: `tau2`, `litellm`, `openai`, `pydantic`, `httpx`
- Full distribution count: `144`
- Main use: reviewer packaging and environment reconstruction
- Key files:
  [REPRODUCIBILITY.md](../artifacts/reproducibility_snapshot/REPRODUCIBILITY.md),
  [requirements-selected.txt](../artifacts/reproducibility_snapshot/requirements-selected.txt),
  [requirements-lock.txt](../artifacts/reproducibility_snapshot/requirements-lock.txt)

## Which Artifacts To Cite

If the claim is about broader retail natural failures:

- use `artifacts/natural`
- and `artifacts/natural_search`

If the claim is about strict retail continuation recovery:

- use `artifacts/natural_runtime_smoke_collect`
- and `artifacts/natural_runtime_smoke_search`

If the claim is about synthetic localization beyond the one-case smoke run:

- use `artifacts/synthetic_collect_3`
- `artifacts/synthetic_strategy_tables_3`
- and `artifacts/synthetic_strategy_figures_3`

If the claim is about a mixed-domain end-to-end paper bundle:

- use `artifacts/paper_bundle_multimodel_32` first
- use `artifacts/paper_bundle_multimodel_16` only as the earlier mid-scale bundle
- use `artifacts/paper_bundle_broader_6` only as the earlier six-case bundle
- use `artifacts/paper_bundle_smoke_cli` only as the smaller earlier smoke run

If the claim is about the manuscript-ready qualitative examples:

- use `artifacts/paper_case_studies_multimodel_32`

If the claim is about reproducibility packaging:

- use `artifacts/reproducibility_snapshot`

## Short Answer To "What Have We Contributed So Far?"

Up to now, the repo's main contribution is not a new benchmark score. It is a
working debugging methodology:

- import real failed `tau2` agent runs;
- snapshot and restore environment state at every step;
- patch one step or state fragment;
- replay from that exact fork;
- measure whether the final benchmark reward flips;
- serialize the winning intervention as a structured autopsy;
- export paper-facing case-study panels and reviewer-facing reproducibility
  artifacts from those saved results.

That is already enough to support a methods paper trajectory, even though the
large-scale natural experiments are still unfinished.
