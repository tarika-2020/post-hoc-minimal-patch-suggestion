import json
import tempfile
import unittest
from pathlib import Path

from main import (
    BudgetConfig,
    FailureCollector,
    MethodVariant,
    NaturalFailureImporter,
    PatchSearchEngine,
    RealBenchmarkRunner,
    Tau3DomainAdapter,
    build_corpus_cli,
    build_synthetic_corpus_cli,
    collect_failures_cli,
    compare_strategies_cli,
    import_natural_failures_cli,
    freeze_deps_cli,
    make_artifact_guide_cli,
    make_case_studies_cli,
    make_figures_cli,
    make_paper_bundle_cli,
    make_paper_tables_cli,
    make_workshop_bundle_cli,
    report_autopsy_cli,
    run_baselines_cli,
    run_batch_cli,
    search_patches_cli,
    sweep_budget_cli,
)


class Tau3PrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.adapter = Tau3DomainAdapter(domain="retail", task_split="base")
        cls.task_id = list(cls.adapter.tasks.keys())[0]
        cls.runner = RealBenchmarkRunner(cls.adapter)
        cls.reference_trajectory = cls.runner.build_reference_trajectory(cls.task_id)
        cls.trajectories, cls.failures = FailureCollector(cls.adapter).collect([cls.task_id])
        cls.search_result = PatchSearchEngine(cls.adapter).search(cls.failures[0])

    def test_reference_trajectory_scores_success(self) -> None:
        self.assertTrue(self.reference_trajectory.outcome.success)
        self.assertGreater(len(self.reference_trajectory.steps), 0)

    def test_snapshot_restore_round_trip(self) -> None:
        step = self.reference_trajectory.steps[0]
        task = self.adapter.get_task(self.task_id)
        restored = self.runner.continue_from_snapshot(
            task=task,
            snapshot=step.pre_snapshot,
            actions=[type(self.runner)._require_task_actions(task)[0]],
            start_step=0,
        )
        self.assertEqual(
            restored.steps[0].tool_result["content"],
            self.reference_trajectory.steps[0].tool_result["content"],
        )
        self.assertEqual(
            restored.steps[0].post_snapshot.agent_db,
            self.reference_trajectory.steps[0].post_snapshot.agent_db,
        )

    def test_partial_replay_skips_final_evaluation(self) -> None:
        step = self.reference_trajectory.steps[0]
        task = self.adapter.get_task(self.task_id)
        partial = self.runner.continue_from_snapshot(
            task=task,
            snapshot=step.pre_snapshot,
            actions=[type(self.runner)._require_task_actions(task)[0]],
            start_step=0,
            finalize=False,
        )
        self.assertEqual(partial.outcome.reason, "Partial rollout without evaluation.")
        self.assertEqual(partial.outcome.reward, 0.0)
        self.assertNotEqual(partial.final_snapshot.message_history[-1]["content"], "done")

    def test_failure_collection_produces_failed_trace(self) -> None:
        self.assertEqual(len(self.trajectories), 1)
        self.assertEqual(len(self.failures), 1)
        self.assertFalse(self.failures[0].trajectory.outcome.success)

    def test_patch_search_recovers_failure(self) -> None:
        self.assertTrue(self.search_result.recovered)
        self.assertEqual(self.search_result.winning_patch.patch_family, "tool_args")
        self.assertEqual(self.search_result.proposer_backend, "deterministic")
        self.assertGreaterEqual(len(self.search_result.localization.ranked_steps), 1)

    def test_cli_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            search_dir = root / "search"
            report_path = root / "autopsy.json"
            collect_summary = collect_failures_cli("retail", "base", 1, collect_dir)
            search_summary = search_patches_cli(collect_dir, search_dir)
            report = report_autopsy_cli(search_dir, report_path)
            self.assertEqual(collect_summary["failure_count"], 1)
            self.assertEqual(search_summary["strategy"], "heuristic")
            self.assertEqual(search_summary["recovered_count"], 1)
            self.assertGreater(search_summary["evaluated_candidate_count"], 0)
            self.assertEqual(search_summary["known_fault_count"], 1)
            self.assertGreater(search_summary["localization_mrr"], 0.0)
            self.assertGreater(search_summary["localization_top3_accuracy"], 0.0)
            self.assertEqual(report["recovered_count"], 1)
            self.assertTrue(report_path.exists())

    def test_compare_strategies_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            compare_dir = root / "compare"
            collect_failures_cli("retail", "base", 1, collect_dir)
            report = compare_strategies_cli(
                collect_dir,
                compare_dir,
                ["heuristic", "latest_only", "oracle_fault_step"],
            )
            self.assertEqual(len(report["summaries"]), 3)
            self.assertTrue((compare_dir / "strategy_comparison.json").exists())

    def test_import_natural_failures_from_saved_tau2_results(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = import_natural_failures_cli(
                "retail",
                "base",
                result_path,
                1,
                Path(temp_dir),
            )
            self.assertEqual(summary["imported_failure_count"], 1)
            self.assertGreater(summary["simulations_seen"], 1)
            self.assertIn("tool_error_rate", summary)

    def test_import_natural_failures_accepts_default_split_alias(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-2025-04-14_airline_default_gpt-4.1-2025-04-14_4trials.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            summary = import_natural_failures_cli(
                "airline",
                "default",
                result_path,
                1,
                Path(temp_dir),
            )
            self.assertEqual(summary["task_split"], "base")
            self.assertEqual(summary["imported_failure_count"], 1)
            self.assertIn("replay_success_skipped_count", summary)

    def test_import_natural_failures_excludes_replay_successes(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "claude-3-7-sonnet-20250219_retail_default_gpt-4.1-2025-04-14_4trials.json"
        )
        importer = NaturalFailureImporter(Tau3DomainAdapter("retail", "default"))
        failures, summary = importer.import_results(result_path, limit=2)
        self.assertEqual(summary["task_split"], "base")
        self.assertGreaterEqual(summary["replay_success_skipped_count"], 1)
        self.assertTrue(all(not item.trajectory.outcome.success for item in failures))

    def test_natural_failures_get_non_oracle_structured_candidates(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        importer = NaturalFailureImporter(self.adapter)
        failures, _ = importer.import_results(result_path, limit=1)
        engine = PatchSearchEngine(self.adapter)
        candidates = engine.generate_candidates(failures[0], 0)
        self.assertTrue(any(candidate.patch_family == "tool_call_replace" for candidate in candidates))

    def test_runtime_continuation_candidate_recovers_imported_failure(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        importer = NaturalFailureImporter(self.adapter)
        failures, _ = importer.import_results(result_path, limit=1)
        engine = PatchSearchEngine(
            self.adapter,
            budget=BudgetConfig(continuation_horizon=3, beam_width=2),
        )
        runtime_candidates = [
            candidate
            for candidate in engine.generate_candidates(failures[0], 0)
            if candidate.patch_family == "continuation_replace"
            and candidate.payload.get("runtime_policy")
        ]
        self.assertGreaterEqual(len(runtime_candidates), 1)
        evaluation = engine.evaluate_candidate(
            failures[0],
            runtime_candidates[-1],
            BudgetConfig(continuation_horizon=3, beam_width=2),
        )
        self.assertTrue(evaluation.recovered)
        self.assertEqual(evaluation.outcome.reward, 1.0)
        self.assertGreaterEqual(evaluation.dynamic_token_cost, 1)

    def test_mutating_tool_deletion_recovers_airline_policy_failure(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json"
        )
        airline_adapter = Tau3DomainAdapter(domain="airline", task_split="base")
        importer = NaturalFailureImporter(airline_adapter)
        failures, _ = importer.import_results(result_path, limit=5)
        failure = next(item for item in failures if item.task_id == "48")
        engine = PatchSearchEngine(airline_adapter)
        deletion_candidates = [
            candidate
            for candidate in engine.generate_candidates(failure, 1)
            if candidate.patch_family == "tool_deletion"
        ]
        self.assertGreaterEqual(len(deletion_candidates), 1)
        result = engine.search(
            failure,
            strategy="heuristic",
            budget=BudgetConfig(max_evaluations_per_failure=1, max_candidates_per_step=5),
        )
        self.assertTrue(result.recovered)
        self.assertEqual(result.winning_patch.patch_family, "tool_deletion")
        self.assertEqual(result.winning_patch.target_step, 1)
        self.assertEqual(result.winning_outcome.reward, 1.0)

    def test_oracle_suffix_candidates_are_explicitly_opt_in(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        importer = NaturalFailureImporter(self.adapter)
        failures, _ = importer.import_results(result_path, limit=1)
        strict_engine = PatchSearchEngine(self.adapter)
        oracle_engine = PatchSearchEngine(self.adapter, include_oracle_suffix=True)

        strict_families = {
            candidate.patch_family
            for step_index in range(len(failures[0].trajectory.steps))
            for candidate in strict_engine.generate_candidates(failures[0], step_index)
        }
        oracle_families = {
            candidate.patch_family
            for step_index in range(len(failures[0].trajectory.steps))
            for candidate in oracle_engine.generate_candidates(failures[0], step_index)
        }

        self.assertNotIn("tool_call_with_oracle_suffix", strict_families)
        self.assertIn("tool_call_with_oracle_suffix", oracle_families)

    def test_oracle_suffix_search_skips_tasks_without_gold_actions(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            natural_dir = root / "natural"
            search_dir = root / "oracle"
            summary = import_natural_failures_cli(
                "airline",
                "base",
                result_path,
                3,
                natural_dir,
            )
            self.assertEqual(summary["imported_failure_count"], 3)
            oracle_summary = search_patches_cli(
                natural_dir,
                search_dir,
                strategy="heuristic",
                max_evaluations=1,
                include_oracle_suffix=True,
            )
            self.assertEqual(oracle_summary["failure_count"], 3)
            self.assertTrue((search_dir / "patch_results.json").exists())

    def test_build_corpus_and_run_batch_cli(self) -> None:
        result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus_dir = root / "corpus"
            batch_dir = root / "batch"
            config_path = root / "experiment.json"
            corpus_summary = build_corpus_cli(
                "test_corpus",
                [f"retail::base::{result_path}"],
                1,
                corpus_dir,
            )
            self.assertEqual(corpus_summary["entry_count"], 1)
            config_path.write_text(
                """{
  "name": "test_batch",
  "input_dir": "%s",
  "output_dir": "%s",
  "strategy": "heuristic",
  "proposer_backend": "deterministic",
  "budget": {
    "max_evaluations_per_failure": 2,
    "continuation_horizon": 2,
    "beam_width": 1
  }
}"""
                % (str(corpus_dir).replace("\\", "\\\\"), str(batch_dir).replace("\\", "\\\\")),
                encoding="utf-8",
            )
            batch_summary = run_batch_cli(config_path)
            self.assertEqual(batch_summary["failure_count"], 1)
            self.assertTrue((batch_dir / "experiment_config.json").exists())

    def test_budget_sweep_and_figure_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            sweep_dir = root / "sweep"
            figures_dir = root / "figures"
            tables_dir = root / "tables"
            collect_failures_cli("retail", "base", 1, collect_dir)
            report = sweep_budget_cli(
                collect_dir,
                sweep_dir,
                "heuristic",
                [1, 2],
            )
            self.assertEqual(len(report["points"]), 2)
            figure_report = make_figures_cli(
                [sweep_dir / "budget_1", sweep_dir / "budget_2"],
                figures_dir,
            )
            table_report = make_paper_tables_cli(
                [sweep_dir / "budget_1", sweep_dir / "budget_2"],
                tables_dir,
            )
            self.assertEqual(figure_report["figure_count"], 2)
            self.assertTrue((figures_dir / "figure_report.md").exists())
            self.assertEqual(table_report["experiment_count"], 2)
            self.assertEqual(len(table_report["synthetic_localization_results"]), 2)
            self.assertTrue((tables_dir / "main_results.csv").exists())
            self.assertTrue((tables_dir / "synthetic_localization_results.csv").exists())
            self.assertTrue((tables_dir / "paper_tables.md").exists())

    def test_make_artifact_guide_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            search_dir = root / "search"
            tables_dir = root / "tables"
            guide_dir = root / "guide"
            collect_failures_cli("retail", "base", 1, collect_dir)
            search_patches_cli(collect_dir, search_dir)
            make_paper_tables_cli([search_dir], tables_dir)
            report = make_artifact_guide_cli(
                [search_dir, tables_dir],
                guide_dir,
                title="Test Artifact Guide",
                paper_draft_path=Path("paper/paper_draft.md"),
                checklist_path=Path("paper/submission_checklist.md"),
            )
            self.assertEqual(report["entry_count"], 2)
            self.assertTrue((guide_dir / "artifact_manifest.json").exists())
            self.assertTrue((guide_dir / "ARTIFACT_README.md").exists())

    def test_compact_search_results_omit_patched_trajectory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            search_dir = root / "search"
            report_path = root / "autopsy.json"
            collect_failures_cli("retail", "base", 1, collect_dir)
            summary = search_patches_cli(
                collect_dir,
                search_dir,
                compact_results=True,
            )
            self.assertTrue(summary["compact_results"])
            payload = json.loads((search_dir / "patch_results.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["serialization_mode"], "compact")
            for evaluation in payload[0]["evaluated_candidates"]:
                self.assertNotIn("patched_trajectory", evaluation)
            report = report_autopsy_cli(search_dir, report_path)
            self.assertEqual(report["case_count"], 1)

    def test_make_case_studies_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            search_dir = root / "search"
            report_path = root / "autopsy.json"
            case_dir = root / "case_studies"
            collect_failures_cli("retail", "base", 1, collect_dir)
            search_patches_cli(collect_dir, search_dir)
            report_autopsy_cli(search_dir, report_path)
            report = make_case_studies_cli(
                [report_path],
                case_dir,
                title="Test Case Studies",
                max_cases=2,
            )
            self.assertEqual(report["selected_case_count"], 1)
            self.assertTrue((case_dir / "case_studies.json").exists())
            self.assertTrue((case_dir / "case_studies.md").exists())

    def test_make_case_studies_cli_prefers_diverse_recovered_cases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            autopsy_a = root / "autopsy_a.json"
            autopsy_b = root / "autopsy_b.json"
            case_dir = root / "case_studies"
            autopsy_a.write_text(
                json.dumps(
                    {
                        "autopsies": [
                            {
                                "failure_id": "airline-case-1",
                                "domain": "airline",
                                "task_id": "1",
                                "recovered": True,
                                "patch_family": "tool_deletion",
                                "continuation_mode": "strict_replay",
                                "patch_size": 1,
                                "total_token_cost": 10,
                                "known_fault_step": None,
                                "benchmark_source_path": "external/tau2-bench/data/tau2/results/final/airline_a.json",
                                "summary": "Recovered airline case 1.",
                                "original_action": {"name": "cancel_reservation"},
                                "patched_action": None,
                                "original_state_fragment": {"message_history_length": 1},
                                "patched_state_fragment": {"step_deleted": True},
                            },
                            {
                                "failure_id": "airline-case-2",
                                "domain": "airline",
                                "task_id": "2",
                                "recovered": True,
                                "patch_family": "tool_deletion",
                                "continuation_mode": "strict_replay",
                                "patch_size": 1,
                                "total_token_cost": 11,
                                "known_fault_step": None,
                                "benchmark_source_path": "external/tau2-bench/data/tau2/results/final/airline_a.json",
                                "summary": "Recovered airline case 2.",
                                "original_action": {"name": "cancel_reservation"},
                                "patched_action": None,
                                "original_state_fragment": {"message_history_length": 3},
                                "patched_state_fragment": {"step_deleted": True},
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            autopsy_b.write_text(
                json.dumps(
                    {
                        "autopsies": [
                            {
                                "failure_id": "retail-case-1",
                                "domain": "retail",
                                "task_id": "35",
                                "recovered": True,
                                "patch_family": "continuation_replace",
                                "continuation_mode": "strict_replay",
                                "patch_size": 3,
                                "total_token_cost": 483,
                                "known_fault_step": None,
                                "benchmark_source_path": "external/tau2-bench/data/tau2/results/final/retail_b.json",
                                "summary": "Recovered retail continuation case.",
                                "original_action": {"name": "find_user_id_by_email"},
                                "patched_action": {"name": "find_user_id_by_email"},
                                "original_state_fragment": {"message_history_length": 1},
                                "patched_state_fragment": {"message_history_length": 3},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            report = make_case_studies_cli(
                [autopsy_a, autopsy_b],
                case_dir,
                title="Diverse Case Studies",
                max_cases=2,
            )
            self.assertEqual(report["selected_case_count"], 2)
            payload = json.loads((case_dir / "case_studies.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["selected_domains"], ["airline", "retail"])
            self.assertEqual(
                payload["selected_patch_families"],
                ["continuation_replace", "tool_deletion"],
            )
            self.assertEqual(payload["selected_continuation_modes"], ["strict_replay"])
            selected = payload["selected_cases"]
            self.assertTrue(all(item.get("artifact_source_path") for item in selected))
            self.assertTrue(all(item.get("benchmark_source_path") for item in selected))
            markdown = (case_dir / "case_studies.md").read_text(encoding="utf-8")
            self.assertIn("Autopsy artifact", markdown)
            self.assertIn("Benchmark source", markdown)

    def test_natural_autopsy_report_preserves_benchmark_provenance(self) -> None:
        results_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            natural_dir = root / "natural"
            search_dir = root / "search"
            report_path = root / "autopsy.json"
            import_natural_failures_cli("retail", "base", results_path, 1, natural_dir)
            search_patches_cli(natural_dir, search_dir, max_evaluations=1)
            report = report_autopsy_cli(search_dir, report_path)
            self.assertGreaterEqual(report["case_count"], 1)
            autopsy = report["autopsies"][0]
            self.assertEqual(autopsy["failure_source"], "natural_tau2_result")
            self.assertEqual(autopsy["benchmark_source_path"], str(results_path))
            self.assertEqual(autopsy["source_metadata"]["results_path"], str(results_path))

    def test_freeze_deps_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            freeze_dir = root / "freeze"
            report = freeze_deps_cli(freeze_dir)
            self.assertGreater(report["distribution_count"], 0)
            self.assertTrue((freeze_dir / "dependency_snapshot.json").exists())
            self.assertTrue((freeze_dir / "requirements-lock.txt").exists())
            self.assertTrue((freeze_dir / "requirements-selected.txt").exists())
            self.assertTrue((freeze_dir / "REPRODUCIBILITY.md").exists())

    def test_openrouter_backend_gracefully_degrades_without_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            search_dir = root / "search"
            collect_failures_cli("retail", "base", 1, collect_dir)
            summary = search_patches_cli(
                collect_dir,
                search_dir,
                proposer_backend="openrouter",
                model_slug="openai/gpt-4.1-mini",
                max_evaluations=1,
            )
            self.assertEqual(summary["proposer_backend"], "openrouter")
            self.assertTrue((search_dir / "patch_results.json").exists())

    def test_make_paper_bundle_cli_supports_mixed_domains(self) -> None:
        retail_result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        airline_result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_dir = root / "bundle"
            report = make_paper_bundle_cli(
                name="mixed_smoke",
                domain_specs=[
                    f"retail::base::{retail_result_path}",
                    f"airline::base::{airline_result_path}",
                ],
                limit_per_domain=1,
                output_dir=bundle_dir,
                strict_strategy="heuristic",
                strict_max_evaluations=1,
                oracle_max_evaluations=1,
                continuation_horizon=2,
                beam_width=1,
                max_candidates_per_step=1,
            )
            self.assertEqual(sorted(report["corpus_summary"]["domains"]), ["airline", "retail"])
            self.assertTrue((bundle_dir / "corpus" / "failures.json").exists())
            self.assertTrue((bundle_dir / "strict_search" / "patch_results.json").exists())
            self.assertTrue((bundle_dir / "oracle_upper_bound" / "patch_results.json").exists())
            self.assertTrue((bundle_dir / "paper_tables" / "paper_tables.md").exists())
            strict_payload = json.loads(
                (bundle_dir / "strict_search" / "patch_results.json").read_text(encoding="utf-8")
            )
            self.assertTrue(strict_payload)
            self.assertEqual(strict_payload[0]["serialization_mode"], "compact")
            for evaluation in strict_payload[0]["evaluated_candidates"]:
                self.assertNotIn("patched_trajectory", evaluation)

    def test_build_synthetic_corpus_cli_supports_mixed_domains(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corpus_dir = root / "synthetic_corpus"
            summary = build_synthetic_corpus_cli(
                name="synthetic_mixed",
                domains=["retail", "airline"],
                limit_per_domain=1,
                output_dir=corpus_dir,
            )
            self.assertEqual(sorted(summary["domains"]), ["airline", "retail"])
            self.assertEqual(summary["entry_count"], 2)
            self.assertTrue((corpus_dir / "corpus_manifest.json").exists())
            self.assertTrue((corpus_dir / "failures.json").exists())
            self.assertTrue((corpus_dir / "summary.json").exists())

    def test_run_baselines_cli_writes_comparable_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            baseline_dir = root / "baselines"
            collect_failures_cli("retail", "base", 1, collect_dir)
            report = run_baselines_cli(
                input_dir=collect_dir,
                output_dir=baseline_dir,
                method_variants=[
                    MethodVariant.RETRY_FROM_SCRATCH.value,
                    MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
                    MethodVariant.RAW_CONTINUATION_FROM_SNAPSHOT.value,
                ],
                proposer_backend="deterministic",
                compact_results=True,
            )
            self.assertEqual(len(report["summaries"]), 3)
            self.assertTrue((baseline_dir / "baseline_comparison.json").exists())
            for method_variant in report["method_variants"]:
                summary_path = baseline_dir / method_variant / "patch_summary.json"
                results_path = baseline_dir / method_variant / "patch_results.json"
                self.assertTrue(summary_path.exists())
                self.assertTrue(results_path.exists())
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                self.assertEqual(summary["method_variant"], method_variant)

    def test_run_batch_cli_supports_retry_method_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            collect_dir = root / "collect"
            batch_dir = root / "batch_retry"
            config_path = root / "retry_batch.json"
            collect_failures_cli("retail", "base", 1, collect_dir)
            config_path.write_text(
                json.dumps(
                    {
                        "name": "retry_batch",
                        "input_dir": str(collect_dir),
                        "output_dir": str(batch_dir),
                        "method_variant": MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
                        "strategy": "heuristic",
                        "proposer_backend": "deterministic",
                        "compact_results": True,
                        "budget": {"max_evaluations_per_failure": 1},
                    }
                ),
                encoding="utf-8",
            )
            summary = run_batch_cli(config_path)
            self.assertEqual(
                summary["method_variant"],
                MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value,
            )
            self.assertTrue((batch_dir / "experiment_config.json").exists())
            self.assertTrue(
                (
                    batch_dir
                    / MethodVariant.RETRY_FROM_LOCALIZED_SNAPSHOT.value
                    / "patch_results.json"
                ).exists()
            )

    def test_make_workshop_bundle_cli_smoke(self) -> None:
        retail_result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_retail_base_gpt-4.1-2025-04-14_4trials.json"
        )
        airline_result_path = Path(
            "external/tau2-bench/data/tau2/results/final/"
            "gpt-4.1-mini-2025-04-14_airline_base_gpt-4.1-2025-04-14_4trials.json"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle_dir = root / "workshop_bundle"
            report = make_workshop_bundle_cli(
                name="workshop_smoke",
                natural_domain_specs=[
                    f"retail::base::{retail_result_path}",
                    f"airline::base::{airline_result_path}",
                ],
                natural_limit_per_domain=1,
                synthetic_domains=["retail", "airline"],
                synthetic_limit_per_domain=1,
                output_dir=bundle_dir,
                strict_max_evaluations=1,
                oracle_max_evaluations=1,
                retry_proposer_backend="deterministic",
                continuation_horizon=2,
                beam_width=1,
                max_candidates_per_step=1,
            )
            self.assertEqual(
                report["title"],
                "Execution Intervention for Post-Hoc Debugging of LLM Agent Trajectories",
            )
            self.assertEqual(
                sorted(report["natural_corpus_summary"]["domains"]),
                ["airline", "retail"],
            )
            self.assertEqual(
                sorted(report["synthetic_corpus_summary"]["domains"]),
                ["airline", "retail"],
            )
            self.assertTrue((bundle_dir / "WORKSHOP_RELEASE.md").exists())
            self.assertTrue((bundle_dir / "workshop_bundle_summary.json").exists())
            self.assertTrue((bundle_dir / "natural_corpus" / "failures.json").exists())
            self.assertTrue((bundle_dir / "synthetic_corpus" / "failures.json").exists())
            self.assertTrue((bundle_dir / "retry_baselines" / "baseline_comparison.json").exists())
            self.assertTrue((bundle_dir / "paper_tables" / "paper_tables.md").exists())


if __name__ == "__main__":
    unittest.main()
