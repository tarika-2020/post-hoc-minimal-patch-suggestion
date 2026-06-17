# Paper Draft

## Working Title

Minimal Execution Interventions for Post-Hoc Debugging of Tool-Using Agents

## Abstract

Tool-using language agents often fail because a single intermediate action
corrupts the downstream execution state, yet standard benchmark evaluation
typically exposes only the final reward and a raw trajectory trace. We propose
post-hoc minimal patch recovery, a debugging methodology that treats failed
agent trajectories as replayable programs. Given a failed run and full
checkpointed environment state, our method restores an intermediate snapshot,
applies a small structured intervention, replays execution, and tests whether
the benchmark outcome flips from failure to success. The smallest successful
intervention serves two purposes at once: it is a repair and a causal autopsy
of the root failure. We instantiate this framework on real `tau2` / tau3-style
agent environments with deterministic state, tool side effects, and benchmark
evaluators. The current system supports multiple patch families, including tool
argument edits, tool-call replacement, insertion, deletion, context edits, and
bounded continuation replacement, together with explicit search-cost
accounting. On controlled synthetic corruptions, the prototype recovers
failures end to end and reports exact fault-localization metrics such as top-k
accuracy and mean reciprocal rank. On imported natural failures from saved
benchmark runs, the current prototype already demonstrates strict non-oracle
recovery without oracle suffix reuse in both single-case and bundle settings.
A dedicated retail identity-lookup failure is repaired via staged continuation
from replayed state, and a clean multi-model mixed-domain bundle of `32`
replay-failing natural cases yields `13 / 32` strict recoveries under bounded
deterministic search, with per-domain recovery `airline = 10 / 16` and
`retail = 3 / 16`. These results position replayable execution intervention as
a promising methodology for agent debugging: more causal than prompt-only
retry, more interpretable than unconstrained regeneration, and naturally
compatible with benchmark-native evaluation.

## Introduction

Language agents that interact with tools, databases, websites, or code
repositories fail for reasons that are often difficult to diagnose from final
task reward alone. In a typical benchmark run, we observe a user goal, a
multi-step trajectory, and a binary or scalar outcome. If the agent fails, the
default response is usually to inspect the raw trace, retry with a stronger
model, or ask the model to reflect and regenerate. These strategies can improve
performance, but they are weak debugging tools: they do not cleanly isolate
which intermediate decision actually caused failure, and they do not distinguish
whether the real bottleneck is action selection, stale context, harmful state
mutation, or continuation from a corrupted state.

This paper argues that replayable agent environments enable a stronger form of
post-hoc analysis. If the environment state can be checkpointed and restored,
then a failed trajectory can be treated as a stateful program rather than a
frozen transcript. We can pause execution at an intermediate step, edit a small
piece of state or a single action, replay from that fork, and test whether the
benchmark reward changes. This makes it possible to ask a causal question:
which minimal intervention is sufficient to flip the final outcome?

We study this question through post-hoc minimal patch recovery. The goal is not
to train a new agent or to win a benchmark with a larger model. Instead, the
goal is to turn failed trajectories into analyzable objects. A successful patch
provides both a repair and an explanation: it identifies a concrete failure
site, measures the cost of finding a fix, and yields an autopsy artifact that
can be aggregated across many failures.

The key claim is methodological. We are not proposing another benchmark or
another reflection prompt. We are proposing a debugging protocol for
benchmark-native agent executions. That protocol combines checkpointed replay,
structured intervention families, bounded search, and reward-based evaluation.
Its main outputs are success recovery rate, patch minimality, search cost, and
root-cause autopsies.

The current repository already supports this protocol on real `tau2` / tau3
style environments. It includes exact snapshot and restore, structured
trajectory logging, patch search over several intervention families, synthetic
fault injection for controlled localization evaluation, import of natural saved
benchmark failures, and reproducible autopsy generation. The natural-failure
evidence is still small-scale rather than benchmark-scale, but it is already
substantive enough to support an early paper narrative: strict non-oracle
recovery is possible on real saved failures, the resulting interventions are
interpretable, and a clean multi-model natural bundle now exists beyond the
earliest smoke anecdotes.

## Current Contribution Framing

The paper-safe contribution claim at the current repo stage is:

