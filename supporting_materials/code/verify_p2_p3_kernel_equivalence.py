"""Compare the selected P2 schedule with the P3 alpha-zero inpatient schedule."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import run_pre_freeze_scenarios as scenarios
import run_unified_scheduler as scheduler
from verify_unified_schedule import patient_timeline_violations


ROOT = Path(__file__).resolve().parents[2]
FROZEN = ROOT / "supporting_materials" / "results" / "final_frozen"
P2 = FROZEN / "p2_inpatient_only"
P3_ZERO = scenarios.p3_shard(0.0)
P3 = FROZEN / "p3_joint"
OUT = P3 / "p2_p3_alpha_zero_equivalence.json"

TASK_COLUMNS = [
    "event_id",
    "patient_id",
    "item_index",
    "sequence_position",
    "start_dt",
    "end_dt",
    "room_id",
    "duration_minutes",
    "transfer_minutes_before",
]
OUTCOME_COLUMNS = [
    "event_id",
    "complete_event",
    "deadline_met",
    "first_start_dt",
    "completion_dt",
    "failure_reason",
]


def normalized(frame: pd.DataFrame, columns: list[str], key: list[str]) -> pd.DataFrame:
    result = frame[columns].copy()
    for column in ["event_id", "patient_id", "room_id", "failure_reason"]:
        if column in result:
            result[column] = result[column].astype("string").fillna("")
    for column in ["start_dt", "end_dt", "first_start_dt", "completion_dt"]:
        if column in result:
            result[column] = pd.to_datetime(result[column], errors="coerce")
    return result.sort_values(key, kind="stable").reset_index(drop=True)


def mismatch_rows(left: pd.DataFrame, right: pd.DataFrame) -> int:
    if len(left) != len(right):
        return max(len(left), len(right))
    equal = left.eq(right) | (left.isna() & right.isna())
    return int((~equal.all(axis=1)).sum())


def main() -> None:
    p2_summary = json.loads((P2 / "summary.json").read_text(encoding="utf-8"))
    p3_selection = json.loads((P3 / "selection.json").read_text(encoding="utf-8"))
    p3_metrics = pd.read_csv(P3_ZERO / "metrics.csv").iloc[0]
    detail_saved = str(p3_metrics.get("detail_saved", False)).lower() == "true"
    alpha_match = abs(float(p3_metrics["background_target_alpha"])) <= 1e-12

    p2_schedule = pd.read_csv(P2 / "final_patient_task_schedule.csv", low_memory=False)
    p3_schedule = pd.read_csv(P3_ZERO / "final_patient_task_schedule.csv", low_memory=False)
    p3_schedule = p3_schedule[p3_schedule["source"].eq("住院")].copy()
    p2_tasks = normalized(p2_schedule, TASK_COLUMNS, ["event_id", "item_index"])
    p3_tasks = normalized(p3_schedule, TASK_COLUMNS, ["event_id", "item_index"])

    p2_outcomes = pd.read_csv(P2 / "final_patient_outcomes.csv", low_memory=False)
    p3_outcomes = pd.read_csv(P3_ZERO / "final_patient_outcomes.csv", low_memory=False)
    p3_outcomes = p3_outcomes[p3_outcomes["source"].eq("住院")].copy()
    p2_events = normalized(p2_outcomes, OUTCOME_COLUMNS, ["event_id"])
    p3_events = normalized(p3_outcomes, OUTCOME_COLUMNS, ["event_id"])

    task_mismatches = mismatch_rows(p2_tasks, p3_tasks)
    outcome_mismatches = mismatch_rows(p2_events, p3_events)
    policy_match = str(p2_summary["selected_policy"]) == str(p3_metrics["policy"])
    p2_transfer = int(p2_summary["metrics"]["transfer_minutes_assumption"])
    p3_transfer = int(p3_metrics["transfer_minutes"])
    transfer_setting_match = p2_transfer == p3_transfer
    p2_patient_overlap, p2_patient_transfer = patient_timeline_violations(
        p2_tasks, p2_transfer,
    )
    p3_patient_overlap, p3_patient_transfer = patient_timeline_violations(
        p3_tasks, p3_transfer,
    )
    patient_constraint_scope_match = (
        p2_summary.get("patient_constraint_scope") == scheduler.PATIENT_CONSTRAINT_SCOPE
        and p3_selection.get("patient_constraint_scope")
        == scheduler.PATIENT_CONSTRAINT_SCOPE
    )
    complete_count_match = (
        int(p2_summary["metrics"]["inpatient_complete_48h"])
        == int(p3_metrics["inpatient_complete_48h"])
    )
    passed = bool(
        detail_saved
        and alpha_match
        and policy_match
        and transfer_setting_match
        and patient_constraint_scope_match
        and p2_patient_overlap == 0
        and p2_patient_transfer == 0
        and p3_patient_overlap == 0
        and p3_patient_transfer == 0
        and complete_count_match
        and task_mismatches == 0
        and outcome_mismatches == 0
    )
    report = {
        "passed": passed,
        "alpha": 0.0,
        "alpha_match": alpha_match,
        "detail_saved": detail_saved,
        "selected_policy": p2_summary["selected_policy"],
        "p3_policy": str(p3_metrics["policy"]),
        "policy_match": policy_match,
        "patient_constraint_scope": scheduler.PATIENT_CONSTRAINT_SCOPE,
        "patient_constraint_scope_match": patient_constraint_scope_match,
        "transfer_setting_match": transfer_setting_match,
        "p2_transfer_minutes": p2_transfer,
        "p3_transfer_minutes": p3_transfer,
        "p2_patient_overlap_violations": p2_patient_overlap,
        "p2_patient_transfer_violations": p2_patient_transfer,
        "p3_patient_overlap_violations": p3_patient_overlap,
        "p3_patient_transfer_violations": p3_patient_transfer,
        "complete_count_match": complete_count_match,
        "p2_task_rows": len(p2_tasks),
        "p3_inpatient_task_rows": len(p3_tasks),
        "task_mismatch_rows": task_mismatches,
        "p2_outcome_rows": len(p2_events),
        "p3_inpatient_outcome_rows": len(p3_events),
        "outcome_mismatch_rows": outcome_mismatches,
        "comparison_columns": {
            "tasks": TASK_COLUMNS,
            "outcomes": OUTCOME_COLUMNS,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
