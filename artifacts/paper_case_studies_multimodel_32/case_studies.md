# Paper Case Studies (Multi-Model 32)

Selected `6` case studies from `33` saved autopsy entries across `2` source artifact(s).

## Summary

- Recovered cases available: `14`
- Selected case count: `6`
- Selected domains: `['airline', 'retail']`
- Selected patch families: `['continuation_replace', 'tool_deletion']`
- Selected continuation modes: `['strict_replay']`

## Case 1: retail:35:natural:0:39d2c249-6e85-4db3-8f36-049be2744cf3

- Domain: `retail`
- Task id: `35`
- Recovered: `True`
- Patch family: `continuation_replace`
- Continuation mode: `strict_replay`
- Root-cause step: `0`
- Known fault step: `None`
- Patch size: `3`
- Total search cost: `483`
- Autopsy artifact: `artifacts\natural_runtime_smoke_autopsy.json`
- Benchmark source: `external\tau2-bench\data\tau2\results\final\gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json`

Summary: Recovered retail:35:natural:0:39d2c249-6e85-4db3-8f36-049be2744cf3 by patching step 0 with continuation_replace.

Explanation: The search localized the likely root cause to step 0, applied a continuation_replace intervention, and recovered benchmark reward.

### Original Action

```json
{
  "action_id": "35_natural_0",
  "arguments": {
    "email": "aarav.santos8321@example.com"
  },
  "compare_args": null,
  "info": null,
  "name": "find_user_id_by_email",
  "requestor": "assistant"
}
```

### Patched Action

```json
{
  "action_id": "35_natural_0",
  "arguments": {
    "email": "aarav.santos8320@example.com"
  },
  "compare_args": null,
  "info": null,
  "name": "find_user_id_by_email",
  "requestor": "assistant"
}
```

### Original State Fragment

```json
{
  "agent_db_keys": [
    "orders",
    "products",
    "users"
  ],
  "message_history_length": 1
}
```

### Patched State Fragment

```json
{
  "agent_db_keys": [
    "orders",
    "products",
    "users"
  ],
  "message_history_length": 1,
  "step_deleted": false
}
```

## Case 2: airline:48:natural:0:830f1ac4-f6d3-4d6b-95b1-f52045527e10

- Domain: `airline`
- Task id: `48`
- Recovered: `True`
- Patch family: `tool_deletion`
- Continuation mode: `strict_replay`
- Root-cause step: `0`
- Known fault step: `None`
- Patch size: `1`
- Total search cost: `13`
- Autopsy artifact: `artifacts\paper_bundle_multimodel_32\strict_autopsy_report.json`
- Benchmark source: `external\tau2-bench\data\tau2\results\final\gpt-4.1-2025-04-14_airline_default_gpt-4.1-2025-04-14_4trials.json`

Summary: Recovered airline:48:natural:0:830f1ac4-f6d3-4d6b-95b1-f52045527e10 by patching step 0 with tool_deletion.

Explanation: The search localized the likely root cause to step 0 and recovered benchmark reward by deleting that assistant tool call.

### Original Action

```json
{
  "action_id": "48_natural_0",
  "arguments": {
    "reservation_id": "3RK2T9"
  },
  "compare_args": null,
  "info": null,
  "name": "cancel_reservation",
  "requestor": "assistant"
}
```

### Patched Action

```json
null
```

### Original State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 1
}
```

### Patched State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 2,
  "step_deleted": true
}
```

## Case 3: airline:48:natural:0:c7760ced-1f0f-48b2-b13f-28b02e218a21

- Domain: `airline`
- Task id: `48`
- Recovered: `True`
- Patch family: `tool_deletion`
- Continuation mode: `strict_replay`
- Root-cause step: `0`
- Known fault step: `None`
- Patch size: `1`
- Total search cost: `13`
- Autopsy artifact: `artifacts\paper_bundle_multimodel_32\strict_autopsy_report.json`
- Benchmark source: `external\tau2-bench\data\tau2\results\final\o4-mini-2025-04-16_airline_default_gpt-4.1-2025-04-14_4trials.json`

Summary: Recovered airline:48:natural:0:c7760ced-1f0f-48b2-b13f-28b02e218a21 by patching step 0 with tool_deletion.