1. We introduce a benchmark-native debugging formulation for tool-using agents:
   post-hoc minimal patch recovery over replayable trajectory state.
2. We build the infrastructure needed to make that formulation real on
   `tau2`-style environments: exact snapshot and restore, structured step
   logging, patchable execution state, and reward-based replay evaluation.
3. We define a concrete intervention/search interface over structured patch
   families rather than only prompt-level retries.
4. We show that controlled synthetic failures support not only recovery
   evaluation, but also exact localization metrics and minimality analysis.
5. We provide early non-oracle natural-failure evidence on real saved benchmark
   failures, showing that this is not only a synthetic corruption story.

What we should not yet claim:

- broad benchmark-scale natural recovery;
- strong model-backed continuation across domains;
- human-validated autopsy quality at scale;
- final comparative superiority over all repair baselines.

## Main Story

The core perspective of this project is that failed agent trajectories should
be debugged more like stateful programs than like one-shot text generations.
If the environment is replayable, then a trajectory can be paused, forked,
edited, and re-executed. This makes it possible to ask a causal question that
is difficult to answer with ordinary prompting alone: what is the smallest
intervention that flips the final task outcome?

That smallest successful intervention is useful even when full repair is not
the only goal. It acts as a localized explanation of failure, exposes whether
the bottleneck is localization or continuation, and yields reproducible autopsy
artifacts that can be inspected, compared, and aggregated across failures.

## Problem Setup

We model a benchmark task as an interactive environment `E` with:

- an initial task specification `x`;
- an environment state `s_0`;
- a deterministic or controlled transition function over tool calls and user
  messages;
- an evaluation function `R` that returns the benchmark outcome for a completed
  trajectory.

Given a baseline agent policy `pi`, executing the task yields a trajectory

`tau = (s_0, a_0, o_0, s_1, a_1, o_1, ..., s_T, y)`

where `a_t` is the agent action at step `t`, `o_t` is the resulting tool or
environment observation, `s_t` is the pre-step environment state, and `y` is
the final benchmark outcome. In our setting, each `s_t` must be serializable
and restorable.

We assume a failed trajectory `tau` with final reward `R(tau) = 0`. A patch
candidate is a tuple

`p = (t, f, delta)`

where `t` is the target step, `f` is a patch family, and `delta` is the patch
payload. Applying `p` means:

1. restore the saved pre-step snapshot `s_t`;
2. modify the action, context, or execution state according to `delta`;
3. resume execution under a specified continuation policy;
4. evaluate the patched rollout with the original benchmark evaluator.

Let `tau'(p)` be the replayed rollout after applying patch `p`. The core search
problem is:

`find p* such that R(tau'(p*)) = 1 and p* minimizes patch size, subject to a bounded search budget`

where patch size depends on patch family and the search budget can include
localization cost, patch-proposal cost, rollout count, and model-token usage.

Two continuation settings are important:

- `strict replay`: continue from the replayed state without using oracle future
  actions from the original benchmark trace;
- `oracle continuation`: use the benchmark reference suffix only as an explicit
  upper-bound analysis tool.

This distinction is central because it separates two sources of difficulty:
localizing the faulty step and generating a good continuation after that step is
changed.

## Method

### Step 1: Failure Collection

We construct two classes of corpora:

- `synthetic corruption` failures, created by perturbing otherwise valid
  benchmark-shaped trajectories so that the true fault step is known;
- `natural imported` failures, loaded from saved `tau2` result files produced
  by an external baseline agent.

For every trajectory we store prompt context, action, tool result, pre-step
snapshot, post-step snapshot, and final outcome metadata.

### Step 2: Fault Localization

Given a failed trajectory, the search ranks candidate intervention steps. The
current system supports deterministic ranking strategies such as heuristic,
reverse, chronological, latest-only, oracle-fault-step for synthetic analysis,
and random candidate order. The long-term interface also supports model-backed
localization, but the current smoke evidence is deterministic.

The point of the localization stage is not only speed. It also enables direct
measurement of root-cause accuracy on synthetic failures with known fault steps.

### Step 3: Patch Proposal

The current intervention families are:

- `tool_args`
- `tool_call_replace`
- `tool_insertion`
- `tool_deletion`
- `context_edit`
- `continuation_replace`
- `tool_call_with_oracle_suffix`

