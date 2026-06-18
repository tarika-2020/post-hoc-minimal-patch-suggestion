from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import platform
import random
import re
import statistics
import sys
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Iterator
from urllib import error as urllib_error
from urllib import request as urllib_request

from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage, UserMessage
from tau2.data_model.simulation import SimulationRun, TerminationReason
from tau2.data_model.tasks import Action as TauAction
from tau2.data_model.tasks import Task
from tau2.domains.airline.data_model import FlightDB
from tau2.domains.airline.environment import get_environment as get_airline_environment
from tau2.domains.airline.environment import get_tasks as get_airline_tasks
from tau2.domains.retail.data_model import RetailDB
from tau2.domains.retail.environment import get_environment as get_retail_environment
from tau2.domains.retail.environment import get_tasks as get_retail_tasks
from tau2.evaluator.evaluator import EvaluationType, evaluate_simulation
from tau2.utils.utils import get_now


JsonDict = dict[str, Any]


EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
ORDER_ID_RE = re.compile(r"#?W\d+")
USER_ID_RE = re.compile(r"\b[a-z]+_[a-z]+_\d+\b")
PRODUCT_ID_RE = re.compile(r"\b\d{10}\b")
PAYMENT_METHOD_RE = re.compile(r"\b(?:paypal|credit_card|gift_card|bank_account)_[0-9]+\b")
ITEM_ID_FIELD_RE = re.compile(r"item_id='(\d+)'")
PRODUCT_ID_FIELD_RE = re.compile(r"product_id='(\d+)'")

SELECTED_DISTRIBUTION_NAMES = ["tau2", "litellm", "openai", "pydantic", "httpx"]


DOMAIN_LOADERS = {
    "retail": {
        "get_tasks": get_retail_tasks,
        "get_environment": get_retail_environment,
        "db_model": RetailDB,
        "supports_user_db": False,
    },
    "airline": {
        "get_tasks": get_airline_tasks,
        "get_environment": get_airline_environment,
        "db_model": FlightDB,
        "supports_user_db": False,
    },
}


@dataclass
class EnvSnapshot:
    domain: str
    task_id: str
    agent_db: JsonDict
    user_db: JsonDict | None
    message_history: list[JsonDict]
    step_index: int


@dataclass
class TrajectoryStep:
    timestep: int
    action: JsonDict
    tool_result: JsonDict
    pre_snapshot: EnvSnapshot
    post_snapshot: EnvSnapshot


@dataclass
class TaskOutcome:
    success: bool
    reward: float
    reason: str
    reward_breakdown: JsonDict = field(default_factory=dict)


@dataclass
class TrajectoryRecord:
    domain: str
    task_id: str
    steps: list[TrajectoryStep]
    outcome: TaskOutcome
    final_snapshot: EnvSnapshot
    simulation: JsonDict
    fault_step: int | None = None
    fault_description: str | None = None


@dataclass
class FailureCase:
    failure_id: str
    domain: str
    task_split: str
    task_id: str
    trajectory: TrajectoryRecord
    failure_reason: str
    source: str = "synthetic_corruption"
    source_metadata: JsonDict = field(default_factory=dict)


class PatchFamily(str, Enum):
    TOOL_ARGS = "tool_args"
    TOOL_CALL_REPLACE = "tool_call_replace"
    TOOL_INSERTION = "tool_insertion"
    TOOL_DELETION = "tool_deletion"
    CONTEXT_EDIT = "context_edit"
    SCRATCHPAD_EDIT = "scratchpad_edit"
    CONTINUATION_REPLACE = "continuation_replace"
    TOOL_CALL_WITH_ORACLE_SUFFIX = "tool_call_with_oracle_suffix"


class ProposerBackend(str, Enum):
    DETERMINISTIC = "deterministic"
    OPENROUTER = "openrouter"


class MethodVariant(str, Enum):
    PATCH_SEARCH_STRUCTURED = "patch_search_structured"
    RETRY_FROM_SCRATCH = "retry_from_scratch"
    RETRY_FROM_LOCALIZED_SNAPSHOT = "retry_from_localized_snapshot"
    RAW_CONTINUATION_FROM_SNAPSHOT = "raw_continuation_from_snapshot"


@dataclass
class BudgetConfig:
    max_evaluations_per_failure: int | None = None
    max_candidates_per_step: int | None = None
    continuation_horizon: int = 3
    beam_width: int = 2
    localization_cost_per_step: int = 8
    replay_cost_per_candidate: int = 1


@dataclass
class ExperimentConfig:
    name: str
    input_dir: str
    output_dir: str
    method_variant: str = MethodVariant.PATCH_SEARCH_STRUCTURED.value
    strategy: str = "heuristic"
    include_oracle_suffix: bool = False
    proposer_backend: str = ProposerBackend.DETERMINISTIC.value
    model_slug: str | None = None
    compact_results: bool = False
    budget: BudgetConfig = field(default_factory=BudgetConfig)


@dataclass
class ProposerMetadata:
    backend: str
    model_slug: str | None = None
    prompt: str | None = None
    raw_response: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    status: str = "not_used"
    error: str | None = None


@dataclass
class LocalizationResult:
    strategy: str
    ranked_steps: list[int]
    suspicious_scores: list[JsonDict]
    token_cost: int
    metadata: JsonDict = field(default_factory=dict)


@dataclass
class ContinuationCandidate:
    target_step: int
    actions: list[JsonDict]
    token_cost: int
    description: str
    metadata: JsonDict = field(default_factory=dict)


@dataclass
class FailureCorpusEntry:
    failure_id: str
    domain: str
    task_split: str
    task_id: str
    split: str
    source: str
    source_path: str
    original_reward: float
    replay_reward: float
    tool_call_count: int
    tool_error_count: int
    step_count: int
    failure_reason: str


@dataclass
class FailureCorpusManifest:
    name: str
    domains: list[str]
    entry_count: int
    split_counts: JsonDict
    entries: list[FailureCorpusEntry]


@dataclass
class PatchCandidate:
    target_step: int
    patch_family: str
    payload: JsonDict
    size_score: int
    token_cost: int
    description: str


@dataclass
class PatchEvaluation:
    candidate: PatchCandidate
    recovered: bool
    outcome: TaskOutcome
    patched_trajectory: TrajectoryRecord
    replay_cost: int = 0
    proposer_metadata: ProposerMetadata | None = None
    dynamic_token_cost: int = 0


@dataclass
class PatchSearchResult:
    failure_id: str
    method_variant: str
    recovered: bool
    winning_patch: PatchCandidate | None
    winning_outcome: TaskOutcome | None
    evaluated_candidates: list[PatchEvaluation]
    total_token_cost: int
    localization: LocalizationResult
    budget: BudgetConfig
    proposer_backend: str
    evaluated_family_counts: JsonDict
    autopsy_report: JsonDict


def serialize_dataclass(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=serialize_dataclass)


def serialize_patch_search_result(
    result: PatchSearchResult,
    compact: bool = False,
) -> JsonDict:
    payload = asdict(result)
    if not compact:
        return payload
    for evaluation in payload.get("evaluated_candidates", []):
        evaluation.pop("patched_trajectory", None)
    payload["serialization_mode"] = "compact"
    return payload


def serialize_patch_search_results(
    results: list[PatchSearchResult],
    compact: bool = False,
) -> list[JsonDict]:
    return [serialize_patch_search_result(result, compact=compact) for result in results]


def serialize_failure_case(failure: FailureCase) -> JsonDict:
    return asdict(failure)


def serialize_failure_cases(failures: list[FailureCase]) -> list[JsonDict]:
    return [serialize_failure_case(failure) for failure in failures]


def save_csv(path: Path, rows: list[JsonDict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, default=serialize_dataclass) + "\n")


def append_jsonl(path: Path, row: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, default=serialize_dataclass) + "\n")


def iter_jsonl(path: Path) -> Iterator[Any]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            yield json.loads(stripped)


def iter_json_array(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as handle:
        buffer = ""
        started = False
        finished = False
        while not finished:
            chunk = handle.read(chunk_size)
            if chunk:
                buffer += chunk
            elif not buffer.strip():
                break
            parse_again = True
            while parse_again:
                parse_again = False
                buffer = buffer.lstrip()
                if not started:
                    if not buffer:
                        break
                    if buffer[0] != "[":
                        raise ValueError(f"{path} does not contain a top-level JSON array.")
                    started = True
                    buffer = buffer[1:]
                    parse_again = True
                    continue
                if not buffer:
                    break
                if buffer[0] == ",":
                    buffer = buffer[1:]
                    parse_again = True
                    continue
                if buffer[0] == "]":
                    finished = True
                    buffer = buffer[1:]
                    break
                try:
                    item, end_index = decoder.raw_decode(buffer)
                except json.JSONDecodeError:
                    if chunk:
                        break
                    raise
                yield item
                buffer = buffer[end_index:]
                parse_again = True
        if not started:
            return
        if buffer.strip():
            tail = buffer.strip()
            if tail not in {"", "]"}:
                raise ValueError(f"{path} has trailing non-array JSON content.")


def count_tokens(value: Any) -> int:
    if isinstance(value, str):
        return max(1, len(value.split()))
    return max(1, len(json.dumps(value, sort_keys=True).split()))


def diff_size(before: Any, after: Any) -> int:
    if before == after:
        return 0
    if isinstance(before, dict) and isinstance(after, dict):
        keys = set(before) | set(after)
        return sum(diff_size(before.get(key), after.get(key)) for key in keys)
    if isinstance(before, list) and isinstance(after, list):
        total = 0
        limit = max(len(before), len(after))
        for index in range(limit):
            left = before[index] if index < len(before) else None
            right = after[index] if index < len(after) else None
            total += diff_size(left, right)
        return total
    return max(count_tokens(before), count_tokens(after))


def normalize_task_split(task_split: str) -> str:
    normalized = (task_split or "base").strip().lower()
    aliases = {
        "default": "base",
    }
    return aliases.get(normalized, normalized)


def normalize_action_requestor(value: Any, default: str = "assistant") -> str:
    normalized = str(value or default).strip().lower()
    aliases = {
        "agent": "assistant",
        "model": "assistant",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"assistant", "user"}:
        return default
    return normalized


class Tau3DomainAdapter:
    def __init__(self, domain: str, task_split: str = "base") -> None:
        if domain not in DOMAIN_LOADERS:
            raise ValueError(f"Unsupported domain: {domain}")
        self.domain = domain
        self.task_split = normalize_task_split(task_split)
        self.loader = DOMAIN_LOADERS[domain]
        self.tasks = {
            task.id: task for task in self.loader["get_tasks"](self.task_split)
        }
        self._tool_introspection_env: Any | None = None
        self._tool_catalog_cache: list[JsonDict] | None = None
        self._tool_name_cache: set[str] | None = None

    def get_task(self, task_id: str) -> Task:
        return self.tasks[task_id]

    def create_environment(
        self, agent_db: JsonDict | None = None, user_db: JsonDict | None = None
    ):
        db = None
        if agent_db is not None:
            db = self.loader["db_model"].model_validate(agent_db)
        kwargs: JsonDict = {}
        if db is not None:
            kwargs["db"] = db
        if self.loader["supports_user_db"] and user_db is not None:
            kwargs["user_db"] = user_db
        return self.loader["get_environment"](**kwargs)

    def is_mutating_tool(self, tool_name: str) -> bool:
        if self._tool_introspection_env is None:
            self._tool_introspection_env = self.create_environment()
        checker = getattr(self._tool_introspection_env, "_is_mutating_tool", None)
        if callable(checker):
            return bool(checker(tool_name))
        lowered = tool_name.lower()
        fallback_prefixes = (
            "book_",
            "cancel_",
            "modify_",
            "transfer_",
            "update_",
            "return_",
            "exchange_",
            "replace_",
            "refund_",
        )
        return lowered.startswith(fallback_prefixes)

    def get_tool_catalog(self) -> list[JsonDict]:
        if self._tool_catalog_cache is not None:
            return copy.deepcopy(self._tool_catalog_cache)
        env = self.create_environment()
        catalog: list[JsonDict] = []
        seen_names: set[str] = set()
        for attr in ("tools", "user_tools"):
            tool_container = getattr(env, attr, None)
            if tool_container is None or not hasattr(tool_container, "get_tools"):
                continue
            try:
                tool_map = tool_container.get_tools()
            except Exception:
                continue
            if not isinstance(tool_map, dict):
                continue
            for name, tool in tool_map.items():
                if not isinstance(name, str) or name in seen_names:
                    continue
                seen_names.add(name)
                short_desc = str(getattr(tool, "short_desc", "") or "")
                long_desc = str(getattr(tool, "long_desc", "") or "")
                parameter_names: list[str] = []
                params_model = getattr(tool, "params", None)
                if params_model is not None and hasattr(params_model, "model_json_schema"):
                    try:
                        schema = params_model.model_json_schema()
                        properties = schema.get("properties") or {}
                        if isinstance(properties, dict):
                            parameter_names = [str(key) for key in properties.keys()]
                    except Exception:
                        parameter_names = []
                catalog.append(
                    {
                        "name": name,
                        "description": short_desc or long_desc,
                        "parameters": parameter_names,
                    }
                )
        self._tool_catalog_cache = sorted(catalog, key=lambda item: item["name"])
        self._tool_name_cache = {item["name"] for item in self._tool_catalog_cache}
        return copy.deepcopy(self._tool_catalog_cache)

    def has_tool(self, tool_name: str) -> bool:
        normalized = str(tool_name or "").strip()
        if not normalized:
            return False
        if self._tool_name_cache is None:
            self.get_tool_catalog()
        return normalized in (self._tool_name_cache or set())

    def initial_messages(self, task: Task) -> list[Any]:
        if task.initial_state and task.initial_state.message_history:
            return copy.deepcopy(task.initial_state.message_history)
        return [UserMessage.text(str(task.user_scenario.instructions))]

    def apply_initial_state(self, env: Any, task: Task) -> list[Any]:
        messages = self.initial_messages(task)
        if task.initial_state is not None:
            env.set_state(
                initialization_data=task.initial_state.initialization_data,
                initialization_actions=task.initial_state.initialization_actions,
                message_history=messages,
            )
        return messages

    def snapshot(
        self,
        task_id: str,
        env: Any,
        messages: list[Any],
        step_index: int,
    ) -> EnvSnapshot:
        agent_db = copy.deepcopy(env.tools.db.model_dump()) if env.tools else {}
        user_db = None
        if getattr(env, "user_tools", None) is not None and env.user_tools.db is not None:
            user_db = copy.deepcopy(env.user_tools.db.model_dump())
        return EnvSnapshot(
            domain=self.domain,
            task_id=task_id,
            agent_db=agent_db,
            user_db=user_db,
            message_history=[message.model_dump(mode="json") for message in messages],
            step_index=step_index,
        )

    @staticmethod
    def _parse_message(payload: JsonDict):
        role = payload["role"]
        if role == "assistant":
            return AssistantMessage.model_validate(payload)
        if role == "user":
            return UserMessage.model_validate(payload)
        if role == "tool":
            return ToolMessage.model_validate(payload)
        raise ValueError(f"Unsupported message role: {role}")

    def restore(self, snapshot: EnvSnapshot) -> tuple[Any, list[Any]]:
        env = self.create_environment(
            agent_db=copy.deepcopy(snapshot.agent_db),
            user_db=copy.deepcopy(snapshot.user_db),
        )
        messages = [
            self._parse_message(message_payload)
            for message_payload in copy.deepcopy(snapshot.message_history)
        ]
        return env, messages


class RealBenchmarkRunner:
    def __init__(self, adapter: Tau3DomainAdapter) -> None:
        self.adapter = adapter

    def build_reference_trajectory(self, task_id: str) -> TrajectoryRecord:
        task = self.adapter.get_task(task_id)
        actions = self._require_task_actions(task)
        return self._run_actions(task, list(actions), fault_step=None, fault_description=None)

    def build_failed_trajectory(self, task_id: str) -> TrajectoryRecord:
        task = self.adapter.get_task(task_id)
        actions = copy.deepcopy(self._require_task_actions(task))
        fault_step = self.choose_fault_step(task, actions)
        mutated_action, description = mutate_action(actions[fault_step])
        actions[fault_step] = mutated_action
        return self._run_actions(task, actions, fault_step=fault_step, fault_description=description)

    def build_trajectory_from_simulation(self, simulation_payload: JsonDict) -> TrajectoryRecord:
        simulation = SimulationRun.model_validate(simulation_payload)
        task = self.adapter.get_task(str(simulation.task_id))
        env = self.adapter.create_environment()
        if task.initial_state is not None:
            env.set_state(
                initialization_data=task.initial_state.initialization_data,
                initialization_actions=task.initial_state.initialization_actions,
                message_history=task.initial_state.message_history or [],
            )
        replayed_messages: list[Any] = []
        steps: list[TrajectoryStep] = []
        messages = simulation.get_messages()
        index = 0
        while index < len(messages):
            message = messages[index]
            if isinstance(message, ToolMessage):
                index += 1
                continue
            replayed_messages.append(message)
            if isinstance(message, (AssistantMessage, UserMessage)) and message.is_tool_call():
                for tool_call in message.tool_calls or []:
                    step_index = len(steps)
                    pre_snapshot = self.adapter.snapshot(task.id, env, replayed_messages, step_index)
                    tool_result = env.get_response(tool_call)
                    replayed_messages.append(tool_result)
                    post_snapshot = self.adapter.snapshot(task.id, env, replayed_messages, step_index + 1)
                    action = TauAction(
                        action_id=f"{task.id}_natural_{step_index}",
                        requestor=tool_call.requestor,
                        name=tool_call.name,
                        arguments=copy.deepcopy(tool_call.arguments),
                    )
                    steps.append(
                        TrajectoryStep(
                            timestep=step_index,
                            action=action.model_dump(mode="json"),
                            tool_result=tool_result.model_dump(mode="json"),
                            pre_snapshot=pre_snapshot,
                            post_snapshot=post_snapshot,
                        )
                    )
            index += 1
        reward = evaluate_simulation(
            simulation=SimulationRun(
                id=simulation.id,
                task_id=task.id,
                start_time=simulation.start_time,
                end_time=simulation.end_time,
                duration=simulation.duration,
                termination_reason=simulation.termination_reason,
                messages=replayed_messages,
            ),
            task=task,
            evaluation_type=EvaluationType.ENV,
            solo_mode=False,
            domain=self.adapter.domain,
        )
        saved_reward = simulation.reward_info.reward if simulation.reward_info else reward.reward
        return TrajectoryRecord(
            domain=self.adapter.domain,
            task_id=task.id,
            steps=steps,
            outcome=TaskOutcome(
                success=saved_reward >= 0.999999,
                reward=saved_reward,
                reason=(
                    "Imported natural trajectory succeeded."
                    if saved_reward >= 0.999999
                    else "Imported natural trajectory failed."
                ),
                reward_breakdown=(
                    {
                        str(key): value
                        for key, value in (simulation.reward_info.reward_breakdown or {}).items()
                    }
                    if simulation.reward_info
                    else {str(key): value for key, value in (reward.reward_breakdown or {}).items()}
                ),
            ),
            final_snapshot=self.adapter.snapshot(task.id, env, replayed_messages, len(steps)),
            simulation=simulation.model_dump(mode="json"),
            fault_step=None,
            fault_description="Natural benchmark failure imported from saved tau2 results.",
        )

    def build_action_trajectory(
        self,
        task_id: str,
        actions: list[TauAction],
        fault_description: str | None = None,
    ) -> TrajectoryRecord:
        task = self.adapter.get_task(task_id)
        return self._run_actions(
            task=task,
            actions=actions,
            fault_step=None,
            fault_description=fault_description,
        )

    @staticmethod
    def _require_task_actions(task: Task) -> list[TauAction]:
        if task.evaluation_criteria is None or not task.evaluation_criteria.actions:
            raise ValueError(f"Task {task.id} does not define evaluation actions.")
        return task.evaluation_criteria.actions

    def _run_actions(
        self,
        task: Task,
        actions: list[TauAction],
        fault_step: int | None,
        fault_description: str | None,
    ) -> TrajectoryRecord:
        env = self.adapter.create_environment()
        messages = self.adapter.apply_initial_state(env, task)
        return self._continue_from_state(
            task=task,
            env=env,
            messages=messages,
            actions=actions,
            start_step=0,
            fault_step=fault_step,
            fault_description=fault_description,
        )

    def continue_from_snapshot(
        self,
        task: Task,
        snapshot: EnvSnapshot,
        actions: list[TauAction],
        start_step: int,
        fault_step: int | None = None,
        fault_description: str | None = None,
        finalize: bool = True,
    ) -> TrajectoryRecord:
        env, messages = self.adapter.restore(snapshot)
        return self._continue_from_state(
            task=task,
            env=env,
            messages=messages,
            actions=actions,
            start_step=start_step,
            fault_step=fault_step,
            fault_description=fault_description,
            finalize=finalize,
        )

    def _continue_from_state(
        self,
        task: Task,
        env: Any,
        messages: list[Any],
        actions: list[TauAction],
        start_step: int,
        fault_step: int | None,
        fault_description: str | None,
        finalize: bool = True,
    ) -> TrajectoryRecord:
        steps: list[TrajectoryStep] = []
        for step_index, action in enumerate(actions, start=start_step):
            pre_snapshot = self.adapter.snapshot(task.id, env, messages, step_index)
            tool_call = ToolCall(
                id=f"call_{task.id}_{step_index}",
                name=action.name,
                arguments=copy.deepcopy(action.arguments),
                requestor=action.requestor,
            )
            requestor_msg = (
                AssistantMessage.text("", tool_calls=[tool_call])
                if action.requestor == "assistant"
                else UserMessage.text("", tool_calls=[tool_call])
            )
            messages.append(requestor_msg)
            tool_result = env.get_response(tool_call)
            messages.append(tool_result)
            post_snapshot = self.adapter.snapshot(task.id, env, messages, step_index + 1)
            steps.append(
                TrajectoryStep(
                    timestep=step_index,
                    action=action.model_dump(mode="json"),
                    tool_result=tool_result.model_dump(mode="json"),
                    pre_snapshot=pre_snapshot,
                    post_snapshot=post_snapshot,
                )
            )
        if finalize:
            messages.append(AssistantMessage.text("done"))
        simulation = SimulationRun(
            id=str(uuid.uuid4()),
            task_id=task.id,
            start_time=get_now(),
            end_time=get_now(),
            duration=0.0,
            termination_reason=TerminationReason.AGENT_STOP,
            messages=messages,
        )
        if finalize:
            reward = evaluate_simulation(
                simulation=simulation,
                task=task,
                evaluation_type=EvaluationType.ENV,
                solo_mode=False,
                domain=self.adapter.domain,
            )
            outcome = TaskOutcome(
                success=reward.reward >= 0.999999,
                reward=reward.reward,
                reason=(
                    "Environment reward succeeded."
                    if reward.reward >= 0.999999
                    else "Environment reward failed."
                ),
                reward_breakdown={
                    str(key): value for key, value in (reward.reward_breakdown or {}).items()
                },
            )
        else:
            outcome = TaskOutcome(
                success=False,
                reward=0.0,
                reason="Partial rollout without evaluation.",
                reward_breakdown={},
            )
        return TrajectoryRecord(
            domain=self.adapter.domain,
            task_id=task.id,
            steps=steps,
            outcome=outcome,
            final_snapshot=self.adapter.snapshot(task.id, env, messages, start_step + len(actions)),
            simulation=simulation.model_dump(mode="json"),
            fault_step=fault_step,
            fault_description=fault_description,
        )

    def choose_fault_step(self, task: Task, actions: list[TauAction]) -> int:
        env = self.adapter.create_environment()
        self.adapter.apply_initial_state(env, task)
        for index in range(len(actions) - 1, -1, -1):
            action = actions[index]
            if action.requestor == "assistant" and env._is_mutating_tool(action.name):
                return index
        for index in range(len(actions) - 1, -1, -1):
            if actions[index].requestor == "assistant":
                return index
        raise ValueError(f"No assistant actions available for task {task.id}")


def mutate_scalar(value: Any) -> Any:
    if isinstance(value, str):
        return f"{value}__bad"
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    return value


def mutate_action(action: TauAction) -> tuple[TauAction, str]:
    mutated = action.model_copy(deep=True)
    for key, value in mutated.arguments.items():
        if isinstance(value, str):
            mutated.arguments[key] = mutate_scalar(value)
            return mutated, f"Corrupted `{key}` in `{action.name}`."
        if isinstance(value, list) and value:
            mutated.arguments[key][0] = mutate_scalar(value[0])
            return mutated, f"Corrupted first element of `{key}` in `{action.name}`."
    first_key = next(iter(mutated.arguments))
    mutated.arguments[first_key] = mutate_scalar(mutated.arguments[first_key])
    return mutated, f"Corrupted `{first_key}` in `{action.name}`."


def extract_actions_from_messages(task_id: str, messages: list[JsonDict]) -> list[TauAction]:
    actions: list[TauAction] = []
    for message in messages:
        if message.get("role") not in {"assistant", "user"}:
            continue
        for tool_call in message.get("tool_calls") or []:
            actions.append(
                TauAction(
                    action_id=f"{task_id}_natural_{len(actions)}",
                    requestor=normalize_action_requestor(tool_call.get("requestor") or message["role"]),
                    name=tool_call["name"],
                    arguments=copy.deepcopy(tool_call.get("arguments") or {}),
                )
            )
    return actions


def action_from_payload(payload: JsonDict) -> TauAction:
    return TauAction(
        action_id=str(payload.get("action_id") or f"replayed_{payload.get('name', 'action')}"),
        requestor=normalize_action_requestor(payload.get("requestor")),
        name=str(payload["name"]),
        arguments=copy.deepcopy(payload.get("arguments") or {}),
    )


def summarize_action_errors(trajectory: TrajectoryRecord) -> JsonDict:
    error_steps = [
        step
        for step in trajectory.steps
        if step.tool_result.get("error")
    ]
    error_tools: dict[str, int] = {}
    for step in error_steps:
        name = step.action.get("name", "<unknown>")
        error_tools[name] = error_tools.get(name, 0) + 1
    return {
        "tool_call_count": len(trajectory.steps),
        "tool_error_count": len(error_steps),
        "tool_error_rate": len(error_steps) / len(trajectory.steps) if trajectory.steps else 0.0,
        "tool_errors_by_name": dict(sorted(error_tools.items())),
    }


def unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            unique_values.append(value)
    return unique_values


def task_hint_text(task: Task) -> str:
    return str(task.user_scenario.instructions)


def extract_task_hints(task: Task) -> JsonDict:
    text = task_hint_text(task)
    return {
        "emails": unique_preserving_order(EMAIL_RE.findall(text)),
        "order_ids": unique_preserving_order(
            order_id if order_id.startswith("#") else f"#{order_id}"
            for order_id in ORDER_ID_RE.findall(text)
        ),
        "user_ids": unique_preserving_order(USER_ID_RE.findall(text)),
        "product_ids": unique_preserving_order(PRODUCT_ID_RE.findall(text)),
    }


def assign_split(index: int) -> str:
    if index % 10 == 0:
        return "test"
    if index % 5 == 0:
        return "dev"
    return "train"


def parse_json_object(text: str) -> JsonDict | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        parts = stripped.split("```")
        if len(parts) >= 3:
            stripped = parts[1]
            if "\n" in stripped:
                stripped = stripped.split("\n", 1)[1]
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        return json.dumps(content, sort_keys=True)
    if content is None:
        return ""
    return str(content)


def extract_runtime_entities(content: Any) -> JsonDict:
    text = stringify_content(content)
    parsed_payload: Any = None
    if isinstance(content, dict):
        parsed_payload = content
    elif isinstance(content, str):
        parsed_payload = parse_json_object(content)
    values_to_scan: list[str] = [text]

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, str):
            values_to_scan.append(value)

    if parsed_payload is not None:
        visit(parsed_payload)

    combined_text = "\n".join(values_to_scan)
    item_ids = ITEM_ID_FIELD_RE.findall(combined_text)
    item_ids.extend(re.findall(r"\b\d{10}\b", combined_text))
    return {
        "emails": unique_preserving_order(EMAIL_RE.findall(combined_text)),
        "order_ids": unique_preserving_order(
            order_id if order_id.startswith("#") else f"#{order_id}"
            for order_id in ORDER_ID_RE.findall(combined_text)
        ),
        "user_ids": unique_preserving_order(USER_ID_RE.findall(combined_text)),
        "product_ids": unique_preserving_order(
            PRODUCT_ID_FIELD_RE.findall(combined_text) + PRODUCT_ID_RE.findall(combined_text)
        ),
        "payment_method_ids": unique_preserving_order(PAYMENT_METHOD_RE.findall(combined_text)),
        "item_ids": unique_preserving_order(item_ids),
    }


