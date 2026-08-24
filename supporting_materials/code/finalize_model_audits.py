"""Build the second-stage technical audit and the final-result manifest.

Every freeze flag is recomputed from the current result artifacts. A missing
or legacy artifact is reported as a failed check instead of being treated as
evidence that the model is ready to freeze.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import run_pre_freeze_scenarios as scenarios
import run_unified_scheduler as scheduler


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "supporting_materials" / "results"
FROZEN = RESULTS / "final_frozen"
VALIDATION = RESULTS / "validation"
CAPABILITY = RESULTS / "capability"
EXACT = RESULTS / "exact_benchmark"
P3_EXACT = RESULTS / "p3_exact_benchmark"
CALIBRATION = RESULTS / "calibration"
P2 = FROZEN / "p2_inpatient_only"
P3 = FROZEN / "p3_joint"

REQUIRED_SCHEDULE_CHECKS = {
    "unique_exported_task_key",
    "outcome_event_id_unique",
    "result_event_scope_complete",
    "outcome_evaluation_cohort_matches_input",
    "outcome_patient_source_matches_input",
    "scheduled_event_has_outcome",
    "scheduled_patient_matches_input",
    "scheduled_task_exists_in_input",
    "duration_matches_5pct_scenario",
    "project_room_compatibility",
    "bedside_uses_room_7",
    "task_not_before_release",
    "task_complete_by_event_deadline",
    "bladder_task_after_readiness",
    "five_minute_grid",
    "inside_single_work_block",
    "fasting_complete_by_10",
    "no_room_overlap",
    "contiguous_event_sequence_numbers",
    "no_same_event_task_overlap",
    "within_event_cross_room_transfer_at_least_configured_minutes",
    "no_patient_task_overlap_across_events",
    "adjacent_patient_cross_room_transfer_at_least_configured_minutes",
    "doctor_capacity_defined",
    "doctor_concurrency_within_capacity",
    "outcome_complete_flag_consistency",
    "outcome_deadline_flag_consistency",
}
P2_EXACT_CASES = {
    "normal_weekday", "peak_weekday", "weekend", "multi_project_peak",
    "bedside_peak", "obstetric_peak",
}
P2_EXACT_EQUIVALENCE_COLUMNS = {
    "equiv_patient_event_identity",
    "equiv_task_object_identity",
    "equiv_task_patient_identity",
    "equiv_complete_event_task_expansion",
    "equiv_room_compatibility_and_choice",
    "equiv_preparation_release",
    "equiv_event_deadline",
    "equiv_transfer",
    "equiv_doctor_capacity",
    "equiv_workblock",
    "equiv_patient_nonoverlap",
    "equiv_deterministic_tie_break",
}
P3_EXACT_CASES = {
    "ordinary_joint_n20", "background_peak_n40", "inpatient_peak_n60",
    "multi_project_peak_n40", "bedside_pressure_n20",
    "obstetric_pressure_n40", "equipment_competition_n60",
    "recommended_alpha_typical_n100",
}
REQUIRED_REPAIR_VALIDATION_CHECKS = {
    "event_completeness",
    "room_compatibility",
    "release_or_preparation",
    "deadline",
    "fasting_window",
    "workblock",
    "room_overlap",
    "patient_overlap_or_transfer",
    "doctor_capacity",
    "background_minimum",
    "task_key_unique",
    "task_identity",
    "patient_identity",
    "duration",
}
SENSITIVITY_SCENARIOS = {
    "preparation_item", "preparation_event", "doctor_low", "capability_AB",
    "bladder45", "bladder90", "transfer5", "transfer15",
}
SEED_SCENARIOS = {"seed_11", "seed_29", "seed_47", "seed_83", "seed_131"}
ALL_SENSITIVITY_SCENARIOS = SENSITIVITY_SCENARIOS | SEED_SCENARIOS
SENSITIVITY_DEFAULTS = {
    "preparation_granularity": "item",
    "special_seed": scheduler.source_config.SEED,
    "capability_mode": "hierarchical",
    "capacity_column": "capacity_main",
    "bladder_minutes": 60,
    "transfer_minutes": scheduler.TRANSFER_MINUTES,
}
SENSITIVITY_OVERRIDES = {
    "preparation_item": {},
    "preparation_event": {"preparation_granularity": "event"},
    "doctor_low": {"capacity_column": "capacity_low"},
    "capability_AB": {"capability_mode": "strict"},
    "bladder45": {"bladder_minutes": 45},
    "bladder90": {"bladder_minutes": 90},
    "transfer5": {"transfer_minutes": 5},
    "transfer15": {"transfer_minutes": 15},
    "seed_11": {"special_seed": 11},
    "seed_29": {"special_seed": 29},
    "seed_47": {"special_seed": 47},
    "seed_83": {"special_seed": 83},
    "seed_131": {"special_seed": 131},
}
DEPRECATED_SENSITIVITY_COLUMNS = {
    "quota_shortfall_days", "quota_target_events",
    "quota_achieved_before_inpatient",
}


def load_json(path: Path, errors: dict[str, str]) -> dict[str, Any]:
    relative = str(path.relative_to(ROOT)).replace("\\", "/")
    if not path.exists():
        errors[relative] = "missing"
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        errors[relative] = f"unreadable: {exc}"
        return {}
    if not isinstance(data, dict):
        errors[relative] = "JSON root is not an object"
        return {}
    return data


def load_csv(path: Path, errors: dict[str, str]) -> pd.DataFrame:
    relative = str(path.relative_to(ROOT)).replace("\\", "/")
    if not path.exists():
        errors[relative] = "missing"
        return pd.DataFrame()
    try:
        return pd.read_csv(path, low_memory=False)
    except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        errors[relative] = f"unreadable: {exc}"
        return pd.DataFrame()


def truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "yes"}


def all_true(frame: pd.DataFrame, columns: list[str]) -> bool:
    return bool(columns) and not frame.empty and all(
        column in frame and frame[column].map(truth).all() for column in columns
    )


def close(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def semantic_check(report: dict[str, Any], name: str) -> bool:
    entry = report.get("checks", {}).get(name, {})
    return entry.get("passed") is True and int(entry.get("violation_count", -1)) == 0


def schedule_verification_passed(report: dict[str, Any]) -> tuple[bool, str]:
    checks = report.get("checks", {})
    missing = sorted(REQUIRED_SCHEDULE_CHECKS - set(checks))
    failed = sorted(
        name for name in REQUIRED_SCHEDULE_CHECKS & set(checks)
        if checks[name].get("passed") is not True
        or int(checks[name].get("violation_count", -1)) != 0
    )
    passed = report.get("passed") is True and not missing and not failed
    return passed, f"missing={missing}; failed={failed}"


def exact_status_metadata_valid(
    frame: pd.DataFrame,
    incumbent_column: str,
    heuristic_column: str,
    legacy_optimal_gap_column: str | None = None,
) -> tuple[bool, str]:
    required = {
        "solver_status", incumbent_column, heuristic_column,
        "best_bound", "solver_relative_gap",
        "heuristic_gap_to_bound", "solve_seconds", "time_limit_seconds",
    }
    missing = sorted(required - set(frame))
    if frame.empty or missing:
        return False, f"missing={missing}; rows={len(frame)}"
    invalid: list[str] = []
    for row in frame.itertuples(index=False):
        case = str(getattr(row, "case", "unknown"))
        status = str(getattr(row, "solver_status"))
        if status not in {"OPTIMAL", "FEASIBLE"}:
            invalid.append(f"{case}:status={status}")
            continue
        incumbent = float(getattr(row, incumbent_column))
        heuristic = float(getattr(row, heuristic_column))
        bound = float(getattr(row, "best_bound"))
        reported_gap = float(getattr(row, "solver_relative_gap"))
        heuristic_bound_gap = float(getattr(row, "heuristic_gap_to_bound"))
        expected_gap = (bound - incumbent) / max(abs(bound), 1.0)
        expected_heuristic_gap = (bound - heuristic) / max(abs(bound), 1.0)
        if not all(map(math.isfinite, (incumbent, heuristic, bound, reported_gap, heuristic_bound_gap))):
            invalid.append(f"{case}:nonfinite objective/bound/gap")
        elif bound + 1e-9 < incumbent or not close(reported_gap, expected_gap):
            invalid.append(f"{case}:inconsistent bound/gap")
        if bound + 1e-9 < heuristic or not close(
            heuristic_bound_gap, expected_heuristic_gap
        ):
            invalid.append(f"{case}:inconsistent heuristic-to-bound gap")
        solve_seconds = float(getattr(row, "solve_seconds"))
        time_limit = float(getattr(row, "time_limit_seconds"))
        if (
            not math.isfinite(solve_seconds)
            or not math.isfinite(time_limit)
            or solve_seconds < 0
            or time_limit <= 0
        ):
            invalid.append(f"{case}:invalid timing")
        if status == "OPTIMAL" and (
            not close(bound, incumbent) or not close(reported_gap, 0.0)
        ):
            invalid.append(f"{case}:OPTIMAL without zero certified gap")
        if legacy_optimal_gap_column is not None:
            value = getattr(row, legacy_optimal_gap_column)
            if status == "FEASIBLE" and not pd.isna(value):
                invalid.append(f"{case}:FEASIBLE populated optimal-only gap")
            if status == "OPTIMAL" and pd.isna(value):
                invalid.append(f"{case}:OPTIMAL missing optimal-only gap")
    return not invalid, "; ".join(invalid[:10]) if invalid else "status/bound/gap/time semantics valid"


def sensitivity_validation_issues(
    metrics: pd.DataFrame,
    p2: dict[str, Any],
    p3: dict[str, Any],
) -> list[str]:
    issues: list[str] = []
    if p2.get("detail_materialized") is not True:
        issues.append("authoritative P2 detail is not materialized")
    if p3.get("selection_ready_for_freeze") is not True:
        issues.append("authoritative P3 selection is not ready for freeze")
    names = set(metrics.get("audit_scenario", pd.Series(dtype=str)).astype(str))
    if names != ALL_SENSITIVITY_SCENARIOS or len(metrics) != len(ALL_SENSITIVITY_SCENARIOS):
        issues.append(
            f"scenario set/row count mismatch: names={sorted(names)}, rows={len(metrics)}"
        )
    deprecated = sorted(DEPRECATED_SENSITIVITY_COLUMNS & set(metrics))
    if deprecated:
        issues.append(f"deprecated daily-quota columns present: {deprecated}")
    required_columns = {
        "audit_scenario", "policy", "p2_room_mode", "background_target_alpha",
        "background_total_events", "background_required_events",
        "background_completed_events", "background_deficit_events",
        "epsilon_constraint_satisfied",
        "daily_quota_used", "inpatient_events", "background_events",
        *SENSITIVITY_DEFAULTS,
    }
    missing = sorted(required_columns - set(metrics))
    if missing:
        issues.append(f"missing current-kernel columns: {missing}")
        return issues

    policy = str(p2.get("selected_policy"))
    selected_alpha = p3.get("selected_alpha")
    p2_events = p2.get("metrics", {}).get("inpatient_events")
    background_events = p3.get("selected_metrics", {}).get("background_total_events")
    expected_room_mode = scheduler.POLICIES.get(policy, {}).get("room_mode")
    for label, overrides in SENSITIVITY_OVERRIDES.items():
        rows = metrics[metrics["audit_scenario"].eq(label)]
        if len(rows) != 1:
            issues.append(f"{label}: expected one row, found {len(rows)}")
            continue
        row = rows.iloc[0]
        expected_config = {**SENSITIVITY_DEFAULTS, **overrides}
        for column, expected in expected_config.items():
            actual = row[column]
            matched = close(actual, expected) if isinstance(expected, int) else str(actual) == str(expected)
            if not matched:
                issues.append(f"{label}:{column}={actual!r}, expected={expected!r}")
        if str(row["policy"]) != policy:
            issues.append(f"{label}:policy={row['policy']!r}, expected={policy!r}")
        if str(row["p2_room_mode"]) != str(expected_room_mode):
            issues.append(
                f"{label}:p2_room_mode={row['p2_room_mode']!r}, expected={expected_room_mode!r}"
            )
        if not close(row["background_target_alpha"], selected_alpha):
            issues.append(f"{label}:alpha={row['background_target_alpha']!r}, expected={selected_alpha!r}")
        if truth(row["daily_quota_used"]):
            issues.append(f"{label}:daily_quota_used is true")
        if not close(row["inpatient_events"], p2_events):
            issues.append(f"{label}:inpatient evaluation denominator mismatch")
        if not close(row["background_events"], background_events) or not close(
            row["background_total_events"], background_events
        ):
            issues.append(f"{label}:background evaluation denominator mismatch")
        expected_required = math.ceil(
            float(row["background_target_alpha"])
            * int(row["background_total_events"])
        )
        if not close(row["background_required_events"], expected_required):
            issues.append(f"{label}:epsilon integer lower bound mismatch")
        completed = int(row["background_completed_events"])
        actual_feasible = completed >= expected_required
        if truth(row["epsilon_constraint_satisfied"]) != actual_feasible:
            issues.append(f"{label}:epsilon feasibility flag contradicts completed/required")
        expected_deficit = max(0, expected_required - completed)
        if not close(row["background_deficit_events"], expected_deficit):
            issues.append(f"{label}:background deficit mismatch")
        if label == "preparation_item":
            selected = p3.get("selected_metrics", {})
            if not actual_feasible:
                issues.append("preparation_item:authoritative configuration misses epsilon target")
            for column in (
                "inpatient_complete_48h", "background_completed_events",
            ):
                if not close(row[column], selected.get(column)):
                    issues.append(
                        f"preparation_item:{column}={row[column]!r}, "
                        f"expected authoritative {selected.get(column)!r}"
                    )
    return issues


def sensitivity_outputs(
    errors: dict[str, str],
    p2: dict[str, Any] | None = None,
    p3: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    shard_root = FROZEN / "sensitivity_shards"
    paths = sorted(shard_root.glob("*/metrics.csv"))
    actual = {path.parent.name for path in paths}
    if actual != ALL_SENSITIVITY_SCENARIOS:
        errors[str(shard_root.relative_to(ROOT)).replace("\\", "/")] = (
            f"scenario mismatch: missing={sorted(ALL_SENSITIVITY_SCENARIOS - actual)}, "
            f"unexpected={sorted(actual - ALL_SENSITIVITY_SCENARIOS)}"
        )
    for path in paths:
        frame = load_csv(path, errors)
        if len(frame) != 1:
            continue
        frame.insert(0, "audit_scenario", path.parent.name)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(), {"seed_count": 0}, pd.DataFrame()

    metrics = pd.concat(frames, ignore_index=True)
    seed_rows = metrics[metrics["audit_scenario"].isin(SEED_SCENARIOS)].copy()
    seed_summary: dict[str, Any] = {
        "seed_count": int(len(seed_rows)),
        "seed_scenarios": sorted(seed_rows["audit_scenario"].astype(str).tolist()),
    }
    for column in ("inpatient_48h_rate", "background_on_time_rate"):
        if column in seed_rows and not seed_rows.empty:
            seed_summary[column] = {
                "mean": float(seed_rows[column].mean()),
                "std": float(seed_rows[column].std(ddof=1)),
                "min": float(seed_rows[column].min()),
                "max": float(seed_rows[column].max()),
            }
    prep = metrics[
        metrics["audit_scenario"].isin({"preparation_item", "preparation_event"})
    ].copy()
    semantic_issues = (
        sensitivity_validation_issues(metrics, p2, p3)
        if p2 is not None and p3 is not None
        else []
    )
    if semantic_issues:
        errors[str(shard_root.relative_to(ROOT)).replace("\\", "/")] = (
            "stale or incompatible shards: " + "; ".join(semantic_issues[:20])
        )
    else:
        metrics.to_csv(
            FROZEN / "sensitivity_metrics.csv", index=False, encoding="utf-8-sig"
        )
        (FROZEN / "special_seed_summary.json").write_text(
            json.dumps(seed_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        prep.to_csv(
            FROZEN / "preparation_granularity_sensitivity.csv",
            index=False,
            encoding="utf-8-sig",
        )
    return metrics, seed_summary, prep


def main() -> None:
    errors: dict[str, str] = {}
    evidence: dict[str, str] = {}
    freeze_checks: dict[str, bool] = {}

    def record(name: str, passed: bool, detail: str) -> None:
        freeze_checks[name] = bool(passed)
        evidence[name] = detail

    p2 = load_json(P2 / "summary.json", errors)
    p3 = load_json(P3 / "selection.json", errors)
    p2_policies = load_csv(P2 / "policy_metrics.csv", errors)
    p3_scan = load_csv(P3 / "pareto_metrics.csv", errors)
    p3_diagnostics = load_json(P3 / "epsilon_diagnostics.json", errors)
    alpha_zero_equivalence = load_json(
        P3 / "p2_p3_alpha_zero_equivalence.json", errors
    )
    semantic = load_json(VALIDATION / "input_semantic_verification.json", errors)
    p2_verify = load_json(P2 / "independent_verification.json", errors)
    p3_verify = load_json(P3 / "independent_verification.json", errors)
    p2_exact = load_csv(EXACT / "exact_vs_heuristic_metrics.csv", errors)
    p3_exact = load_csv(P3_EXACT / "p3_exact_vs_heuristic_metrics.csv", errors)
    p3_repair_audit = load_json(P3_EXACT / "p3_repair_path_audit.json", errors)
    calibration = load_csv(CALIBRATION / "calibration_metrics.csv", errors)
    legacy_fallback = load_csv(
        CAPABILITY / "LEGACY_50_FALLBACK_PROJECT_AUDIT.csv", errors
    )
    capability_failure = load_csv(
        CAPABILITY / "P2_CAPABILITY_FAILURE_DECOMPOSITION.csv", errors
    )
    p2_failure = load_csv(P2 / "failure_reason_breakdown.csv", errors)
    peak = load_csv(RESULTS / "p1" / "peak_flat_summary.csv", errors)
    chronological = load_csv(
        RESULTS / "p1" / "chronological_validation.csv", errors
    )
    p1_summary = load_json(RESULTS / "p1" / "analysis_summary.json", errors)
    paper_consistency_path = ROOT / "qa" / "MODEL_RESULT_FINAL_CONSISTENCY_AUDIT.json"
    paper_consistency = load_json(paper_consistency_path, errors)
    sensitivity, seed_summary, prep = sensitivity_outputs(errors, p2, p3)

    record(
        "train_holdout_no_leakage",
        not peak.empty
        and "threshold_data_role" in peak
        and peak["threshold_data_role"].eq("training_only").all()
        and not chronological.empty
        and {"train_end", "validation_start", "validation_end"}.issubset(
            chronological
        )
        and chronological["train_end"].astype(str).eq("2024-03-31").all()
        and chronological["validation_start"].astype(str).eq("2024-04-01").all()
        and chronological["validation_end"].astype(str).eq("2025-03-31").all()
        and p1_summary.get("catalog_boundary", {}).get(
            "holdout_names_used_for_dispatch_join"
        ) is False
        and p1_summary.get("doctor_time_boundary", {}).get(
            "holdout_report_times_used_for_doctor_or_duration_estimation"
        ) is False
        and semantic_check(semantic, "train_holdout_boundary"),
        "P1 thresholds, forecast split, project catalog and duration/doctor estimates must all respect 2024-03-31",
    )
    record(
        "all_50_fallback_reviewed",
        len(legacy_fallback) == 50
        and "legacy_project" in legacy_fallback
        and not legacy_fallback["legacy_project"].duplicated().any()
        and semantic_check(semantic, "all_former_fallback_projects_reviewed")
        and semantic_check(semantic, "review_has_explicit_treatment"),
        f"legacy_review_rows={len(legacy_fallback)}; expected=50",
    )
    record(
        "no_blanket_category_fallback",
        semantic_check(semantic, "no_blanket_category_fallback")
        and semantic_check(semantic, "compatible_rooms_trace_to_A_B_C_evidence")
        and semantic_check(semantic, "level_D_excluded_from_hard_capability")
        and semantic_check(semantic, "legacy_category_fallback_removed"),
        "rooms must trace to A/B/C evidence; level D and family-wide fallback are excluded",
    )
    record(
        "bedside_semantics_passed",
        semantic_check(semantic, "bedside_is_project_capability_intersection"),
        "machine 7 requires project capability intersect bedside-location capability",
    )
    record(
        "input_semantics_passed",
        semantic.get("passed") is True,
        f"input_semantic_verification.passed={semantic.get('passed')!r}",
    )

    p2_metrics = p2.get("metrics", {})
    p2_scope = p2_verify.get("evaluation_scope", {})
    record(
        "p2_pure_inpatient_scenario",
        p2.get("scenario") == "P2_INPATIENT_ONLY"
        and int(p2_metrics.get("background_events", -1)) == 0
        and not p2_policies.empty
        and "scenario" in p2_policies
        and p2_policies["scenario"].eq("P2_INPATIENT_ONLY").all()
        and "background_events" in p2_policies
        and p2_policies["background_events"].fillna(-1).eq(0).all()
        and p2.get("detail_materialized") is True
        and p2_verify.get("scenario") == "p2"
        and int(p2_scope.get("evaluation_inpatient_events", -1))
        == int(p2_metrics.get("inpatient_events", -2))
        and int(p2_scope.get("evaluation_background_events", -1)) == 0
        and p2_scope.get("warmup_in_statistics") is False,
        "P2 must contain no background events; warm-up may seed state but not evaluation statistics",
    )
    expected_policies = set(scheduler.P2_POLICY_CANDIDATES)
    policy_set = (
        set(p2_policies["policy"].astype(str)) if "policy" in p2_policies else set()
    )
    selected_from_code = None
    if len(p2_policies) == len(expected_policies) and policy_set == expected_policies:
        selected_index = min(
            range(len(p2_policies)),
            key=lambda index: scheduler.p2_metrics_lexicographic_key(
                p2_policies.iloc[index]
            ),
        )
        selected_from_code = str(p2_policies.iloc[selected_index]["policy"])
    p2_selection_ok = (
        selected_from_code is not None
        and p2.get("selected_policy") == selected_from_code
        and tuple(p2.get("candidate_policies", []))
        == scheduler.P2_POLICY_CANDIDATES
        and tuple(p2.get("selection_rule", [])) == scheduler.P2_SELECTION_RULE
        and str(p2_metrics.get("policy")) == selected_from_code
    )
    record(
        "p2_policy_selection_matches_code",
        p2_selection_ok,
        f"summary={p2.get('selected_policy')!r}; fixed-key result={selected_from_code!r}; policies={sorted(policy_set)}",
    )
    record(
        "p2_slack_definition_matches_code",
        p2.get("slack_definition") == scheduler.INPATIENT_SLACK_DEFINITION,
        f"summary={p2.get('slack_definition')!r}; code={scheduler.INPATIENT_SLACK_DEFINITION!r}",
    )

    p2_equiv_columns = {column for column in p2_exact if column.startswith("equiv_")}
    p2_case_values = set(p2_exact.get("case", pd.Series(dtype=str)).astype(str))
    p2_exact_equivalent = (
        p2_case_values == P2_EXACT_CASES
        and p2_equiv_columns == P2_EXACT_EQUIVALENCE_COLUMNS
        and all_true(p2_exact, sorted(P2_EXACT_EQUIVALENCE_COLUMNS))
        and "exact_schedule_violations" in p2_exact
        and p2_exact["exact_schedule_violations"].fillna(1).eq(0).all()
        and "policy" in p2_exact
        and p2_exact["policy"].astype(str).eq(str(p2.get("selected_policy"))).all()
    )
    record(
        "p2_exact_implementation_equivalent",
        p2_exact_equivalent,
        f"cases={sorted(p2_case_values)}; equivalence_columns={p2_equiv_columns}",
    )
    p2_status_ok, p2_status_detail = exact_status_metadata_valid(
        p2_exact, "exact_incumbent", "heuristic_complete", "heuristic_gap_to_exact",
    )
    record(
        "p2_exact_status_metadata_valid",
        p2_status_ok,
        p2_status_detail,
    )
    peak_rows = (
        p2_exact[p2_exact["case"].eq("peak_weekday")]
        if "case" in p2_exact else pd.DataFrame()
    )
    p2_high_load = (
        p2_case_values == P2_EXACT_CASES
        and "solver_status" in p2_exact
        and p2_exact["solver_status"].isin({"OPTIMAL", "FEASIBLE"}).all()
        and {"event_count", "target_event_count"}.issubset(p2_exact)
        and p2_exact["event_count"].eq(p2_exact["target_event_count"]).all()
        and p2_status_ok
        and not peak_rows.empty
        and int(peak_rows["event_count"].iloc[0]) >= 100
    )
    record(
        "p2_high_load_benchmark_passed",
        p2_high_load,
        "six fixed windows need incumbents; peak_weekday must contain at least 100 events",
    )

    categories = set(
        capability_failure.get("category_code", pd.Series(dtype=str)).astype(str)
    )
    decomposition_total = (
        int(capability_failure["event_count"].sum())
        if "event_count" in capability_failure else -1
    )
    capability_failure_total = -1
    if {"failure_reason", "event_count"}.issubset(p2_failure):
        matching = p2_failure[
            p2_failure["failure_reason"].eq("no_compatible_room_under_scenario")
        ]
        capability_failure_total = int(matching["event_count"].sum())
    record(
        "p2_capability_failure_decomposed",
        categories == set("ABCDEF")
        and decomposition_total == capability_failure_total >= 0,
        f"categories={sorted(categories)}; decomposition={decomposition_total}; P2 failures={capability_failure_total}",
    )
    p2_verify_ok, p2_verify_detail = schedule_verification_passed(p2_verify)
    p3_verify_ok, p3_verify_detail = schedule_verification_passed(p3_verify)
    record("p2_schedule_verification_passed", p2_verify_ok, p2_verify_detail)

    selected_alpha = p3.get("selected_alpha")
    p3_scope = p3_verify.get("evaluation_scope", {})
    p3_semantics_ok = False
    required_columns = {
        "background_target_alpha", "background_total_events",
        "background_required_events", "background_completed_events",
        "epsilon_feasible",
    }
    if not p3_scan.empty and required_columns.issubset(p3_scan):
        expected_required = p3_scan.apply(
            lambda row: math.ceil(
                float(row["background_target_alpha"])
                * int(row["background_total_events"])
            ),
            axis=1,
        )
        actual_feasible = p3_scan["background_completed_events"].ge(
            p3_scan["background_required_events"]
        )
        selected_rows = p3_scan[
            p3_scan["background_target_alpha"].map(
                lambda value: close(value, selected_alpha)
            )
        ]
        selected_counts_match = False
        if len(selected_rows) == 1:
            selected_row = selected_rows.iloc[0]
            selected_metrics = p3.get("selected_metrics", {})
            selected_counts_match = (
                all(
                    close(selected_row[column], selected_metrics.get(column))
                    for column in (
                        "inpatient_complete_48h", "background_required_events",
                        "background_completed_events",
                    )
                )
                and truth(selected_row["epsilon_feasible"])
                and "pareto_nondominated" in selected_row
                and truth(selected_row["pareto_nondominated"])
                and truth(selected_metrics.get("epsilon_constraint_satisfied"))
            )
        selection_grid = {
            round(float(value), 10) for value in p3.get("alpha_grid", [])
        }
        result_grid = {
            round(float(value), 10)
            for value in p3_scan["background_target_alpha"]
        }
        p3_semantics_ok = (
            p3.get("formal_constraint")
            == "background_completed >= ceil(alpha * total_background)"
            and p3.get("global_epsilon_algorithm")
            == "inpatient_first_then_global_deficit_repair"
            and p3.get("p2_policy") == p2.get("selected_policy")
            and expected_required.eq(p3_scan["background_required_events"]).all()
            and actual_feasible.eq(p3_scan["epsilon_feasible"].map(truth)).all()
            and selection_grid == result_grid
            and selected_counts_match
            and p3.get("selection_ready_for_freeze") is True
            and p3.get("detail_materialized") is True
            and p3_verify.get("scenario") == "p3"
            and int(p3_scope.get("evaluation_inpatient_events", -1))
            == int(p3.get("selected_metrics", {}).get("inpatient_events", -2))
            and int(p3_scope.get("evaluation_background_events", -1))
            == int(p3.get("selected_metrics", {}).get("background_events", -2))
            and p3_scope.get("warmup_in_statistics") is False
        )
    record(
        "p3_global_epsilon_semantics_passed",
        p3_semantics_ok,
        "required=ceil(alpha*total), feasibility and selected counts are recomputed",
    )

    diagnostics_candidates = p3_diagnostics.get("candidates", [])
    deprecated_quota_columns = {
        column for column in p3_scan
        if "quota" in column.lower() and column != "daily_quota_used"
    }
    p3_quota_mappings = [p3.get("selected_metrics", {}), p3_diagnostics]
    p3_quota_mappings.extend(
        candidate for candidate in diagnostics_candidates if isinstance(candidate, dict)
    )
    deprecated_quota_keys = {
        key for mapping in p3_quota_mappings if isinstance(mapping, dict)
        for key in mapping
        if "quota" in str(key).lower() and key != "daily_quota_used"
    }
    no_daily_quota = (
        p3.get("daily_quota_used") is False
        and "daily_quota_used" in p3_scan
        and not p3_scan["daily_quota_used"].map(truth).any()
        and p3_diagnostics.get("daily_quota_used") is False
        and bool(diagnostics_candidates)
        and all(
            candidate.get("daily_quota_used") is False
            for candidate in diagnostics_candidates
        )
        and not deprecated_quota_columns
        and not deprecated_quota_keys
    )
    record(
        "p3_no_daily_quota",
        no_daily_quota,
        f"selection, scan and every candidate must use daily_quota_used=false; deprecated_columns={sorted(deprecated_quota_columns)}; deprecated_keys={sorted(deprecated_quota_keys)}",
    )
    coarse = {round(value, 10) for value in scenarios.DEFAULT_COARSE_ALPHAS}
    scan_alphas = (
        {round(float(value), 10) for value in p3_scan["background_target_alpha"]}
        if "background_target_alpha" in p3_scan else set()
    )
    record(
        "p3_alpha_grid_dense",
        coarse.issubset(scan_alphas),
        f"required={sorted(coarse)}; actual={sorted(scan_alphas)}",
    )
    has_local_point = bool(scan_alphas - coarse)
    record(
        "p3_local_refinement_completed",
        p3.get("local_refinement_completed") is True
        and p3.get("requires_new_point_runs_before_final_selection") is False
        and has_local_point,
        f"noncoarse_point={has_local_point}; completed={p3.get('local_refinement_completed')!r}",
    )

    p3_exact_cases = set(p3_exact.get("case", pd.Series(dtype=str)).astype(str))
    p3_exact_deprecated_quota = {
        column for column in p3_exact
        if "quota" in column.lower() and column != "daily_quota_used"
    }
    p3_status_ok, p3_status_detail = exact_status_metadata_valid(
        p3_exact, "exact_inpatient_incumbent", "heuristic_inpatient_complete",
    )
    p3_source_counts_ok = False
    p3_epsilon_rows_ok = False
    if {
        "inpatient_events", "outpatient_events", "physical_exam_events",
        "event_count", "background_events", "required_background", "alpha",
        "exact_background_complete", "heuristic_background_complete",
    }.issubset(p3_exact):
        source_sum = (
            p3_exact["inpatient_events"]
            + p3_exact["outpatient_events"]
            + p3_exact["physical_exam_events"]
        )
        p3_source_counts_ok = (
            source_sum.eq(p3_exact["event_count"]).all()
            and p3_exact[[
                "inpatient_events", "outpatient_events", "physical_exam_events",
            ]].gt(0).to_numpy().all()
            and p3_exact["background_events"].eq(
                p3_exact["outpatient_events"] + p3_exact["physical_exam_events"]
            ).all()
        )
        recomputed_required = p3_exact.apply(
            lambda row: math.ceil(float(row["alpha"]) * int(row["background_events"])),
            axis=1,
        )
        p3_epsilon_rows_ok = (
            recomputed_required.eq(p3_exact["required_background"]).all()
            and p3_exact["exact_background_complete"].ge(
                p3_exact["required_background"]
            ).all()
            and p3_exact["heuristic_background_complete"].ge(
                p3_exact["required_background"]
            ).all()
        )
    p3_exact_ok = (
        p3_exact_cases == P3_EXACT_CASES
        and "solver_status" in p3_exact
        and p3_exact["solver_status"].isin({"OPTIMAL", "FEASIBLE"}).all()
        and {"event_count", "target_event_count"}.issubset(p3_exact)
        and p3_exact["event_count"].eq(p3_exact["target_event_count"]).all()
        and all_true(p3_exact, ["all_three_sources", "heuristic_epsilon_satisfied"])
        and p3_source_counts_ok
        and p3_epsilon_rows_ok
        and p3_status_ok
        and not p3_exact_deprecated_quota
        and "exact_schedule_violations" in p3_exact
        and p3_exact["exact_schedule_violations"].fillna(1).eq(0).all()
        and "heuristic_schedule_violations" in p3_exact
        and p3_exact["heuristic_schedule_violations"].fillna(1).eq(0).all()
        and "alpha" in p3_exact
        and p3_exact["alpha"].map(lambda value: close(value, selected_alpha)).all()
        and "policy" in p3_exact
        and p3_exact["policy"].astype(str).eq(str(p2.get("selected_policy"))).all()
        and "alpha_source" in p3_exact
        and p3_exact["alpha_source"].astype(str).str.endswith(
            "supporting_materials/results/final_frozen/p3_joint/selection.json"
        ).all()
    )
    record(
        "p3_exact_benchmark_exists",
        p3_exact_ok,
        f"cases={sorted(p3_exact_cases)}; alpha={selected_alpha!r}; deprecated_quota_columns={sorted(p3_exact_deprecated_quota)}; source must be selection.json",
    )
    record(
        "p3_exact_status_metadata_valid",
        p3_status_ok,
        p3_status_detail,
    )

    repair_candidates = p3_repair_audit.get("candidates", [])
    baseline_candidates = [
        candidate for candidate in repair_candidates
        if candidate.get("construction_method") == "inpatient_first"
    ]
    repair_candidates_only = [
        candidate for candidate in repair_candidates
        if candidate.get("construction_method") == "global_deficit_repair"
    ]
    repair_source_sum = sum(
        int(p3_repair_audit.get(name, -10**9))
        for name in ("inpatient_events", "outpatient_events", "physical_exam_events")
    )
    repair_required = int(p3_repair_audit.get("required_background", -1))
    repair_background = int(p3_repair_audit.get("background_events", -1))
    repair_violations = p3_repair_audit.get("validation_violations", {})
    selected_candidate_rows = [
        candidate for candidate in repair_candidates
        if candidate.get("construction_method")
        == p3_repair_audit.get("selected_construction_method")
        and candidate.get("background_order_strategy")
        == p3_repair_audit.get("selected_background_order_strategy")
    ]
    repair_input_ok = False
    events_path = ROOT / "supporting_materials/processed_data/unified_holdout/events.csv"
    if events_path.exists():
        repair_input = pd.read_csv(
            events_path,
            usecols=[
                "event_id", "source", "order_dt", "planned_date",
                "mandatory_background", "evaluation_cohort", "upper_minutes",
            ],
            low_memory=False,
        )
        repair_input["evaluation_cohort"] = scheduler.as_bool(
            repair_input["evaluation_cohort"]
        )
        repair_input["mandatory_background"] = scheduler.as_bool(
            repair_input["mandatory_background"]
        )
        repair_input = repair_input[repair_input["evaluation_cohort"]].copy()
        repair_input["case_date"] = pd.to_datetime(
            repair_input["order_dt"]
        ).dt.normalize()
        background_mask = repair_input["mandatory_background"]
        repair_input.loc[background_mask, "case_date"] = pd.to_datetime(
            repair_input.loc[background_mask, "planned_date"]
        ).dt.normalize()
        repair_input["upper_minutes"] = pd.to_numeric(
            repair_input["upper_minutes"], errors="raise"
        )
        daily_peak = (
            repair_input.groupby("case_date", as_index=False)
            .agg(
                event_count=("event_id", "size"),
                upper_minutes_total=("upper_minutes", "sum"),
            )
            .sort_values(
                ["upper_minutes_total", "case_date"],
                ascending=[False, True],
                kind="stable",
            )
            .iloc[0]
        )
        expected_date = pd.Timestamp(daily_peak["case_date"])
        expected_events = repair_input[repair_input["case_date"].eq(expected_date)]
        expected_sources = expected_events["source"].value_counts().to_dict()
        repair_input_ok = (
            p3_repair_audit.get("date") == str(expected_date.date())
            and int(p3_repair_audit.get("event_count", -1))
            == int(daily_peak["event_count"])
            and int(p3_repair_audit.get("upper_minutes_total", -1))
            == int(daily_peak["upper_minutes_total"])
            and int(p3_repair_audit.get("inpatient_events", -1))
            == int(expected_sources.get("住院", 0))
            and int(p3_repair_audit.get("outpatient_events", -1))
            == int(expected_sources.get("门诊", 0))
            and int(p3_repair_audit.get("physical_exam_events", -1))
            == int(expected_sources.get("体检", 0))
        )
    repair_audit_ok = (
        p3_repair_audit.get("selection_rule")
        == (
            "evaluation case_date maximizing sum(upper_minutes); "
            "ties resolved by earliest case_date"
        )
        and int(p3_repair_audit.get("event_count", -1)) == repair_source_sum
        and repair_input_ok
        and repair_background
        == int(p3_repair_audit.get("outpatient_events", -1))
        + int(p3_repair_audit.get("physical_exam_events", -1))
        and repair_required == math.ceil(selected_alpha * repair_background)
        and p3_repair_audit.get("policy") == p2.get("selected_policy")
        and close(p3_repair_audit.get("alpha"), selected_alpha)
        and str(p3_repair_audit.get("alpha_source", "")).endswith(
            "supporting_materials/results/final_frozen/p3_joint/selection.json"
        )
        and p3_repair_audit.get("repair_triggered") is True
        and len(baseline_candidates) == 1
        and baseline_candidates[0].get("background_order_strategy") == "scarcity"
        and int(baseline_candidates[0].get("background_completed_events", -1))
        < repair_required
        and baseline_candidates[0].get("epsilon_constraint_satisfied") is False
        and int(baseline_candidates[0].get("background_deficit_events", -1))
        == repair_required
        - int(baseline_candidates[0].get("background_completed_events", -1))
        and len(repair_candidates_only) == 2
        and {
            candidate.get("background_order_strategy")
            for candidate in repair_candidates_only
        } == {"scarcity", "fcfs"}
        and all(
            candidate.get("epsilon_constraint_satisfied") is True
            and int(candidate.get("background_completed_events", -1)) >= repair_required
            and int(candidate.get("background_deficit_events", -1)) == 0
            for candidate in repair_candidates_only
        )
        and p3_repair_audit.get("selected_construction_method")
        == "global_deficit_repair"
        and p3_repair_audit.get("selected_background_order_strategy")
        in {"scarcity", "fcfs"}
        and p3_repair_audit.get("selected_epsilon_satisfied") is True
        and int(p3_repair_audit.get("selected_background_complete", -1))
        >= repair_required
        and len(selected_candidate_rows) == 1
        and int(selected_candidate_rows[0].get("background_completed_events", -1))
        == int(p3_repair_audit.get("selected_background_complete", -2))
        and int(selected_candidate_rows[0].get("inpatient_completed_events", -1))
        == int(p3_repair_audit.get("selected_inpatient_complete", -2))
        and selected_candidate_rows[0].get("epsilon_constraint_satisfied")
        is p3_repair_audit.get("selected_epsilon_satisfied")
        and set(repair_violations) == REQUIRED_REPAIR_VALIDATION_CHECKS
        and all(int(value) == 0 for value in repair_violations.values())
        and int(p3_repair_audit.get("validation_violation_count", -1))
        == sum(int(value) for value in repair_violations.values())
        and p3_repair_audit.get("repair_branch_optimality_claimed") is False
    )
    record(
        "p3_repair_path_audit_passed",
        repair_audit_ok,
        f"input_recomputed={repair_input_ok}; date={p3_repair_audit.get('date')}; baseline={baseline_candidates}; selected={p3_repair_audit.get('selected_construction_method')}/{p3_repair_audit.get('selected_background_order_strategy')}; validation_keys={sorted(repair_violations)}; violations={p3_repair_audit.get('validation_violation_count')}",
    )

    kernel_equivalent = (
        alpha_zero_equivalence.get("passed") is True
        and alpha_zero_equivalence.get("detail_saved") is True
        and alpha_zero_equivalence.get("alpha_match") is True
        and alpha_zero_equivalence.get("policy_match") is True
        and alpha_zero_equivalence.get("patient_constraint_scope_match") is True
        and alpha_zero_equivalence.get("transfer_setting_match") is True
        and int(alpha_zero_equivalence.get("p2_patient_overlap_violations", -1)) == 0
        and int(alpha_zero_equivalence.get("p2_patient_transfer_violations", -1)) == 0
        and int(alpha_zero_equivalence.get("p3_patient_overlap_violations", -1)) == 0
        and int(alpha_zero_equivalence.get("p3_patient_transfer_violations", -1)) == 0
        and alpha_zero_equivalence.get("complete_count_match") is True
        and int(alpha_zero_equivalence.get("task_mismatch_rows", -1)) == 0
        and int(alpha_zero_equivalence.get("outcome_mismatch_rows", -1)) == 0
        and alpha_zero_equivalence.get("selected_policy") == p2.get("selected_policy")
        and p2.get("patient_constraint_scope") == scheduler.PATIENT_CONSTRAINT_SCOPE
        and p3.get("patient_constraint_scope") == scheduler.PATIENT_CONSTRAINT_SCOPE
    )
    record(
        "p2_p3_kernel_equivalent",
        kernel_equivalent,
        "P3 alpha=0 inpatient tasks and outcomes must match selected P2 row for row",
    )
    record("p3_schedule_verification_passed", p3_verify_ok, p3_verify_detail)

    calibration_names = set(
        calibration.get("scenario", pd.Series(dtype=str)).astype(str)
    )
    expected_calibration_names = {
        "C0_historical_report", "C1_duration_only", "C2_standard_hours",
        "C3_doctor_capacity", "C4_project_capability",
        "C5_item_preparation", "C6_joint_background", "C7_formal_heuristic",
    }
    calibration_match = (
        calibration_names == expected_calibration_names
        and len(calibration) == len(expected_calibration_names)
        and {"completed", "total", "rate", "policy", "warmup_in_statistics"}.issubset(
            calibration
        )
    )
    if calibration_match:
        by_name = calibration.set_index("scenario")
        selected_metrics = p3.get("selected_metrics", {})
        model_stages = sorted(expected_calibration_names - {"C0_historical_report"})
        evaluation_only = all(
            not truth(by_name.loc[name, "warmup_in_statistics"])
            and close(by_name.loc[name, "total"], p2_metrics.get("inpatient_events"))
            and str(by_name.loc[name, "policy"]) == str(p2.get("selected_policy"))
            for name in model_stages
        )
        calibration_match = (
            close(by_name.loc["C0_historical_report", "total"], p2_metrics.get("inpatient_events"))
            and not truth(by_name.loc["C0_historical_report", "warmup_in_statistics"])
            and evaluation_only
            and close(by_name.loc["C5_item_preparation", "completed"], p2_metrics.get("inpatient_complete_48h"))
            and close(by_name.loc["C5_item_preparation", "total"], p2_metrics.get("inpatient_events"))
            and close(by_name.loc["C5_item_preparation", "rate"], p2_metrics.get("inpatient_48h_rate"))
            and close(by_name.loc["C6_joint_background", "completed"], selected_metrics.get("inpatient_complete_48h"))
            and close(by_name.loc["C6_joint_background", "total"], selected_metrics.get("inpatient_events"))
            and close(by_name.loc["C6_joint_background", "rate"], selected_metrics.get("inpatient_48h_rate"))
            and close(by_name.loc["C7_formal_heuristic", "completed"], by_name.loc["C6_joint_background", "completed"])
            and close(by_name.loc["C7_formal_heuristic", "rate"], by_name.loc["C6_joint_background", "rate"])
        )
    record(
        "historical_calibration_exists",
        calibration_match,
        f"scenarios={sorted(calibration_names)}; all rates exclude warm-up; C5=P2 and C6/C7=selected P3",
    )

    sensitivity_names = set(
        sensitivity.get("audit_scenario", pd.Series(dtype=str)).astype(str)
    )
    sensitivity_issues = sensitivity_validation_issues(sensitivity, p2, p3)
    sensitivity_valid = not sensitivity_issues
    prep_names = set(prep.get("audit_scenario", pd.Series(dtype=str)).astype(str))
    record(
        "preparation_sensitivity_exists",
        prep_names == {"preparation_item", "preparation_event"}
        and sensitivity_valid,
        f"preparation_scenarios={sorted(prep_names)}; issues={sensitivity_issues[:10]}",
    )
    record(
        "sensitivity_scenarios_complete",
        sensitivity_names == ALL_SENSITIVITY_SCENARIOS
        and sensitivity_valid,
        f"required={sorted(ALL_SENSITIVITY_SCENARIOS)}; actual={sorted(sensitivity_names)}; issues={sensitivity_issues[:10]}",
    )
    record(
        "multi_seed_exists",
        SEED_SCENARIOS.issubset(sensitivity_names)
        and int(seed_summary.get("seed_count", 0)) == len(SEED_SCENARIOS)
        and sensitivity_valid,
        f"required={sorted(SEED_SCENARIOS)}; count={seed_summary.get('seed_count', 0)}; issues={sensitivity_issues[:10]}",
    )

    record(
        "paper_numbers_match_final_results",
        paper_consistency.get("passed") is True,
        f"consistency passed={paper_consistency.get('passed')!r}",
    )
    record(
        "authoritative_result_unique",
        not (RESULTS / "unified_schedule").exists(),
        "legacy supporting_materials/results/unified_schedule must be absent",
    )

    authoritative_paths = [
        P2 / "summary.json", P2 / "policy_metrics.csv",
        P2 / "final_patient_task_schedule.csv", P2 / "final_patient_outcomes.csv",
        P2 / "failure_reason_breakdown.csv", P2 / "independent_verification.json",
        P3 / "selection.json",
        P3 / "pareto_metrics.csv", P3 / "final_patient_task_schedule.csv",
        P3 / "final_patient_outcomes.csv", P3 / "epsilon_diagnostics.json",
        P3 / "independent_verification.json",
        P3 / "p2_p3_alpha_zero_equivalence.json",
        scenarios.p3_shard(0.0) / "metrics.csv",
        scenarios.p3_shard(0.0) / "final_patient_task_schedule.csv",
        scenarios.p3_shard(0.0) / "final_patient_outcomes.csv",
        FROZEN / "sensitivity_metrics.csv", FROZEN / "special_seed_summary.json",
        FROZEN / "preparation_granularity_sensitivity.csv",
        EXACT / "exact_vs_heuristic_metrics.csv",
        P3_EXACT / "p3_exact_vs_heuristic_metrics.csv",
        P3_EXACT / "p3_repair_path_audit.json",
        CALIBRATION / "calibration_metrics.csv",
        VALIDATION / "input_semantic_verification.json",
        RESULTS / "p1" / "peak_flat_summary.csv",
        RESULTS / "p1" / "chronological_validation.csv",
        RESULTS / "p1" / "analysis_summary.json",
        CAPABILITY / "LEGACY_50_FALLBACK_PROJECT_AUDIT.csv",
        CAPABILITY / "FALLBACK_PROJECT_REVIEW.csv",
        CAPABILITY / "P2_CAPABILITY_FAILURE_DECOMPOSITION.csv",
        paper_consistency_path,
    ]
    required_files_present = all(
        path.exists() and path.stat().st_size > 0 for path in authoritative_paths
    )
    record(
        "all_authoritative_files_present",
        required_files_present,
        "all manifest inputs must exist and be non-empty",
    )

    frozen = all(freeze_checks.values())
    generated_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()
    manifest = {
        "MODEL_AND_RESULTS_FROZEN": frozen,
        "generated_at": generated_at,
        "generated_by": "supporting_materials/code/finalize_model_audits.py",
        "random_seed": 20260824,
        "special_seed_experiment": [11, 29, 47, 83, 131],
        "training_period": ["2019-03-01", "2024-03-31"],
        "evaluation_period": ["2024-04-01", "2025-03-31"],
        "main_assumptions": {
            "work_blocks": "08:00-12:00 and 13:00-17:00",
            "slot_minutes": 5,
            "transfer_minutes": 10,
            "bladder_minutes": 60,
            "preparation_granularity": "item",
            "capability": "Table-1 project-level A/B/C reviewed mapping; D excluded",
            "doctor_capacity": "training weekday-by-slot concurrent proxy",
            "report_completion": "last scheduled task end proxy",
        },
        "p2": p2,
        "p3": p3,
        "selected_alpha": selected_alpha,
        "paper_numbers_match_final_results": freeze_checks[
            "paper_numbers_match_final_results"
        ],
        "freeze_checks": freeze_checks,
        "freeze_check_evidence": evidence,
        "artifact_errors": errors,
        "authoritative_files": [
            {
                "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "exists": path.exists(),
                "size_bytes": path.stat().st_size if path.exists() else 0,
            }
            for path in authoritative_paths
        ],
    }
    FROZEN.mkdir(parents=True, exist_ok=True)
    (FROZEN / "FINAL_RESULT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    failed = [name for name, passed in freeze_checks.items() if not passed]
    checklist = "\n".join(
        f"| `{name}` | {'PASS' if passed else 'FAIL'} | "
        f"{evidence[name].replace('|', '/')} |"
        for name, passed in freeze_checks.items()
    )
    p2_result = p2.get("metrics", {})
    p3_result = p3.get("selected_metrics", {})
    report = f"""# 第二阶段最终技术审计报告