These patch families intentionally operate on structured execution objects
rather than unconstrained free-form text. This keeps search interpretable and
makes patch size measurable by family-specific criteria.

### Step 4: Replay And Continuation

For each candidate patch we restore the saved pre-step snapshot, apply the
patch, execute the modified step when appropriate, and resume execution.

The continuation policy is a critical part of the method. Some failures can be
recovered by editing one action and replaying the original suffix. Others
cannot, because the patched state changes later observations and invalidates the
old suffix. The current system therefore distinguishes:

- simple strict replay of the observed remainder;
- staged continuation from the replayed state;
- oracle suffix continuation as an upper bound only.

This decomposition lets the paper quantify a strict-vs-oracle gap instead of
hiding continuation difficulty inside a single repair number.

### Step 5: Selection And Autopsy Generation

Among successful patches, the system selects the smallest one, breaking ties by
lower search cost. It then emits a structured autopsy containing:

- failure identifier and task metadata;
- root-cause step;
- patch family and patch size;
- original versus patched action or state fragment;
- continuation mode;
- total search cost;
- a short natural-language explanation.

The autopsy is not just an analysis convenience. It is one of the main research
artifacts of the method.

## Evaluation Protocol

The clean evaluation story has two tracks that should remain separate in the
paper.

### Controlled Synthetic Evaluation

Synthetic corruptions provide known fault steps and known pre-corruption
reference behavior. This enables:

- exact localization accuracy;
- minimality analysis under known single-fault settings;
- strategy comparisons where recovery and localization can diverge.

The current repo already exports metrics such as top-1 accuracy, top-3
accuracy, mean reciprocal rank, mean fault rank, and true-fault recovery rate.

### Natural Failure Evaluation

Natural failures are imported from saved benchmark result files. These runs are
ecologically more realistic because the failures were produced by an external
baseline agent rather than injected by our pipeline. The main natural headline
metric should be strict non-oracle recovery. Oracle continuation should be
reported separately as an upper bound, never mixed into the main claim.

### Baselines And Ablations

The current method is positioned against search-order baselines and no-repair
controls. The current implemented set includes:

- `heuristic`
- `reverse`
- `chronological`
- `latest_only`
- `oracle_fault_step`
- `random_candidate`
- `no_repair`

The paper should also retain patch-family ablations, strict-versus-oracle
continuation comparisons, and budget sweeps.

### Core Metrics

The main metrics for the paper should be:

- Success Recovery Rate
- patch size
- total search cost
- success at bounded budget
- per-family recovery
- per-domain recovery
- localization metrics on synthetic failures
- strict-versus-oracle continuation gap

### Main Tables And Figures

The first complete submission should contain at least:

1. A synthetic localization table:
   recovery, top-1 accuracy, top-3 accuracy, MRR, and patch size.
2. A natural recovery table:
   strict recovery, oracle upper bound, search cost, and per-domain breakdown.
3. A patch-family table:
   which interventions actually recover failures.
4. A budget figure:
   recovery versus evaluation budget.
5. A case-study panel:
   before/after autopsy examples for several representative failures.

## Preliminary Experiments

This section documents the current artifact-backed evidence in the repository.
These are smoke-scale results, not final paper-scale experiments, but they are
already useful for validating the methodology and identifying the main research
bottlenecks.

### Experimental Sources

The current evidence comes from four kinds of saved runs:

1. A minimal controlled synthetic recovery run over a single corrupted
   benchmark-shaped trajectory.
2. A broader synthetic strategy-comparison run over three controlled failures
   with seven search strategies and localization metrics.
3. Imported natural retail failures from the saved
   `gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json`
   result file.
4. Mixed-domain natural bundles over saved retail and airline failures,
   including a clean `32`-case multi-model bundle and a separate
   staged-continuation retail recovery run.

Unless otherwise stated, the patch-search runs cited here used the deterministic
proposer backend rather than an external repair LLM.

### Synthetic Setup

The controlled synthetic setting uses benchmark-shaped trajectories with a known
single corruption. This gives exact fault-step supervision and enables direct
measurement of:

- recovery;
- patch size;
- search cost;
- localization top-1 and top-3 accuracy;
- mean reciprocal rank.