Explanation: The search localized the likely root cause to step 0 and recovered benchmark reward by deleting that assistant tool call.

### Original Action

```json
{
  "action_id": "48_natural_0",
  "arguments": {
    "reservation_id": "3RK2T9"
  },
  "compare_args": null,
  "info": null,
  "name": "cancel_reservation",
  "requestor": "assistant"
}
```

### Patched Action

```json
null
```

### Original State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 1
}
```

### Patched State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 2,
  "step_deleted": true
}
```

## Case 4: airline:28:natural:0:764b3beb-e513-4fe2-a7ea-249b40719bc7

- Domain: `airline`
- Task id: `28`
- Recovered: `True`
- Patch family: `tool_deletion`
- Continuation mode: `strict_replay`
- Root-cause step: `1`
- Known fault step: `None`
- Patch size: `1`
- Total search cost: `21`
- Autopsy artifact: `artifacts\paper_bundle_multimodel_32\strict_autopsy_report.json`
- Benchmark source: `external\tau2-bench\data\tau2\results\final\gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json`

Summary: Recovered airline:28:natural:0:764b3beb-e513-4fe2-a7ea-249b40719bc7 by patching step 1 with tool_deletion.

Explanation: The search localized the likely root cause to step 1 and recovered benchmark reward by deleting that assistant tool call.

### Original Action

```json
{
  "action_id": "28_natural_1",
  "arguments": {
    "reservation_id": "SI5UKW"
  },
  "compare_args": null,
  "info": null,
  "name": "cancel_reservation",
  "requestor": "assistant"
}
```

### Patched Action

```json
null
```

### Original State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 3
}
```

### Patched State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 4,
  "step_deleted": true
}
```

## Case 5: airline:47:natural:0:7b6f70f0-fda5-46a9-9cfa-60de828632f3

- Domain: `airline`
- Task id: `47`
- Recovered: `True`
- Patch family: `tool_deletion`
- Continuation mode: `strict_replay`
- Root-cause step: `1`
- Known fault step: `None`
- Patch size: `1`
- Total search cost: `21`
- Autopsy artifact: `artifacts\paper_bundle_multimodel_32\strict_autopsy_report.json`
- Benchmark source: `external\tau2-bench\data\tau2\results\final\gpt-4.1-2025-04-14_airline_default_gpt-4.1-2025-04-14_4trials.json`

Summary: Recovered airline:47:natural:0:7b6f70f0-fda5-46a9-9cfa-60de828632f3 by patching step 1 with tool_deletion.

Explanation: The search localized the likely root cause to step 1 and recovered benchmark reward by deleting that assistant tool call.

### Original Action

```json
{
  "action_id": "47_natural_1",
  "arguments": {
    "reservation_id": "H8Q05L"
  },
  "compare_args": null,
  "info": null,
  "name": "cancel_reservation",
  "requestor": "assistant"
}
```

### Patched Action

```json
null
```

### Original State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 3
}
```

### Patched State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 4,
  "step_deleted": true
}
```

## Case 6: airline:47:natural:0:ac4ce417-4b30-4470-91db-6605b6df8759

- Domain: `airline`
- Task id: `47`
- Recovered: `True`
- Patch family: `tool_deletion`
- Continuation mode: `strict_replay`
- Root-cause step: `1`
- Known fault step: `None`
- Patch size: `1`
- Total search cost: `21`
- Autopsy artifact: `artifacts\paper_bundle_multimodel_32\strict_autopsy_report.json`
- Benchmark source: `external\tau2-bench\data\tau2\results\final\gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json`

Summary: Recovered airline:47:natural:0:ac4ce417-4b30-4470-91db-6605b6df8759 by patching step 1 with tool_deletion.

Explanation: The search localized the likely root cause to step 1 and recovered benchmark reward by deleting that assistant tool call.

### Original Action

```json
{
  "action_id": "47_natural_1",
  "arguments": {
    "reservation_id": "H8Q05L"
  },
  "compare_args": null,
  "info": null,
  "name": "cancel_reservation",
  "requestor": "assistant"
}
```

### Patched Action

```json
null
```

### Original State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 3
}
```

### Patched State Fragment

```json
{
  "agent_db_keys": [
    "flights",
    "reservations",
    "users"
  ],
  "message_history_length": 4,
  "step_deleted": true
}
```

