param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

& $Python main.py collect-failures `
    --domain retail `
    --limit 1 `
    --output-dir artifacts\collect

& $Python main.py search-patches `
    --input-dir artifacts\collect `
    --output-dir artifacts\search `
    --strategy heuristic `
    --max-evaluations 3

& $Python main.py report-autopsy `
    --input-dir artifacts\search `
    --output-path artifacts\autopsy_report.json

& $Python main.py compare-strategies `
    --input-dir artifacts\collect `
    --output-dir artifacts\strategy_comparison `
    --max-evaluations 3 `
    --strategies heuristic reverse chronological latest_only oracle_fault_step

& $Python main.py import-natural-failures `
    --domain retail `
    --task-split base `
    --results-path external\tau2-bench\data\tau2\results\final\gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json `
    --limit 1 `
    --output-dir artifacts\natural_collect

& $Python main.py compare-strategies `
    --input-dir artifacts\natural_collect `
    --output-dir artifacts\natural_strategy_comparison `
    --max-evaluations 3 `
    --strategies heuristic reverse chronological latest_only oracle_fault_step