class BaseProposer(ABC):
    def __init__(self, backend: str, model_slug: str | None = None) -> None:
        self.backend = backend
        self.model_slug = model_slug

    @abstractmethod
    def propose_continuations(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        patched_action: JsonDict,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        raise NotImplementedError

    def propose_runtime_continuations(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        partial_trajectory: TrajectoryRecord,
        patched_action: JsonDict,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        return self.propose_continuations(task, failure, step_index, patched_action, budget)

    def propose_actions_from_task(
        self,
        task: Task,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        metadata = ProposerMetadata(
            backend=self.backend,
            model_slug=self.model_slug,
            status="unsupported",
            error="Task-level retry proposal is not implemented for this proposer.",
        )
        return [], metadata

    def propose_actions_from_snapshot(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        snapshot: EnvSnapshot,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        metadata = ProposerMetadata(
            backend=self.backend,
            model_slug=self.model_slug,
            status="unsupported",
            error="Snapshot-level retry proposal is not implemented for this proposer.",
        )
        return [], metadata


class DeterministicProposer(BaseProposer):
    def __init__(self) -> None:
        super().__init__(backend=ProposerBackend.DETERMINISTIC.value, model_slug=None)

    @staticmethod
    def _make_action(task_id: str, requestor: str, index: int, name: str, arguments: JsonDict) -> JsonDict:
        return {
            "action_id": f"{task_id}_continuation_{index}",
            "requestor": normalize_action_requestor(requestor),
            "name": name,
            "arguments": copy.deepcopy(arguments),
            "info": None,
            "compare_args": None,
        }

    @staticmethod
    def _first_existing(values: list[str], collection: JsonDict) -> str | None:
        for value in values:
            if value in collection:
                return value
        return None

    @staticmethod
    def _choose_payment_method_id(user_record: JsonDict, order: JsonDict) -> str | None:
        for payment in order.get("payment_history") or []:
            payment_method_id = payment.get("payment_method_id")
            if isinstance(payment_method_id, str):
                return payment_method_id
        payment_methods = user_record.get("payment_methods") or {}
        if payment_methods:
            return next(iter(payment_methods))
        return None

    def _select_retail_return_action(
        self,
        task: Task,
        snapshot: EnvSnapshot,
        user_id: str,
    ) -> JsonDict | None:
        task_text = task_hint_text(task).lower()
        users = snapshot.agent_db.get("users") or {}
        orders = snapshot.agent_db.get("orders") or {}
        user_record = users.get(user_id)
        if not user_record:
            return None
        best_choice: tuple[int, float, JsonDict, JsonDict] | None = None
        for order_id in user_record.get("orders") or []:
            order = orders.get(order_id)
            if not order:
                continue
            status = str(order.get("status") or "").lower()
            for item in order.get("items") or []:
                options_text = json.dumps(item.get("options") or {}, sort_keys=True).lower()
                score = 0
                if "return" in task_text:
                    score += 2
                if "speaker" in task_text and "speaker" in str(item.get("name") or "").lower():
                    score += 10
                if "water" in task_text and '"water resistance": "no"' in options_text:
                    score += 12
                if status in {"delivered", "return requested"}:
                    score += 5
                if order.get("fulfillments"):
                    score += 5
                if best_choice is None or (score, float(item.get("price") or 0.0)) > best_choice[:2]:
                    best_choice = (score, float(item.get("price") or 0.0), order, item)
        if best_choice is None or best_choice[0] < 10:
            return None
        _, _, order, item = best_choice
        payment_method_id = self._choose_payment_method_id(user_record, order)
        if payment_method_id is None:
            return None
        return {
            "name": "return_delivered_order_items",
            "requestor": "assistant",
            "arguments": {
                "order_id": order["order_id"],
                "item_ids": [item["item_id"]],
                "payment_method_id": payment_method_id,
            },
        }

    def _select_retail_modify_action(
        self,
        task: Task,
        snapshot: EnvSnapshot,
        user_id: str,
    ) -> JsonDict | None:
        task_text = task_hint_text(task).lower()
        users = snapshot.agent_db.get("users") or {}
        orders = snapshot.agent_db.get("orders") or {}
        products = snapshot.agent_db.get("products") or {}
        user_record = users.get(user_id)
        if not user_record:
            return None
        target_choice: tuple[int, JsonDict, JsonDict] | None = None
        for order_id in user_record.get("orders") or []:
            order = orders.get(order_id)
            if not order:
                continue
            status = str(order.get("status") or "").lower()
            for item in order.get("items") or []:
                options = item.get("options") or {}
                score = 0
                if "pending" in status:
                    score += 5
                if "laptop" in task_text and "laptop" in str(item.get("name") or "").lower():
                    score += 10
                if "17-inch" in task_text and str(options.get("screen size") or "").lower() == "17-inch":
                    score += 12
                if target_choice is None or score > target_choice[0]:
                    target_choice = (score, order, item)
        if target_choice is None or target_choice[0] < 10:
            return None
        _, order, item = target_choice
        product = products.get(item.get("product_id"))
        if not product:
            return None
        best_variant: tuple[int, JsonDict] | None = None
        for variant in (product.get("variants") or {}).values():
            if variant.get("item_id") == item.get("item_id"):
                continue
            options = variant.get("options") or {}
            score = 0
            if variant.get("available"):
                score += 50
            if "13-inch" in task_text and str(options.get("screen size") or "").lower() == "13-inch":
                score += 30
            processor = str(options.get("processor") or "").lower()
            if processor == "i5":
                score += 20
            elif processor == "i7":
                score += 10
            color = str(options.get("color") or "").lower()
            if color == "silver":
                score += 12
            elif color == "black":
                score += 10
            if best_variant is None or score > best_variant[0]:
                best_variant = (score, variant)
        if best_variant is None or best_variant[0] < 40:
            return None
        payment_method_id = self._choose_payment_method_id(user_record, order)
        if payment_method_id is None:
            return None
        return {
            "name": "modify_pending_order_items",
            "requestor": "assistant",
            "arguments": {
                "order_id": order["order_id"],
                "item_ids": [item["item_id"]],
                "new_item_ids": [best_variant[1]["item_id"]],
                "payment_method_id": payment_method_id,
            },
        }

    def _retail_runtime_candidates(
        self,
        task: Task,
        partial_trajectory: TrajectoryRecord,
        patched_action: JsonDict,
        runtime_entities: JsonDict,
        budget: BudgetConfig,
    ) -> list[ContinuationCandidate]:
        snapshot = partial_trajectory.final_snapshot
        users = snapshot.agent_db.get("users") or {}
        user_ids = list(runtime_entities["user_ids"])
        patched_user_id = patched_action.get("arguments", {}).get("user_id")
        if isinstance(patched_user_id, str):
            user_ids.append(patched_user_id)
        user_id = self._first_existing(unique_preserving_order(user_ids), users)
        if user_id is None:
            return []
        direct_actions: list[JsonDict] = []
        return_action = self._select_retail_return_action(task, snapshot, user_id)
        modify_action = self._select_retail_modify_action(task, snapshot, user_id)
        if return_action is not None:
            direct_actions.append(return_action)
        if modify_action is not None:
            direct_actions.append(modify_action)
        requestor = patched_action["requestor"]
        candidates: list[ContinuationCandidate] = []
        if direct_actions:
            normalized_direct = [
                self._make_action(task.id, requestor, index, action["name"], action["arguments"])
                for index, action in enumerate(direct_actions[: budget.continuation_horizon])
            ]
            candidates.append(
                ContinuationCandidate(
                    target_step=partial_trajectory.steps[-1].timestep,
                    actions=normalized_direct,
                    token_cost=max(1, count_tokens(normalized_direct)),
                    description="Use replayed retail state to apply direct terminal repair actions.",
                    metadata={"source": "retail_runtime_db"},
                )
            )
        if patched_action["name"] != "get_user_details":
            detail_then_direct = [
                self._make_action(task.id, requestor, 0, "get_user_details", {"user_id": user_id}),
                *[
                    self._make_action(task.id, requestor, index + 1, action["name"], action["arguments"])
                    for index, action in enumerate(direct_actions[: max(0, budget.continuation_horizon - 1)])
                ],
            ][: budget.continuation_horizon]
            if detail_then_direct:
                candidates.append(
                    ContinuationCandidate(
                        target_step=partial_trajectory.steps[-1].timestep,
                        actions=detail_then_direct,
                        token_cost=max(1, count_tokens(detail_then_direct)),
                        description="Confirm the recovered user, then execute direct retail repair actions.",
                        metadata={"source": "retail_runtime_db_with_user_details"},
                    )
                )
        return candidates[: budget.beam_width]

    def propose_continuations(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        patched_action: JsonDict,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        hints = extract_task_hints(task)
        actions: list[JsonDict] = []
        if patched_action["name"] == "get_user_details":
            for order_id in hints["order_ids"][: budget.continuation_horizon]:
                actions.append(
                    {
                        "action_id": f"{task.id}_continuation_{len(actions)}",
                        "requestor": patched_action["requestor"],
                        "name": "get_order_details",
                        "arguments": {"order_id": order_id},
                        "info": None,
                        "compare_args": None,
                    }
                )
        elif patched_action["name"] == "get_order_details":
            for product_id in hints["product_ids"][: budget.continuation_horizon]:
                actions.append(
                    {
                        "action_id": f"{task.id}_continuation_{len(actions)}",
                        "requestor": patched_action["requestor"],
                        "name": "get_product_details",
                        "arguments": {"product_id": product_id},
                        "info": None,
                        "compare_args": None,
                    }
                )
        metadata = ProposerMetadata(
            backend=self.backend,
            status="completed" if actions else "empty",
            total_tokens=count_tokens(actions) if actions else 0,
        )
        if not actions:
            return [], metadata
        return (
            [
                ContinuationCandidate(
                    target_step=step_index,
                    actions=actions[: budget.continuation_horizon],
                    token_cost=max(1, count_tokens(actions)),
                    description="Deterministically extend the patched action with scenario-hinted follow-up tools.",
                    metadata={"source": "task_hints"},
                )
            ],
            metadata,
        )

    def propose_runtime_continuations(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        partial_trajectory: TrajectoryRecord,
        patched_action: JsonDict,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        prompt = json.dumps(
            {
                "task_id": task.id,
                "user_scenario": task_hint_text(task),
                "failure_id": failure.failure_id,
                "target_step": step_index,
                "patched_action": patched_action,
                "partial_tool_result": (
                    partial_trajectory.steps[-1].tool_result if partial_trajectory.steps else None
                ),
                "runtime_entities": extract_runtime_entities(
                    partial_trajectory.steps[-1].tool_result.get("content")
                    if partial_trajectory.steps
                    else ""
                ),
                "instructions": (
                    "Return JSON with key 'actions' whose value is a short list of tool actions "
                    "to continue from this patched state. Prefer the smallest action list that can recover the task."
                ),
            },
            indent=2,
        )
        metadata = ProposerMetadata(
            backend=self.backend,
            model_slug=self.model_slug,
            prompt=prompt,
            prompt_tokens=count_tokens(prompt),
            status="skipped",
        )
        if not self.api_key:
            metadata.status = "missing_api_key"
            metadata.error = "OPENROUTER_API_KEY is not set."
            return [], metadata
        body = {
            "model": self.model_slug,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You propose short structured tool continuations for benchmark agents. "
                        "Return valid JSON only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        request = urllib_request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            metadata.status = "request_failed"
            metadata.error = str(exc)
            return [], metadata
        choice = payload.get("choices", [{}])[0]
        content = ""
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            content = message["content"]
        usage = payload.get("usage") or {}
        metadata.raw_response = content
        metadata.completion_tokens = int(usage.get("completion_tokens") or 0)
        metadata.total_tokens = int(usage.get("total_tokens") or 0)
        metadata.status = "completed"
        parsed = parse_json_object(content)
        if not parsed:
            metadata.status = "invalid_json"
            metadata.error = "Model response was not parseable JSON."
            return [], metadata
        proposed_actions = parsed.get("actions") or []
        if not isinstance(proposed_actions, list):
            metadata.status = "invalid_actions"
            metadata.error = "JSON payload did not contain an actions list."
            return [], metadata
        normalized_actions: list[JsonDict] = []
        for index, action in enumerate(proposed_actions[: budget.continuation_horizon]):
            if not isinstance(action, dict):
                continue
            name = action.get("name")
            requestor = normalize_action_requestor(action.get("requestor", patched_action["requestor"]))
            arguments = action.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                continue
            normalized_actions.append(
                {
                    "action_id": f"{task.id}_openrouter_runtime_{index}",
                    "requestor": requestor,
                    "name": name,
                    "arguments": arguments,
                    "info": None,
                    "compare_args": None,
                }
            )
        if not normalized_actions:
            metadata.status = "empty"
            return [], metadata
        return (
            [
                ContinuationCandidate(
                    target_step=step_index,
                    actions=normalized_actions,
                    token_cost=max(1, metadata.total_tokens or count_tokens(normalized_actions)),
                    description=f"OpenRouter runtime continuation proposal from {self.model_slug}.",
                    metadata={"source": "openrouter_runtime", "model_slug": self.model_slug},
                )
            ],
            metadata,
        )

    def propose_runtime_continuations(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        partial_trajectory: TrajectoryRecord,
        patched_action: JsonDict,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        last_step = partial_trajectory.steps[-1] if partial_trajectory.steps else None
        runtime_entities = extract_runtime_entities(last_step.tool_result.get("content") if last_step else "")
        candidates: list[ContinuationCandidate] = []
        if partial_trajectory.domain == "retail":
            candidates.extend(
                self._retail_runtime_candidates(
                    task=task,
                    partial_trajectory=partial_trajectory,
                    patched_action=patched_action,
                    runtime_entities=runtime_entities,
                    budget=budget,
                )
            )
        if not candidates:
            fallback, _ = self.propose_continuations(task, failure, step_index, patched_action, budget)
            candidates.extend(fallback)
        metadata = ProposerMetadata(
            backend=self.backend,
            status="completed" if candidates else "empty",
            total_tokens=sum(candidate.token_cost for candidate in candidates),
        )
        return candidates[: budget.beam_width], metadata


class OpenRouterProposer(BaseProposer):
    def __init__(
        self,
        adapter: Tau3DomainAdapter,
        model_slug: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            backend=ProposerBackend.OPENROUTER.value,
            model_slug=model_slug or "openai/gpt-4.1-mini",
        )
        self.adapter = adapter
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")

    def _request_actions(
        self,
        *,
        task: Task,
        prompt_payload: JsonDict,
        budget: BudgetConfig,
        requestor: str = "assistant",
        prompt_label: str,
        source: str,
        action_prefix: str,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        tool_catalog = self.adapter.get_tool_catalog()
        enriched_payload = {
            **copy.deepcopy(prompt_payload),
            "available_tools": tool_catalog,
            "requestor_constraint": normalize_action_requestor(requestor),
            "output_rules": [
                "Use only tool names from available_tools.",
                "Do not invent or rename tools.",
                "Set requestor to the provided requestor_constraint unless the action must be user-authored.",
                "If no valid tool action helps, return {\"actions\": []}.",
            ],
        }
        prompt = json.dumps(enriched_payload, indent=2)
        metadata = ProposerMetadata(
            backend=self.backend,
            model_slug=self.model_slug,
            prompt=prompt,
            prompt_tokens=count_tokens(prompt),
            status="skipped",
        )
        if not self.api_key:
            metadata.status = "missing_api_key"
            metadata.error = "OPENROUTER_API_KEY is not set."
            return [], metadata
        body = {
            "model": self.model_slug,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You propose short structured tool actions for benchmark agents. "
                        "Return valid JSON only. Use exact benchmark tool names only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        request = urllib_request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib_error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            metadata.status = "request_failed"
            metadata.error = str(exc)
            return [], metadata
        choice = payload.get("choices", [{}])[0]
        content = ""
        message = choice.get("message") or {}
        if isinstance(message.get("content"), str):
            content = message["content"]
        usage = payload.get("usage") or {}
        metadata.raw_response = content
        metadata.completion_tokens = int(usage.get("completion_tokens") or 0)
        metadata.total_tokens = int(usage.get("total_tokens") or 0)
        metadata.status = "completed"
        parsed = parse_json_object(content)
        if not parsed:
            metadata.status = "invalid_json"
            metadata.error = "Model response was not parseable JSON."
            return [], metadata
        proposed_actions = parsed.get("actions") or []
        if not isinstance(proposed_actions, list):
            metadata.status = "invalid_actions"
            metadata.error = "JSON payload did not contain an actions list."
            return [], metadata
        normalized_actions: list[JsonDict] = []
        invalid_tool_names: list[str] = []
        for index, action in enumerate(proposed_actions[: budget.continuation_horizon]):
            if not isinstance(action, dict):
                continue
            name = action.get("name")
            action_requestor = normalize_action_requestor(action.get("requestor", requestor))
            arguments = action.get("arguments", {})
            if not isinstance(name, str) or not isinstance(arguments, dict):
                continue
            if not self.adapter.has_tool(name):
                invalid_tool_names.append(str(name))
                continue
            normalized_actions.append(
                {
                    "action_id": f"{task.id}_{action_prefix}_{index}",
                    "requestor": action_requestor,
                    "name": name,
                    "arguments": arguments,
                    "info": None,
                    "compare_args": None,
                }
            )
        if not normalized_actions:
            metadata.status = "empty"
            if invalid_tool_names:
                unique_names = sorted(set(invalid_tool_names))
                metadata.error = (
                    "Model proposed only invalid tool names: "
                    + ", ".join(unique_names[:8])
                )
            return [], metadata
        if invalid_tool_names:
            unique_names = sorted(set(invalid_tool_names))
            metadata.error = (
                "Dropped invalid tool names: "
                + ", ".join(unique_names[:8])
            )
        return (
            [
                ContinuationCandidate(
                    target_step=int(prompt_payload.get("target_step") or 0),
                    actions=normalized_actions,
                    token_cost=max(1, metadata.total_tokens or count_tokens(normalized_actions)),
                    description=f"{prompt_label} from {self.model_slug}.",
                    metadata={"source": source, "model_slug": self.model_slug},
                )
            ],
            metadata,
        )

    def propose_continuations(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        patched_action: JsonDict,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        return self._request_actions(
            task=task,
            prompt_payload={
                "task_id": task.id,
                "user_scenario": task_hint_text(task),
                "failure_id": failure.failure_id,
                "target_step": step_index,
                "patched_action": patched_action,
                "recent_actions": [
                    step.action
                    for step in failure.trajectory.steps[max(0, step_index - 2) : step_index + 1]
                ],
                "instructions": (
                    "Return JSON with key 'actions' whose value is a short list of tool actions "
                    "to continue after the patched action. Each action needs requestor, name, and arguments."
                ),
            },
            budget=budget,
            requestor=str(patched_action["requestor"]),
            prompt_label="OpenRouter continuation proposal",
            source="openrouter",
            action_prefix="openrouter",
        )

    def propose_runtime_continuations(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        partial_trajectory: TrajectoryRecord,
        patched_action: JsonDict,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        prompt_payload = {
            "task_id": task.id,
            "user_scenario": task_hint_text(task),
            "failure_id": failure.failure_id,
            "target_step": step_index,
            "patched_action": patched_action,
            "partial_tool_result": (
                partial_trajectory.steps[-1].tool_result if partial_trajectory.steps else None
            ),
            "runtime_entities": extract_runtime_entities(
                partial_trajectory.steps[-1].tool_result.get("content")
                if partial_trajectory.steps
                else ""
            ),
            "instructions": (
                "Return JSON with key 'actions' whose value is a short list of tool actions "
                "to continue from this replayed state. Prefer the smallest action list that can recover the task."
            ),
        }
        return self._request_actions(
            task=task,
            prompt_payload=prompt_payload,
            budget=budget,
            requestor=str(patched_action["requestor"]),
            prompt_label="OpenRouter runtime continuation proposal",
            source="openrouter_runtime",
            action_prefix="openrouter_runtime",
        )

    def propose_actions_from_task(
        self,
        task: Task,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        return self._request_actions(
            task=task,
            prompt_payload={
                "task_id": task.id,
                "user_scenario": task_hint_text(task),
                "target_step": 0,
                "instructions": (
                    "Return JSON with key 'actions' whose value is a short list of tool actions "
                    "that attempts to solve this task from scratch. Each action needs requestor, name, and arguments."
                ),
            },
            budget=budget,
            requestor="assistant",
            prompt_label="OpenRouter retry-from-scratch proposal",
            source="openrouter_retry_from_scratch",
            action_prefix="openrouter_retry",
        )

    def propose_actions_from_snapshot(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        snapshot: EnvSnapshot,
        budget: BudgetConfig,
    ) -> tuple[list[ContinuationCandidate], ProposerMetadata]:
        recent_history = snapshot.message_history[-6:]
        return self._request_actions(
            task=task,
            prompt_payload={
                "task_id": task.id,
                "user_scenario": task_hint_text(task),
                "failure_id": failure.failure_id,
                "target_step": step_index,
                "snapshot_step_index": snapshot.step_index,
                "recent_messages": recent_history,
                "runtime_entities": extract_runtime_entities(recent_history),
                "instructions": (
                    "Return JSON with key 'actions' whose value is a short list of tool actions "
                    "to continue this task from the restored snapshot. Each action needs requestor, name, and arguments."
                ),
            },
            budget=budget,
            requestor="assistant",
            prompt_label="OpenRouter retry-from-snapshot proposal",
            source="openrouter_retry_from_snapshot",
            action_prefix="openrouter_snapshot_retry",
        )


class NaturalFailureImporter:
    def __init__(self, adapter: Tau3DomainAdapter) -> None:
        self.adapter = adapter
        self.runner = RealBenchmarkRunner(adapter)

    def import_results(
        self,
        results_path: Path,
        limit: int | None,
    ) -> tuple[list[FailureCase], JsonDict]:
        payload = load_json(results_path)
        simulations = payload.get("simulations", [])
        failures: list[FailureCase] = []
        skipped: list[JsonDict] = []
        replay_success_skipped = 0
        for simulation in simulations:
            reward_info = simulation.get("reward_info") or {}
            reward = float(reward_info.get("reward") or 0.0)
            if reward >= 0.999999:
                continue
            task_id = str(simulation["task_id"])
            if task_id not in self.adapter.tasks:
                skipped.append({"task_id": task_id, "reason": "task not available in selected split"})
                continue
            actions = extract_actions_from_messages(task_id, simulation.get("messages") or [])
            if not actions:
                skipped.append({"task_id": task_id, "reason": "no tool calls found"})
                continue
            trajectory = self.runner.build_action_trajectory(
                task_id=task_id,
                actions=actions,
                fault_description="Natural failed trajectory imported from saved tau2 benchmark results.",
            )
            if trajectory.outcome.success:
                replay_success_skipped += 1
                skipped.append(
                    {
                        "task_id": task_id,
                        "reason": "replay trajectory succeeded; excluded from natural failure corpus",
                        "simulation_id": simulation.get("id"),
                    }
                )
                continue
            metadata = {
                "results_path": str(results_path),
                "simulation_id": simulation.get("id"),
                "trial": simulation.get("trial"),
                "seed": simulation.get("seed"),
                "termination_reason": simulation.get("termination_reason"),
                "task_split": self.adapter.task_split,
                "original_reward": reward,
                "original_reward_breakdown": reward_info.get("reward_breakdown") or {},
                "original_agent_cost": simulation.get("agent_cost"),
                "original_user_cost": simulation.get("user_cost"),
                "replay_outcome": asdict(trajectory.outcome),
                **summarize_action_errors(trajectory),
            }
            failures.append(
                FailureCase(
                    failure_id=f"{self.adapter.domain}:{task_id}:natural:{simulation.get('trial', 'na')}:{simulation.get('id')}",
                    domain=self.adapter.domain,
                    task_split=self.adapter.task_split,
                    task_id=task_id,
                    trajectory=trajectory,
                    failure_reason=f"Natural benchmark failure with original reward {reward}.",
                    source="natural_tau2_result",
                    source_metadata=metadata,
                )
            )
            if limit is not None and len(failures) >= limit:
                break
        summary = {
            "source_results_path": str(results_path),
            "domain": self.adapter.domain,
            "task_split": self.adapter.task_split,
            "simulations_seen": len(simulations),
            "imported_failure_count": len(failures),
            "skipped_count": len(skipped),
            "skipped_examples": skipped[:10],
            "replay_success_skipped_count": replay_success_skipped,
            "total_tool_calls": sum(item.source_metadata["tool_call_count"] for item in failures),
            "total_tool_errors": sum(item.source_metadata["tool_error_count"] for item in failures),
        }
        summary["tool_error_rate"] = (
            summary["total_tool_errors"] / summary["total_tool_calls"]
            if summary["total_tool_calls"]
            else 0.0
        )
        return failures, summary


class FailureCollector:
    def __init__(self, adapter: Tau3DomainAdapter) -> None:
        self.adapter = adapter
        self.runner = RealBenchmarkRunner(adapter)

    def collect(self, task_ids: list[str]) -> tuple[list[TrajectoryRecord], list[FailureCase]]:
        trajectories: list[TrajectoryRecord] = []
        failures: list[FailureCase] = []
        for task_id in task_ids:
            trajectory = self.runner.build_failed_trajectory(task_id)
            trajectories.append(trajectory)
            if not trajectory.outcome.success:
                failures.append(
                    FailureCase(
                        failure_id=f"{self.adapter.domain}:{task_id}:failure",
                        domain=self.adapter.domain,
                        task_split=self.adapter.task_split,
                        task_id=task_id,
                        trajectory=trajectory,
                        failure_reason=trajectory.outcome.reason,
                    )
                )
        return trajectories, failures

class PatchSearchEngine:
    def __init__(
        self,
        adapter: Tau3DomainAdapter,
        include_oracle_suffix: bool = False,
        proposer_backend: str = ProposerBackend.DETERMINISTIC.value,
        model_slug: str | None = None,
        budget: BudgetConfig | None = None,
    ) -> None:
        self.adapter = adapter
        self.runner = RealBenchmarkRunner(adapter)
        self.include_oracle_suffix = include_oracle_suffix
        self.default_budget = copy.deepcopy(budget) if budget else BudgetConfig()
        self.proposer_backend = proposer_backend
        if proposer_backend == ProposerBackend.OPENROUTER.value:
            self.proposer: BaseProposer = OpenRouterProposer(adapter=adapter, model_slug=model_slug)
        else:
            self.proposer = DeterministicProposer()

    def search(
        self,
        failure: FailureCase,
        strategy: str = "heuristic",
        max_evaluations: int | None = None,
        budget: BudgetConfig | None = None,
    ) -> PatchSearchResult:
        active_budget = copy.deepcopy(budget) if budget else copy.deepcopy(self.default_budget)
        if max_evaluations is not None:
            active_budget.max_evaluations_per_failure = max_evaluations
        localization = self.localize_step(failure, strategy, active_budget)
        total_cost = localization.token_cost
        evaluations: list[PatchEvaluation] = []
        winning: PatchEvaluation | None = None
        evaluated_family_counts: dict[str, int] = {}
        for step_index in localization.ranked_steps:
            candidates = self.propose_patch_candidates(failure, step_index, active_budget)
            if active_budget.max_candidates_per_step is not None:
                candidates = self._truncate_candidates_for_budget(
                    candidates,
                    active_budget.max_candidates_per_step,
                )
            if strategy == "random_candidate":
                random.shuffle(candidates)
            for candidate in candidates:
                if (
                    active_budget.max_evaluations_per_failure is not None
                    and len(evaluations) >= active_budget.max_evaluations_per_failure
                ):
                    break
                total_cost += candidate.token_cost + active_budget.replay_cost_per_candidate
                evaluation = self.evaluate_candidate(failure, candidate, active_budget)
                total_cost += evaluation.dynamic_token_cost
                evaluations.append(evaluation)
                evaluated_family_counts[evaluation.candidate.patch_family] = (
                    evaluated_family_counts.get(evaluation.candidate.patch_family, 0) + 1
                )
                if evaluation.recovered and (
                    winning is None
                    or evaluation.candidate.size_score < winning.candidate.size_score
                    or (
                        evaluation.candidate.size_score == winning.candidate.size_score
                        and evaluation.candidate.token_cost < winning.candidate.token_cost
                    )
                ):
                    winning = evaluation
            if (
                active_budget.max_evaluations_per_failure is not None
                and len(evaluations) >= active_budget.max_evaluations_per_failure
            ):
                break
            if winning is not None and strategy not in {"chronological", "random_candidate"}:
                break
        autopsy = self.build_autopsy_report(
            failure,
            winning,
            total_cost,
            localization,
            active_budget,
            self.proposer.backend,
            method_variant=MethodVariant.PATCH_SEARCH_STRUCTURED.value,
        )
        return PatchSearchResult(
            failure_id=failure.failure_id,
            method_variant=MethodVariant.PATCH_SEARCH_STRUCTURED.value,
            recovered=winning is not None,
            winning_patch=winning.candidate if winning else None,
            winning_outcome=winning.outcome if winning else None,
            evaluated_candidates=evaluations,
            total_token_cost=total_cost,
            localization=localization,
            budget=active_budget,
            proposer_backend=self.proposer.backend,
            evaluated_family_counts=dict(sorted(evaluated_family_counts.items())),
            autopsy_report=autopsy,
        )

    def _truncate_candidates_for_budget(
        self,
        candidates: list[PatchCandidate],
        max_candidates_per_step: int,
    ) -> list[PatchCandidate]:
        if max_candidates_per_step <= 0:
            return []
        if not self.include_oracle_suffix:
            return candidates[:max_candidates_per_step]
        oracle_candidates = [
            candidate
            for candidate in candidates
            if candidate.patch_family == PatchFamily.TOOL_CALL_WITH_ORACLE_SUFFIX.value
        ]
        if not oracle_candidates:
            return candidates[:max_candidates_per_step]
        non_oracle_candidates = [
            candidate
            for candidate in candidates
            if candidate.patch_family != PatchFamily.TOOL_CALL_WITH_ORACLE_SUFFIX.value
        ]
        selected = oracle_candidates[:max_candidates_per_step]
        remaining = max_candidates_per_step - len(selected)
        if remaining > 0:
            selected.extend(non_oracle_candidates[:remaining])
        return selected

    def localize_step(
        self,
        failure: FailureCase,
        strategy: str,
        budget: BudgetConfig,
    ) -> LocalizationResult:
        ranked_steps, suspicious_scores = self.rank_candidate_steps(failure, strategy)
        return LocalizationResult(
            strategy=strategy,
            ranked_steps=ranked_steps,
            suspicious_scores=suspicious_scores,
            token_cost=len(ranked_steps) * budget.localization_cost_per_step,
        )

    @staticmethod
    def rank_candidate_steps(
        failure: FailureCase,
        strategy: str = "heuristic",
    ) -> tuple[list[int], list[JsonDict]]:
        step_count = len(failure.trajectory.steps)
        suspicious_scores: list[JsonDict] = []
        if strategy == "no_repair":
            return [], []
        if strategy == "latest_only":
            ranked = [step_count - 1] if step_count else []
        elif strategy == "reverse":
            ranked = list(reversed(range(step_count)))
        elif strategy == "chronological":
            ranked = list(range(step_count))
        elif strategy == "random_candidate":
            ranked = list(range(step_count))
            random.shuffle(ranked)
        elif strategy == "oracle_fault_step":
            if failure.trajectory.fault_step is not None:
                remaining = [
                    index for index in reversed(range(step_count))
                    if index != failure.trajectory.fault_step
                ]
                ranked = [failure.trajectory.fault_step] + remaining
            else:
                ranked, suspicious_scores = PatchSearchEngine.rank_candidate_steps(failure, "heuristic")
                return ranked, suspicious_scores
        elif strategy == "heuristic":
            scored_steps: list[tuple[int, int]] = []
            for step in failure.trajectory.steps:
                suspicion = step.timestep
                if step.action.get("requestor") == "assistant":
                    suspicion += 100
                if step.tool_result.get("error"):
                    suspicion += 50
                if step.action.get("name", "").startswith("find_"):
                    suspicion += 10
                scored_steps.append((suspicion, step.timestep))
            scored_steps.sort(reverse=True)
            ranked = [step_index for _, step_index in scored_steps]
            suspicious_scores = [
                {"step_index": step_index, "score": score}
                for score, step_index in scored_steps
            ]
            return ranked, suspicious_scores
        else:
            raise ValueError(f"Unknown search strategy: {strategy}")
        suspicious_scores = [
            {"step_index": step_index, "score": step_count - rank}
            for rank, step_index in enumerate(ranked)
        ]
        return ranked, suspicious_scores

    def propose_patch_candidates(
        self,
        failure: FailureCase,
        step_index: int,
        budget: BudgetConfig,
    ) -> list[PatchCandidate]:
        task = self.adapter.get_task(failure.task_id)
        failed_step = failure.trajectory.steps[step_index]
        candidates: list[PatchCandidate] = []
        if failure.source == "synthetic_corruption":
            candidates.extend(self.generate_reference_argument_candidates(task, failed_step, step_index))
        base_candidates = self.generate_structured_candidates(task, failed_step, step_index)
        candidates.extend(base_candidates)
        candidates.extend(self.generate_context_candidates(failed_step, step_index))
        candidates.extend(self.generate_deletion_candidates(failed_step, step_index))
        continuation_candidates: list[PatchCandidate] = []
        for base_candidate in base_candidates:
            continuation_candidates.extend(
                self.generate_continuation_candidates(task, failure, step_index, base_candidate, budget)
            )
        candidates.extend(continuation_candidates)
        if self.include_oracle_suffix:
            candidates.extend(self.generate_oracle_suffix_candidates(task, base_candidates))
        return candidates

    def generate_candidates(self, failure: FailureCase, step_index: int) -> list[PatchCandidate]:
        return self.propose_patch_candidates(failure, step_index, copy.deepcopy(self.default_budget))

    def generate_reference_argument_candidates(
        self,
        task: Task,
        failed_step: TrajectoryStep,
        step_index: int,
    ) -> list[PatchCandidate]:
        gold_actions = RealBenchmarkRunner._require_task_actions(task)
        aligned_gold_actions = [
            action
            for action in gold_actions
            if action.requestor == failed_step.action["requestor"]
            and action.name == failed_step.action["name"]
            and action.arguments != failed_step.action["arguments"]
        ]
        if step_index < len(gold_actions):
            indexed_gold_action = gold_actions[step_index]
            if (
                indexed_gold_action.requestor == failed_step.action["requestor"]
                and indexed_gold_action.name == failed_step.action["name"]
                and indexed_gold_action.arguments != failed_step.action["arguments"]
            ):
                aligned_gold_actions.insert(0, indexed_gold_action)
        candidates: list[PatchCandidate] = []
        seen_payloads: set[str] = set()
        for gold_action in aligned_gold_actions:
            payload_key = json.dumps(gold_action.arguments, sort_keys=True)
            if payload_key in seen_payloads:
                continue
            seen_payloads.add(payload_key)
            candidates.append(
                PatchCandidate(
                    target_step=step_index,
                    patch_family=PatchFamily.TOOL_ARGS.value,
                    payload={"arguments": copy.deepcopy(gold_action.arguments)},
                    size_score=diff_size(failed_step.action["arguments"], gold_action.arguments),
                    token_cost=10 + count_tokens(gold_action.arguments),
                    description=(
                        "Replace the observed tool arguments with arguments from "
                        f"reference action {gold_action.action_id}."
                    ),
                )
            )
        return candidates

    def generate_structured_candidates(
        self,
        task: Task,
        failed_step: TrajectoryStep,
        step_index: int,
    ) -> list[PatchCandidate]:
        hints = extract_task_hints(task)
        current_action = failed_step.action
        candidates: list[PatchCandidate] = []
        seen_payloads: set[str] = set()

        def add_action_candidate(name: str, arguments: JsonDict, description: str) -> None:
            payload = {
                "name": name,
                "requestor": current_action["requestor"],
                "arguments": copy.deepcopy(arguments),
            }
            payload_key = json.dumps(payload, sort_keys=True)
            if payload_key in seen_payloads:
                return
            seen_payloads.add(payload_key)
            original = {
                "name": current_action["name"],
                "requestor": current_action["requestor"],
                "arguments": current_action["arguments"],
            }
            candidates.append(
                PatchCandidate(
                    target_step=step_index,
                    patch_family=PatchFamily.TOOL_CALL_REPLACE.value,
                    payload=payload,
                    size_score=diff_size(original, payload),
                    token_cost=12 + count_tokens(payload),
                    description=description,
                )
            )

        if current_action["name"].startswith("find_user_id") and failed_step.tool_result.get("error"):
            for user_id in hints["user_ids"]:
                add_action_candidate(
                    "get_user_details",
                    {"user_id": user_id},
                    "Use a scenario-provided user id after a failed identity lookup.",
                )
            for email in hints["emails"]:
                if current_action.get("arguments", {}).get("email") != email:
                    add_action_candidate(
                        "find_user_id_by_email",
                        {"email": email},
                        "Try an alternate scenario-provided email address.",
                    )

        if current_action["name"] == "get_order_details" and failed_step.tool_result.get("error"):
            for order_id in hints["order_ids"]:
                if current_action.get("arguments", {}).get("order_id") != order_id:
                    add_action_candidate(
                        "get_order_details",
                        {"order_id": order_id},
                        "Try a scenario-mentioned order id after a failed order lookup.",
                    )
            if hints["user_ids"]:
                candidates.append(
                    PatchCandidate(
                        target_step=step_index,
                        patch_family=PatchFamily.TOOL_INSERTION.value,
                        payload={
                            "insert_before": copy.deepcopy(current_action),
                            "action": {
                                "name": "get_user_details",
                                "requestor": current_action["requestor"],
                                "arguments": {"user_id": hints["user_ids"][0]},
                            },
                        },
                        size_score=1 + count_tokens(hints["user_ids"][0]),
                        token_cost=14 + count_tokens(hints["user_ids"][0]),
                        description="Insert a user-details lookup before the failing order lookup.",
                    )
                )

        return candidates

    def generate_context_candidates(
        self,
        failed_step: TrajectoryStep,
        step_index: int,
    ) -> list[PatchCandidate]:
        history = copy.deepcopy(failed_step.pre_snapshot.message_history)
        candidates: list[PatchCandidate] = []
        if history and failed_step.tool_result.get("error"):
            pruned_history = history[:-1]
            candidates.append(
                PatchCandidate(
                    target_step=step_index,
                    patch_family=PatchFamily.CONTEXT_EDIT.value,
                    payload={"message_history": pruned_history},
                    size_score=1,
                    token_cost=6 + count_tokens(pruned_history),
                    description="Prune the latest stale message from context before replaying the suffix.",
                )
            )
        return candidates

    def generate_deletion_candidates(
        self,
        failed_step: TrajectoryStep,
        step_index: int,
    ) -> list[PatchCandidate]:
        if failed_step.action.get("requestor") != "assistant":
            return []
        action_name = str(failed_step.action.get("name") or "")
        deletion_reasons: list[str] = []
        if failed_step.tool_result.get("error"):
            deletion_reasons.append("error")
        if action_name and self.adapter.is_mutating_tool(action_name):
            deletion_reasons.append("mutating")
        if not deletion_reasons:
            return []
        if deletion_reasons == ["error"]:
            description = "Delete the failing tool step and replay the remaining suffix."
        elif deletion_reasons == ["mutating"]:
            description = "Delete the mutating tool step and replay the remaining suffix."
        else:
            description = (
                "Delete the mutating tool step that also produced a failure signal, "
                "then replay the remaining suffix."
            )
        return [
            PatchCandidate(
                target_step=step_index,
                patch_family=PatchFamily.TOOL_DELETION.value,
                payload={"delete": True},
                size_score=1,
                token_cost=4,
                description=description,
            )
        ]

    def generate_continuation_candidates(
        self,
        task: Task,
        failure: FailureCase,
        step_index: int,
        base_candidate: PatchCandidate,
        budget: BudgetConfig,
    ) -> list[PatchCandidate]:
        if base_candidate.patch_family not in {
            PatchFamily.TOOL_ARGS.value,
            PatchFamily.TOOL_CALL_REPLACE.value,
        }:
            return []
        patched_action = self.materialize_patched_action(
            failure.trajectory.steps[step_index].action,
            base_candidate,
        )
        continuations, metadata = self.proposer.propose_continuations(
            task,
            failure,
            step_index,
            patched_action,
            budget,
        )
        candidates: list[PatchCandidate] = []
        for continuation in continuations[: budget.beam_width]:
            candidates.append(
                PatchCandidate(
                    target_step=step_index,
                    patch_family=PatchFamily.CONTINUATION_REPLACE.value,
                    payload={
                        "patched_action": patched_action,
                        "continuation_actions": continuation.actions,
                        "continuation_metadata": continuation.metadata,
                        "proposer_metadata": asdict(metadata),
                        "base_patch_family": base_candidate.patch_family,
                    },
                    size_score=base_candidate.size_score + len(continuation.actions),
                    token_cost=base_candidate.token_cost + continuation.token_cost,
                    description=(
                        base_candidate.description
                        + " Replace the downstream suffix with a bounded continuation proposal."
                    ),
                )
            )
        candidates.append(
            PatchCandidate(
                target_step=step_index,
                patch_family=PatchFamily.CONTINUATION_REPLACE.value,
                payload={
                    "patched_action": patched_action,
                    "continuation_actions": [],
                    "continuation_metadata": {"source": "runtime_policy"},
                    "proposer_metadata": {
                        "backend": self.proposer.backend,
                        "status": "pending_runtime_replay",
                    },
                    "base_patch_family": base_candidate.patch_family,
                    "runtime_policy": True,
                    "base_patch_size": base_candidate.size_score,
                },
                size_score=base_candidate.size_score,
                token_cost=base_candidate.token_cost + 1,
                description=(
                    base_candidate.description
                    + " Run the patched action first, then synthesize a bounded continuation from the replayed state."
                ),
            )
        )
        return candidates

    def generate_oracle_suffix_candidates(
        self,
        task: Task,
        base_candidates: list[PatchCandidate],
    ) -> list[PatchCandidate]:
        try:
            gold_actions = RealBenchmarkRunner._require_task_actions(task)
        except ValueError:
            return []
        candidates: list[PatchCandidate] = []
        seen_payloads: set[str] = set()
        for base_candidate in base_candidates:
            if base_candidate.patch_family != PatchFamily.TOOL_CALL_REPLACE.value:
                continue
            match_index = self.find_matching_gold_action(gold_actions, base_candidate.payload)
            if match_index is None:
                continue
            suffix_actions = [action.model_dump(mode="json") for action in gold_actions[match_index + 1 :]]
            payload = {
                **copy.deepcopy(base_candidate.payload),
                "suffix_actions": suffix_actions,
                "suffix_source": "reference_evaluation_actions",
                "matched_reference_index": match_index,
            }
            payload_key = json.dumps(payload, sort_keys=True)
            if payload_key in seen_payloads:
                continue
            seen_payloads.add(payload_key)
            candidates.append(
                PatchCandidate(
                    target_step=base_candidate.target_step,
                    patch_family=PatchFamily.TOOL_CALL_WITH_ORACLE_SUFFIX.value,
                    payload=payload,
                    size_score=base_candidate.size_score,
                    token_cost=base_candidate.token_cost + count_tokens(suffix_actions),
                    description=(
                        base_candidate.description
                        + " Continue with the reference-action suffix as an explicit oracle upper-bound ablation."
                    ),
                )
            )
        return candidates

    @staticmethod
    def find_matching_gold_action(gold_actions: list[TauAction], payload: JsonDict) -> int | None:
        for index, action in enumerate(gold_actions):
            if (
                action.requestor == payload["requestor"]
                and action.name == payload["name"]
                and action.arguments == payload["arguments"]
            ):
                return index
        return None

    @staticmethod
    def materialize_patched_action(original_action: JsonDict, candidate: PatchCandidate) -> JsonDict:
        patched_action = copy.deepcopy(original_action)
        if candidate.patch_family == PatchFamily.TOOL_ARGS.value:
            patched_action["arguments"] = copy.deepcopy(candidate.payload["arguments"])
        elif candidate.patch_family in {
            PatchFamily.TOOL_CALL_REPLACE.value,
            PatchFamily.TOOL_CALL_WITH_ORACLE_SUFFIX.value,
        }:
            patched_action["name"] = candidate.payload["name"]
            patched_action["requestor"] = candidate.payload["requestor"]
            patched_action["arguments"] = copy.deepcopy(candidate.payload["arguments"])
        return patched_action

    def evaluate_candidate(
        self,
        failure: FailureCase,
        candidate: PatchCandidate,
        budget: BudgetConfig,
    ) -> PatchEvaluation:
        task = self.adapter.get_task(failure.task_id)
        actions = [TauAction.model_validate(copy.deepcopy(step.action)) for step in failure.trajectory.steps]
        snapshot = copy.deepcopy(failure.trajectory.steps[candidate.target_step].pre_snapshot)
        prefix_steps = failure.trajectory.steps[: candidate.target_step]
        proposer_metadata: ProposerMetadata | None = None
        dynamic_token_cost = 0
        resolved_candidate = copy.deepcopy(candidate)
        if candidate.patch_family == PatchFamily.TOOL_ARGS.value:
            actions[candidate.target_step].arguments = copy.deepcopy(candidate.payload["arguments"])
            remaining_actions = actions[candidate.target_step :]
        elif candidate.patch_family == PatchFamily.TOOL_CALL_REPLACE.value:
            actions[candidate.target_step].name = candidate.payload["name"]
            actions[candidate.target_step].requestor = candidate.payload["requestor"]
            actions[candidate.target_step].arguments = copy.deepcopy(candidate.payload["arguments"])
            remaining_actions = actions[candidate.target_step :]
        elif candidate.patch_family == PatchFamily.CONTINUATION_REPLACE.value:
            first_action = TauAction.model_validate(copy.deepcopy(candidate.payload["patched_action"]))
            proposer_metadata = ProposerMetadata(**candidate.payload.get("proposer_metadata", {}))
            if candidate.payload.get("runtime_policy"):
                try:
                    partial = self.runner.continue_from_snapshot(
                        task=task,
                        snapshot=snapshot,
                        actions=[first_action],
                        start_step=candidate.target_step,
                        fault_step=None,
                        fault_description=None,
                        finalize=False,
                    )
                    runtime_continuations, runtime_metadata = self.proposer.propose_runtime_continuations(
                        task=task,
                        failure=failure,
                        step_index=candidate.target_step,
                        partial_trajectory=partial,
                        patched_action=candidate.payload["patched_action"],
                        budget=budget,
                    )
                    proposer_metadata = runtime_metadata
                    chosen_continuation = runtime_continuations[0] if runtime_continuations else None
                    continuation_actions = [
                        TauAction.model_validate(copy.deepcopy(action))
                        for action in (chosen_continuation.actions if chosen_continuation else [])
                    ]
                    dynamic_token_cost = max(
                        runtime_metadata.total_tokens,
                        chosen_continuation.token_cost if chosen_continuation else 0,
                    )
                    resolved_candidate.payload["proposer_metadata"] = asdict(runtime_metadata)
                    resolved_candidate.payload["continuation_actions"] = (
                        copy.deepcopy(chosen_continuation.actions) if chosen_continuation else []
                    )
                    resolved_candidate.payload["continuation_metadata"] = (
                        copy.deepcopy(chosen_continuation.metadata) if chosen_continuation else {}
                    )
                    resolved_candidate.size_score = (
                        int(candidate.payload.get("base_patch_size", candidate.size_score))
                        + len(continuation_actions)
                    )
                    resolved_candidate.token_cost = candidate.token_cost + dynamic_token_cost
                    if continuation_actions:
                        followup = self.runner.continue_from_snapshot(
                            task=task,
                            snapshot=partial.final_snapshot,
                            actions=continuation_actions,
                            start_step=candidate.target_step + 1,
                            fault_step=None,
                            fault_description=None,
                        )
                    else:
                        followup = self.runner.continue_from_snapshot(
                            task=task,
                            snapshot=partial.final_snapshot,
                            actions=[],
                            start_step=candidate.target_step + 1,
                            fault_step=None,
                            fault_description=None,
                        )
                    trajectory = copy.deepcopy(followup)
                    trajectory.steps = prefix_steps + partial.steps + followup.steps
                    return PatchEvaluation(
                        candidate=resolved_candidate,
                        recovered=trajectory.outcome.success,
                        outcome=trajectory.outcome,
                        patched_trajectory=trajectory,
                        replay_cost=budget.replay_cost_per_candidate,
                        proposer_metadata=proposer_metadata,
                        dynamic_token_cost=dynamic_token_cost,
                    )
                except Exception as exc:
                    trajectory = copy.deepcopy(failure.trajectory)
                    trajectory.outcome = TaskOutcome(
                        success=False,
                        reward=0.0,
                        reason=f"Patched rollout failed before evaluation: {exc}",
                        reward_breakdown={"exception_type": type(exc).__name__},
                    )
                    return PatchEvaluation(
                        candidate=resolved_candidate,
                        recovered=False,
                        outcome=trajectory.outcome,
                        patched_trajectory=trajectory,
                        replay_cost=budget.replay_cost_per_candidate,
                        proposer_metadata=proposer_metadata,
                        dynamic_token_cost=dynamic_token_cost,
                    )
            continuation_actions = [
                TauAction.model_validate(copy.deepcopy(action))
                for action in candidate.payload["continuation_actions"]
            ]
            remaining_actions = [first_action, *continuation_actions]
        elif candidate.patch_family == PatchFamily.TOOL_INSERTION.value:
            inserted = TauAction.model_validate(
                {
                    **copy.deepcopy(candidate.payload["action"]),
                    "action_id": f"{task.id}_inserted_{candidate.target_step}",
                    "info": None,
                    "compare_args": None,
                }
            )
            remaining_actions = [inserted, *actions[candidate.target_step :]]
        elif candidate.patch_family == PatchFamily.TOOL_DELETION.value:
            remaining_actions = actions[candidate.target_step + 1 :]
        elif candidate.patch_family == PatchFamily.CONTEXT_EDIT.value:
            snapshot.message_history = copy.deepcopy(candidate.payload["message_history"])
            remaining_actions = actions[candidate.target_step :]
        elif candidate.patch_family == PatchFamily.TOOL_CALL_WITH_ORACLE_SUFFIX.value:
            first_action = TauAction.model_validate(
                {
                    **copy.deepcopy(candidate.payload),
                    "action_id": actions[candidate.target_step].action_id,
                    "info": actions[candidate.target_step].info,
                    "compare_args": actions[candidate.target_step].compare_args,
                }
            )
            suffix_actions = [
                TauAction.model_validate(copy.deepcopy(action))
                for action in candidate.payload["suffix_actions"]
            ]
            remaining_actions = [first_action, *suffix_actions]
        else:
            raise ValueError(f"Unsupported patch family: {candidate.patch_family}")
        try:
            trajectory = self.runner.continue_from_snapshot(
                task=task,
                snapshot=snapshot,
                actions=remaining_actions,
                start_step=candidate.target_step,
                fault_step=None,
                fault_description=None,
            )
            trajectory.steps = prefix_steps + trajectory.steps
        except Exception as exc:
            trajectory = copy.deepcopy(failure.trajectory)
            trajectory.outcome = TaskOutcome(
                success=False,
                reward=0.0,
                reason=f"Patched rollout failed before evaluation: {exc}",
                reward_breakdown={"exception_type": type(exc).__name__},
            )
        return PatchEvaluation(
            candidate=resolved_candidate,
            recovered=trajectory.outcome.success,
            outcome=trajectory.outcome,
            patched_trajectory=trajectory,
            replay_cost=budget.replay_cost_per_candidate,
            proposer_metadata=proposer_metadata,
            dynamic_token_cost=dynamic_token_cost,
        )

    @staticmethod
    def build_autopsy_report(
        failure: FailureCase,
        winning: PatchEvaluation | None,
        total_cost: int,
        localization: LocalizationResult,
        budget: BudgetConfig,
        proposer_backend: str,
        method_variant: str = MethodVariant.PATCH_SEARCH_STRUCTURED.value,
    ) -> JsonDict:
        source_metadata = copy.deepcopy(failure.source_metadata)
        report: JsonDict = {
            "failure_id": failure.failure_id,
            "method_variant": method_variant,
            "domain": failure.domain,
            "task_split": failure.task_split,
            "task_id": failure.task_id,
            "original_reward": failure.trajectory.outcome.reward,
            "original_failure_reason": failure.failure_reason,
            "recovered": winning is not None,
            "total_token_cost": total_cost,
            "fault_step": failure.trajectory.fault_step,
            "fault_description": failure.trajectory.fault_description,
            "known_fault_step": failure.trajectory.fault_step,
            "continuation_mode": "oracle_upper_bound" if winning and winning.candidate.patch_family == PatchFamily.TOOL_CALL_WITH_ORACLE_SUFFIX.value else "strict_replay",
            "localization": asdict(localization),
            "budget": asdict(budget),
            "proposer_backend": proposer_backend,
            "failure_source": failure.source,
            "benchmark_source_path": source_metadata.get("results_path") or "",
            "source_metadata": source_metadata,
        }
        if winning is None:
            report["summary"] = "No successful patch was found."
            return report
        original_step = failure.trajectory.steps[winning.candidate.target_step]
        patched_step = next(
            (
                step
                for step in winning.patched_trajectory.steps
                if step.timestep == winning.candidate.target_step
            ),
            None,
        )
        if patched_step is None:
            patched_action: JsonDict | None = None
            patched_state_fragment = {
                "step_deleted": True,
                "message_history_length": len(winning.patched_trajectory.final_snapshot.message_history),
                "agent_db_keys": sorted(winning.patched_trajectory.final_snapshot.agent_db.keys())[:10],
            }
        else:
            patched_action = patched_step.action
            patched_state_fragment = {
                "step_deleted": False,
                "message_history_length": len(patched_step.pre_snapshot.message_history),
                "agent_db_keys": sorted(patched_step.pre_snapshot.agent_db.keys())[:10],
            }
        explanation = (
            f"The search localized the likely root cause to step {winning.candidate.target_step}, "
            f"applied a {winning.candidate.patch_family} intervention, and recovered benchmark reward."
        )
        if winning.candidate.patch_family == PatchFamily.TOOL_DELETION.value:
            explanation = (
                f"The search localized the likely root cause to step {winning.candidate.target_step} "
                "and recovered benchmark reward by deleting that assistant tool call."
            )
        report.update(
            {
                "root_cause_step": winning.candidate.target_step,
                "patch_family": winning.candidate.patch_family,
                "patch_size": winning.candidate.size_score,
                "patch_description": winning.candidate.description,
                "original_action": original_step.action,
                "patched_action": patched_action,
                "original_state_fragment": {
                    "message_history_length": len(original_step.pre_snapshot.message_history),
                    "agent_db_keys": sorted(original_step.pre_snapshot.agent_db.keys())[:10],
                },
                "patched_state_fragment": patched_state_fragment,
                "winning_outcome_reason": winning.outcome.reason,
                "natural_language_explanation": explanation,
                "summary": (
                    f"Recovered {failure.failure_id} by patching step "
                    f"{winning.candidate.target_step} with {winning.candidate.patch_family}."
                ),
            }
        )
        return report


class RetryBaselineEngine:
    def __init__(
        self,
        adapter: Tau3DomainAdapter,
        proposer_backend: str = ProposerBackend.OPENROUTER.value,
        model_slug: str | None = None,
        budget: BudgetConfig | None = None,
    ) -> None:
        self.adapter = adapter
        self.runner = RealBenchmarkRunner(adapter)
        self.default_budget = copy.deepcopy(budget) if budget else BudgetConfig()
        self.proposer_backend = proposer_backend
        if proposer_backend == ProposerBackend.OPENROUTER.value:
            self.proposer: BaseProposer = OpenRouterProposer(adapter=adapter, model_slug=model_slug)
        else:
            self.proposer = DeterministicProposer()

    def run(
        self,
        failure: FailureCase,
        method_variant: str,
        strategy: str = "heuristic",
        max_evaluations: int | None = None,
        budget: BudgetConfig | None = None,
    ) -> PatchSearchResult:
        active_budget = copy.deepcopy(budget) if budget else copy.deepcopy(self.default_budget)
        if max_evaluations is not None:
            active_budget.max_evaluations_per_failure = max_evaluations
        if method_variant == MethodVariant.RETRY_FROM_SCRATCH.value:
            localization = LocalizationResult(
                strategy="not_applicable",
                ranked_steps=[],
                suspicious_scores=[],
                token_cost=0,
                metadata={"method_variant": method_variant},
            )
        else:
            ranked_steps, suspicious_scores = PatchSearchEngine.rank_candidate_steps(failure, strategy)
            localization = LocalizationResult(
                strategy=strategy,
                ranked_steps=ranked_steps,
                suspicious_scores=suspicious_scores,
                token_cost=len(ranked_steps) * active_budget.localization_cost_per_step,
                metadata={"method_variant": method_variant},
            )
        evaluations, total_cost = self._evaluate_baseline(
            failure=failure,
            method_variant=method_variant,
            localization=localization,
            budget=active_budget,
        )
        winning = next((item for item in evaluations if item.recovered), None)
        evaluated_family_counts: dict[str, int] = {}
        for evaluation in evaluations:
            family = evaluation.candidate.patch_family
            evaluated_family_counts[family] = evaluated_family_counts.get(family, 0) + 1
        autopsy = self._build_autopsy_report(
            failure=failure,
            method_variant=method_variant,
            winning=winning,
            total_cost=total_cost,
            localization=localization,
            budget=active_budget,
        )
        return PatchSearchResult(
            failure_id=failure.failure_id,
            method_variant=method_variant,
            recovered=winning is not None,
            winning_patch=winning.candidate if winning else None,
            winning_outcome=winning.outcome if winning else None,
            evaluated_candidates=evaluations,
            total_token_cost=total_cost,
            localization=localization,
            budget=active_budget,
            proposer_backend=self.proposer.backend,
            evaluated_family_counts=dict(sorted(evaluated_family_counts.items())),
            autopsy_report=autopsy,
        )

    def _evaluate_baseline(
        self,
        failure: FailureCase,
        method_variant: str,
        localization: LocalizationResult,
        budget: BudgetConfig,
    ) -> tuple[list[PatchEvaluation], int]:
        task = self.adapter.get_task(failure.task_id)
        total_cost = localization.token_cost
        evaluations: list[PatchEvaluation] = []
        if method_variant == MethodVariant.RETRY_FROM_SCRATCH.value:
            candidates, metadata = self.proposer.propose_actions_from_task(task, budget)
            total_cost += metadata.total_tokens or metadata.prompt_tokens
            if not candidates:
                return evaluations, total_cost
            continuation = candidates[0]
            actions = [action_from_payload(action) for action in continuation.actions]
            trajectory = self.runner.build_action_trajectory(
                task_id=failure.task_id,
                actions=actions,
                fault_description="Retry-from-scratch baseline rollout.",
            )
            candidate = PatchCandidate(
                target_step=0,
                patch_family=method_variant,
                payload={
                    "continuation_actions": continuation.actions,
                    "proposer_metadata": asdict(metadata),
                },
                size_score=len(continuation.actions),
                token_cost=continuation.token_cost,
                description="Rerun the task from the initial state with a fresh OpenRouter action plan.",
            )
            evaluations.append(
                PatchEvaluation(
                    candidate=candidate,
                    recovered=trajectory.outcome.success,
                    outcome=trajectory.outcome,
                    patched_trajectory=trajectory,
                    replay_cost=budget.replay_cost_per_candidate,
                    proposer_metadata=metadata,
                )
            )
            total_cost += continuation.token_cost + budget.replay_cost_per_candidate
            return evaluations, total_cost

        if not localization.ranked_steps:
            return evaluations, total_cost
        target_step = localization.ranked_steps[0]
        snapshot = copy.deepcopy(failure.trajectory.steps[target_step].pre_snapshot)
        if method_variant == MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value:
            candidates, metadata = self.proposer.propose_actions_from_snapshot(
                task=task,
                failure=failure,
                step_index=target_step,
                snapshot=snapshot,
                budget=budget,
            )
            total_cost += metadata.total_tokens or metadata.prompt_tokens
            if not candidates:
                return evaluations, total_cost
            continuation = candidates[0]
            trajectory = self.runner.continue_from_snapshot(
                task=task,
                snapshot=snapshot,
                actions=[action_from_payload(action) for action in continuation.actions],
                start_step=target_step,
            )
            candidate = PatchCandidate(
                target_step=target_step,
                patch_family=method_variant,
                payload={
                    "continuation_actions": continuation.actions,
                    "proposer_metadata": asdict(metadata),
                },
                size_score=len(continuation.actions),
                token_cost=continuation.token_cost,
                description="Restore the localized snapshot and continue with a fresh unstructured retry suffix.",
            )
            evaluations.append(
                PatchEvaluation(
                    candidate=candidate,
                    recovered=trajectory.outcome.success,
                    outcome=trajectory.outcome,
                    patched_trajectory=trajectory,
                    replay_cost=budget.replay_cost_per_candidate,
                    proposer_metadata=metadata,
                )
            )
            total_cost += continuation.token_cost + budget.replay_cost_per_candidate
            return evaluations, total_cost

        if method_variant == MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value:
            original_action = failure.trajectory.steps[target_step].action
            partial = self.runner.continue_from_snapshot(
                task=task,
                snapshot=snapshot,
                actions=[action_from_payload(original_action)],
                start_step=target_step,
                finalize=False,
            )
            candidates, metadata = self.proposer.propose_runtime_continuations(
                task=task,
                failure=failure,
                step_index=target_step,
                partial_trajectory=partial,
                patched_action=original_action,
                budget=budget,
            )
            total_cost += metadata.total_tokens or metadata.prompt_tokens
            continuation = candidates[0] if candidates else None
            replay_actions = [action_from_payload(original_action)]
            continuation_payload: list[JsonDict] = []
            if continuation is not None:
                continuation_payload = continuation.actions
                replay_actions.extend(action_from_payload(action) for action in continuation.actions)
                continuation_cost = continuation.token_cost
            else:
                continuation_cost = 0
            trajectory = self.runner.continue_from_snapshot(
                task=task,
                snapshot=snapshot,
                actions=replay_actions,
                start_step=target_step,
            )
            candidate = PatchCandidate(
                target_step=target_step,
                patch_family=method_variant,
                payload={
                    "original_action": original_action,
                    "continuation_actions": continuation_payload,
                    "proposer_metadata": asdict(metadata),
                },
                size_score=len(continuation_payload),
                token_cost=continuation_cost,
                description="Replay the original failing action, then request a fresh downstream continuation only.",
            )
            evaluations.append(
                PatchEvaluation(
                    candidate=candidate,
                    recovered=trajectory.outcome.success,
                    outcome=trajectory.outcome,
                    patched_trajectory=trajectory,
                    replay_cost=budget.replay_cost_per_candidate,
                    proposer_metadata=metadata,
                )
            )
            total_cost += continuation_cost + budget.replay_cost_per_candidate
            return evaluations, total_cost

        raise ValueError(f"Unsupported method variant: {method_variant}")

    @staticmethod
    def _build_autopsy_report(
        failure: FailureCase,
        method_variant: str,
        winning: PatchEvaluation | None,
        total_cost: int,
        localization: LocalizationResult,
        budget: BudgetConfig,
    ) -> JsonDict:
        source_metadata = copy.deepcopy(failure.source_metadata)
        report: JsonDict = {
            "failure_id": failure.failure_id,
            "method_variant": method_variant,
            "domain": failure.domain,
            "task_split": failure.task_split,
            "task_id": failure.task_id,
            "original_reward": failure.trajectory.outcome.reward,
            "original_failure_reason": failure.failure_reason,
            "recovered": winning is not None,
            "total_token_cost": total_cost,
            "fault_step": failure.trajectory.fault_step,
            "fault_description": failure.trajectory.fault_description,
            "known_fault_step": failure.trajectory.fault_step,
            "continuation_mode": method_variant,
            "localization": asdict(localization),
            "budget": asdict(budget),
            "proposer_backend": (
                winning.proposer_metadata.backend
                if winning is not None and winning.proposer_metadata is not None
                else ProposerBackend.DETERMINISTIC.value
            ),
            "failure_source": failure.source,
            "benchmark_source_path": source_metadata.get("results_path") or "",
            "source_metadata": source_metadata,
        }
        if winning is None:
            report["summary"] = f"No successful {method_variant} rollout was found."
            return report
        target_step = winning.candidate.target_step
        original_action = (
            failure.trajectory.steps[target_step].action
            if 0 <= target_step < len(failure.trajectory.steps)
            else None
        )
        baseline_first_action = (
            winning.patched_trajectory.steps[0].action if winning.patched_trajectory.steps else None
        )
        explanations = {
            MethodVariant.RETRY_FROM_SCRATCH.value: (
                "A full retry from the initial task state recovered the benchmark reward."
            ),
            MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value: (
                f"A fresh retry from localized snapshot step {target_step} recovered the benchmark reward."
            ),
            MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value: (
                f"Replaying the original action at step {target_step} and generating a fresh continuation recovered the benchmark reward."
            ),
        }
        report.update(
            {
                "root_cause_step": (
                    None if method_variant == MethodVariant.RETRY_FROM_SCRATCH.value else target_step
                ),
                "patch_family": method_variant,
                "patch_size": winning.candidate.size_score,
                "patch_description": winning.candidate.description,
                "original_action": original_action,
                "patched_action": baseline_first_action,
                "original_state_fragment": {
                    "message_history_length": len(failure.trajectory.steps[target_step].pre_snapshot.message_history)
                    if 0 <= target_step < len(failure.trajectory.steps)
                    else 0,
                    "agent_db_keys": sorted(
                        failure.trajectory.steps[target_step].pre_snapshot.agent_db.keys()
                    )[:10]
                    if 0 <= target_step < len(failure.trajectory.steps)
                    else [],
                },
                "patched_state_fragment": {
                    "message_history_length": len(winning.patched_trajectory.final_snapshot.message_history),
                    "agent_db_keys": sorted(winning.patched_trajectory.final_snapshot.agent_db.keys())[:10],
                },
                "winning_outcome_reason": winning.outcome.reason,
                "natural_language_explanation": explanations.get(
                    method_variant,
                    f"The {method_variant} baseline recovered benchmark reward.",
                ),
                "summary": (
                    f"Recovered {failure.failure_id} with baseline {method_variant}."
                ),
            }
        )
        return report


def reconstruct_snapshot(payload: JsonDict) -> EnvSnapshot:
    return EnvSnapshot(**payload)


def reconstruct_trajectory(payload: JsonDict) -> TrajectoryRecord:
    steps = [
        TrajectoryStep(
            timestep=step["timestep"],
            action=step["action"],
            tool_result=step["tool_result"],
            pre_snapshot=reconstruct_snapshot(step["pre_snapshot"]),
            post_snapshot=reconstruct_snapshot(step["post_snapshot"]),
        )
        for step in payload["steps"]
    ]
    outcome = TaskOutcome(**payload["outcome"])
    return TrajectoryRecord(
        domain=payload["domain"],
        task_id=payload["task_id"],
        steps=steps,
        outcome=outcome,
        final_snapshot=reconstruct_snapshot(payload["final_snapshot"]),
        simulation=payload["simulation"],
        fault_step=payload.get("fault_step"),
        fault_description=payload.get("fault_description"),
    )


def reconstruct_failure(item: JsonDict) -> FailureCase:
    return FailureCase(
        failure_id=item["failure_id"],
        domain=item["domain"],
        task_split=item.get("task_split") or item.get("source_metadata", {}).get("task_split", "base"),
        task_id=item["task_id"],
        trajectory=reconstruct_trajectory(item["trajectory"]),
        failure_reason=item["failure_reason"],
        source=item.get("source", "synthetic_corruption"),
        source_metadata=item.get("source_metadata") or {},
    )


def reconstruct_failures(payload: list[JsonDict]) -> list[FailureCase]:
    return [reconstruct_failure(item) for item in payload]


def iter_failure_cases(path: Path) -> Iterator[FailureCase]:
    for item in iter_json_array(path):
        if not isinstance(item, dict):
            raise ValueError(f"{path} contained a non-object failure payload.")
        yield reconstruct_failure(item)


def failure_shard_name(domain: str, task_split: str) -> str:
    safe_domain = re.sub(r"[^A-Za-z0-9._-]+", "_", domain)
    safe_split = re.sub(r"[^A-Za-z0-9._-]+", "_", task_split)
    return f"{safe_domain}__{safe_split}.jsonl"


def write_failure_artifacts(output_dir: Path, failures: list[FailureCase]) -> JsonDict:
    output_dir.mkdir(parents=True, exist_ok=True)
    serialized = serialize_failure_cases(failures)
    write_jsonl(output_dir / "failures.jsonl", serialized)
    shard_dir = output_dir / "failure_shards"
    shards: dict[tuple[str, str], list[JsonDict]] = {}
    for payload in serialized:
        key = (
            str(payload.get("domain") or ""),
            str(payload.get("task_split") or payload.get("source_metadata", {}).get("task_split", "base")),
        )
        shards.setdefault(key, []).append(payload)
    shard_entries: list[JsonDict] = []
    for (domain, task_split), shard_rows in sorted(shards.items()):
        shard_name = failure_shard_name(domain, task_split)
        shard_path = shard_dir / shard_name
        write_jsonl(shard_path, shard_rows)
        shard_entries.append(
            {
                "domain": domain,
                "task_split": task_split,
                "path": str(shard_path.relative_to(output_dir)),
                "entry_count": len(shard_rows),
            }
        )
    manifest = {
        "format": "jsonl_sharded_v1",
        "entry_count": len(serialized),
        "root_path": "failures.jsonl",
        "shards": shard_entries,
    }
    save_json(output_dir / "failures_manifest.json", manifest)
    return manifest


def iter_failure_cases_from_dir(input_dir: Path) -> Iterator[FailureCase]:
    manifest_path = input_dir / "failures_manifest.json"
    root_jsonl_path = input_dir / "failures.jsonl"
    legacy_json_path = input_dir / "failures.json"
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        shards = manifest.get("shards") or []
        if shards:
            for shard in shards:
                shard_path = input_dir / str(shard["path"])
                for item in iter_jsonl(shard_path):
                    if not isinstance(item, dict):
                        raise ValueError(f"{shard_path} contained a non-object failure payload.")
                    yield reconstruct_failure(item)
            return
        root_path = manifest.get("root_path")
        if isinstance(root_path, str) and (input_dir / root_path).exists():
            for item in iter_jsonl(input_dir / root_path):
                if not isinstance(item, dict):
                    raise ValueError(f"{input_dir / root_path} contained a non-object failure payload.")
                yield reconstruct_failure(item)
            return
    if root_jsonl_path.exists():
        for item in iter_jsonl(root_jsonl_path):
            if not isinstance(item, dict):
                raise ValueError(f"{root_jsonl_path} contained a non-object failure payload.")
            yield reconstruct_failure(item)
        return
    if legacy_json_path.exists():
        for failure in iter_failure_cases(legacy_json_path):
            yield failure
        return
    raise FileNotFoundError(f"No supported failure artifact found in {input_dir}.")


def select_collectable_task_ids(
    adapter: Tau3DomainAdapter,
    limit: int,
) -> tuple[list[str], list[str]]:
    selected: list[str] = []
    skipped: list[str] = []
    for task_id, task in adapter.tasks.items():
        try:
            RealBenchmarkRunner._require_task_actions(task)
        except ValueError:
            skipped.append(task_id)
            continue
        selected.append(task_id)
        if len(selected) >= limit:
            break
    return selected, skipped


def collect_synthetic_failures(
    adapter: Tau3DomainAdapter,
    limit: int,
) -> tuple[list[TrajectoryRecord], list[FailureCase], list[TrajectoryRecord], list[str], list[str]]:
    collector = FailureCollector(adapter)
    reference_runner = RealBenchmarkRunner(adapter)
    reference_trajectories: list[TrajectoryRecord] = []
    trajectories: list[TrajectoryRecord] = []
    failures: list[FailureCase] = []
    selected_task_ids: list[str] = []
    skipped_task_ids: list[str] = []
    for task_id, task in adapter.tasks.items():
        try:
            RealBenchmarkRunner._require_task_actions(task)
        except ValueError:
            skipped_task_ids.append(task_id)
            continue
        selected_task_ids.append(task_id)
        reference_trajectories.append(reference_runner.build_reference_trajectory(task_id))
        collected_trajectories, collected_failures = collector.collect([task_id])
        trajectories.extend(collected_trajectories)
        failures.extend(collected_failures)
        if len(failures) >= limit:
            break
    return reference_trajectories, trajectories[:limit], failures[:limit], selected_task_ids, skipped_task_ids


def collect_failures_cli(domain: str, task_split: str, limit: int, output_dir: Path) -> JsonDict:
    adapter = Tau3DomainAdapter(domain=domain, task_split=task_split)
    (
        reference_trajectories,
        trajectories,
        failures,
        task_ids,
        skipped_task_ids,
    ) = collect_synthetic_failures(adapter, limit)
    summary = {
        "domain": domain,
        "task_split": task_split,
        "task_count": len(task_ids),
        "skipped_task_count": len(skipped_task_ids),
        "skipped_task_ids": skipped_task_ids,
        "reference_success_count": sum(1 for item in reference_trajectories if item.outcome.success),
        "failure_count": len(failures),
        "failure_ids": [item.failure_id for item in failures],
    }
    save_json(output_dir / "reference_trajectories.json", reference_trajectories)
    save_json(output_dir / "failed_trajectories.json", trajectories)
    write_failure_artifacts(output_dir, failures)
    save_json(output_dir / "summary.json", summary)
    return summary


def import_natural_failures_cli(
    domain: str,
    task_split: str,
    results_path: Path,
    limit: int,
    output_dir: Path,
) -> JsonDict:
    adapter = Tau3DomainAdapter(domain=domain, task_split=task_split)
    importer = NaturalFailureImporter(adapter)
    failures, summary = importer.import_results(
        results_path=results_path,
        limit=limit if limit > 0 else None,
    )
    write_failure_artifacts(output_dir, failures)
    save_json(output_dir / "summary.json", summary)
    return summary


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def load_serialized_patch_results(input_dir: Path) -> list[JsonDict]:
    jsonl_path = input_dir / "patch_results.jsonl"
    legacy_json_path = input_dir / "patch_results.json"
    if jsonl_path.exists():
        return [item for item in iter_jsonl(jsonl_path) if isinstance(item, dict)]
    if legacy_json_path.exists():
        payload = load_json(legacy_json_path)
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
    return []


def extract_result_domain(result_payload: JsonDict) -> str:
    autopsy = result_payload.get("autopsy_report") or {}
    return str(autopsy.get("domain") or "")


def extract_result_task_split(result_payload: JsonDict) -> str:
    autopsy = result_payload.get("autopsy_report") or {}
    source_metadata = autopsy.get("source_metadata") or {}
    task_split = autopsy.get("task_split") or source_metadata.get("task_split") or "base"
    return normalize_task_split(str(task_split))


def aggregate_patch_result_payloads(payload: list[JsonDict]) -> JsonDict:
    recovered = [item for item in payload if item.get("recovered")]
    patch_sizes = [
        item["winning_patch"]["size_score"]
        for item in recovered
        if item.get("winning_patch")
    ]
    token_costs = [int(item.get("total_token_cost") or 0) for item in payload]
    evaluated_family_counts: dict[str, int] = {}
    for item in payload:
        family_counts = item.get("evaluated_family_counts") or {}
        for family, count in family_counts.items():
            evaluated_family_counts[str(family)] = (
                evaluated_family_counts.get(str(family), 0) + int(count)
            )
    return {
        "failure_count": len(payload),
        "recovered_count": len(recovered),
        "success_recovery_rate": len(recovered) / len(payload) if payload else 0.0,
        "total_token_cost": sum(token_costs),
        "evaluated_candidate_count": sum(
            len(item.get("evaluated_candidates") or []) for item in payload
        ),
        "evaluated_family_counts": dict(sorted(evaluated_family_counts.items())),
        "average_patch_size": sum(patch_sizes) / len(patch_sizes) if patch_sizes else 0.0,
        "median_token_cost": statistics.median(token_costs) if token_costs else 0.0,
        "p90_token_cost": percentile(token_costs, 0.9),
        "localization_metrics": build_localization_metrics(payload),
    }


def write_patch_result_artifacts(
    output_dir: Path,
    serialized_results: list[JsonDict],
    summary: JsonDict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "patch_results.jsonl", serialized_results)
    save_json(
        output_dir / "patch_results_manifest.json",
        {
            "format": "jsonl_v1",
            "entry_count": len(serialized_results),
            "root_path": "patch_results.jsonl",
            "summary_path": "patch_summary.json",
            "progress_summary_path": "patch_summary.progress.json",
        },
    )
    save_json(output_dir / "patch_summary.json", summary)


def save_patch_progress_summary(output_dir: Path, summary: JsonDict) -> None:
    save_json(output_dir / "patch_summary.progress.json", summary)


def build_corpus_cli(
    name: str,
    domain_specs: list[str],
    limit_per_domain: int,
    output_dir: Path,
) -> JsonDict:
    entries: list[FailureCorpusEntry] = []
    all_failures: list[FailureCase] = []
    domains: list[str] = []
    for spec in domain_specs:
        domain, task_split, results_path_text = spec.split("::", 2)
        domains.append(domain)
        adapter = Tau3DomainAdapter(domain=domain, task_split=task_split)
        importer = NaturalFailureImporter(adapter)
        failures, summary = importer.import_results(Path(results_path_text), limit=limit_per_domain)
        for index, failure in enumerate(failures):
            trajectory = failure.trajectory
            tool_error_count = sum(1 for step in trajectory.steps if step.tool_result.get("error"))
            entry = FailureCorpusEntry(
                failure_id=failure.failure_id,
                domain=domain,
                task_split=failure.task_split,
                task_id=failure.task_id,
                split=assign_split(index),
                source=failure.source,
                source_path=results_path_text,
                original_reward=float(failure.source_metadata.get("original_reward", 0.0)),
                replay_reward=trajectory.outcome.reward,
                tool_call_count=len(trajectory.steps),
                tool_error_count=tool_error_count,
                step_count=len(trajectory.steps),
                failure_reason=trajectory.outcome.reason or summary.get("source_results_path", ""),
            )
            entries.append(entry)
            all_failures.append(failure)
    split_counts: dict[str, int] = {}
    for entry in entries:
        split_counts[entry.split] = split_counts.get(entry.split, 0) + 1
    manifest = FailureCorpusManifest(
        name=name,
        domains=sorted(set(domains)),
        entry_count=len(entries),
        split_counts=dict(sorted(split_counts.items())),
        entries=entries,
    )
    rows = [asdict(entry) for entry in entries]
    save_json(output_dir / "corpus_manifest.json", manifest)
    write_failure_artifacts(output_dir, all_failures)
    if rows:
        save_csv(output_dir / "corpus_manifest.csv", rows, list(rows[0].keys()))
    return {
        "name": name,
        "domains": manifest.domains,
        "entry_count": manifest.entry_count,
        "split_counts": manifest.split_counts,
    }


def build_synthetic_corpus_cli(
    name: str,
    domains: list[str],
    limit_per_domain: int,
    output_dir: Path,
    task_split: str = "base",
) -> JsonDict:
    entries: list[FailureCorpusEntry] = []
    all_failures: list[FailureCase] = []
    ordered_domains: list[str] = []
    global_index = 0
    for domain in domains:
        adapter = Tau3DomainAdapter(domain=domain, task_split=task_split)
        _, _, failures, _, _ = collect_synthetic_failures(adapter, limit_per_domain)
        ordered_domains.append(domain)
        for failure in failures:
            trajectory = failure.trajectory
            tool_error_count = sum(1 for step in trajectory.steps if step.tool_result.get("error"))
            entry = FailureCorpusEntry(
                failure_id=failure.failure_id,
                domain=domain,
                task_split=failure.task_split,
                task_id=failure.task_id,
                split=assign_split(global_index),
                source=failure.source,
                source_path="synthetic_failure_collector",
                original_reward=0.0,
                replay_reward=trajectory.outcome.reward,
                tool_call_count=len(trajectory.steps),
                tool_error_count=tool_error_count,
                step_count=len(trajectory.steps),
                failure_reason=failure.failure_reason,
            )
            entries.append(entry)
            all_failures.append(failure)
            global_index += 1
    split_counts: dict[str, int] = {}
    for entry in entries:
        split_counts[entry.split] = split_counts.get(entry.split, 0) + 1
    manifest = FailureCorpusManifest(
        name=name,
        domains=sorted(set(ordered_domains)),
        entry_count=len(entries),
        split_counts=dict(sorted(split_counts.items())),
        entries=entries,
    )
    rows = [asdict(entry) for entry in entries]
    save_json(output_dir / "corpus_manifest.json", manifest)
    write_failure_artifacts(output_dir, all_failures)
    if rows:
        save_csv(output_dir / "corpus_manifest.csv", rows, list(rows[0].keys()))
    summary = {
        "name": name,
        "domains": manifest.domains,
        "entry_count": manifest.entry_count,
        "split_counts": manifest.split_counts,
        "task_split": task_split,
        "limit_per_domain": limit_per_domain,
    }
    save_json(output_dir / "summary.json", summary)
    return summary


def search_patches_cli(
    input_dir: Path,
    output_dir: Path,
    strategy: str = "heuristic",
    max_evaluations: int | None = None,
    include_oracle_suffix: bool = False,
    proposer_backend: str = ProposerBackend.DETERMINISTIC.value,
    model_slug: str | None = None,
    continuation_horizon: int = 3,
    beam_width: int = 2,
    max_candidates_per_step: int | None = None,
    compact_results: bool = False,
) -> JsonDict:
    output_dir.mkdir(parents=True, exist_ok=True)
    existing_results = load_serialized_patch_results(output_dir)
    results_jsonl_path = output_dir / "patch_results.jsonl"
    if existing_results and not results_jsonl_path.exists():
        write_jsonl(results_jsonl_path, existing_results)
    existing_failure_ids = {
        str(item.get("failure_id"))
        for item in existing_results
        if item.get("failure_id") is not None
    }
    budget = BudgetConfig(
        max_evaluations_per_failure=max_evaluations,
        max_candidates_per_step=max_candidates_per_step,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
    )
    engines: dict[tuple[str, str], PatchSearchEngine] = {}
    serialized_results: list[JsonDict] = list(existing_results)
    domains: set[str] = {
        extract_result_domain(item) for item in existing_results if extract_result_domain(item)
    }
    task_splits: set[str] = {
        extract_result_task_split(item) for item in existing_results if extract_result_task_split(item)
    }
    for failure in iter_failure_cases_from_dir(input_dir):
        domains.add(failure.domain)
        task_splits.add(failure.task_split)
        if failure.failure_id in existing_failure_ids:
            continue
        engine_key = (failure.domain, failure.task_split)
        if engine_key not in engines:
            adapter = Tau3DomainAdapter(domain=failure.domain, task_split=failure.task_split)
            engines[engine_key] = PatchSearchEngine(
                adapter,
                include_oracle_suffix=include_oracle_suffix,
                proposer_backend=proposer_backend,
                model_slug=model_slug,
                budget=budget,
            )
        result = engines[engine_key].search(
            failure,
            strategy=strategy,
            max_evaluations=max_evaluations,
            budget=budget,
        )
        serialized_result = serialize_patch_search_result(result, compact=compact_results)
        serialized_results.append(serialized_result)
        existing_failure_ids.add(failure.failure_id)
        append_jsonl(results_jsonl_path, serialized_result)
        aggregate = aggregate_patch_result_payloads(serialized_results)
        progress_summary = {
            "method_variant": MethodVariant.PATCH_SEARCH_STRUCTURED.value,
            "strategy": strategy,
            "include_oracle_suffix": include_oracle_suffix,
            "proposer_backend": proposer_backend,
            "model_slug": model_slug,
            "domains": sorted(domain for domain in domains if domain),
            "task_splits": sorted(task_split for task_split in task_splits if task_split),
            "failure_count": aggregate["failure_count"],
            "recovered_count": aggregate["recovered_count"],
            "success_recovery_rate": aggregate["success_recovery_rate"],
            "total_token_cost": aggregate["total_token_cost"],
            "max_evaluations_per_failure": max_evaluations,
            "max_candidates_per_step": max_candidates_per_step,
            "continuation_horizon": continuation_horizon,
            "beam_width": beam_width,
            "evaluated_candidate_count": aggregate["evaluated_candidate_count"],
            "evaluated_family_counts": aggregate["evaluated_family_counts"],
            "compact_results": compact_results,
            "average_patch_size": aggregate["average_patch_size"],
            "median_token_cost": aggregate["median_token_cost"],
            "p90_token_cost": aggregate["p90_token_cost"],
            **aggregate["localization_metrics"],
        }
        save_patch_progress_summary(output_dir, progress_summary)
    if not serialized_results:
        summary = {
            "method_variant": MethodVariant.PATCH_SEARCH_STRUCTURED.value,
            "strategy": strategy,
            "include_oracle_suffix": include_oracle_suffix,
            "proposer_backend": proposer_backend,
            "model_slug": model_slug,
            "compact_results": compact_results,
            "failure_count": 0,
            "recovered_count": 0,
            "success_recovery_rate": 0.0,
            "total_token_cost": 0,
            "max_evaluations_per_failure": max_evaluations,
            "max_candidates_per_step": max_candidates_per_step,
            "continuation_horizon": continuation_horizon,
            "beam_width": beam_width,
            "evaluated_candidate_count": 0,
            "evaluated_family_counts": {},
            "average_patch_size": 0.0,
            "median_token_cost": 0.0,
            "p90_token_cost": 0.0,
            "known_fault_count": 0,
            "known_fault_recovered_count": 0,
            "localization_top1_accuracy": 0.0,
            "localization_top3_accuracy": 0.0,
            "localization_mrr": 0.0,
            "mean_fault_rank": 0.0,
            "median_fault_rank": 0.0,
            "true_fault_recovery_rate": 0.0,
            "recovered_true_fault_alignment": 0.0,
        }
        write_patch_result_artifacts(output_dir, [], summary)
        return summary
    aggregate = aggregate_patch_result_payloads(serialized_results)
    summary = {
        "method_variant": MethodVariant.PATCH_SEARCH_STRUCTURED.value,
        "strategy": strategy,
        "include_oracle_suffix": include_oracle_suffix,
        "proposer_backend": proposer_backend,
        "model_slug": model_slug,
        "domains": sorted(domain for domain in domains if domain),
        "task_splits": sorted(task_split for task_split in task_splits if task_split),
        "failure_count": aggregate["failure_count"],
        "recovered_count": aggregate["recovered_count"],
        "success_recovery_rate": aggregate["success_recovery_rate"],
        "total_token_cost": aggregate["total_token_cost"],
        "max_evaluations_per_failure": max_evaluations,
        "max_candidates_per_step": max_candidates_per_step,
        "continuation_horizon": continuation_horizon,
        "beam_width": beam_width,
        "evaluated_candidate_count": aggregate["evaluated_candidate_count"],
        "evaluated_family_counts": aggregate["evaluated_family_counts"],
        "compact_results": compact_results,
        "average_patch_size": aggregate["average_patch_size"],
        "median_token_cost": aggregate["median_token_cost"],
        "p90_token_cost": aggregate["p90_token_cost"],
        **aggregate["localization_metrics"],
    }
    write_patch_result_artifacts(output_dir, serialized_results, summary)
    return summary


def run_baselines_cli(
    input_dir: Path,
    output_dir: Path,
    method_variants: list[str],
    strategy: str = "heuristic",
    max_evaluations: int | None = None,
    proposer_backend: str = ProposerBackend.OPENROUTER.value,
    model_slug: str | None = None,
    continuation_horizon: int = 3,
    beam_width: int = 2,
    compact_results: bool = False,
) -> JsonDict:
    budget = BudgetConfig(
        max_evaluations_per_failure=max_evaluations,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
    )
    summaries: list[JsonDict] = []
    for method_variant in method_variants:
        variant_dir = output_dir / method_variant
        variant_dir.mkdir(parents=True, exist_ok=True)
        existing_results = load_serialized_patch_results(variant_dir)
        results_jsonl_path = variant_dir / "patch_results.jsonl"
        if existing_results and not results_jsonl_path.exists():
            write_jsonl(results_jsonl_path, existing_results)
        existing_failure_ids = {
            str(item.get("failure_id"))
            for item in existing_results
            if item.get("failure_id") is not None
        }
        engines: dict[tuple[str, str], RetryBaselineEngine] = {}
        serialized_results: list[JsonDict] = list(existing_results)
        domains: set[str] = {
            extract_result_domain(item) for item in existing_results if extract_result_domain(item)
        }
        task_splits: set[str] = {
            extract_result_task_split(item) for item in existing_results if extract_result_task_split(item)
        }
        for failure in iter_failure_cases_from_dir(input_dir):
            domains.add(failure.domain)
            task_splits.add(failure.task_split)
            if failure.failure_id in existing_failure_ids:
                continue
            engine_key = (failure.domain, failure.task_split)
            if engine_key not in engines:
                adapter = Tau3DomainAdapter(domain=failure.domain, task_split=failure.task_split)
                engines[engine_key] = RetryBaselineEngine(
                    adapter=adapter,
                    proposer_backend=proposer_backend,
                    model_slug=model_slug,
                    budget=budget,
                )
            result = engines[engine_key].run(
                failure=failure,
                method_variant=method_variant,
                strategy=strategy,
                max_evaluations=max_evaluations,
                budget=budget,
            )
            serialized_result = serialize_patch_search_result(result, compact=compact_results)
            serialized_results.append(serialized_result)
            existing_failure_ids.add(failure.failure_id)
            append_jsonl(results_jsonl_path, serialized_result)
            aggregate = aggregate_patch_result_payloads(serialized_results)
            progress_summary = {
                "method_variant": method_variant,
                "strategy": strategy,
                "proposer_backend": proposer_backend,
                "model_slug": model_slug,
                "domains": sorted(domain for domain in domains if domain),
                "task_splits": sorted(task_split for task_split in task_splits if task_split),
                "failure_count": aggregate["failure_count"],
                "recovered_count": aggregate["recovered_count"],
                "success_recovery_rate": aggregate["success_recovery_rate"],
                "total_token_cost": aggregate["total_token_cost"],
                "max_evaluations_per_failure": max_evaluations,
                "continuation_horizon": continuation_horizon,
                "beam_width": beam_width,
                "evaluated_candidate_count": aggregate["evaluated_candidate_count"],
                "evaluated_family_counts": aggregate["evaluated_family_counts"],
                "compact_results": compact_results,
                "average_patch_size": aggregate["average_patch_size"],
                "median_token_cost": aggregate["median_token_cost"],
                "p90_token_cost": aggregate["p90_token_cost"],
                **aggregate["localization_metrics"],
            }
            save_patch_progress_summary(variant_dir, progress_summary)
        if not serialized_results:
            summary = {
                "method_variant": method_variant,
                "strategy": strategy,
                "proposer_backend": proposer_backend,
                "model_slug": model_slug,
                "compact_results": compact_results,
                "failure_count": 0,
                "recovered_count": 0,
                "success_recovery_rate": 0.0,
                "total_token_cost": 0,
                "evaluated_candidate_count": 0,
                "average_patch_size": 0.0,
                "known_fault_count": 0,
                "known_fault_recovered_count": 0,
                "localization_top1_accuracy": 0.0,
                "localization_top3_accuracy": 0.0,
                "localization_mrr": 0.0,
                "mean_fault_rank": 0.0,
                "median_fault_rank": 0.0,
                "true_fault_recovery_rate": 0.0,
                "recovered_true_fault_alignment": 0.0,
            }
            write_patch_result_artifacts(variant_dir, [], summary)
            summaries.append(summary)
            continue
        aggregate = aggregate_patch_result_payloads(serialized_results)
        summary = {
            "method_variant": method_variant,
            "strategy": strategy,
            "proposer_backend": proposer_backend,
            "model_slug": model_slug,
            "domains": sorted(domain for domain in domains if domain),
            "task_splits": sorted(task_split for task_split in task_splits if task_split),
            "failure_count": aggregate["failure_count"],
            "recovered_count": aggregate["recovered_count"],
            "success_recovery_rate": aggregate["success_recovery_rate"],
            "total_token_cost": aggregate["total_token_cost"],
            "max_evaluations_per_failure": max_evaluations,
            "continuation_horizon": continuation_horizon,
            "beam_width": beam_width,
            "evaluated_candidate_count": aggregate["evaluated_candidate_count"],
            "evaluated_family_counts": aggregate["evaluated_family_counts"],
            "compact_results": compact_results,
            "average_patch_size": aggregate["average_patch_size"],
            "median_token_cost": aggregate["median_token_cost"],
            "p90_token_cost": aggregate["p90_token_cost"],
            **aggregate["localization_metrics"],
        }
        write_patch_result_artifacts(variant_dir, serialized_results, summary)
        summaries.append(summary)
    report = {
        "method_variants": method_variants,
        "strategy": strategy,
        "proposer_backend": proposer_backend,
        "model_slug": model_slug,
        "compact_results": compact_results,
        "summaries": summaries,
    }
    save_json(output_dir / "baseline_comparison.json", report)
    return report


def compare_strategies_cli(
    input_dir: Path,
    output_dir: Path,
    strategies: list[str],
    max_evaluations: int | None = None,
    include_oracle_suffix: bool = False,
    proposer_backend: str = ProposerBackend.DETERMINISTIC.value,
    model_slug: str | None = None,
    continuation_horizon: int = 3,
    beam_width: int = 2,
    max_candidates_per_step: int | None = None,
    compact_results: bool = False,
) -> JsonDict:
    strategy_summaries: list[JsonDict] = []
    for strategy in strategies:
        strategy_dir = output_dir / strategy
        summary = search_patches_cli(
            input_dir,
            strategy_dir,
            strategy,
            max_evaluations,
            include_oracle_suffix,
            proposer_backend,
            model_slug,
            continuation_horizon,
            beam_width,
            max_candidates_per_step,
            compact_results,
        )
        strategy_summaries.append(summary)
    best = max(
        strategy_summaries,
        key=lambda item: (
            item["success_recovery_rate"],
            -item["total_token_cost"],
        ),
        default=None,
    )
    report = {
        "strategies": strategies,
        "max_evaluations_per_failure": max_evaluations,
        "include_oracle_suffix": include_oracle_suffix,
        "proposer_backend": proposer_backend,
        "model_slug": model_slug,
        "compact_results": compact_results,
        "best_strategy": best["strategy"] if best else None,
        "summaries": strategy_summaries,
    }
    save_json(output_dir / "strategy_comparison.json", report)
    return report


def build_localization_metrics(payload: list[JsonDict]) -> JsonDict:
    known_fault_count = 0
    known_fault_recovered_count = 0
    top1_hits = 0
    top3_hits = 0
    reciprocal_rank_sum = 0.0
    ranks: list[int] = []
    true_fault_recoveries = 0
    recovered_true_fault_hits = 0
    for item in payload:
        autopsy = item.get("autopsy_report") or {}
        fault_step = autopsy.get("fault_step")
        if fault_step is None:
            continue
        known_fault_count += 1
        localization = item.get("localization") or autopsy.get("localization") or {}
        ranked_steps = localization.get("ranked_steps") or []
        if fault_step in ranked_steps:
            rank = ranked_steps.index(fault_step) + 1
        else:
            rank = max(1, len(ranked_steps)) + 1
        ranks.append(rank)
        reciprocal_rank_sum += 1.0 / rank
        if rank == 1:
            top1_hits += 1
        if rank <= 3:
            top3_hits += 1
        winning_patch = item.get("winning_patch") or {}
        if item.get("recovered"):
            known_fault_recovered_count += 1
            if winning_patch.get("target_step") == fault_step:
                recovered_true_fault_hits += 1
        if winning_patch.get("target_step") == fault_step and item.get("recovered"):
            true_fault_recoveries += 1
    return {
        "known_fault_count": known_fault_count,
        "known_fault_recovered_count": known_fault_recovered_count,
        "localization_top1_accuracy": top1_hits / known_fault_count if known_fault_count else 0.0,
        "localization_top3_accuracy": top3_hits / known_fault_count if known_fault_count else 0.0,
        "localization_mrr": reciprocal_rank_sum / known_fault_count if known_fault_count else 0.0,
        "mean_fault_rank": (
            sum(ranks) / len(ranks)
            if ranks
            else 0.0
        ),
        "median_fault_rank": statistics.median(ranks) if ranks else 0.0,
        "true_fault_recovery_rate": (
            true_fault_recoveries / known_fault_count
            if known_fault_count
            else 0.0
        ),
        "recovered_true_fault_alignment": (
            recovered_true_fault_hits / known_fault_recovered_count
            if known_fault_recovered_count
            else 0.0
        ),
    }


def build_aggregate_autopsy_report(payload: list[JsonDict]) -> JsonDict:
    recovered = [item for item in payload if item["recovered"]]
    patch_sizes = [item["winning_patch"]["size_score"] for item in recovered if item["winning_patch"]]
    token_costs = [item["total_token_cost"] for item in payload]
    family_counts: dict[str, int] = {}
    per_domain: dict[str, dict[str, int]] = {}
    for item in payload:
        family = item["winning_patch"]["patch_family"] if item.get("winning_patch") else "none"
        family_counts[family] = family_counts.get(family, 0) + 1
        domain_bucket = per_domain.setdefault(
            item["autopsy_report"]["domain"],
            {"case_count": 0, "recovered_count": 0},
        )
        domain_bucket["case_count"] += 1
        if item["recovered"]:
            domain_bucket["recovered_count"] += 1
    localization_metrics = build_localization_metrics(payload)
    report = {
        "case_count": len(payload),
        "recovered_count": len(recovered),
        "success_recovery_rate": len(recovered) / len(payload) if payload else 0.0,
        "total_token_cost": sum(item["total_token_cost"] for item in payload),
        "average_patch_size": sum(patch_sizes) / len(patch_sizes) if patch_sizes else 0.0,
        "median_token_cost": statistics.median(token_costs) if token_costs else 0.0,
        "p90_token_cost": percentile(token_costs, 0.9),
        "success_at_k": len(recovered) / len(payload) if payload else 0.0,
        "cost_normalized_recovery": (
            len(recovered) / max(1, sum(item["total_token_cost"] for item in payload))
        ),
        "per_patch_family_recovery": dict(sorted(family_counts.items())),
        "per_domain_recovery": {
            domain: {
                **counts,
                "success_recovery_rate": counts["recovered_count"] / counts["case_count"]
                if counts["case_count"]
                else 0.0,
            }
            for domain, counts in sorted(per_domain.items())
        },
        "localization_metrics": localization_metrics,
        "autopsies": [item["autopsy_report"] for item in payload],
    }
    return report


def report_autopsy_cli(input_dir: Path, output_path: Path) -> JsonDict:
    payload = load_serialized_patch_results(input_dir)
    report = build_aggregate_autopsy_report(payload)
    save_json(output_path, report)
    return report


def make_paper_tables_cli(
    input_dirs: list[Path],
    output_dir: Path,
) -> JsonDict:
    main_rows: list[JsonDict] = []
    patch_family_rows: list[JsonDict] = []
    domain_rows: list[JsonDict] = []
    localization_rows: list[JsonDict] = []
    for input_dir in input_dirs:
        summary_path = input_dir / "patch_summary.json"
        if not summary_path.exists():
            continue
        summary = load_json(summary_path)
        payload = load_serialized_patch_results(input_dir)
        if not payload:
            continue
        aggregate = build_aggregate_autopsy_report(payload)
        label = input_dir.name
        main_rows.append(
            {
                "label": label,
                "method_variant": summary.get(
                    "method_variant", MethodVariant.PATCH_SEARCH_STRUCTURED.value
                ),
                "strategy": summary.get("strategy", ""),
                "proposer_backend": (
                    summary.get("proposer_backend") or ProposerBackend.DETERMINISTIC.value
                ),
                "include_oracle_suffix": summary.get("include_oracle_suffix", False),
                "failure_count": summary.get("failure_count", 0),
                "recovered_count": summary.get("recovered_count", 0),
                "success_recovery_rate": summary.get("success_recovery_rate", 0.0),
                "total_token_cost": summary.get("total_token_cost", 0),
                "median_token_cost": aggregate.get("median_token_cost", 0.0),
                "p90_token_cost": aggregate.get("p90_token_cost", 0.0),
                "average_patch_size": aggregate.get("average_patch_size", 0.0),
                "success_at_k": aggregate.get("success_at_k", 0.0),
                "cost_normalized_recovery": aggregate.get("cost_normalized_recovery", 0.0),
                "evaluated_candidate_count": summary.get("evaluated_candidate_count", 0),
                "continuation_horizon": summary.get("continuation_horizon"),
                "beam_width": summary.get("beam_width"),
            }
        )
        for family, recovered_count in sorted((aggregate.get("per_patch_family_recovery") or {}).items()):
            patch_family_rows.append(
                {
                    "label": label,
                    "patch_family": family,
                    "recovered_count": recovered_count,
                }
            )
        for domain, domain_summary in sorted((aggregate.get("per_domain_recovery") or {}).items()):
            domain_rows.append(
                {
                    "label": label,
                    "domain": domain,
                    "case_count": domain_summary.get("case_count", 0),
                    "recovered_count": domain_summary.get("recovered_count", 0),
                    "success_recovery_rate": domain_summary.get("success_recovery_rate", 0.0),
                }
            )
        localization_summary = aggregate.get("localization_metrics") or {}
        if localization_summary.get("known_fault_count", 0) > 0:
            localization_rows.append(
                {
                    "label": label,
                    "strategy": summary.get("strategy", ""),
                    "known_fault_count": localization_summary.get("known_fault_count", 0),
                    "known_fault_recovered_count": localization_summary.get(
                        "known_fault_recovered_count", 0
                    ),
                    "localization_top1_accuracy": localization_summary.get(
                        "localization_top1_accuracy", 0.0
                    ),
                    "localization_top3_accuracy": localization_summary.get(
                        "localization_top3_accuracy", 0.0
                    ),
                    "localization_mrr": localization_summary.get("localization_mrr", 0.0),
                    "mean_fault_rank": localization_summary.get("mean_fault_rank", 0.0),
                    "median_fault_rank": localization_summary.get("median_fault_rank", 0.0),
                    "true_fault_recovery_rate": localization_summary.get(
                        "true_fault_recovery_rate", 0.0
                    ),
                    "recovered_true_fault_alignment": localization_summary.get(
                        "recovered_true_fault_alignment", 0.0
                    ),
                }
            )
    if main_rows:
        save_csv(output_dir / "main_results.csv", main_rows, list(main_rows[0].keys()))
    if patch_family_rows:
        save_csv(output_dir / "patch_family_results.csv", patch_family_rows, list(patch_family_rows[0].keys()))
    if domain_rows:
        save_csv(output_dir / "domain_results.csv", domain_rows, list(domain_rows[0].keys()))
    if localization_rows:
        save_csv(
            output_dir / "synthetic_localization_results.csv",
            localization_rows,
            list(localization_rows[0].keys()),
        )
    report = {
        "experiment_count": len(main_rows),
        "main_results": main_rows,
        "patch_family_results": patch_family_rows,
        "domain_results": domain_rows,
        "synthetic_localization_results": localization_rows,
    }
    save_json(output_dir / "paper_tables.json", report)
    markdown_lines = [
        "# Paper Tables",
        "",
        "## Main Results",
        "",
        "| label | method_variant | strategy | proposer_backend | include_oracle_suffix | recovered_count | failure_count | success_recovery_rate | total_token_cost | median_token_cost | p90_token_cost | average_patch_size | success_at_k | cost_normalized_recovery |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in main_rows:
        markdown_lines.append(
            f"| {row['label']} | {row['method_variant']} | {row['strategy']} | {row['proposer_backend']} | "
            f"{int(bool(row['include_oracle_suffix']))} | {row['recovered_count']} | {row['failure_count']} | "
            f"{row['success_recovery_rate']:.3f} | {row['total_token_cost']} | {row['median_token_cost']:.1f} | "
            f"{row['p90_token_cost']:.1f} | {row['average_patch_size']:.3f} | {row['success_at_k']:.3f} | "
            f"{row['cost_normalized_recovery']:.6f} |"
        )
    markdown_lines.extend(
        [
            "",
            "## Per-Domain Recovery",
            "",
            "| label | domain | case_count | recovered_count | success_recovery_rate |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in domain_rows:
        markdown_lines.append(
            f"| {row['label']} | {row['domain']} | {row['case_count']} | "
            f"{row['recovered_count']} | {row['success_recovery_rate']:.3f} |"
        )
    markdown_lines.extend(
        [
            "",
            "## Per-Patch-Family Recovery",
            "",
            "| label | patch_family | recovered_count |",
            "| --- | --- | ---: |",
        ]
    )
    for row in patch_family_rows:
        markdown_lines.append(
            f"| {row['label']} | {row['patch_family']} | {row['recovered_count']} |"
        )
    if localization_rows:
        markdown_lines.extend(
            [
                "",
                "## Synthetic Localization",
                "",
                "| label | strategy | known_fault_count | localization_top1_accuracy | localization_top3_accuracy | localization_mrr | mean_fault_rank | median_fault_rank | true_fault_recovery_rate | recovered_true_fault_alignment |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in localization_rows:
            markdown_lines.append(
                f"| {row['label']} | {row['strategy']} | {row['known_fault_count']} | "
                f"{row['localization_top1_accuracy']:.3f} | {row['localization_top3_accuracy']:.3f} | "
                f"{row['localization_mrr']:.3f} | {row['mean_fault_rank']:.3f} | "
                f"{row['median_fault_rank']:.3f} | {row['true_fault_recovery_rate']:.3f} | "
                f"{row['recovered_true_fault_alignment']:.3f} |"
            )
    (output_dir / "paper_tables.md").parent.mkdir(parents=True, exist_ok=True)
    with (output_dir / "paper_tables.md").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(markdown_lines) + "\n")
    return report


def make_paper_bundle_cli(
    name: str,
    domain_specs: list[str],
    limit_per_domain: int,
    output_dir: Path,
    strict_strategy: str = "heuristic",
    strict_max_evaluations: int | None = None,
    oracle_max_evaluations: int | None = None,
    continuation_horizon: int = 3,
    beam_width: int = 2,
    max_candidates_per_step: int | None = None,
    proposer_backend: str = ProposerBackend.DETERMINISTIC.value,
    model_slug: str | None = None,
    compact_results: bool = True,
) -> JsonDict:
    corpus_dir = output_dir / "corpus"
    strict_dir = output_dir / "strict_search"
    oracle_dir = output_dir / "oracle_upper_bound"
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "paper_tables"
    strict_autopsy_path = output_dir / "strict_autopsy_report.json"
    oracle_autopsy_path = output_dir / "oracle_autopsy_report.json"

    corpus_summary = build_corpus_cli(name, domain_specs, limit_per_domain, corpus_dir)
    strict_summary = search_patches_cli(
        input_dir=corpus_dir,
        output_dir=strict_dir,
        strategy=strict_strategy,
        max_evaluations=strict_max_evaluations,
        include_oracle_suffix=False,
        proposer_backend=proposer_backend,
        model_slug=model_slug,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
        max_candidates_per_step=max_candidates_per_step,
        compact_results=compact_results,
    )
    strict_autopsy = report_autopsy_cli(strict_dir, strict_autopsy_path)
    oracle_summary = search_patches_cli(
        input_dir=corpus_dir,
        output_dir=oracle_dir,
        strategy=strict_strategy,
        max_evaluations=oracle_max_evaluations,
        include_oracle_suffix=True,
        proposer_backend=proposer_backend,
        model_slug=model_slug,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
        max_candidates_per_step=max_candidates_per_step,
        compact_results=compact_results,
    )
    oracle_autopsy = report_autopsy_cli(oracle_dir, oracle_autopsy_path)
    figure_report = make_figures_cli([strict_dir, oracle_dir], figures_dir)
    table_report = make_paper_tables_cli([strict_dir, oracle_dir], tables_dir)

    bundle_report = {
        "name": name,
        "domain_specs": domain_specs,
        "limit_per_domain": limit_per_domain,
        "strict_strategy": strict_strategy,
        "strict_max_evaluations": strict_max_evaluations,
        "oracle_max_evaluations": oracle_max_evaluations,
        "continuation_horizon": continuation_horizon,
        "beam_width": beam_width,
        "max_candidates_per_step": max_candidates_per_step,
        "proposer_backend": proposer_backend,
        "model_slug": model_slug,
        "compact_results": compact_results,
        "corpus_summary": corpus_summary,
        "strict_summary": strict_summary,
        "strict_autopsy": strict_autopsy,
        "oracle_summary": oracle_summary,
        "oracle_autopsy": oracle_autopsy,
        "figure_report": figure_report,
        "table_report": table_report,
        "paths": {
            "corpus_dir": str(corpus_dir),
            "strict_dir": str(strict_dir),
            "oracle_dir": str(oracle_dir),
            "figures_dir": str(figures_dir),
            "tables_dir": str(tables_dir),
            "strict_autopsy_path": str(strict_autopsy_path),
            "oracle_autopsy_path": str(oracle_autopsy_path),
        },
    }
    save_json(output_dir / "paper_bundle_summary.json", bundle_report)
    return bundle_report


def make_workshop_bundle_cli(
    name: str,
    natural_domain_specs: list[str],
    natural_limit_per_domain: int,
    synthetic_domains: list[str],
    synthetic_limit_per_domain: int,
    output_dir: Path,
    strict_strategy: str = "heuristic",
    strict_max_evaluations: int | None = None,
    oracle_max_evaluations: int | None = None,
    retry_method_variants: list[str] | None = None,
    retry_proposer_backend: str = ProposerBackend.OPENROUTER.value,
    retry_model_slug: str | None = None,
    continuation_horizon: int = 3,
    beam_width: int = 2,
    max_candidates_per_step: int | None = None,
    compact_results: bool = True,
) -> JsonDict:
    retry_variants = retry_method_variants or [
        MethodVariant.RETRY_FROM_SCRATCH.value,
        MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
        MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value,
    ]
    natural_corpus_dir = output_dir / "natural_corpus"
    synthetic_corpus_dir = output_dir / "synthetic_corpus"
    strict_dir = output_dir / "strict_search"
    oracle_dir = output_dir / "oracle_upper_bound"
    retry_dir = output_dir / "retry_baselines"
    synthetic_compare_dir = output_dir / "synthetic_strategy_comparison"
    budget_dir = output_dir / "budget_sweep"
    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "paper_tables"
    case_dir = output_dir / "case_studies"
    guide_dir = output_dir / "reviewer_artifact_guide"
    strict_autopsy_path = output_dir / "strict_autopsy_report.json"
    oracle_autopsy_path = output_dir / "oracle_autopsy_report.json"

    natural_corpus_summary = build_corpus_cli(
        name=f"{name}_natural",
        domain_specs=natural_domain_specs,
        limit_per_domain=natural_limit_per_domain,
        output_dir=natural_corpus_dir,
    )
    synthetic_corpus_summary = build_synthetic_corpus_cli(
        name=f"{name}_synthetic",
        domains=synthetic_domains,
        limit_per_domain=synthetic_limit_per_domain,
        output_dir=synthetic_corpus_dir,
    )
    strict_summary = search_patches_cli(
        input_dir=natural_corpus_dir,
        output_dir=strict_dir,
        strategy=strict_strategy,
        max_evaluations=strict_max_evaluations,
        include_oracle_suffix=False,
        proposer_backend=ProposerBackend.DETERMINISTIC.value,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
        max_candidates_per_step=max_candidates_per_step,
        compact_results=compact_results,
    )
    strict_autopsy = report_autopsy_cli(strict_dir, strict_autopsy_path)
    baseline_report = run_baselines_cli(
        input_dir=natural_corpus_dir,
        output_dir=retry_dir,
        method_variants=retry_variants,
        strategy=strict_strategy,
        max_evaluations=strict_max_evaluations,
        proposer_backend=retry_proposer_backend,
        model_slug=retry_model_slug,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
        compact_results=compact_results,
    )
    oracle_summary = search_patches_cli(
        input_dir=natural_corpus_dir,
        output_dir=oracle_dir,
        strategy=strict_strategy,
        max_evaluations=oracle_max_evaluations,
        include_oracle_suffix=True,
        proposer_backend=ProposerBackend.DETERMINISTIC.value,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
        max_candidates_per_step=max_candidates_per_step,
        compact_results=compact_results,
    )
    oracle_autopsy = report_autopsy_cli(oracle_dir, oracle_autopsy_path)
    synthetic_report = compare_strategies_cli(
        input_dir=synthetic_corpus_dir,
        output_dir=synthetic_compare_dir,
        strategies=[
            "heuristic",
            "reverse",
            "chronological",
            "latest_only",
            "oracle_fault_step",
            "random_candidate",
            "no_repair",
        ],
        max_evaluations=strict_max_evaluations,
        proposer_backend=ProposerBackend.DETERMINISTIC.value,
        continuation_horizon=continuation_horizon,
        beam_width=beam_width,
        max_candidates_per_step=max_candidates_per_step,
        compact_results=compact_results,
    )
    budget_report = sweep_budget_cli(
        input_dir=natural_corpus_dir,
        output_dir=budget_dir,
        strategy=strict_strategy,
        evaluation_budgets=[1, 2, 4],
        proposer_backend=ProposerBackend.DETERMINISTIC.value,
        compact_results=compact_results,
    )
    figure_inputs = [strict_dir, oracle_dir]
    figure_inputs.extend(retry_dir / item for item in retry_variants)
    figure_inputs.extend(
        synthetic_compare_dir / item
        for item in [
            "heuristic",
            "reverse",
            "chronological",
            "latest_only",
            "oracle_fault_step",
            "random_candidate",
            "no_repair",
        ]
    )
    figure_report = make_figures_cli(figure_inputs, figures_dir)
    table_report = make_paper_tables_cli(figure_inputs, tables_dir)
    case_report = make_case_studies_cli(
        input_paths=[strict_autopsy_path],
        output_dir=case_dir,
        title="Workshop Case Studies",
        max_cases=3,
    )
    artifact_guide = make_artifact_guide_cli(
        input_dirs=[strict_dir, oracle_dir, retry_dir, synthetic_compare_dir, tables_dir, case_dir],
        output_dir=guide_dir,
        title="Workshop Reviewer Artifact Guide",
        paper_draft_path=Path("paper/paper_draft.md"),
        checklist_path=Path("paper/submission_checklist.md"),
    )
    release_lines = [
        "# Workshop Release",
        "",
        f"- Title: `Execution Intervention for Post-Hoc Debugging of LLM Agent Trajectories`",
        f"- Natural corpus entries: `{natural_corpus_summary['entry_count']}`",
        f"- Synthetic corpus entries: `{synthetic_corpus_summary['entry_count']}`",
        f"- Strict natural recovery: `{strict_summary['recovered_count']} / {strict_summary['failure_count']}`",
        f"- Oracle natural recovery: `{oracle_summary['recovered_count']} / {oracle_summary['failure_count']}`",
        f"- Retry baselines: `{retry_variants}`",
        "",
        "## Artifact Map",
        "",
        f"- Natural corpus: `{natural_corpus_dir}`",
        f"- Synthetic corpus: `{synthetic_corpus_dir}`",
        f"- Strict search: `{strict_dir}`",
        f"- Oracle upper bound: `{oracle_dir}`",
        f"- Retry baselines: `{retry_dir}`",
        f"- Synthetic comparison: `{synthetic_compare_dir}`",
        f"- Budget sweep: `{budget_dir}`",
        f"- Paper tables: `{tables_dir}`",
        f"- Case studies: `{case_dir}`",
        f"- Reviewer guide: `{guide_dir}`",
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "WORKSHOP_RELEASE.md").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(release_lines) + "\n")
    report = {
        "name": name,
        "title": "Execution Intervention for Post-Hoc Debugging of LLM Agent Trajectories",
        "natural_domain_specs": natural_domain_specs,
        "natural_limit_per_domain": natural_limit_per_domain,
        "synthetic_domains": synthetic_domains,
        "synthetic_limit_per_domain": synthetic_limit_per_domain,
        "strict_strategy": strict_strategy,
        "strict_max_evaluations": strict_max_evaluations,
        "oracle_max_evaluations": oracle_max_evaluations,
        "retry_method_variants": retry_variants,
        "retry_proposer_backend": retry_proposer_backend,
        "retry_model_slug": retry_model_slug,
        "continuation_horizon": continuation_horizon,
        "beam_width": beam_width,
        "max_candidates_per_step": max_candidates_per_step,
        "compact_results": compact_results,
        "natural_corpus_summary": natural_corpus_summary,
        "synthetic_corpus_summary": synthetic_corpus_summary,
        "strict_summary": strict_summary,
        "strict_autopsy": strict_autopsy,
        "baseline_report": baseline_report,
        "oracle_summary": oracle_summary,
        "oracle_autopsy": oracle_autopsy,
        "synthetic_report": synthetic_report,
        "budget_report": budget_report,
        "figure_report": figure_report,
        "table_report": table_report,
        "case_report": case_report,
        "artifact_guide": artifact_guide,
        "paths": {
            "natural_corpus_dir": str(natural_corpus_dir),
            "synthetic_corpus_dir": str(synthetic_corpus_dir),
            "strict_dir": str(strict_dir),
            "retry_dir": str(retry_dir),
            "oracle_dir": str(oracle_dir),
            "synthetic_compare_dir": str(synthetic_compare_dir),
            "budget_dir": str(budget_dir),
            "figures_dir": str(figures_dir),
            "tables_dir": str(tables_dir),
            "case_dir": str(case_dir),
            "guide_dir": str(guide_dir),
            "strict_autopsy_path": str(strict_autopsy_path),
            "oracle_autopsy_path": str(oracle_autopsy_path),
            "workshop_release_path": str(output_dir / "WORKSHOP_RELEASE.md"),
        },
    }
    save_json(output_dir / "workshop_bundle_summary.json", report)
    return report


def run_batch_cli(
    config_path: Path,
    output_dir: Path | None = None,
) -> JsonDict:
    payload = load_json(config_path)
    budget_payload = payload.get("budget") or {}
    budget = BudgetConfig(**budget_payload)
    config = ExperimentConfig(
        name=payload["name"],
        input_dir=payload["input_dir"],
        output_dir=payload["output_dir"],
        method_variant=payload.get(
            "method_variant", MethodVariant.PATCH_SEARCH_STRUCTURED.value
        ),
        strategy=payload.get("strategy", "heuristic"),
        include_oracle_suffix=payload.get("include_oracle_suffix", False),
        proposer_backend=payload.get("proposer_backend", ProposerBackend.DETERMINISTIC.value),
        model_slug=payload.get("model_slug"),
        compact_results=payload.get("compact_results", False),
        budget=budget,
    )
    target_output_dir = output_dir or Path(config.output_dir)
    if config.method_variant == MethodVariant.PATCH_SEARCH_STRUCTURED.value:
        summary = search_patches_cli(
            input_dir=Path(config.input_dir),
            output_dir=target_output_dir,
            strategy=config.strategy,
            max_evaluations=config.budget.max_evaluations_per_failure,
            include_oracle_suffix=config.include_oracle_suffix,
            proposer_backend=config.proposer_backend,
            model_slug=config.model_slug,
            continuation_horizon=config.budget.continuation_horizon,
            beam_width=config.budget.beam_width,
            max_candidates_per_step=config.budget.max_candidates_per_step,
            compact_results=config.compact_results,
        )
    else:
        baseline_report = run_baselines_cli(
            input_dir=Path(config.input_dir),
            output_dir=target_output_dir,
            method_variants=[config.method_variant],
            strategy=config.strategy,
            max_evaluations=config.budget.max_evaluations_per_failure,
            proposer_backend=config.proposer_backend,
            model_slug=config.model_slug,
            continuation_horizon=config.budget.continuation_horizon,
            beam_width=config.budget.beam_width,
            compact_results=config.compact_results,
        )
        summary = baseline_report["summaries"][0]
    save_json(target_output_dir / "experiment_config.json", config)
    return summary


def sweep_budget_cli(
    input_dir: Path,
    output_dir: Path,
    strategy: str,
    evaluation_budgets: list[int],
    proposer_backend: str = ProposerBackend.DETERMINISTIC.value,
    model_slug: str | None = None,
    compact_results: bool = False,
) -> JsonDict:
    rows: list[JsonDict] = []
    for budget_value in evaluation_budgets:
        budget_dir = output_dir / f"budget_{budget_value}"
        summary = search_patches_cli(
            input_dir=input_dir,
            output_dir=budget_dir,
            strategy=strategy,
            max_evaluations=budget_value,
            include_oracle_suffix=False,
            proposer_backend=proposer_backend,
            model_slug=model_slug,
            compact_results=compact_results,
        )
        rows.append(
            {
                "max_evaluations": budget_value,
                "success_recovery_rate": summary["success_recovery_rate"],
                "total_token_cost": summary["total_token_cost"],
                "average_patch_size": summary["average_patch_size"],
            }
        )
    save_json(output_dir / "budget_sweep.json", rows)
    if rows:
        save_csv(output_dir / "budget_sweep.csv", rows, list(rows[0].keys()))
    return {
        "strategy": strategy,
        "proposer_backend": proposer_backend,
        "compact_results": compact_results,
        "points": rows,
    }


def sweep_models_cli(
    input_dir: Path,
    output_dir: Path,
    strategy: str,
    model_slugs: list[str],
    max_evaluations: int | None = None,
    compact_results: bool = False,
) -> JsonDict:
    rows: list[JsonDict] = []
    for model_slug in model_slugs:
        model_dir = output_dir / model_slug.replace("/", "_").replace(":", "_")
        summary = search_patches_cli(
            input_dir=input_dir,
            output_dir=model_dir,
            strategy=strategy,
            max_evaluations=max_evaluations,
            proposer_backend=ProposerBackend.OPENROUTER.value,
            model_slug=model_slug,
            compact_results=compact_results,
        )
        rows.append(
            {
                "model_slug": model_slug,
                "success_recovery_rate": summary["success_recovery_rate"],
                "total_token_cost": summary["total_token_cost"],
                "evaluated_candidate_count": summary["evaluated_candidate_count"],
            }
        )
    save_json(output_dir / "model_sweep.json", rows)
    if rows:
        save_csv(output_dir / "model_sweep.csv", rows, list(rows[0].keys()))
    return {
        "strategy": strategy,
        "compact_results": compact_results,
        "models": rows,
    }


def make_figures_cli(
    input_dirs: list[Path],
    output_dir: Path,
) -> JsonDict:
    rows: list[JsonDict] = []
    for input_dir in input_dirs:
        summary_path = input_dir / "patch_summary.json"
        if not summary_path.exists():
            continue
        summary = load_json(summary_path)
        rows.append(
            {
                "label": input_dir.name,
                "method_variant": summary.get(
                    "method_variant", MethodVariant.PATCH_SEARCH_STRUCTURED.value
                ),
                "success_recovery_rate": summary.get("success_recovery_rate", 0.0),
                "total_token_cost": summary.get("total_token_cost", 0),
                "average_patch_size": summary.get("average_patch_size", 0.0),
                "known_fault_count": summary.get("known_fault_count", 0),
                "localization_top1_accuracy": summary.get("localization_top1_accuracy", 0.0),
                "localization_mrr": summary.get("localization_mrr", 0.0),
                "true_fault_recovery_rate": summary.get("true_fault_recovery_rate", 0.0),
            }
        )
    if rows:
        save_csv(output_dir / "figure_data.csv", rows, list(rows[0].keys()))
    markdown_lines = [
        "# Paper Figure Data",
        "",
        "| label | method_variant | success_recovery_rate | total_token_cost | average_patch_size | known_fault_count | localization_top1_accuracy | localization_mrr | true_fault_recovery_rate |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        markdown_lines.append(
            f"| {row['label']} | {row['method_variant']} | {row['success_recovery_rate']:.3f} | "
            f"{row['total_token_cost']} | {row['average_patch_size']:.3f} | "
            f"{row['known_fault_count']} | {row['localization_top1_accuracy']:.3f} | "
            f"{row['localization_mrr']:.3f} | {row['true_fault_recovery_rate']:.3f} |"
        )
    (output_dir / "figure_report.md").parent.mkdir(parents=True, exist_ok=True)
    with (output_dir / "figure_report.md").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(markdown_lines) + "\n")
    return {"figure_count": len(rows), "output_dir": str(output_dir)}


def maybe_distribution_version(distribution_name: str) -> str | None:
    try:
        return importlib_metadata.version(distribution_name)
    except importlib_metadata.PackageNotFoundError:
        return None


def build_environment_manifest() -> JsonDict:
    selected_distributions = {}
    for name in SELECTED_DISTRIBUTION_NAMES:
        version = maybe_distribution_version(name)
        if version is not None:
            selected_distributions[name] = version
    return {
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "cwd": str(Path.cwd()),
        "selected_distributions": selected_distributions,
    }


def _artifact_entry_paths(input_dir: Path) -> list[str]:
    candidates = [
        "workshop_bundle_summary.json",
        "WORKSHOP_RELEASE.md",
        "paper_bundle_summary.json",
        "baseline_comparison.json",
        "strategy_comparison.json",
        "corpus_manifest.json",
        "summary.json",
        "failures_manifest.json",
        "failures.jsonl",
        "patch_summary.json",
        "patch_summary.progress.json",
        "patch_results_manifest.json",
        "patch_results.jsonl",
        "paper_tables.json",
        "paper_tables.md",
        "figure_data.csv",
        "figure_report.md",
        "strict_autopsy_report.json",
        "oracle_autopsy_report.json",
        "case_studies.json",
        "case_studies.md",
        "dependency_snapshot.json",
        "requirements-lock.txt",
        "requirements-selected.txt",
        "REPRODUCIBILITY.md",
    ]
    return [item for item in candidates if (input_dir / item).exists()]


def summarize_artifact_dir(input_dir: Path) -> JsonDict:
    entry: JsonDict = {
        "label": input_dir.name,
        "path": str(input_dir),
        "available_files": _artifact_entry_paths(input_dir),
    }
    workshop_summary_path = input_dir / "workshop_bundle_summary.json"
    bundle_summary_path = input_dir / "paper_bundle_summary.json"
    baseline_report_path = input_dir / "baseline_comparison.json"
    strategy_report_path = input_dir / "strategy_comparison.json"
    corpus_manifest_path = input_dir / "corpus_manifest.json"
    corpus_summary_path = input_dir / "summary.json"
    patch_summary_path = input_dir / "patch_summary.json"
    paper_tables_path = input_dir / "paper_tables.json"

    if workshop_summary_path.exists():
        payload = load_json(workshop_summary_path)
        entry.update(
            {
                "artifact_type": "workshop_bundle",
                "title": payload.get("title", ""),
                "natural_entry_count": payload.get("natural_corpus_summary", {}).get("entry_count", 0),
                "synthetic_entry_count": payload.get("synthetic_corpus_summary", {}).get("entry_count", 0),
                "strict_success_recovery_rate": payload.get("strict_summary", {}).get(
                    "success_recovery_rate", 0.0
                ),
                "oracle_success_recovery_rate": payload.get("oracle_summary", {}).get(
                    "success_recovery_rate", 0.0
                ),
                "retry_method_variants": payload.get("retry_method_variants", []),
            }
        )
        return entry

    if bundle_summary_path.exists():
        payload = load_json(bundle_summary_path)
        entry.update(
            {
                "artifact_type": "paper_bundle",
                "domains": payload.get("corpus_summary", {}).get("domains", []),
                "entry_count": payload.get("corpus_summary", {}).get("entry_count", 0),
                "strict_success_recovery_rate": payload.get("strict_summary", {}).get(
                    "success_recovery_rate", 0.0
                ),
                "oracle_success_recovery_rate": payload.get("oracle_summary", {}).get(
                    "success_recovery_rate", 0.0
                ),
                "strict_recovered_count": payload.get("strict_summary", {}).get(
                    "recovered_count", 0
                ),
                "oracle_recovered_count": payload.get("oracle_summary", {}).get(
                    "recovered_count", 0
                ),
                "figure_count": payload.get("figure_report", {}).get("figure_count", 0),
                "table_experiment_count": payload.get("table_report", {}).get(
                    "experiment_count", 0
                ),
            }
        )
        return entry

    if baseline_report_path.exists():
        payload = load_json(baseline_report_path)
        summaries = payload.get("summaries", [])
        entry.update(
            {
                "artifact_type": "baseline_comparison",
                "method_variants": payload.get("method_variants", []),
                "summary_count": len(summaries),
                "best_success_recovery_rate": max(
                    (item.get("success_recovery_rate", 0.0) for item in summaries),
                    default=0.0,
                ),
                "total_token_cost": sum(item.get("total_token_cost", 0) for item in summaries),
            }
        )
        return entry

    if strategy_report_path.exists():
        payload = load_json(strategy_report_path)
        summaries = payload.get("summaries", [])
        entry.update(
            {
                "artifact_type": "strategy_comparison",
                "strategies": payload.get("strategies", []),
                "summary_count": len(summaries),
                "best_strategy": payload.get("best_strategy"),
                "best_success_recovery_rate": max(
                    (item.get("success_recovery_rate", 0.0) for item in summaries),
                    default=0.0,
                ),
            }
        )
        return entry

    if corpus_manifest_path.exists():
        payload = load_json(corpus_manifest_path)
        summary_payload = load_json(corpus_summary_path) if corpus_summary_path.exists() else {}
        entry.update(
            {
                "artifact_type": "corpus_manifest",
                "name": payload.get("name", summary_payload.get("name", "")),
                "domains": payload.get("domains", summary_payload.get("domains", [])),
                "entry_count": payload.get("entry_count", summary_payload.get("entry_count", 0)),
                "split_counts": payload.get("split_counts", summary_payload.get("split_counts", {})),
            }
        )
        return entry

    if patch_summary_path.exists():
        payload = load_json(patch_summary_path)
        entry.update(
            {
                "artifact_type": "patch_run",
                "method_variant": payload.get(
                    "method_variant", MethodVariant.PATCH_SEARCH_STRUCTURED.value
                ),
                "strategy": payload.get("strategy", ""),
                "proposer_backend": payload.get(
                    "proposer_backend", ProposerBackend.DETERMINISTIC.value
                ),
                "model_slug": payload.get("model_slug"),
                "include_oracle_suffix": payload.get("include_oracle_suffix", False),
                "failure_count": payload.get("failure_count", 0),
                "recovered_count": payload.get("recovered_count", 0),
                "success_recovery_rate": payload.get("success_recovery_rate", 0.0),
                "total_token_cost": payload.get("total_token_cost", 0),
                "evaluated_candidate_count": payload.get("evaluated_candidate_count", 0),
                "average_patch_size": payload.get("average_patch_size", 0.0),
                "known_fault_count": payload.get("known_fault_count", 0),
                "localization_top1_accuracy": payload.get(
                    "localization_top1_accuracy", 0.0
                ),
                "localization_mrr": payload.get("localization_mrr", 0.0),
            }
        )
        return entry

    if paper_tables_path.exists():
        payload = load_json(paper_tables_path)
        entry.update(
            {
                "artifact_type": "paper_tables",
                "experiment_count": payload.get("experiment_count", 0),
                "main_result_count": len(payload.get("main_results", [])),
                "domain_result_count": len(payload.get("domain_results", [])),
                "patch_family_result_count": len(payload.get("patch_family_results", [])),
                "synthetic_localization_result_count": len(
                    payload.get("synthetic_localization_results", [])
                ),
            }
        )
        return entry

    if (input_dir / "figure_data.csv").exists() or (input_dir / "figure_report.md").exists():
        entry.update(
            {
                "artifact_type": "figure_data",
                "has_csv": (input_dir / "figure_data.csv").exists(),
                "has_markdown_report": (input_dir / "figure_report.md").exists(),
            }
        )
        return entry

    case_studies_path = input_dir / "case_studies.json"
    if case_studies_path.exists():
        payload = load_json(case_studies_path)
        entry.update(
            {
                "artifact_type": "case_studies",
                "selected_case_count": payload.get("selected_case_count", 0),
                "recovered_case_count": payload.get("recovered_case_count", 0),
                "source_count": len(payload.get("input_paths", [])),
            }
        )
        return entry

    dependency_snapshot_path = input_dir / "dependency_snapshot.json"
    if dependency_snapshot_path.exists() or (input_dir / "requirements-lock.txt").exists():
        payload = load_json(dependency_snapshot_path) if dependency_snapshot_path.exists() else {}
        entry.update(
            {
                "artifact_type": "dependency_snapshot",
                "distribution_count": payload.get("distribution_count", 0),
                "selected_distribution_count": len(
                    (payload.get("environment") or {}).get("selected_distributions", {})
                ),
                "upstream_lockfile_count": len(payload.get("upstream_lockfiles", [])),
            }
        )
        return entry

    entry["artifact_type"] = "unknown"
    return entry


def make_artifact_guide_cli(
    input_dirs: list[Path],
    output_dir: Path,
    title: str = "Artifact Guide",
    include_environment: bool = True,
    paper_draft_path: Path | None = None,
    checklist_path: Path | None = None,
) -> JsonDict:
    entries = [summarize_artifact_dir(item) for item in input_dirs]
    manifest = {
        "title": title,
        "entry_count": len(entries),
        "input_dirs": [str(item) for item in input_dirs],
        "paper_draft_path": str(paper_draft_path) if paper_draft_path else None,
        "checklist_path": str(checklist_path) if checklist_path else None,
        "environment": build_environment_manifest() if include_environment else None,
        "artifacts": entries,
    }
    save_json(output_dir / "artifact_manifest.json", manifest)

    markdown_lines = [
        f"# {title}",
        "",
        "This guide maps saved experiment artifacts to their current role in the paper pipeline.",
    ]
    if paper_draft_path:
        markdown_lines.append(f"- Paper draft: `{paper_draft_path}`")
    if checklist_path:
        markdown_lines.append(f"- Submission checklist: `{checklist_path}`")
    if include_environment:
        environment = manifest["environment"] or {}
        markdown_lines.extend(
            [
                "",
                "## Environment",
                "",
                f"- Python: `{environment.get('python_version', 'unknown')}`",
                f"- Platform: `{environment.get('platform', 'unknown')}`",
                f"- Working directory: `{environment.get('cwd', 'unknown')}`",
            ]
        )
        distributions = environment.get("selected_distributions") or {}
        if distributions:
            markdown_lines.append("- Selected distributions:")
            for name, version in sorted(distributions.items()):
                markdown_lines.append(f"  - `{name}=={version}`")
    markdown_lines.extend(["", "## Artifact Entries", ""])
    for entry in entries:
        markdown_lines.extend(
            [
                f"### {entry['label']}",
                "",
                f"- Type: `{entry['artifact_type']}`",
                f"- Path: `{entry['path']}`",
            ]
        )
        if entry["artifact_type"] == "paper_bundle":
            markdown_lines.extend(
                [
                    f"- Domains: `{entry.get('domains', [])}`",
                    f"- Corpus entry count: `{entry.get('entry_count', 0)}`",
                    f"- Strict SRR: `{entry.get('strict_success_recovery_rate', 0.0)}`",
                    f"- Oracle SRR: `{entry.get('oracle_success_recovery_rate', 0.0)}`",
                ]
            )
        elif entry["artifact_type"] == "patch_run":
            markdown_lines.extend(
                [
                    f"- Strategy: `{entry.get('strategy', '')}`",
                    f"- Recovered / failures: `{entry.get('recovered_count', 0)} / {entry.get('failure_count', 0)}`",
                    f"- Success recovery rate: `{entry.get('success_recovery_rate', 0.0)}`",
                    f"- Total token cost: `{entry.get('total_token_cost', 0)}`",
                ]
            )
            if entry.get("known_fault_count", 0):
                markdown_lines.extend(
                    [
                        f"- Known fault count: `{entry.get('known_fault_count', 0)}`",
                        f"- Localization top-1: `{entry.get('localization_top1_accuracy', 0.0)}`",
                        f"- Localization MRR: `{entry.get('localization_mrr', 0.0)}`",
                    ]
                )
        elif entry["artifact_type"] == "paper_tables":
            markdown_lines.extend(
                [
                    f"- Experiment count: `{entry.get('experiment_count', 0)}`",
                    f"- Main result rows: `{entry.get('main_result_count', 0)}`",
                    f"- Synthetic localization rows: `{entry.get('synthetic_localization_result_count', 0)}`",
                ]
            )
        elif entry["artifact_type"] == "figure_data":
            markdown_lines.extend(
                [
                    f"- Has CSV: `{entry.get('has_csv', False)}`",
                    f"- Has markdown report: `{entry.get('has_markdown_report', False)}`",
                ]
            )
        elif entry["artifact_type"] == "case_studies":
            markdown_lines.extend(
                [
                    f"- Selected case count: `{entry.get('selected_case_count', 0)}`",
                    f"- Recovered case count: `{entry.get('recovered_case_count', 0)}`",
                    f"- Source artifact count: `{entry.get('source_count', 0)}`",
                ]
            )
        elif entry["artifact_type"] == "dependency_snapshot":
            markdown_lines.extend(
                [
                    f"- Distribution count: `{entry.get('distribution_count', 0)}`",
                    f"- Selected distribution count: `{entry.get('selected_distribution_count', 0)}`",
                    f"- Upstream lockfile count: `{entry.get('upstream_lockfile_count', 0)}`",
                ]
            )
        available_files = entry.get("available_files") or []
        if available_files:
            markdown_lines.append("- Available files:")
            for file_name in available_files:
                markdown_lines.append(f"  - `{file_name}`")
        markdown_lines.append("")
    with (output_dir / "ARTIFACT_README.md").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(markdown_lines) + "\n")
    return {
        "title": title,
        "entry_count": len(entries),
        "output_dir": str(output_dir),
        "manifest_path": str(output_dir / "artifact_manifest.json"),
        "readme_path": str(output_dir / "ARTIFACT_README.md"),
    }


def resolve_autopsy_input_path(input_path: Path) -> Path:
    if input_path.is_file():
        return input_path
    candidates = [
        input_path / "strict_autopsy_report.json",
        input_path / "oracle_autopsy_report.json",
        input_path / "autopsy_report.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Could not find an autopsy report under {input_path}")


def load_autopsy_cases(input_paths: list[Path]) -> tuple[list[JsonDict], list[str]]:
    cases: list[JsonDict] = []
    resolved_paths: list[str] = []
    seen_signatures: set[tuple[str, bool, str, str]] = set()
    for input_path in input_paths:
        resolved = resolve_autopsy_input_path(input_path)
        resolved_paths.append(str(resolved))
        payload = load_json(resolved)
        autopsies: list[JsonDict]
        if isinstance(payload, dict) and "autopsies" in payload:
            autopsies = payload.get("autopsies", [])
        elif isinstance(payload, list):
            autopsies = [
                item["autopsy_report"]
                for item in payload
                if isinstance(item, dict) and isinstance(item.get("autopsy_report"), dict)
            ]
        else:
            raise ValueError(f"Unsupported autopsy payload at {resolved}")
        for index, case in enumerate(autopsies):
            enriched = copy.deepcopy(case)
            enriched["artifact_source_path"] = str(resolved)
            enriched["source_index"] = index
            if not enriched.get("benchmark_source_path"):
                enriched["benchmark_source_path"] = (
                    enriched.get("source_metadata", {}).get("results_path")
                    or enriched.get("source_path")
                    or ""
                )
            signature = (
                str(enriched.get("failure_id", "")),
                bool(enriched.get("recovered", False)),
                str(enriched.get("patch_family") or "none"),
                str(enriched.get("continuation_mode") or ""),
            )
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            cases.append(enriched)
    return cases, resolved_paths


def _case_sort_key(case: JsonDict) -> tuple[int, str, int, int, str]:
    return (
        0 if case.get("recovered") else 1,
        str(case.get("domain", "")),
        int(case.get("patch_size") or 0),
        int(case.get("total_token_cost") or 0),
        str(case.get("failure_id", "")),
    )


def _case_feature_items(case: JsonDict) -> tuple[tuple[str, str], ...]:
    return (
        ("domain", str(case.get("domain", ""))),
        ("patch_family", str(case.get("patch_family") or "none")),
        ("continuation_mode", str(case.get("continuation_mode") or "")),
        ("artifact_source_path", str(case.get("artifact_source_path") or "")),
    )


def select_case_studies(cases: list[JsonDict], max_cases: int) -> list[JsonDict]:
    if max_cases <= 0:
        return []
    ordered = sorted(cases, key=_case_sort_key)
    if len(ordered) <= max_cases:
        return ordered

    feature_counts: dict[tuple[str, str], int] = {}
    for case in ordered:
        for feature in _case_feature_items(case):
            feature_counts[feature] = feature_counts.get(feature, 0) + 1

    selected: list[JsonDict] = []
    remaining = ordered[:]
    covered: set[tuple[str, str]] = set()
    while remaining and len(selected) < max_cases:
        best_index = 0
        best_gain = -1
        best_rarity = -1.0
        best_key = _case_sort_key(remaining[0])
        for index, case in enumerate(remaining):
            new_features = [
                feature for feature in _case_feature_items(case) if feature not in covered
            ]
            gain = len(new_features)
            rarity = sum(1.0 / feature_counts[feature] for feature in new_features)
            case_key = _case_sort_key(case)
            if (
                gain > best_gain
                or (gain == best_gain and rarity > best_rarity)
                or (gain == best_gain and rarity == best_rarity and case_key < best_key)
            ):
                best_index = index
                best_gain = gain
                best_rarity = rarity
                best_key = case_key
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        covered.update(_case_feature_items(chosen))
    return selected


def render_json_block(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


def make_case_studies_cli(
    input_paths: list[Path],
    output_dir: Path,
    title: str = "Paper Case Studies",
    max_cases: int = 5,
    include_unrecovered: bool = False,
) -> JsonDict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases, resolved_paths = load_autopsy_cases(input_paths)
    ordered = sorted(cases, key=_case_sort_key)
    if not include_unrecovered:
        ordered = [item for item in ordered if item.get("recovered")]
    selected_cases = select_case_studies(ordered, max_cases)
    report = {
        "title": title,
        "input_paths": resolved_paths,
        "source_case_count": len(cases),
        "recovered_case_count": sum(1 for item in cases if item.get("recovered")),
        "selected_case_count": len(selected_cases),
        "selected_domains": sorted({str(item.get("domain", "")) for item in selected_cases}),
        "selected_patch_families": sorted(
            {
                str(item.get("patch_family") or "none")
                for item in selected_cases
            }
        ),
        "selected_continuation_modes": sorted(
            {
                str(item.get("continuation_mode") or "")
                for item in selected_cases
            }
        ),
        "selected_cases": selected_cases,
    }
    save_json(output_dir / "case_studies.json", report)

    markdown_lines = [
        f"# {title}",
        "",
        (
            f"Selected `{len(selected_cases)}` case studies from `{len(cases)}` saved autopsy entries "
            f"across `{len(resolved_paths)}` source artifact(s)."
        ),
        "",
        "## Summary",
        "",
        f"- Recovered cases available: `{report['recovered_case_count']}`",
        f"- Selected case count: `{report['selected_case_count']}`",
        f"- Selected domains: `{report['selected_domains']}`",
        f"- Selected patch families: `{report['selected_patch_families']}`",
        f"- Selected continuation modes: `{report['selected_continuation_modes']}`",
        "",
    ]
    for index, case in enumerate(selected_cases, start=1):
        markdown_lines.extend(
            [
                f"## Case {index}: {case.get('failure_id', 'unknown')}",
                "",
                f"- Domain: `{case.get('domain', '')}`",
                f"- Task id: `{case.get('task_id', '')}`",
                f"- Recovered: `{bool(case.get('recovered', False))}`",
                f"- Patch family: `{case.get('patch_family') or 'none'}`",
                f"- Continuation mode: `{case.get('continuation_mode') or ''}`",
                f"- Root-cause step: `{case.get('root_cause_step')}`",
                f"- Known fault step: `{case.get('known_fault_step')}`",
                f"- Patch size: `{case.get('patch_size')}`",
                f"- Total search cost: `{case.get('total_token_cost')}`",
                f"- Autopsy artifact: `{case.get('artifact_source_path', '')}`",
                f"- Benchmark source: `{case.get('benchmark_source_path', '')}`",
                "",
                f"Summary: {case.get('summary', '')}",
                "",
                f"Explanation: {case.get('natural_language_explanation', case.get('summary', ''))}",
                "",
                "### Original Action",
                "",
                "```json",
                render_json_block(case.get("original_action")),
                "```",
                "",
                "### Patched Action",
                "",
                "```json",
                render_json_block(case.get("patched_action")),
                "```",
                "",
                "### Original State Fragment",
                "",
                "```json",
                render_json_block(case.get("original_state_fragment")),
                "```",
                "",
                "### Patched State Fragment",
                "",
                "```json",
                render_json_block(case.get("patched_state_fragment")),
                "```",
                "",
            ]
        )
    with (output_dir / "case_studies.md").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(markdown_lines) + "\n")
    return {
        "title": title,
        "selected_case_count": len(selected_cases),
        "output_dir": str(output_dir),
        "json_path": str(output_dir / "case_studies.json"),
        "markdown_path": str(output_dir / "case_studies.md"),
    }


def build_dependency_snapshot() -> JsonDict:
    distributions: list[JsonDict] = []
    for distribution in importlib_metadata.distributions():
        name = distribution.metadata.get("Name") or ""
        if not name:
            continue
        distributions.append({"name": name, "version": distribution.version})
    distributions.sort(key=lambda item: item["name"].lower())
    upstream_lockfiles = [
        str(path)
        for path in [
            Path("external/tau2-bench/pyproject.toml"),
            Path("external/tau2-bench/uv.lock"),
        ]
        if path.exists()
    ]
    selected_requirements = [
        f"{name}=={version}"
        for name, version in sorted((build_environment_manifest().get("selected_distributions") or {}).items())
    ]
    return {
        "environment": build_environment_manifest(),
        "distribution_count": len(distributions),
        "distributions": distributions,
        "selected_requirements": selected_requirements,
        "upstream_lockfiles": upstream_lockfiles,
    }


def freeze_deps_cli(output_dir: Path) -> JsonDict:
    snapshot = build_dependency_snapshot()
    save_json(output_dir / "dependency_snapshot.json", snapshot)
    all_requirements = [f"{item['name']}=={item['version']}" for item in snapshot["distributions"]]
    with (output_dir / "requirements-lock.txt").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(all_requirements) + "\n")
    with (output_dir / "requirements-selected.txt").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(snapshot["selected_requirements"]) + "\n")
    markdown_lines = [
        "# Reproducibility Snapshot",
        "",
        "This directory captures the currently installed local Python environment used for paper artifacts.",
        "",
        "## Summary",
        "",
        f"- Distribution count: `{snapshot['distribution_count']}`",
        f"- Selected project distributions: `{snapshot['selected_requirements']}`",
        f"- Upstream tau2 lockfiles: `{snapshot['upstream_lockfiles']}`",
        "",
        "## Files",
        "",
        "- `dependency_snapshot.json`",
        "- `requirements-lock.txt`",
        "- `requirements-selected.txt`",
        "",
        "The selected requirements file is the shortest paper-facing snapshot.",
        "The full lock file is a broader local environment capture and may include unrelated packages.",
    ]
    with (output_dir / "REPRODUCIBILITY.md").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(markdown_lines) + "\n")
    return {
        "distribution_count": snapshot["distribution_count"],
        "selected_distribution_count": len(snapshot["selected_requirements"]),
        "output_dir": str(output_dir),
        "snapshot_path": str(output_dir / "dependency_snapshot.json"),
        "requirements_lock_path": str(output_dir / "requirements-lock.txt"),
        "requirements_selected_path": str(output_dir / "requirements-selected.txt"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Real tau3-bench minimal patch recovery prototype.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect-failures", help="Collect real benchmark failures.")
    collect.add_argument("--domain", choices=sorted(DOMAIN_LOADERS.keys()), default="retail")
    collect.add_argument("--task-split", default="base")
    collect.add_argument("--limit", type=int, default=3)
    collect.add_argument("--output-dir", type=Path, default=Path("artifacts/collect"))

    natural = subparsers.add_parser(
        "import-natural-failures",
        help="Import naturally failed trajectories from saved tau2 result JSON.",
    )
    natural.add_argument("--domain", choices=sorted(DOMAIN_LOADERS.keys()), required=True)
    natural.add_argument("--task-split", default="base")
    natural.add_argument("--results-path", type=Path, required=True)
    natural.add_argument("--limit", type=int, default=25)
    natural.add_argument("--output-dir", type=Path, default=Path("artifacts/natural"))

    corpus = subparsers.add_parser(
        "build-corpus",
        help="Import many natural failures and normalize them into a corpus manifest.",
    )
    corpus.add_argument("--name", default="paper_corpus")
    corpus.add_argument(
        "--domain-specs",
        nargs="+",
        required=True,
        help="Entries of the form domain::task_split::results_path",
    )
    corpus.add_argument("--limit-per-domain", type=int, default=100)
    corpus.add_argument("--output-dir", type=Path, default=Path("artifacts/corpus"))

    synthetic_corpus = subparsers.add_parser(
        "build-synthetic-corpus",
        help="Collect synthetic benchmark failures across multiple domains into a corpus manifest.",
    )
    synthetic_corpus.add_argument("--name", default="synthetic_corpus")
    synthetic_corpus.add_argument(
        "--domains",
        nargs="+",
        choices=sorted(DOMAIN_LOADERS.keys()),
        required=True,
    )
    synthetic_corpus.add_argument("--limit-per-domain", type=int, default=12)
    synthetic_corpus.add_argument("--task-split", default="base")
    synthetic_corpus.add_argument("--output-dir", type=Path, default=Path("artifacts/synthetic_corpus"))

    search = subparsers.add_parser("search-patches", help="Search patches for collected failures.")
    search.add_argument("--input-dir", type=Path, default=Path("artifacts/collect"))
    search.add_argument("--output-dir", type=Path, default=Path("artifacts/search"))
    search.add_argument(
        "--strategy",
        choices=[
            "heuristic",
            "reverse",
            "chronological",
            "latest_only",
            "oracle_fault_step",
            "random_candidate",
            "no_repair",
        ],
        default="heuristic",
    )
    search.add_argument("--max-evaluations", type=int, default=None)
    search.add_argument("--max-candidates-per-step", type=int, default=None)
    search.add_argument("--continuation-horizon", type=int, default=3)
    search.add_argument("--beam-width", type=int, default=2)
    search.add_argument(
        "--proposer-backend",
        choices=[item.value for item in ProposerBackend],
        default=ProposerBackend.DETERMINISTIC.value,
    )
    search.add_argument("--model-slug", default=None)
    search.add_argument(
        "--include-oracle-suffix",
        action="store_true",
        help=(
            "Opt into the reference-action continuation upper-bound ablation. "
            "Strict replay remains the default."
        ),
    )
    search.add_argument(
        "--compact-results",
        action="store_true",
        help="Omit per-candidate replay trajectories from incremental patch_results.jsonl writes to keep large runs lightweight.",
    )

    compare = subparsers.add_parser(
        "compare-strategies",
        help="Run patch search baselines over the same failure corpus.",
    )
    compare.add_argument("--input-dir", type=Path, default=Path("artifacts/collect"))
    compare.add_argument("--output-dir", type=Path, default=Path("artifacts/strategy_comparison"))
    compare.add_argument(
        "--strategies",
        nargs="+",
        choices=[
            "heuristic",
            "reverse",
            "chronological",
            "latest_only",
            "oracle_fault_step",
            "random_candidate",
            "no_repair",
        ],
        default=[
            "heuristic",
            "reverse",
            "chronological",
            "latest_only",
            "oracle_fault_step",
            "random_candidate",
            "no_repair",
        ],
    )
    compare.add_argument("--max-evaluations", type=int, default=None)
    compare.add_argument("--max-candidates-per-step", type=int, default=None)
    compare.add_argument("--continuation-horizon", type=int, default=3)
    compare.add_argument("--beam-width", type=int, default=2)
    compare.add_argument(
        "--proposer-backend",
        choices=[item.value for item in ProposerBackend],
        default=ProposerBackend.DETERMINISTIC.value,
    )
    compare.add_argument("--model-slug", default=None)
    compare.add_argument(
        "--include-oracle-suffix",
        action="store_true",
        help="Run strategy comparison with the oracle continuation upper-bound enabled.",
    )
    compare.add_argument(
        "--compact-results",
        action="store_true",
        help="Write lightweight patch_results.jsonl files without replay trajectories.",
    )

    baselines = subparsers.add_parser(
        "run-baselines",
        help="Run simple retry baselines over a saved failure corpus.",
    )
    baselines.add_argument("--input-dir", type=Path, required=True)
    baselines.add_argument("--output-dir", type=Path, required=True)
    baselines.add_argument(
        "--method-variants",
        nargs="+",
        choices=[
            MethodVariant.RETRY_FROM_SCRATCH.value,
            MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
            MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value,
        ],
        default=[
            MethodVariant.RETRY_FROM_SCRATCH.value,
            MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
            MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value,
        ],
    )
    baselines.add_argument("--strategy", default="heuristic")
    baselines.add_argument("--max-evaluations", type=int, default=None)
    baselines.add_argument("--continuation-horizon", type=int, default=3)
    baselines.add_argument("--beam-width", type=int, default=2)
    baselines.add_argument(
        "--proposer-backend",
        choices=[item.value for item in ProposerBackend],
        default=ProposerBackend.OPENROUTER.value,
    )
    baselines.add_argument("--model-slug", default=None)
    baselines.add_argument(
        "--compact-results",
        action="store_true",
        help="Write lightweight patch_results.jsonl files without replay trajectories.",
    )

    batch = subparsers.add_parser(
        "run-batch",
        help="Run a saved experiment config over a failure corpus.",
    )
    batch.add_argument("--config", type=Path, required=True)
    batch.add_argument("--output-dir", type=Path, default=None)

    sweep_budget = subparsers.add_parser(
        "sweep-budget",
        help="Run the same search over a set of evaluation budgets.",
    )
    sweep_budget.add_argument("--input-dir", type=Path, required=True)
    sweep_budget.add_argument("--output-dir", type=Path, required=True)
    sweep_budget.add_argument("--strategy", default="heuristic")
    sweep_budget.add_argument("--evaluation-budgets", nargs="+", type=int, required=True)
    sweep_budget.add_argument(
        "--proposer-backend",
        choices=[item.value for item in ProposerBackend],
        default=ProposerBackend.DETERMINISTIC.value,
    )
    sweep_budget.add_argument("--model-slug", default=None)
    sweep_budget.add_argument(
        "--compact-results",
        action="store_true",
        help="Write lightweight patch_results.jsonl files without replay trajectories.",
    )

    sweep_models = subparsers.add_parser(
        "sweep-models",
        help="Run the same search across multiple OpenRouter model slugs.",
    )
    sweep_models.add_argument("--input-dir", type=Path, required=True)
    sweep_models.add_argument("--output-dir", type=Path, required=True)
    sweep_models.add_argument("--strategy", default="heuristic")
    sweep_models.add_argument("--model-slugs", nargs="+", required=True)
    sweep_models.add_argument("--max-evaluations", type=int, default=None)
    sweep_models.add_argument(
        "--compact-results",
        action="store_true",
        help="Write lightweight patch_results.jsonl files without replay trajectories.",
    )

    figures = subparsers.add_parser(
        "make-figures",
        help="Build paper-facing figure data from saved patch summaries.",
    )
    figures.add_argument("--input-dirs", nargs="+", type=Path, required=True)
    figures.add_argument("--output-dir", type=Path, default=Path("artifacts/figures"))

    bundle = subparsers.add_parser(
        "make-paper-bundle",
        help="Run a reproducible paper bundle from raw tau result files to tables and figures.",
    )
    bundle.add_argument("--name", default="paper_bundle")
    bundle.add_argument(
        "--domain-specs",
        nargs="+",
        required=True,
        help="Entries of the form domain::task_split::results_path",
    )
    bundle.add_argument("--limit-per-domain", type=int, default=100)
    bundle.add_argument("--output-dir", type=Path, default=Path("artifacts/paper_bundle"))
    bundle.add_argument("--strict-strategy", default="heuristic")
    bundle.add_argument("--strict-max-evaluations", type=int, default=None)
    bundle.add_argument("--oracle-max-evaluations", type=int, default=None)
    bundle.add_argument("--continuation-horizon", type=int, default=3)
    bundle.add_argument("--beam-width", type=int, default=2)
    bundle.add_argument("--max-candidates-per-step", type=int, default=None)
    bundle.add_argument(
        "--proposer-backend",
        choices=[item.value for item in ProposerBackend],
        default=ProposerBackend.DETERMINISTIC.value,
    )
    bundle.add_argument("--model-slug", default=None)
    bundle.add_argument(
        "--full-results",
        action="store_true",
        help="Keep full replay trajectories inside patch_results.jsonl instead of the compact paper-bundle default.",
    )

    workshop_bundle = subparsers.add_parser(
        "make-workshop-bundle",
        help="Build the workshop-first artifact bundle with natural, synthetic, strict, retry, and oracle outputs.",
    )
    workshop_bundle.add_argument("--name", default="workshop_bundle")
    workshop_bundle.add_argument(
        "--natural-domain-specs",
        nargs="+",
        required=True,
        help="Entries of the form domain::task_split::results_path",
    )
    workshop_bundle.add_argument("--natural-limit-per-domain", type=int, default=40)
    workshop_bundle.add_argument(
        "--synthetic-domains",
        nargs="+",
        choices=sorted(DOMAIN_LOADERS.keys()),
        default=["retail", "airline"],
    )
    workshop_bundle.add_argument("--synthetic-limit-per-domain", type=int, default=12)
    workshop_bundle.add_argument("--output-dir", type=Path, default=Path("artifacts/workshop_bundle"))
    workshop_bundle.add_argument("--strict-strategy", default="heuristic")
    workshop_bundle.add_argument("--strict-max-evaluations", type=int, default=None)
    workshop_bundle.add_argument("--oracle-max-evaluations", type=int, default=None)
    workshop_bundle.add_argument(
        "--retry-method-variants",
        nargs="+",
        choices=[
            MethodVariant.RETRY_FROM_SCRATCH.value,
            MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
            MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value,
        ],
        default=[
            MethodVariant.RETRY_FROM_SCRATCH.value,
            MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
            MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value,
        ],
    )
    workshop_bundle.add_argument(
        "--retry-proposer-backend",
        choices=[item.value for item in ProposerBackend],
        default=ProposerBackend.OPENROUTER.value,
    )
    workshop_bundle.add_argument("--retry-model-slug", default=None)
    workshop_bundle.add_argument("--continuation-horizon", type=int, default=3)
    workshop_bundle.add_argument("--beam-width", type=int, default=2)
    workshop_bundle.add_argument("--max-candidates-per-step", type=int, default=None)
    workshop_bundle.add_argument(
        "--full-results",
        action="store_true",
        help="Keep full replay trajectories inside patch_results.jsonl instead of the compact workshop-bundle default.",
    )

    tables = subparsers.add_parser(
        "make-paper-tables",
        help="Build paper-facing result tables from saved patch outputs.",
    )
    tables.add_argument("--input-dirs", nargs="+", type=Path, required=True)
    tables.add_argument("--output-dir", type=Path, default=Path("artifacts/paper_tables"))

    artifact_guide = subparsers.add_parser(
        "make-artifact-guide",
        help="Build a reviewer-facing artifact guide and environment manifest from saved outputs.",
    )
    artifact_guide.add_argument("--input-dirs", nargs="+", type=Path, required=True)
    artifact_guide.add_argument("--output-dir", type=Path, default=Path("artifacts/artifact_guide"))
    artifact_guide.add_argument("--title", default="Artifact Guide")
    artifact_guide.add_argument("--paper-draft-path", type=Path, default=None)
    artifact_guide.add_argument("--checklist-path", type=Path, default=None)
    artifact_guide.add_argument(
        "--skip-environment",
        action="store_true",
        help="Do not include local environment metadata in the manifest.",
    )

    case_studies = subparsers.add_parser(
        "make-case-studies",
        help="Build paper-facing case-study panels from saved autopsy reports.",
    )
    case_studies.add_argument("--input-paths", nargs="+", type=Path, required=True)
    case_studies.add_argument("--output-dir", type=Path, default=Path("artifacts/case_studies"))
    case_studies.add_argument("--title", default="Paper Case Studies")
    case_studies.add_argument("--max-cases", type=int, default=5)
    case_studies.add_argument(
        "--include-unrecovered",
        action="store_true",
        help="Include unrecovered autopsies if needed to fill the requested case count.",
    )

    freeze = subparsers.add_parser(
        "freeze-deps",
        help="Capture a pinned dependency snapshot for reproducibility artifacts.",
    )
    freeze.add_argument("--output-dir", type=Path, default=Path("artifacts/reproducibility_snapshot"))

    report = subparsers.add_parser("report-autopsy", help="Aggregate autopsy reports.")
    report.add_argument("--input-dir", type=Path, default=Path("artifacts/search"))
    report.add_argument("--output-path", type=Path, default=Path("artifacts/autopsy_report.json"))
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "collect-failures":
        result = collect_failures_cli(args.domain, args.task_split, args.limit, args.output_dir)
    elif args.command == "import-natural-failures":
        result = import_natural_failures_cli(
            args.domain,
            args.task_split,
            args.results_path,
            args.limit,
            args.output_dir,
        )
    elif args.command == "build-corpus":
        result = build_corpus_cli(
            args.name,
            args.domain_specs,
            args.limit_per_domain,
            args.output_dir,
        )
    elif args.command == "build-synthetic-corpus":
        result = build_synthetic_corpus_cli(
            args.name,
            args.domains,
            args.limit_per_domain,
            args.output_dir,
            args.task_split,
        )
    elif args.command == "search-patches":
        result = search_patches_cli(
            args.input_dir,
            args.output_dir,
            args.strategy,
            args.max_evaluations,
            args.include_oracle_suffix,
            args.proposer_backend,
            args.model_slug,
            args.continuation_horizon,
            args.beam_width,
            args.max_candidates_per_step,
            args.compact_results,
        )
    elif args.command == "compare-strategies":
        result = compare_strategies_cli(
            args.input_dir,
            args.output_dir,
            args.strategies,
            args.max_evaluations,
            args.include_oracle_suffix,
            args.proposer_backend,
            args.model_slug,
            args.continuation_horizon,
            args.beam_width,
            args.max_candidates_per_step,
            args.compact_results,
        )
    elif args.command == "run-baselines":
        result = run_baselines_cli(
            args.input_dir,
            args.output_dir,
            args.method_variants,
            args.strategy,
            args.max_evaluations,
            args.proposer_backend,
            args.model_slug,
            args.continuation_horizon,
            args.beam_width,
            args.compact_results,
        )
    elif args.command == "run-batch":
        result = run_batch_cli(args.config, args.output_dir)
    elif args.command == "sweep-budget":
        result = sweep_budget_cli(
            args.input_dir,
            args.output_dir,
            args.strategy,
            args.evaluation_budgets,
            args.proposer_backend,
            args.model_slug,
            args.compact_results,
        )
    elif args.command == "sweep-models":
        result = sweep_models_cli(
            args.input_dir,
            args.output_dir,
            args.strategy,
            args.model_slugs,
            args.max_evaluations,
            args.compact_results,
        )
    elif args.command == "make-figures":
        result = make_figures_cli(args.input_dirs, args.output_dir)
    elif args.command == "make-paper-bundle":
        result = make_paper_bundle_cli(
            name=args.name,
            domain_specs=args.domain_specs,
            limit_per_domain=args.limit_per_domain,
            output_dir=args.output_dir,
            strict_strategy=args.strict_strategy,
            strict_max_evaluations=args.strict_max_evaluations,
            oracle_max_evaluations=args.oracle_max_evaluations,
            continuation_horizon=args.continuation_horizon,
            beam_width=args.beam_width,
            max_candidates_per_step=args.max_candidates_per_step,
            proposer_backend=args.proposer_backend,
            model_slug=args.model_slug,
            compact_results=not args.full_results,
        )
    elif args.command == "make-workshop-bundle":
        result = make_workshop_bundle_cli(
            name=args.name,
            natural_domain_specs=args.natural_domain_specs,
            natural_limit_per_domain=args.natural_limit_per_domain,
            synthetic_domains=args.synthetic_domains,
            synthetic_limit_per_domain=args.synthetic_limit_per_domain,
            output_dir=args.output_dir,
            strict_strategy=args.strict_strategy,
            strict_max_evaluations=args.strict_max_evaluations,
            oracle_max_evaluations=args.oracle_max_evaluations,
            retry_method_variants=args.retry_method_variants,
            retry_proposer_backend=args.retry_proposer_backend,
            retry_model_slug=args.retry_model_slug,
            continuation_horizon=args.continuation_horizon,
            beam_width=args.beam_width,
            max_candidates_per_step=args.max_candidates_per_step,
            compact_results=not args.full_results,
        )
    elif args.command == "make-paper-tables":
        result = make_paper_tables_cli(args.input_dirs, args.output_dir)
    elif args.command == "make-artifact-guide":
        result = make_artifact_guide_cli(
            args.input_dirs,
            args.output_dir,
            args.title,
            not args.skip_environment,
            args.paper_draft_path,
            args.checklist_path,
        )
    elif args.command == "make-case-studies":
        result = make_case_studies_cli(
            args.input_paths,
            args.output_dir,
            args.title,
            args.max_cases,
            args.include_unrecovered,
        )
    elif args.command == "freeze-deps":
        result = freeze_deps_cli(args.output_dir)
    elif args.command == "report-autopsy":
        result = report_autopsy_cli(args.input_dir, args.output_path)
    else:
        raise ValueError(f"Unknown command: {args.command}")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
