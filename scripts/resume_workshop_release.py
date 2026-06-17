import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import (
    MethodVariant,
    ProposerBackend,
    build_aggregate_autopsy_report,
    compare_strategies_cli,
    load_json,
    make_artifact_guide_cli,
    make_case_studies_cli,
    make_figures_cli,
    make_paper_tables_cli,
    reconstruct_failures,
    report_autopsy_cli,
    run_baselines_cli,
    save_json,
    search_patches_cli,
    sweep_budget_cli,
)


DEFAULT_RETRY_VARIANTS = [
    MethodVariant.RETRY_FROM_SCRATCH.value,
    MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
    MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value,
]


def _existing_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    return load_json(path)


def _write_subset_manifest(
    source_dir: Path,
    target_dir: Path,
    limit: int,
) -> dict:
    manifest = load_json(source_dir / "corpus_manifest.json")
    failures_payload = load_json(source_dir / "failures.json")
    failures = reconstruct_failures(failures_payload)

    failure_by_id = {failure.failure_id: failure for failure in failures}
    ordered_entries = manifest["entries"]

    preferred_entries = [
        entry
        for entry in ordered_entries
        if entry.get("split") in {"test", "dev"}
    ]
    remaining_entries = [
        entry
        for entry in ordered_entries
        if entry.get("split") not in {"test", "dev"}
    ]
    selected_entries = (preferred_entries + remaining_entries)[:limit]
    selected_ids = {entry["failure_id"] for entry in selected_entries}
    selected_failures = [asdict(failure_by_id[item_id]) for item_id in selected_ids if item_id in failure_by_id]

    split_counts: dict[str, int] = {}
    for entry in selected_entries:
        split = entry["split"]
        split_counts[split] = split_counts.get(split, 0) + 1

    target_dir.mkdir(parents=True, exist_ok=True)
    manifest["entry_count"] = len(selected_entries)
    manifest["entries"] = selected_entries
    manifest["split_counts"] = dict(sorted(split_counts.items()))

    save_json(target_dir / "corpus_manifest.json", manifest)
    save_json(target_dir / "failures.json", selected_failures)
    summary = {
        "name": f"{manifest['name']}_subset_{limit}",
        "domains": manifest.get("domains", []),
        "entry_count": len(selected_entries),
        "split_counts": dict(sorted(split_counts.items())),
        "source_dir": str(source_dir),
        "limit": limit,
        "selection_policy": "prefer_test_then_dev_then_train",
    }
    save_json(target_dir / "summary.json", summary)
    return summary