The smallest smoke run contains one failed trajectory and validates end-to-end
restore, patch, replay, and evaluation. The larger synthetic comparison
contains three failures evaluated under seven search strategies:

- `heuristic`
- `reverse`
- `chronological`
- `latest_only`
- `oracle_fault_step`
- `random_candidate`
- `no_repair`

### Natural Setup

The current natural-failure evidence comes from saved `tau2` result files. The
broader mixed-domain bundle aggregates failures originally produced by
`claude-3-7-sonnet-20250219`, `gpt-4.1-2025-04-14`,
`gpt-4.1-mini-2025-04-14`, and `o4-mini-2025-04-16`, with
`gpt-4.1-2025-04-14` as the user simulator. The importer now excludes saved
failures that already succeed under exact replay, so the mixed-domain bundle is
a clean replay-failing corpus rather than a mix of replay failures and replay
successes.

The broader imported retail corpus currently contains:

- `456` simulations seen;
- `3` imported failures;
- `16` total tool calls across those failures;
- tool error rate `0.1875`.

The broader imported airline corpus currently contains:

- `200` simulations seen;
- `3` imported failures;
- `6` total tool calls across those failures;
- tool error rate `0.0`.

In addition to this broader import, the repository also contains:

- a dedicated staged-continuation retail smoke run over `1` natural failure;
- an earlier mixed-domain paper-bundle smoke run over `1` retail and `1`
  airline natural failure;
- a clean multi-model mixed-domain bundle over `8` retail and `8` airline
  failures.

## Preliminary Results

### Result 1: Controlled Recovery Works End To End

The minimal synthetic smoke run recovers its single corrupted failure with:

- `failure_count = 1`
- `recovered_count = 1`
- `success_recovery_rate = 1.0`
- `total_token_cost = 28`
- `evaluated_candidate_count = 1`
- winning patch family `tool_args`

This is the first sanity check the paper needs: replay, patch application, and
reward re-evaluation function correctly in a benchmark-native environment.

### Result 2: Recovery And Localization Are Distinct Quantities

The broader synthetic strategy-comparison run shows that recovery alone is not
an adequate debugging metric. Across three controlled corruptions, strategies
diverged substantially in both recovery and localization quality.

Representative examples:

- `heuristic`, `reverse`, `latest_only`, and `oracle_fault_step` each recovered
  `3 / 3` failures with `localization_top1_accuracy = 1.0` and
  `localization_mrr = 1.0`.
- `latest_only` had the lowest total token cost among the perfectly localized
  successful strategies: `3165`, with median token cost `866`.
- `heuristic`, `reverse`, `latest_only`, and `oracle_fault_step` all achieved
  `true_fault_recovery_rate = 1.0`.
- `chronological` dropped to `2 / 3` recovery, with
  `localization_top1_accuracy = 0.0`, `localization_top3_accuracy = 0.0`,
  `localization_mrr = 0.164`, and `mean_fault_rank = 7.0`.
- `random_candidate` also dropped to `2 / 3` recovery with weaker
  localization: `localization_top1_accuracy = 0.0`,
  `localization_top3_accuracy = 0.667`, and `localization_mrr = 0.264`.
- `no_repair` correctly remained at `success_recovery_rate = 0.0`.

The main takeaway is that the paper should report both recovery and
localization metrics. A method can eventually stumble onto a successful patch
without having localized the causal fault well, and this is now visible on a
small multi-case suite rather than only a single corruption anecdote.

### Result 3: Naive Single-Step Natural Repair Fails On The Broader Retail Import

On the broader imported retail natural corpus, heuristic strict replay with
simple tool-call patching recovered:

- `0 / 3` failures
- `success_recovery_rate = 0.0`
- `total_token_cost = 280`
- `evaluated_candidate_count = 8`

This negative result is important. It shows that natural failures are not
solved by merely swapping a single tool call while keeping the observed suffix
fixed. That negative evidence motivates the need for richer continuation and
deletion-style interventions.

### Result 4: Oracle Upper Bound Reveals A Continuation Gap

On the same three imported retail failures, the oracle-continuation upper bound
recovers:

- `1 / 3` failures
- `success_recovery_rate = 0.3333`
- `total_token_cost = 443`
- `evaluated_candidate_count = 6`