## 1. 冻结结论

`MODEL_AND_RESULTS_FROZEN = {'TRUE' if frozen else 'FALSE'}`。

本结论由当前代码和当前结果逐项重算，不沿用旧 QA 报告中的 PASS。未通过项：{', '.join(failed) if failed else '无'}。

## 2. 当前权威方案

- P2 候选策略数：{len(p2_policies)}；固定词典序选中：`{p2.get('selected_policy', '未生成')}`。
- P2 住院 48 小时完整完成：{p2_result.get('inpatient_complete_48h', '未生成')}/{p2_result.get('inpatient_events', '未生成')}。
- P3 扫描点数：{len(p3_scan)}；选中 alpha：{selected_alpha if selected_alpha is not None else '未生成'}。
- P3 住院 48 小时完整完成：{p3_result.get('inpatient_complete_48h', '未生成')}/{p3_result.get('inpatient_events', '未生成')}。
- P3 全年背景 ε 目标/完成：{p3_result.get('background_required_events', '未生成')}/{p3_result.get('background_completed_events', '未生成')}。

## 3. 模型与算法核验边界

P2 策略选择按代码中的固定词典序重算；slack 仅指“到院窗口余量”，不是动态排程时刻剩余量。P2 与 P3 共用患者、项目、房间、医生容量和跨室转运内核。P3 正式约束只使用全年整数下限 `background_completed >= ceil(alpha * total_background)`，逐日 quota 不进入约束。启发式 Pareto 前沿仅称为“已达到的非支配解集”，不宣称全年全局最优。