def _retry_input_dir(
    natural_corpus_dir: Path,
    retry_dir: Path,
    model_slug: str | None,
    retry_case_limit: int | None,
) -> tuple[Path, dict | None]:
    if retry_case_limit is None:
        return natural_corpus_dir, None
    subset_dir = retry_dir / f"subset_{retry_case_limit}"
    summary = _write_subset_manifest(natural_corpus_dir, subset_dir, retry_case_limit)
    return subset_dir, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Resume workshop release generation from frozen corpora.")
    parser.add_argument("--root-dir", type=Path, default=Path("artifacts/workshop_bundle_release"))
    parser.add_argument("--retry-backend", default=ProposerBackend.OPENROUTER.value)
    parser.add_argument("--retry-model-slug", default="openai/gpt-oss-120b:free")
    parser.add_argument("--retry-case-limit", type=int, default=None)
    parser.add_argument("--strict-strategy", default="heuristic")
    parser.add_argument("--strict-max-evaluations", type=int, default=1)
    parser.add_argument("--oracle-max-evaluations", type=int, default=1)
    parser.add_argument("--continuation-horizon", type=int, default=2)
    parser.add_argument("--beam-width", type=int, default=1)
    parser.add_argument("--max-candidates-per-step", type=int, default=1)
    parser.add_argument("--compact-results", action="store_true", default=True)
    args = parser.parse_args()

    root_dir = args.root_dir
    natural_corpus_dir = root_dir / "natural_corpus"
    synthetic_corpus_dir = root_dir / "synthetic_corpus"
    strict_dir = root_dir / "strict_search"
    oracle_dir = root_dir / "oracle_upper_bound"
    retry_dir = root_dir / "retry_baselines"
    synthetic_compare_dir = root_dir / "synthetic_strategy_comparison"
    budget_dir = root_dir / "budget_sweep"
    figures_dir = root_dir / "figures"
    tables_dir = root_dir / "paper_tables"
    case_dir = root_dir / "case_studies"
    guide_dir = root_dir / "reviewer_artifact_guide"
    strict_autopsy_path = root_dir / "strict_autopsy_report.json"
    oracle_autopsy_path = root_dir / "oracle_autopsy_report.json"

    if args.retry_case_limit is None and args.retry_model_slug.endswith(":free"):
        args.retry_case_limit = 16

    strict_summary = _existing_json(strict_dir / "patch_summary.json")
    if strict_summary is None:
        strict_summary = search_patches_cli(
            input_dir=natural_corpus_dir,
            output_dir=strict_dir,
            strategy=args.strict_strategy,
            max_evaluations=args.strict_max_evaluations,
            include_oracle_suffix=False,
            proposer_backend=ProposerBackend.DETERMINISTIC.value,
            continuation_horizon=args.continuation_horizon,
            beam_width=args.beam_width,
            max_candidates_per_step=args.max_candidates_per_step,
            compact_results=args.compact_results,
        )

    strict_autopsy = _existing_json(strict_autopsy_path)
    if strict_autopsy is None:
        strict_autopsy = report_autopsy_cli(strict_dir, strict_autopsy_path)

    oracle_summary = _existing_json(oracle_dir / "patch_summary.json")
    if oracle_summary is None:
        oracle_summary = search_patches_cli(
            input_dir=natural_corpus_dir,
            output_dir=oracle_dir,
            strategy=args.strict_strategy,
            max_evaluations=args.oracle_max_evaluations,
            include_oracle_suffix=True,
            proposer_backend=ProposerBackend.DETERMINISTIC.value,
            continuation_horizon=args.continuation_horizon,
            beam_width=args.beam_width,
            max_candidates_per_step=args.max_candidates_per_step,
            compact_results=args.compact_results,
        )

    oracle_autopsy = _existing_json(oracle_autopsy_path)
    if oracle_autopsy is None:
        oracle_autopsy = report_autopsy_cli(oracle_dir, oracle_autopsy_path)

    retry_input_dir, retry_subset_summary = _retry_input_dir(
        natural_corpus_dir=natural_corpus_dir,
        retry_dir=retry_dir,
        model_slug=args.retry_model_slug,
        retry_case_limit=args.retry_case_limit,
    )
    baseline_report = _existing_json(retry_dir / "baseline_comparison.json")
    if baseline_report is None:
        baseline_report = run_baselines_cli(
            input_dir=retry_input_dir,
            output_dir=retry_dir,
            method_variants=DEFAULT_RETRY_VARIANTS,
            strategy=args.strict_strategy,
            max_evaluations=args.strict_max_evaluations,
            proposer_backend=args.retry_backend,
            model_slug=args.retry_model_slug,
            continuation_horizon=args.continuation_horizon,
            beam_width=args.beam_width,
            compact_results=args.compact_results,
        )

    synthetic_report = _existing_json(synthetic_compare_dir / "strategy_comparison.json")
    if synthetic_report is None:
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
            max_evaluations=args.strict_max_evaluations,
            proposer_backend=ProposerBackend.DETERMINISTIC.value,
            continuation_horizon=args.continuation_horizon,
            beam_width=args.beam_width,
            max_candidates_per_step=args.max_candidates_per_step,
            compact_results=args.compact_results,
        )

    budget_report = _existing_json(budget_dir / "budget_sweep.json")
    if budget_report is None:
        budget_report = sweep_budget_cli(
            input_dir=natural_corpus_dir,
            output_dir=budget_dir,
            strategy=args.strict_strategy,
            evaluation_budgets=[1, 2, 4],
            proposer_backend=ProposerBackend.DETERMINISTIC.value,
            compact_results=args.compact_results,
        )

    figure_inputs = [strict_dir, oracle_dir]
    figure_inputs.extend(retry_dir / variant for variant in DEFAULT_RETRY_VARIANTS)
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
    figure_inputs.extend(budget_dir / item for item in ["budget_1", "budget_2", "budget_4"])
    figure_report = make_figures_cli(figure_inputs, figures_dir)
    table_report = make_paper_tables_cli(figure_inputs, tables_dir)
    case_report = make_case_studies_cli(
        input_paths=[strict_autopsy_path],
        output_dir=case_dir,
        title="Workshop Case Studies",
        max_cases=3,
    )
    artifact_guide = make_artifact_guide_cli(
        input_dirs=[strict_dir, oracle_dir, retry_dir, synthetic_compare_dir, budget_dir, tables_dir, case_dir],
        output_dir=guide_dir,
        title="Workshop Reviewer Artifact Guide",
        paper_draft_path=Path("paper/paper_draft.md"),
        checklist_path=Path("paper/submission_checklist.md"),
    )

    natural_summary = _existing_json(natural_corpus_dir / "summary.json")
    if natural_summary is None:
        natural_manifest = load_json(natural_corpus_dir / "corpus_manifest.json")
        natural_summary = {
            "name": natural_manifest["name"],
            "domains": natural_manifest["domains"],
            "entry_count": natural_manifest["entry_count"],
            "split_counts": natural_manifest["split_counts"],
        }
    synthetic_summary = load_json(synthetic_corpus_dir / "summary.json")

    release_lines = [
        "# Workshop Release",
        "",
        "- Title: `Execution Intervention for Post-Hoc Debugging of LLM Agent Trajectories`",
        f"- Natural corpus entries: `{natural_summary['entry_count']}`",
        f"- Synthetic corpus entries: `{synthetic_summary['entry_count']}`",
        f"- Strict natural recovery: `{strict_summary['recovered_count']} / {strict_summary['failure_count']}`",
        f"- Oracle natural recovery: `{oracle_summary['recovered_count']} / {oracle_summary['failure_count']}`",
        f"- Retry backend: `{args.retry_backend}`",
        f"- Retry model slug: `{args.retry_model_slug}`",
        f"- Retry case limit: `{args.retry_case_limit}`",
    ]
    if retry_subset_summary is not None:
        release_lines.extend(
            [
                "",
                "## Hosted Baseline Note",
                "",
                "Hosted retry baselines were run on a capped natural subset to stay within free-model request limits.",
                f"- Retry subset entries: `{retry_subset_summary['entry_count']}`",
                f"- Retry subset split counts: `{retry_subset_summary['split_counts']}`",
            ]
        )
    release_lines.extend(
        [
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
            f"- Figures: `{figures_dir}`",
            f"- Paper tables: `{tables_dir}`",
            f"- Case studies: `{case_dir}`",
            f"- Reviewer guide: `{guide_dir}`",
        ]
    )
    (root_dir / "WORKSHOP_RELEASE.md").write_text("\n".join(release_lines) + "\n", encoding="utf-8")

    report = {
        "name": "workshop_bundle_release",
        "title": "Execution Intervention for Post-Hoc Debugging of LLM Agent Trajectories",
        "natural_corpus_summary": natural_summary,
        "synthetic_corpus_summary": synthetic_summary,
        "strict_summary": strict_summary,
        "strict_autopsy": strict_autopsy,
        "oracle_summary": oracle_summary,
        "oracle_autopsy": oracle_autopsy,
        "baseline_report": baseline_report,
        "synthetic_report": synthetic_report,
        "budget_report": budget_report,
        "figure_report": figure_report,
        "table_report": table_report,
        "case_report": case_report,
        "artifact_guide": artifact_guide,
        "retry_backend": args.retry_backend,
        "retry_model_slug": args.retry_model_slug,
        "retry_case_limit": args.retry_case_limit,
        "retry_subset_summary": retry_subset_summary,
        "paths": {
            "natural_corpus_dir": str(natural_corpus_dir),
            "synthetic_corpus_dir": str(synthetic_corpus_dir),
            "strict_dir": str(strict_dir),
            "oracle_dir": str(oracle_dir),
            "retry_dir": str(retry_dir),
            "synthetic_compare_dir": str(synthetic_compare_dir),
            "budget_dir": str(budget_dir),
            "figures_dir": str(figures_dir),
            "tables_dir": str(tables_dir),
            "case_dir": str(case_dir),
            "guide_dir": str(guide_dir),
            "strict_autopsy_path": str(strict_autopsy_path),
            "oracle_autopsy_path": str(oracle_autopsy_path),
            "workshop_release_path": str(root_dir / "WORKSHOP_RELEASE.md"),
        },
    }
    save_json(root_dir / "workshop_bundle_summary.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