The recovered case patches a failed identity-lookup trajectory by replacing a
bad `find_user_id_by_name_zip` action with `get_user_details(user_id=...)` and
then following the reference suffix.

This matters because it distinguishes two problems:

- the system can sometimes localize and identify a viable repair;
- the remaining challenge is generating a correct downstream continuation
  without oracle help.

That gap is a central quantity for the paper, not just an implementation
detail.

### Result 5: Strict Non-Oracle Natural Recovery Is Already Possible

The repo now contains two qualitatively different strict non-oracle recoveries
on real saved benchmark failures.

First, a staged-continuation retail smoke run recovers `1 / 1` imported
natural failure with:

- `success_recovery_rate = 1.0`
- `total_token_cost = 483`
- patch family `continuation_replace`
- patch size `3`

In this case, the repaired action changes an email lookup from
`aarav.santos8321@example.com` to `aarav.santos8320@example.com`, executes that
patched lookup, and then synthesizes a bounded continuation from the replayed
state.

Second, the clean multi-model mixed-domain bundle recovers `13 / 32` natural
failures under strict replay:

- `domains = {retail, airline}`
- `source model families = {claude-3.7-sonnet, gpt-4.1, gpt-4.1-mini, o4-mini}`
- `recovered_count = 13`
- `success_recovery_rate = 0.40625`
- `total_token_cost = 2000`
- per-domain recovery `airline = 10 / 16`, `retail = 3 / 16`
- winning strict patch family `tool_deletion`
- oracle recovery on this slice also `13 / 32`

The recovered cases are dominated by airline failures, including
`airline:48:natural:1:1417fd8f-4882-446d-8dd7-4a389ffee0c5`, where deleting a
harmful mutating `cancel_reservation` tool call at step `1` flips the benchmark
reward to success. The bundle also contains one recovered retail case under the
same strict search configuration. This larger bundle contains three recovered
retail cases in total. It is a stronger real-evidence point than the earlier
one-plus-one, six-case, and sixteen-case bundles because it shows repeatable
natural recovery across a larger, replay-validated, multi-model slice, even
though the current lift is still dominated by one domain and one patch family.

Together, these cases show that the project is no longer only a synthetic
corruption study. Strict non-oracle recovery is already possible on real saved
benchmark failures, though not yet at paper-scale breadth.

### Result 6: Paper-Facing Case Studies And Reproducibility Artifacts Now Exist

The repository now also contains two paper-facing support artifacts that make
the current evidence easier to package.

First, a saved case-study panel artifact selects `6` recovered autopsies across
the current retail continuation run and the clean multi-model mixed-domain
bundle. The selected patch families are `continuation_replace` and
`tool_deletion`, which cover the two main strict natural repair mechanisms the
repo currently demonstrates.

Second, the repo now emits a reproducibility snapshot containing:

- a selected requirements file for the core project packages;
- a full pinned local requirements lock;
- a machine-readable environment manifest;
- references to the upstream `tau2-bench` `pyproject.toml` and `uv.lock`.

These artifacts do not yet replace a full clean-room reproduction audit, but
they move the project closer to submission-ready packaging.

### Result 7: The Current Evidence Supports A Method Paper, Not A Leaderboard Claim

Across all saved smoke results, the strongest current conclusion is:

- the replay-and-patch methodology is real and reproducible;
- synthetic recovery and localization evaluation already work cleanly;
- natural failures expose a genuine continuation bottleneck;
- richer interventions such as staged continuation and action deletion can
  recover some real failures that simple local tool-call substitution cannot;
- a clean thirty-two-case mixed-domain bundle already produces repeatable strict
  recovery, but current success is still uneven across domains.

This is already enough to motivate a NeurIPS-style methodological paper, but it
is not yet enough to claim broad benchmark-scale natural repair performance.

## Limitations And Scope

The current project is promising but not yet at final submission scale. The
most important limitations should be stated plainly in the paper.

First, the current natural-failure evidence is real but still modest. The repo
has verified strict non-oracle recoveries on saved benchmark failures,
including a clean thirty-two-case mixed-domain bundle, but not yet at the scale
needed for a strong benchmark-wide claim.