## 4. 冻结检查

| 检查 | 结果 | 当前证据 |
|---|---|---|
{checklist}

## 5. 产物读取异常

{json.dumps(errors, ensure_ascii=False, indent=2) if errors else '无。'}

## 6. 结论

只有全部检查为 PASS，且论文—结果一致性审计重新读取最终结果后也通过，manifest 才会写入 `MODEL_AND_RESULTS_FROZEN = true`。代表窗口的精确求解只验证相应子问题；全年 P2/P3 仍按确定性启发式可行解表述。
"""
    (ROOT / "SECOND_STAGE_FINAL_TECHNICAL_AUDIT.md").write_text(
        report, encoding="utf-8"
    )

    validation_report = f"""# FINAL_MODEL_VALIDATION_REPORT

## 输入语义

`input_semantics_passed = {freeze_checks['input_semantics_passed']}`。

## P2 排程可行性

`p2_schedule_verification_passed = {freeze_checks['p2_schedule_verification_passed']}`。独立验证器必须包含按 `patient_id` 跨全部 event 的互斥检查和相邻异室转运检查；旧版仅 event 内检查的 JSON 不满足冻结条件。

## P3 排程可行性

`p3_schedule_verification_passed = {freeze_checks['p3_schedule_verification_passed']}`。P3 还必须同时通过全年 ε 语义、无逐日 quota、精确小窗口和 alpha=0 内核等价检查。

## 最终状态

`MODEL_AND_RESULTS_FROZEN = {'TRUE' if frozen else 'FALSE'}`。未通过项：{', '.join(failed) if failed else '无'}。
"""
    VALIDATION.mkdir(parents=True, exist_ok=True)
    (VALIDATION / "FINAL_MODEL_VALIDATION_REPORT.md").write_text(
        validation_report, encoding="utf-8"
    )
    print(json.dumps(
        {"MODEL_AND_RESULTS_FROZEN": frozen, "checks": freeze_checks},
        ensure_ascii=False,
        indent=2,
    ))
    if not frozen:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
