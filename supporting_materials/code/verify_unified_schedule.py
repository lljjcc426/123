"""Independent feasibility checks for the authoritative final schedule.

This verifier deliberately does not import the scheduler.  It reconstructs
duration, compatibility, interval and capacity checks from the exported input
and result tables so that implementation errors are not silently shared.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "supporting_materials" / "processed_data" / "unified_holdout"
SLOT_MINUTES = 5
TRANSFER_MINUTES = 10


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype("string").str.lower().isin(["true", "1", "yes"])


def room_set(value: object) -> set[str]:
    if pd.isna(value):
        return set()
    result: set[str] = set()
    for part in str(value).split("|"):
        if not part:
            continue
        number = float(part)
        result.add(str(int(number)) if number.is_integer() else part)
    return result


def slot_index(timestamp: pd.Timestamp) -> int | None:
    minute = timestamp.hour * 60 + timestamp.minute
    if 8 * 60 <= minute < 12 * 60:
        return (minute - 8 * 60) // SLOT_MINUTES
    if 13 * 60 <= minute < 17 * 60:
        return 48 + (minute - 13 * 60) // SLOT_MINUTES
    return None


def patient_timeline_violations(
    schedule: pd.DataFrame, transfer_minutes: int,
) -> tuple[int, int]:
    """Count adjacent patient overlaps and cross-room transfer shortfalls."""
    overlap = 0
    transfer_bad = 0
    for _, group in schedule.sort_values(
        ["patient_id", "start_dt", "end_dt", "event_id", "sequence_position"],
        kind="stable",
    ).groupby("patient_id", sort=False):
        if len(group) < 2:
            continue
        starts = group["start_dt"].iloc[1:].reset_index(drop=True)
        prior_ends = group["end_dt"].iloc[:-1].reset_index(drop=True)
        prior_rooms = group["room_id"].iloc[:-1].reset_index(drop=True)
        current_rooms = group["room_id"].iloc[1:].reset_index(drop=True)
        switches = current_rooms.ne(prior_rooms)
        overlap += int(starts.lt(prior_ends).sum())
        transfer_bad += int(
            (
                switches
                & starts.lt(prior_ends + pd.Timedelta(minutes=transfer_minutes))
            ).sum()
        )
    return overlap, transfer_bad


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result-dir", type=Path, required=True)
    parser.add_argument("--scenario", choices=["p2", "p3"])
    parser.add_argument("--preparation-mode", choices=["item", "event"], default="item")
    parser.add_argument("--transfer-minutes", type=int, default=TRANSFER_MINUTES)
    args = parser.parse_args()
    result_dir = args.result_dir
    events = pd.read_csv(
        INPUT / "events.csv",
        encoding="utf-8-sig",
        parse_dates=["order_dt", "planned_date", "base_release_dt", "bladder_ready_dt", "release_dt", "deadline_dt"],
    )
    items = pd.read_csv(INPUT / "items.csv", encoding="utf-8-sig", low_memory=False)
    schedule = pd.read_csv(
        result_dir / "final_patient_task_schedule.csv",
        encoding="utf-8-sig",
        parse_dates=["start_dt", "end_dt", "release_dt", "deadline_dt"],
        dtype={"room_id": "string"},
        low_memory=False,
    )
    outcomes = pd.read_csv(
        result_dir / "final_patient_outcomes.csv",
        encoding="utf-8-sig",
        parse_dates=["release_dt", "deadline_dt", "first_start_dt", "completion_dt"],
    )
    capacity = pd.read_csv(INPUT / "doctor_slot_capacity.csv", encoding="utf-8-sig")
    for frame, columns in [
        (events, ["mandatory_background", "special_case", "evaluation_cohort", "bedside", "fasting", "bladder"]),
        (items, ["item_bedside", "item_fasting", "item_bladder", "event_bedside", "event_fasting", "event_bladder"]),
        (schedule, ["bedside", "fasting", "bladder", "room_switch_from_previous"]),
        (outcomes, ["complete_event", "deadline_met", "evaluation_cohort"]),
    ]:
        for column in columns:
            frame[column] = as_bool(frame[column])

    checks: dict[str, dict[str, object]] = {}

    def record(name: str, violation_count: int, detail: object = "") -> None:
        checks[name] = {
            "passed": int(violation_count) == 0,
            "violation_count": int(violation_count),
            "detail": detail,
        }

    scenario = args.scenario or {
        "p2_inpatient_only": "p2",
        "p3_joint": "p3",
    }.get(result_dir.name)
    if scenario is None:
        raise ValueError(
            "cannot infer P2/P3 result scope from the directory name; pass --scenario"
        )

    for frame in (events, items, schedule, outcomes):
        frame["event_id"] = frame["event_id"].astype(str)
    schedule["patient_id"] = schedule["patient_id"].astype(str)

    expected_events = (
        events[~events["mandatory_background"]].copy()
        if scenario == "p2"
        else events.copy()
    )
    expected_event_ids = set(expected_events["event_id"])
    duplicate_outcomes = int(outcomes.duplicated("event_id").sum())
    record("outcome_event_id_unique", duplicate_outcomes)
    outcomes = outcomes.drop_duplicates("event_id", keep="first").copy()
    result_event_ids = set(outcomes["event_id"])
    missing_outcomes = expected_event_ids - result_event_ids
    unexpected_outcomes = result_event_ids - expected_event_ids
    record(
        "result_event_scope_complete",
        len(missing_outcomes) + len(unexpected_outcomes),
        {
            "scenario": scenario,
            "expected_state_events": len(expected_event_ids),
            "outcome_events": len(result_event_ids),
            "missing_count": len(missing_outcomes),
            "unexpected_count": len(unexpected_outcomes),
            "missing_examples": sorted(missing_outcomes)[:10],
            "unexpected_examples": sorted(unexpected_outcomes)[:10],
        },
    )
    outcome_scope = outcomes[
        ["event_id", "patient_id", "source", "evaluation_cohort"]
    ].merge(
        expected_events[["event_id", "patient_id", "source", "evaluation_cohort"]],
        on="event_id",
        how="left",
        suffixes=("_outcome", "_input"),
        indicator=True,
        validate="one_to_one",
    )
    evaluation_scope_bad = (
        outcome_scope["_merge"].ne("both")
        | outcome_scope["evaluation_cohort_outcome"].ne(
            outcome_scope["evaluation_cohort_input"]
        )
    )
    record(
        "outcome_evaluation_cohort_matches_input",
        int(evaluation_scope_bad.sum()),
        "warm-up events remain in scheduler state but are excluded from evaluation statistics",
    )
    patient_source_bad = (
        outcome_scope["_merge"].ne("both")
        | outcome_scope["patient_id_outcome"].astype(str).ne(
            outcome_scope["patient_id_input"].astype(str)
        )
        | outcome_scope["source_outcome"].astype(str).ne(
            outcome_scope["source_input"].astype(str)
        )
    )
    record(
        "outcome_patient_source_matches_input",
        int(patient_source_bad.sum()),
    )
    record(
        "scheduled_event_has_outcome",
        int((~schedule["event_id"].isin(result_event_ids)).sum()),
    )
    events = expected_events
    items = items[items["event_id"].isin(expected_event_ids)].copy()

    record(
        "unique_exported_task_key",
        int(schedule.duplicated(["event_id", "item_index"]).sum()),
        "each scheduled task must occur exactly once",
    )
    merged = schedule.merge(
        items,
        on=["event_id", "item_index"],
        how="left",
        suffixes=("_scheduled", "_input"),
        indicator=True,
        validate="many_to_one",
    )
    record("scheduled_task_exists_in_input", int(merged["_merge"].ne("both").sum()))
    prefix = "item" if args.preparation_mode == "item" else "event"
    merged["bedside_input"] = merged[f"{prefix}_bedside"]
    merged["fasting_input"] = merged[f"{prefix}_fasting"]
    merged["bladder_input"] = merged[f"{prefix}_bladder"]

    event_meta = events.set_index("event_id")
    scheduled_patient = merged["event_id"].map(event_meta["patient_id"]).astype(str)
    record(
        "scheduled_patient_matches_input",
        int(merged["patient_id"].astype(str).ne(scheduled_patient).sum()),
    )
    merged["special_case_input"] = merged["event_id"].map(event_meta["special_case"])
    merged["expected_duration_minutes"] = np.where(
        merged["special_case_input"],
        merged["duration_upper_min"],
        merged["duration_nominal_min"],
    )
    merged["expected_duration_minutes"] = (
        np.ceil(merged["expected_duration_minutes"].astype(float) / SLOT_MINUTES)
        .clip(lower=1)
        * SLOT_MINUTES
    )
    duration_bad = (
        merged["duration_minutes"].ne(merged["expected_duration_minutes"])
        | (merged["end_dt"] - merged["start_dt"]).dt.total_seconds().div(60).ne(
            merged["duration_minutes"]
        )
    )
    record("duration_matches_5pct_scenario", int(duration_bad.sum()))

    compat_bad = [
        room not in room_set(rooms)
        for room, rooms in zip(
            merged["room_id"].astype(str),
            np.where(merged["bedside_input"], merged["bedside_compatible_rooms"], merged["project_compatible_rooms"]),
        )
    ]
    record("project_room_compatibility", int(sum(compat_bad)))
    record(
        "bedside_uses_room_7",
        int((merged["bedside_input"] & merged["room_id"].ne("7")).sum()),
    )

    release_column = "base_release_dt" if args.preparation_mode == "item" else "release_dt"
    release = schedule["event_id"].map(event_meta[release_column])
    deadline = schedule["event_id"].map(event_meta["deadline_dt"])
    record("task_not_before_release", int(schedule["start_dt"].lt(release).sum()))
    record("task_complete_by_event_deadline", int(schedule["end_dt"].gt(deadline).sum()))
    bladder_ready = schedule["event_id"].map(pd.to_datetime(event_meta["bladder_ready_dt"]))
    record(
        "bladder_task_after_readiness",
        int((merged["bladder_input"] & merged["start_dt"].lt(bladder_ready.to_numpy())).sum()),
    )
    record(
        "five_minute_grid",
        int(
            (
                schedule["start_dt"].dt.minute.mod(SLOT_MINUTES).ne(0)
                | schedule["end_dt"].dt.minute.mod(SLOT_MINUTES).ne(0)
                | schedule["start_dt"].dt.second.ne(0)
                | schedule["end_dt"].dt.second.ne(0)
            ).sum()
        ),
    )

    block_bad = 0
    for row in schedule[["start_dt", "end_dt"]].itertuples(index=False):
        morning = row.start_dt.hour < 12 and row.end_dt <= row.start_dt.normalize() + pd.Timedelta(hours=12)
        afternoon = row.start_dt.hour >= 13 and row.end_dt <= row.start_dt.normalize() + pd.Timedelta(hours=17)
        if row.start_dt.normalize() != row.end_dt.normalize() or not (morning or afternoon):
            block_bad += 1
    record("inside_single_work_block", block_bad)

    fasting_bad = merged["fasting_input"] & merged["end_dt"].gt(
        merged["start_dt"].dt.normalize() + pd.Timedelta(hours=10)
    )
    record("fasting_complete_by_10", int(fasting_bad.sum()))

    room_overlap = 0
    for _, group in schedule.sort_values(["room_id", "start_dt"]).groupby("room_id", sort=False):
        room_overlap += int(group["start_dt"].iloc[1:].reset_index(drop=True).lt(
            group["end_dt"].iloc[:-1].reset_index(drop=True)
        ).sum())
    record("no_room_overlap", room_overlap)

    event_overlap = 0
    transfer_bad = 0
    sequence_bad = 0
    for _, group in schedule.sort_values(["event_id", "sequence_position"]).groupby("event_id", sort=False):
        expected_sequence = np.arange(1, len(group) + 1)
        sequence_bad += int((group["sequence_position"].to_numpy() != expected_sequence).sum())
        if len(group) < 2:
            continue
        starts = group["start_dt"].iloc[1:].reset_index(drop=True)
        ends = group["end_dt"].iloc[:-1].reset_index(drop=True)
        prior_rooms = group["room_id"].iloc[:-1].reset_index(drop=True)
        current_rooms = group["room_id"].iloc[1:].reset_index(drop=True)
        switches = current_rooms.ne(prior_rooms)
        event_overlap += int(starts.lt(ends).sum())
        transfer_bad += int((switches & starts.lt(ends + pd.Timedelta(minutes=args.transfer_minutes))).sum())
    record("contiguous_event_sequence_numbers", sequence_bad)
    record("no_same_event_task_overlap", event_overlap)
    record(
        "within_event_cross_room_transfer_at_least_configured_minutes",
        transfer_bad,
        {"transfer_minutes": args.transfer_minutes},
    )

    patient_overlap, patient_transfer_bad = patient_timeline_violations(
        schedule, args.transfer_minutes,
    )
    record("no_patient_task_overlap_across_events", patient_overlap)
    record(
        "adjacent_patient_cross_room_transfer_at_least_configured_minutes",
        patient_transfer_bad,
        {"transfer_minutes": args.transfer_minutes},
    )

    # Reconstruct doctor concurrency by expanding each scheduled interval to
    # its occupied 5-minute starts, then compare with weekday-slot capacity.
    occupied_parts: list[pd.DataFrame] = []
    for slots, group in schedule.groupby(schedule["duration_minutes"].floordiv(SLOT_MINUTES).astype(int)):
        base = group[["start_dt"]].reset_index(drop=True)
        repeated = pd.DataFrame(
            {
                "slot_dt": np.concatenate(
                    [
                        (base["start_dt"] + pd.Timedelta(minutes=offset * SLOT_MINUTES)).to_numpy()
                        for offset in range(int(slots))
                    ]
                )
            }
        )
        occupied_parts.append(repeated)
    occupied = pd.concat(occupied_parts, ignore_index=True)
    load = occupied.groupby("slot_dt", as_index=False).size().rename(columns={"size": "doctor_load"})
    load["weekday"] = load["slot_dt"].dt.dayofweek
    load["slot_index"] = load["slot_dt"].map(slot_index)
    cap = capacity[["weekday", "slot_index", "capacity_main"]]
    load = load.merge(cap, on=["weekday", "slot_index"], how="left", validate="many_to_one")
    record("doctor_capacity_defined", int(load["capacity_main"].isna().sum()))
    record(
        "doctor_concurrency_within_capacity",
        int(load["doctor_load"].gt(load["capacity_main"]).sum()),
        {
            "max_observed_load": int(load["doctor_load"].max()),
            "max_capacity": int(load["capacity_main"].max()),
        },
    )

    scheduled_count = schedule.groupby("event_id").size()
    expected_count = events.set_index("event_id")["service_project_count"]
    computed_complete = scheduled_count.reindex(expected_count.index, fill_value=0).eq(expected_count)
    outcome_complete = outcomes.set_index("event_id")["complete_event"].reindex(expected_count.index)
    record("outcome_complete_flag_consistency", int(computed_complete.ne(outcome_complete).sum()))
    computed_deadline = computed_complete.copy()
    completion = schedule.groupby("event_id")["end_dt"].max().reindex(expected_count.index)
    computed_deadline &= completion.le(events.set_index("event_id")["deadline_dt"])
    outcome_deadline = outcomes.set_index("event_id")["deadline_met"].reindex(expected_count.index)
    record("outcome_deadline_flag_consistency", int(computed_deadline.ne(outcome_deadline).sum()))

    passed = all(entry["passed"] for entry in checks.values())
    report = {
        "passed": passed,
        "scenario": scenario,
        "schedule_rows": int(len(schedule)),
        "scheduled_events": int(schedule["event_id"].nunique()),
        "input_events": int(len(events)),
        "evaluation_scope": {
            "state_events": int(len(events)),
            "evaluation_events": int(events["evaluation_cohort"].sum()),
            "warmup_state_events": int((~events["evaluation_cohort"]).sum()),
            "evaluation_inpatient_events": int(
                (events["evaluation_cohort"] & events["source"].eq("住院")).sum()
            ),
            "evaluation_background_events": int(
                (events["evaluation_cohort"] & ~events["source"].eq("住院")).sum()
            ),
            "warmup_in_statistics": False,
        },
        "checks": checks,
    }
    result_dir.mkdir(parents=True, exist_ok=True)
    (result_dir / "independent_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