Second, continuation remains a major bottleneck. Some failures are easy to
localize yet hard to recover because the patched action changes the future state
distribution. This is exactly why the strict-versus-oracle gap is informative,
but it also limits current natural recovery.

Third, several intervention families exist in the interface before they are
fully mature as high-quality proposers across domains. The paper should be
careful to distinguish interface support from fully competitive evaluated
methods.

Fourth, autopsy usefulness has not yet been validated with human studies or a
large expert annotation pass. At the current stage, autopsies should be treated
as structured artifacts and qualitative evidence, not yet as fully validated
human-facing explanations.

Finally, the paper is about debugging methodology, not deployment. The current
system operates on offline benchmark trajectories and replayable environments.
It is not a claim about safe online automated intervention in real customer
service systems.

## Related Work

### Agent Benchmarks And Interactive Environments

Recent work on agent evaluation has established the importance of realistic,
interactive benchmarks with tool use, persistent state, and goal-conditioned
tasks. `tau`-style customer-service environments, WebArena and WorkArena style
web-interaction benchmarks, AgentDojo, and software-oriented settings such as
SWE-bench all share a core insight: final task success depends on multi-step
interaction with an external environment, not just single-turn text quality.

Our work is complementary to this benchmark line. These benchmarks tell us
whether an agent succeeded or failed, and they often provide rich traces, but
they do not by themselves offer a principled way to intervene on failed runs.
We build on benchmark-style environments rather than replacing them. The key
difference is methodological: instead of treating a failed trajectory as a dead
artifact, we treat it as a replayable object that can be restored, patched, and
re-evaluated under the original benchmark reward.

This distinction matters because our main output is not only a score. It is a
structured autopsy: a root-cause step, a minimal successful patch, the replayed
outcome, and the explicit search cost required to find that patch.

### Reflection, Retry, And Self-Repair Methods

A second relevant line of work studies how language models can critique and
improve their own outputs through reflection, refinement, or search. This
includes approaches in the spirit of Reflexion, Self-Refine, tree-search style
deliberation, self-debugging, and regenerate-until-success pipelines. These
methods have shown that models can often repair intermediate reasoning or code
when given another chance to think.

Our setting is related but importantly different. Reflection-style methods
typically operate in prompt space: they ask the model to reconsider, critique,
or regenerate a solution. In contrast, we operate in execution space. We do not
only ask the model to "try again"; we restore the exact environment state at a
chosen step, apply a targeted structured intervention, and measure whether the
real downstream environment reward changes. This lets us distinguish several
failure modes that prompt-only retry tends to conflate:

- the localized step was wrong, but the remainder of the trajectory was still
  usable once patched;
- the localized step was wrong, and a fresh continuation was required;
- the observed step itself should be deleted because it caused harmful state
  mutation;
- no allowed local intervention can recover the run under the current budget.

Because of that, our method yields a more causal notion of repair than
reflection-only pipelines, while also exposing a strict-vs-oracle continuation
gap that can be studied directly.

### Fault Localization, Program Repair, And Minimal Counterfactuals

Our problem is also closely related to classic ideas from fault localization,
delta debugging, automated program repair, and minimal counterfactual
explanations. In those settings, one seeks a small change that either explains
or repairs undesirable behavior. The smallest successful edit is often more
informative than a large unconstrained rewrite.

We adopt the same spirit in the agent setting, but the object being edited is
not source code alone. It is a trajectory embedded in a live task environment
with dialogue history, retrieved context, tool calls, and stateful side
effects. That makes the setting harder than ordinary static repair: changing an
action can alter later observations, invalidate the original suffix, or require
fresh continuation planning from the replayed state.

Our framework therefore combines ideas from minimal repair and counterfactual
analysis with benchmark-native execution replay. The result is a form of causal
debugging tailored to stateful LLM agents rather than ordinary programs.

### Positioning Claim

The cleanest way to position this paper is:

- benchmarks provide the environment and reward;
- reflection and self-repair provide prompt-space baselines;
- program repair and counterfactual analysis provide the conceptual precedent
  for minimal interventions;
- our contribution is replayable execution intervention for agent trajectories,
  with recovery, localization, and autopsy generation all measured in the
  original benchmark environment.

## Current Evidence To Reference In The Paper

These points are grounded in the current repository state and are safe to cite
in an early draft:

- Controlled synthetic corruption recovery is implemented and reproducible.
- Synthetic comparisons already expose a separation between recovery and
  localization quality.
- Imported natural failures come from saved `tau2` benchmark result files whose
  acting agents include `claude-3-7-sonnet-20250219`,
  `gpt-4.1-2025-04-14`, `gpt-4.1-mini-2025-04-14`, and
  `o4-mini-2025-04-16`, with `gpt-4.1-2025-04-14` as the user simulator.
- Strict natural-failure evidence now includes:
  one retail recovery via `continuation_replace` from replayed state, plus a
  clean thirty-two-case mixed-domain bundle with `13 / 32` strict recoveries
  and per-domain recovery `airline = 10 / 16`, `retail = 3 / 16`.
- A paper-facing case-study panel now exists for `6` recovered natural cases.
- A dependency snapshot artifact now exists in addition to the lighter
  environment manifest.
- The patch-search smoke runs that produced these artifacts used a
  deterministic proposer backend, not an external repair LLM.

## Conclusion And Future Work

This project supports a simple but powerful thesis: failed agent trajectories
in replayable environments can be debugged through causal execution
intervention rather than only through prompt-level retry. By restoring a saved
state, applying a bounded structured patch, and re-evaluating the resulting
rollout in the original benchmark environment, we can convert opaque failures
into concrete autopsies with explicit recovery cost.

The current repository already validates the main shape of that thesis.
Controlled synthetic failures can be localized and repaired end to end.
Natural saved benchmark failures are harder, but they already show the most
important methodological pattern: some failures are irrecoverable under naive
single-step replay, some become recoverable under oracle continuation, and some
can be recovered strictly once the intervention space includes richer repair
operations such as staged continuation or action deletion.

The most important next step is scale. A final paper should move from smoke
artifacts to a frozen corpus of hundreds of natural failures across at least
`retail` and `airline`, while preserving the current split between synthetic
localization analysis and natural ecological evaluation. The strongest version
of the paper will also strengthen strict continuation, add model-backed proposal
ablations, and produce camera-ready figures directly from saved JSON artifacts.

If that scale-up succeeds, the final contribution is not merely a better repair
rate. It is a new evaluation and debugging methodology for agent systems:
checkpointed execution intervention, bounded minimal patch search, and
reproducible autopsy generation under benchmark-native reward.

## Reproducibility And Release Plan

The paper should emphasize reproducibility as part of the contribution, not as
an afterthought. The current repo already contains several components that make
this realistic:

- benchmark-native replay with saved pre-step and post-step snapshots;
- JSON artifacts for corpora, search outputs, autopsies, figure data, and
  paper tables;
- saved paper-facing case-study panels derived directly from autopsy JSON;
- a dependency snapshot artifact containing both a selected package list and a
  full local requirements lock;
- CLI entrypoints for corpus construction, patch search, autopsy generation,
  strategy comparison, budget sweeps, model sweeps, case-study export,
  dependency snapshotting, and paper-bundle creation;
- a one-command smoke bundle path that exercises the end-to-end pipeline.

The final release package should include:

1. a pinned environment specification and dependency lock;
2. frozen corpus manifests for synthetic and natural experiments;
3. exact commands for each main table and figure;
4. a release bundle of raw JSON results and exported CSV tables;
5. a short artifact README that maps paper claims to the corresponding files in
   the repository.

The target standard should be that an external reader can reproduce the main
paper tables from saved artifacts without repairing notebooks or inferring
hidden preprocessing steps.

## Citation Checklist

The final paper draft should verify and add exact citations for at least:

- `tau2` / tau3 benchmark papers or repos
- WebArena
- WorkArena
- AgentDojo
- SWE-bench
- Reflexion
- Self-Refine
- Tree-of-Thought or related search-over-thought methods
- representative automated program repair or delta-debugging work
- representative minimal counterfactual explanation work

## Writing Notes

- Keep the main claim centered on debugging methodology, not on beating a
  benchmark leaderboard.
- Treat oracle continuation strictly as an upper-bound analysis tool.
- Keep synthetic and natural evaluation separate in the paper narrative:
  synthetic for localization and minimality, natural for ecological validity.
- Do not overclaim broad natural recovery until larger multi-domain runs are in
  place.
