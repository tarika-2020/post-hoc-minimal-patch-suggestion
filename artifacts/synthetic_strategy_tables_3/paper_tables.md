# Paper Tables

## Main Results

| label | strategy | proposer_backend | include_oracle_suffix | recovered_count | failure_count | success_recovery_rate | total_token_cost | median_token_cost | p90_token_cost | average_patch_size | success_at_k | cost_normalized_recovery |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| heuristic | heuristic | deterministic | 0 | 3 | 3 | 1.000 | 3309 | 898.0 | 1390.8 | 1.000 | 1.000 | 0.000907 |
| reverse | reverse | deterministic | 0 | 3 | 3 | 1.000 | 3309 | 898.0 | 1390.8 | 1.000 | 1.000 | 0.000907 |
| chronological | chronological | deterministic | 0 | 2 | 3 | 0.667 | 2109 | 918.0 | 918.8 | 1.000 | 0.667 | 0.000948 |
| latest_only | latest_only | deterministic | 0 | 3 | 3 | 1.000 | 3165 | 866.0 | 1320.4 | 1.000 | 1.000 | 0.000948 |
| oracle_fault_step | oracle_fault_step | deterministic | 0 | 3 | 3 | 1.000 | 3309 | 898.0 | 1390.8 | 1.000 | 1.000 | 0.000907 |
| random_candidate | random_candidate | deterministic | 0 | 2 | 3 | 0.667 | 1961 | 910.0 | 910.8 | 1.000 | 0.667 | 0.001020 |
| no_repair | no_repair | deterministic | 0 | 0 | 3 | 0.000 | 0 | 0.0 | 0.0 | 0.000 | 0.000 | 0.000000 |

## Per-Domain Recovery

| label | domain | case_count | recovered_count | success_recovery_rate |
| --- | --- | ---: | ---: | ---: |
| heuristic | retail | 3 | 3 | 1.000 |
| reverse | retail | 3 | 3 | 1.000 |
| chronological | retail | 3 | 2 | 0.667 |
| latest_only | retail | 3 | 3 | 1.000 |
| oracle_fault_step | retail | 3 | 3 | 1.000 |
| random_candidate | retail | 3 | 2 | 0.667 |
| no_repair | retail | 3 | 0 | 0.000 |

## Per-Patch-Family Recovery

| label | patch_family | recovered_count |
| --- | --- | ---: |
| heuristic | tool_args | 3 |
| reverse | tool_args | 3 |
| chronological | none | 1 |
| chronological | tool_args | 2 |
| latest_only | tool_args | 3 |
| oracle_fault_step | tool_args | 3 |
| random_candidate | none | 1 |
| random_candidate | tool_args | 2 |
| no_repair | none | 3 |

## Synthetic Localization

| label | strategy | known_fault_count | localization_top1_accuracy | localization_top3_accuracy | localization_mrr | mean_fault_rank | median_fault_rank | true_fault_recovery_rate | recovered_true_fault_alignment |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| heuristic | heuristic | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| reverse | reverse | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| chronological | chronological | 3 | 0.000 | 0.000 | 0.164 | 7.000 | 5.000 | 0.667 | 1.000 |
| latest_only | latest_only | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| oracle_fault_step | oracle_fault_step | 3 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| random_candidate | random_candidate | 3 | 0.000 | 0.667 | 0.264 | 4.667 | 3.000 | 0.667 | 1.000 |
| no_repair | no_repair | 3 | 0.000 | 1.000 | 0.500 | 2.000 | 2.000 | 0.000 | 0.000 |
