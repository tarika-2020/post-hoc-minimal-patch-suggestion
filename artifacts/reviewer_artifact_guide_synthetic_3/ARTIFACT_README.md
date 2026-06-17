# Reviewer Artifact Guide (Synthetic 3)

This guide maps saved experiment artifacts to their current role in the paper pipeline.
- Paper draft: `paper\paper_draft.md`
- Submission checklist: `paper\submission_checklist.md`

## Environment

- Python: `3.13.11`
- Platform: `Windows-11-10.0.26100-SP0`
- Working directory: `C:\Users\Admin\VSCodeProjects\Post-Hoc Minimal Patch Suggestion via Execution Intervention`
- Selected distributions:
  - `httpx==0.28.1`
  - `litellm==1.82.6`
  - `openai==2.26.0`
  - `pydantic==2.12.4`
  - `tau2==1.0.0`

## Artifact Entries

### synthetic_strategy_tables_3

- Type: `paper_tables`
- Path: `artifacts\synthetic_strategy_tables_3`
- Experiment count: `7`
- Main result rows: `7`
- Synthetic localization rows: `7`
- Available files:
  - `paper_tables.json`
  - `paper_tables.md`

### synthetic_strategy_figures_3

- Type: `figure_data`
- Path: `artifacts\synthetic_strategy_figures_3`
- Has CSV: `True`
- Has markdown report: `True`
- Available files:
  - `figure_data.csv`
  - `figure_report.md`

### latest_only

- Type: `patch_run`
- Path: `artifacts\synthetic_strategy_comparison_3\latest_only`
- Strategy: `latest_only`
- Recovered / failures: `3 / 3`
- Success recovery rate: `1.0`
- Total token cost: `3165`
- Known fault count: `3`
- Localization top-1: `1.0`
- Localization MRR: `1.0`
- Available files:
  - `patch_summary.json`
  - `patch_results.json`

### chronological

- Type: `patch_run`
- Path: `artifacts\synthetic_strategy_comparison_3\chronological`
- Strategy: `chronological`
- Recovered / failures: `2 / 3`
- Success recovery rate: `0.6666666666666666`
- Total token cost: `2109`
- Known fault count: `3`
- Localization top-1: `0.0`
- Localization MRR: `0.16363636363636366`
- Available files:
  - `patch_summary.json`
  - `patch_results.json`

### random_candidate

- Type: `patch_run`
- Path: `artifacts\synthetic_strategy_comparison_3\random_candidate`
- Strategy: `random_candidate`
- Recovered / failures: `2 / 3`
- Success recovery rate: `0.6666666666666666`
- Total token cost: `1961`
- Known fault count: `3`
- Localization top-1: `0.0`
- Localization MRR: `0.2638888888888889`
- Available files:
  - `patch_summary.json`
  - `patch_results.json`

### no_repair

- Type: `patch_run`
- Path: `artifacts\synthetic_strategy_comparison_3\no_repair`
- Strategy: `no_repair`
- Recovered / failures: `0 / 3`
- Success recovery rate: `0.0`
- Total token cost: `0`
- Known fault count: `3`
- Localization top-1: `0.0`
- Localization MRR: `0.5`
- Available files:
  - `patch_summary.json`
  - `patch_results.json`

