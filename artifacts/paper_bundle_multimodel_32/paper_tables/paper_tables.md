# Paper Tables

## Main Results

| label | strategy | proposer_backend | include_oracle_suffix | recovered_count | failure_count | success_recovery_rate | total_token_cost | median_token_cost | p90_token_cost | average_patch_size | success_at_k | cost_normalized_recovery |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| strict_search | heuristic | deterministic | 0 | 13 | 32 | 0.406 | 2000 | 45.0 | 92.2 | 1.000 | 0.406 | 0.006500 |
| oracle_upper_bound | heuristic | deterministic | 1 | 13 | 32 | 0.406 | 2000 | 45.0 | 92.2 | 1.000 | 0.406 | 0.006500 |

## Per-Domain Recovery

| label | domain | case_count | recovered_count | success_recovery_rate |
| --- | --- | ---: | ---: | ---: |
| strict_search | airline | 16 | 10 | 0.625 |
| strict_search | retail | 16 | 3 | 0.188 |
| oracle_upper_bound | airline | 16 | 10 | 0.625 |
| oracle_upper_bound | retail | 16 | 3 | 0.188 |

## Per-Patch-Family Recovery

| label | patch_family | recovered_count |
| --- | --- | ---: |
| strict_search | none | 19 |
| strict_search | tool_deletion | 13 |
| oracle_upper_bound | none | 19 |
| oracle_upper_bound | tool_deletion | 13 |
