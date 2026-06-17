# NeurIPS Submission Outline

## Working Title

Minimal Execution Interventions for Post-Hoc Debugging of Tool-Using Agents

## Abstract Claim

Tool-using agents often fail because one intermediate action corrupts later state.
We study post-hoc repair as an execution-intervention problem: given a failed
trajectory and a replayable environment, search for the smallest action or state
patch that flips final task success. The successful patch provides both a recovery
and a concrete autopsy of the failure.

## Method

1. Collect failed trajectories with full environment snapshots.
2. Rank candidate intervention steps.
3. Generate bounded candidate patches.
4. Restore the pre-step snapshot.
5. Apply one patch and replay the suffix.
6. Select the smallest successful patch, breaking ties by search cost.

## Implemented Patch Families

- `tool_args`: replace arguments while keeping the same tool name.
- `tool_call`: replace tool name, requestor, and arguments as one structured call.

Current structured natural-failure candidates use task text hints for:

- failed identity lookup repair
- alternate email lookup
- failed order lookup repair

## Experimental Setup

### Controlled Corpus

Synthetic corruption of real `tau2` reference action trajectories. This validates
that snapshot replay and minimal repair work when the causal fault is known.

### Natural Corpus

Saved `tau2` baseline result files under:

```text
external/tau2-bench/data/tau2/results/final/
```

The current smoke run imports natural retail failures from:

```text
gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json
```

## Baselines

- `heuristic`: suspicious assistant/error steps first.
- `reverse`: latest step to earliest step.
- `chronological`: earliest step to latest step.
- `latest_only`: patch only the final step.
- `oracle_fault_step`: use known synthetic fault step when available.

## Metrics

- Success Recovery Rate.
- Total search token cost.
- Evaluated candidate count.
- Patch size.
- Patch family distribution.
- Tool error rate for imported natural failures.
- Recovery under fixed rollout budget.

## Current Smoke Results

### Controlled Synthetic Retail

- 1 failure imported.
- Heuristic recovery: 1/1.
- Patch size: 1.
- Heuristic token cost: 28.
- Chronological baseline cost: 84 for the same recovery.

### Natural Saved Retail

- 456 simulations seen.
- 1 failed trajectory imported for the smoke run.
- 4 tool calls.
- 3 tool errors.
- Recovery under budget 3: 0/1.

This negative result is useful: the current structured candidate space is not yet
sufficient for broad natural recovery.

## Main Gaps Before Submission

1. Scale natural failure import to hundreds of failures across retail and airline.
2. Add missing-action insertion and extra-action deletion.
3. Add local model patch proposal via Ollama or vLLM.
4. Add manual autopsy validation for a sampled subset.
5. Produce tables and figures from full experimental runs.
6. Write the final paper with limitations stated directly.

