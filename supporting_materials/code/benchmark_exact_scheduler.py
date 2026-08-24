"""Exact-vs-production benchmark utilities for the P2 inpatient scheduler.

The heuristic side calls the production scheduler directly. The CP-SAT side
uses the same loaded Event/Task objects, five-minute calendar, room set,
preparation semantics, transfer time and weekday-by-slot doctor capacity.
"""

from __future__ import annotations

import argparse
import inspect
import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

import run_unified_scheduler as scheduler


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "supporting_materials" / "results" / "exact_benchmark"
DEFAULT_TIME_LIMIT_SECONDS = 120.0
DEFAULT_CASE_WORKERS = 4
DEFAULT_SOLVER_WORKERS = 2
VALID_SOLVER_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)


@dataclass(frozen=True)
class BenchmarkCase:
    """A calendar-local benchmark cohort."""

    name: str
    date: pd.Timestamp
    event_ids: tuple[str, ...]
    target_size: int


@dataclass
class ExactResult:
    """CP-SAT outcome plus a schedule used for independent constraint checks."""

    status: str
    objective_value: int
    best_bound: float
    solve_seconds: float
    schedule: pd.DataFrame
    background_completed: int
    inpatient_completed: int
    required_background: int
    violation_counts: dict[str, int]


def _date_nearest(series: pd.Series, target: float) -> pd.Timestamp:
    return pd.Timestamp((series.astype(float) - float(target)).abs().idxmin())


def _event_features(
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
) -> pd.DataFrame:
    frame = events.copy()
    frame["multi"] = frame["service_project_count"].gt(1)
    frame["bedside_task"] = frame["event_id"].map(
        lambda event_id: any(task.bedside for task in tasks[str(event_id)])
    )
    frame["obstetric_task"] = frame["event_id"].map(
        lambda event_id: any(task.category == "产科III/IV级" for task in tasks[str(event_id)])
    )
    frame["minimum_room_count"] = frame["event_id"].map(
        lambda event_id: min(
            (len(task.compatible_rooms) for task in tasks[str(event_id)]),
            default=0,
        )
    )
    frame["equipment_pressure"] = frame["minimum_room_count"].between(1, 2)
    return frame


def representative_p2_cases(
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
) -> list[BenchmarkCase]:
    """Select deterministic P2 windows, including materially larger loads."""

    inpatient = _event_features(
        events[(~events["mandatory_background"]) & events["evaluation_cohort"]],
        tasks,
    )
    inpatient["case_date"] = inpatient["order_dt"].dt.normalize()
    daily = inpatient.groupby("case_date").agg(
        events=("event_id", "size"),
        multi_count=("multi", "sum"),
        bedside_count=("bedside_task", "sum"),
        obstetric_count=("obstetric_task", "sum"),
        equipment_pressure_count=("equipment_pressure", "sum"),
    )
    weekday = daily[daily.index.dayofweek < 5]
    weekend = daily[daily.index.dayofweek >= 5]
    definitions = [
        ("normal_weekday", _date_nearest(weekday["events"], weekday["events"].median()), 20, None),
        ("peak_weekday", pd.Timestamp(weekday["events"].idxmax()), 100, None),
        ("weekend", pd.Timestamp(weekend["events"].idxmax()), 40, None),
        ("multi_project_peak", pd.Timestamp(daily["multi_count"].idxmax()), 40, "multi"),
        ("bedside_peak", pd.Timestamp(daily["bedside_count"].idxmax()), 20, "bedside_task"),
        ("obstetric_peak", pd.Timestamp(daily["obstetric_count"].idxmax()), 40, "obstetric_task"),
    ]
    cases: list[BenchmarkCase] = []
    for name, date, target_size, priority_column in definitions:
        group = inpatient[inpatient["case_date"].eq(date)].copy()
        sort_columns: list[str] = []
        ascending: list[bool] = []
        if priority_column is not None:
            sort_columns.append(priority_column)
            ascending.append(False)
            sort_columns.append("service_project_count")
            ascending.append(False)
        sort_columns.extend(["order_dt", "event_id"])
        ascending.extend([True, True])
        selected = group.sort_values(sort_columns, ascending=ascending, kind="stable").head(target_size)
        cases.append(
            BenchmarkCase(
                name=name,
                date=pd.Timestamp(date),
                event_ids=tuple(selected["event_id"].astype(str)),
                target_size=target_size,
            )
        )
    return cases


def make_calendar(
    date: pd.Timestamp,
    rooms: list[str],
    capacity: pd.DataFrame,
    *,
    policy: str,
    capacity_column: str = "capacity_main",
    transfer_minutes: int = scheduler.TRANSFER_MINUTES,
) -> scheduler.WorkCalendar:
    """Create the same three-calendar-day state used by both benchmark arms."""

    start_date = pd.Timestamp(date).normalize()
    return scheduler.create_calendar(
        capacity,
        rooms,
        policy,
        capacity_column,
        transfer_minutes,
        start_date=start_date,
        end_date_exclusive=start_date + pd.Timedelta(days=3),
    )


def _actual_slot(calendar: scheduler.WorkCalendar, timestamp: pd.Timestamp) -> int:
    delta = pd.Timestamp(timestamp) - pd.Timestamp(calendar.times[0])
    return int(delta.total_seconds() // (scheduler.SLOT_MINUTES * 60))


def feasible_start_values(
    calendar: scheduler.WorkCalendar,
    task: scheduler.Task,
    release: pd.Timestamp,
    deadline: pd.Timestamp,
) -> list[int]:
    """Return exact five-minute starts allowed by release/prep/deadline/workblocks."""

    task_release = max(pd.Timestamp(release), task.bladder_ready_dt) if task.bladder else pd.Timestamp(release)
    start_index = calendar.search_start(task_release)
    stop_index = min(
        int(calendar.times.searchsorted(deadline, side="left")),
        len(calendar.times) - task.duration_slots + 1,
    )
    values: list[int] = []
    for index in range(start_index, stop_index):
        if not calendar.fits_block(index, task.duration_slots):
            continue
        end = calendar.end_timestamp(index, task.duration_slots)
        if end > deadline:
            continue
        if task.fasting:
            start = calendar.times[index]
            if start.hour >= 10 or end > start.normalize() + pd.Timedelta(hours=10):
                continue
        values.append(_actual_slot(calendar, calendar.times[index]))
    return values


def _add_doctor_capacity(
    model: cp_model.CpModel,
    calendar: scheduler.WorkCalendar,
    task_intervals: list[cp_model.IntervalVar],
) -> None:
    """Encode the full weekday-by-five-minute doctor capacity exactly."""

    max_capacity = int(np.max(calendar.capacity)) if len(calendar.capacity) else 0
    if max_capacity <= 0:
        model.add(0 == 1)
        return
    intervals = list(task_intervals)
    demands: list[int] = [1] * len(task_intervals)
    slots = [_actual_slot(calendar, timestamp) for timestamp in calendar.times]
    segment_start: int | None = None
    segment_end: int | None = None
    segment_deficit: int | None = None
    segment_number = 0

    def flush() -> None:
        nonlocal segment_start, segment_end, segment_deficit, segment_number
        if segment_start is None or segment_end is None or not segment_deficit:
            segment_start = segment_end = segment_deficit = None
            return
        interval = model.new_fixed_size_interval_var(
            segment_start,
            segment_end - segment_start,
            f"doctor_capacity_block_{segment_number}",
        )
        intervals.append(interval)
        demands.append(segment_deficit)
        segment_number += 1
        segment_start = segment_end = segment_deficit = None

    for slot, capacity_value in zip(slots, calendar.capacity):
        deficit = max_capacity - int(capacity_value)
        if deficit <= 0:
            flush()
            continue
        if segment_start is None:
            segment_start, segment_end, segment_deficit = slot, slot + 1, deficit
        elif slot == segment_end and deficit == segment_deficit:
            segment_end += 1
        else:
            flush()
            segment_start, segment_end, segment_deficit = slot, slot + 1, deficit
    flush()
    model.add_cumulative(intervals, demands, max_capacity)


def _add_transfer_constraints(
    model: cp_model.CpModel,
    task_records: list[dict[str, Any]],
    transfer_slots: int,
) -> None:
    """Enforce patient non-overlap and room-change transfer for every task pair."""

    for left_index, left in enumerate(task_records):
        for right_index in range(left_index + 1, len(task_records)):
            right = task_records[right_index]
            order = model.new_bool_var(
                f"patient_order_{left['event_id']}_{left['item_index']}_{right['event_id']}_{right['item_index']}"
            )
            for left_room, left_room_var in left["room_vars"].items():
                for right_room, right_room_var in right["room_vars"].items():
                    gap = 0 if left_room == right_room else transfer_slots
                    model.add(
                        right["start"] >= left["start"] + left["duration"] + gap
                    ).only_enforce_if([order, left_room_var, right_room_var])
                    model.add(
                        left["start"] >= right["start"] + right["duration"] + gap
                    ).only_enforce_if([order.negated(), left_room_var, right_room_var])


def _schedule_from_solver(
    solver: cp_model.CpSolver,
    event_vars: dict[str, cp_model.IntVar],
    task_records: list[dict[str, Any]],
    event_lookup: pd.DataFrame,
    calendar: scheduler.WorkCalendar,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    origin = pd.Timestamp(calendar.times[0])
    for record in task_records:
        event_id = record["event_id"]
        if not solver.boolean_value(event_vars[event_id]):
            continue
        room_id = next(
            room for room, variable in record["room_vars"].items() if solver.boolean_value(variable)
        )
        start_slot = int(solver.value(record["start"]))
        start_dt = origin + pd.Timedelta(minutes=start_slot * scheduler.SLOT_MINUTES)
        end_dt = start_dt + pd.Timedelta(minutes=record["duration"] * scheduler.SLOT_MINUTES)
        event = event_lookup.loc[event_id]
        rows.append(
            {
                "event_id": event_id,
                "patient_id": str(event.patient_id),
                "source": str(event.source),
                "item_index": int(record["item_index"]),
                "room_id": str(room_id),
                "start_slot": start_slot,
                "end_slot": start_slot + int(record["duration"]),
                "start_dt": start_dt,
                "end_dt": end_dt,
            }
        )
    return pd.DataFrame(rows)


def validate_exact_schedule(
    schedule: pd.DataFrame,
    selected_ids: set[str],
    event_ids: Iterable[str],
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    calendar: scheduler.WorkCalendar,
    required_background: int,
) -> dict[str, int]:
    """Independently recount each modeled constraint on the extracted schedule."""

    keys = [
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
    ]
    violations = {key: 0 for key in keys}
    event_lookup = events.set_index("event_id")
    event_ids = list(event_ids)
    task_lookup = {
        (event_id, task.item_index): task
        for event_id in event_ids
        for task in tasks[event_id]
    }
    counts = {} if schedule.empty else schedule.groupby("event_id").size().astype(int).to_dict()
    for event_id in event_ids:
        expected = len(tasks[event_id]) if event_id in selected_ids else 0
        violations["event_completeness"] += int(counts.get(event_id, 0) != expected)

    timestamp_index = {pd.Timestamp(timestamp): index for index, timestamp in enumerate(calendar.times)}
    for row in schedule.itertuples(index=False):
        task = task_lookup[(row.event_id, int(row.item_index))]
        event = event_lookup.loc[row.event_id]
        violations["room_compatibility"] += int(str(row.room_id) not in task.compatible_rooms)
        release = max(pd.Timestamp(event.release_dt), task.bladder_ready_dt) if task.bladder else pd.Timestamp(event.release_dt)
        violations["release_or_preparation"] += int(pd.Timestamp(row.start_dt) < release)
        violations["deadline"] += int(pd.Timestamp(row.end_dt) > pd.Timestamp(event.deadline_dt))
        if task.fasting:
            start = pd.Timestamp(row.start_dt)
            end = pd.Timestamp(row.end_dt)
            violations["fasting_window"] += int(start.hour >= 10 or end > start.normalize() + pd.Timedelta(hours=10))
        index = timestamp_index.get(pd.Timestamp(row.start_dt))
        violations["workblock"] += int(index is None or not calendar.fits_block(int(index), task.duration_slots))

    if not schedule.empty:
        for _, group in schedule.groupby("room_id"):
            ordered = group.sort_values(["start_slot", "end_slot", "event_id", "item_index"], kind="stable")
            previous_end = -1
            for row in ordered.itertuples(index=False):
                violations["room_overlap"] += int(int(row.start_slot) < previous_end)
                previous_end = max(previous_end, int(row.end_slot))

        for _, group in schedule.groupby("patient_id"):
            ordered = group.sort_values(["start_slot", "end_slot", "event_id", "item_index"], kind="stable")
            previous_end = -1
            previous_room: str | None = None
            for row in ordered.itertuples(index=False):
                required_start = previous_end
                if previous_room is not None and previous_room != str(row.room_id):
                    required_start += calendar.transfer_slots
                violations["patient_overlap_or_transfer"] += int(int(row.start_slot) < required_start)
                previous_end = int(row.end_slot)
                previous_room = str(row.room_id)

    slot_load: dict[int, int] = {}
    if not schedule.empty:
        for row in schedule.itertuples(index=False):
            for slot in range(int(row.start_slot), int(row.end_slot)):
                slot_load[slot] = slot_load.get(slot, 0) + 1
    capacity_by_slot = {
        _actual_slot(calendar, timestamp): int(value)
        for timestamp, value in zip(calendar.times, calendar.capacity)
    }
    violations["doctor_capacity"] = sum(
        int(load > capacity_by_slot.get(slot, 0)) for slot, load in slot_load.items()
    )
    selected_background = sum(
        int(event_id in selected_ids and bool(event_lookup.loc[event_id, "mandatory_background"]))
        for event_id in event_ids
    )
    violations["background_minimum"] = int(selected_background < required_background)
    return violations


def solve_exact_subset(
    case: BenchmarkCase,
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    *,
    alpha: float = 0.0,
    policy: str,
    capacity_column: str = "capacity_main",
    transfer_minutes: int = scheduler.TRANSFER_MINUTES,
    time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
    solver_workers: int = DEFAULT_SOLVER_WORKERS,
) -> ExactResult:
    """Solve the exact complete-event epsilon model on one benchmark subset."""

    event_ids = list(case.event_ids)
    subset = events[events["event_id"].isin(event_ids)].copy()
    if len(subset) != len(event_ids):
        raise ValueError(f"case {case.name} contains event ids absent from the production input")
    if "evaluation_cohort" in subset and not bool(subset["evaluation_cohort"].all()):
        raise ValueError(f"case {case.name} mixes evaluation and non-evaluation events")
    event_lookup = subset.set_index("event_id")
    calendar = make_calendar(
        case.date,
        rooms,
        capacity,
        policy=policy,
        capacity_column=capacity_column,
        transfer_minutes=transfer_minutes,
    )
    model = cp_model.CpModel()
    event_vars: dict[str, cp_model.IntVar] = {
        event_id: model.new_bool_var(f"complete_{event_id}") for event_id in event_ids
    }
    room_intervals: dict[str, list[cp_model.IntervalVar]] = {room: [] for room in rooms}
    patient_intervals: dict[str, list[cp_model.IntervalVar]] = {}
    patient_records: dict[str, list[dict[str, Any]]] = {}
    doctor_intervals: list[cp_model.IntervalVar] = []
    task_records: list[dict[str, Any]] = []

    for event_id in event_ids:
        event = event_lookup.loc[event_id]
        selected = event_vars[event_id]
        event_possible = True
        for task in tasks[event_id]:
            if str(task.patient_id) != str(event.patient_id):
                raise ValueError(
                    f"task/event patient mismatch for {event_id}: {task.patient_id} != {event.patient_id}"
                )
            compatible_rooms = [room for room in task.compatible_rooms if room in calendar.room_index]
            starts = feasible_start_values(calendar, task, event.release_dt, event.deadline_dt)
            if not compatible_rooms or not starts:
                event_possible = False
                continue
            start_var = model.new_int_var_from_domain(
                cp_model.Domain.from_values(starts),
                f"start_{event_id}_{task.item_index}",
            )
            room_vars: dict[str, cp_model.IntVar] = {}
            for room in compatible_rooms:
                room_var = model.new_bool_var(f"room_{event_id}_{task.item_index}_{room}")
                room_vars[room] = room_var
                room_intervals[room].append(
                    model.new_optional_fixed_size_interval_var(
                        start_var,
                        task.duration_slots,
                        room_var,
                        f"room_iv_{event_id}_{task.item_index}_{room}",
                    )
                )
            model.add(sum(room_vars.values()) == selected)
            master_interval = model.new_optional_fixed_size_interval_var(
                start_var,
                task.duration_slots,
                selected,
                f"task_iv_{event_id}_{task.item_index}",
            )
            patient_id = str(task.patient_id)
            patient_intervals.setdefault(patient_id, []).append(master_interval)
            doctor_intervals.append(master_interval)
            record = {
                "event_id": event_id,
                "item_index": task.item_index,
                "task": task,
                "start": start_var,
                "duration": task.duration_slots,
                "room_vars": room_vars,
            }
            task_records.append(record)
            patient_records.setdefault(patient_id, []).append(record)
        if not event_possible:
            model.add(selected == 0)

    for intervals in room_intervals.values():
        if intervals:
            model.add_no_overlap(intervals)
    for patient_id, intervals in patient_intervals.items():
        if intervals:
            model.add_no_overlap(intervals)
            _add_transfer_constraints(model, patient_records[patient_id], calendar.transfer_slots)
    _add_doctor_capacity(model, calendar, doctor_intervals)

    background_ids = [
        event_id for event_id in event_ids if bool(event_lookup.loc[event_id, "mandatory_background"])
    ]
    inpatient_ids = [event_id for event_id in event_ids if event_id not in background_ids]
    required_background = int(math.ceil(float(alpha) * len(background_ids)))
    if background_ids:
        model.add(sum(event_vars[event_id] for event_id in background_ids) >= required_background)
    elif required_background:
        raise ValueError("positive background target without background events")
    objective_ids = inpatient_ids if background_ids else event_ids
    model.maximize(sum(event_vars[event_id] for event_id in objective_ids))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_seconds)
    solver.parameters.num_search_workers = int(max(1, solver_workers))
    started = time.perf_counter()
    status = solver.solve(model)
    elapsed = time.perf_counter() - started
    status_name = solver.status_name(status)
    if status not in VALID_SOLVER_STATUSES:
        return ExactResult(
            status=status_name,
            objective_value=0,
            best_bound=float(len(objective_ids)),
            solve_seconds=elapsed,
            schedule=pd.DataFrame(),
            background_completed=0,
            inpatient_completed=0,
            required_background=required_background,
            violation_counts={"solver_no_incumbent": 1},
        )

    selected_ids = {
        event_id for event_id, variable in event_vars.items() if solver.boolean_value(variable)
    }
    schedule_frame = _schedule_from_solver(solver, event_vars, task_records, event_lookup, calendar)
    violations = validate_exact_schedule(
        schedule_frame,
        selected_ids,
        event_ids,
        subset,
        tasks,
        calendar,
        required_background,
    )
    background_completed = sum(event_id in selected_ids for event_id in background_ids)
    inpatient_completed = sum(event_id in selected_ids for event_id in inpatient_ids)
    return ExactResult(
        status=status_name,
        objective_value=int(round(solver.objective_value)),
        best_bound=float(solver.best_objective_bound),
        solve_seconds=elapsed,
        schedule=schedule_frame,
        background_completed=int(background_completed),
        inpatient_completed=int(inpatient_completed),
        required_background=required_background,
        violation_counts=violations,
    )


def _plan_signature(plans: dict[str, list[scheduler.PlanStep]]) -> tuple[tuple[Any, ...], ...]:
    rows = []
    for event_id, steps in plans.items():
        for step in steps:
            rows.append(
                (
                    event_id,
                    step.task.item_index,
                    step.start_index,
                    step.room_id,
                    step.sequence_position,
                    step.transfer_slots_before,
                )
            )
    return tuple(sorted(rows))


def _heuristic_runtime_audit(
    plans: dict[str, list[scheduler.PlanStep]],
    replay_plans: dict[str, list[scheduler.PlanStep]],
    order: list[str],
    replay_order: list[str],
    event_ids: list[str],
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    calendar: scheduler.WorkCalendar,
    rooms: list[str],
) -> dict[str, bool]:
    lookup = events.set_index("event_id")
    steps = [step for event_id in plans for step in plans[event_id]]
    task_identity = all(any(step.task is task for task in tasks[step.task.event_id]) for step in steps)
    task_patient_identity = all(
        str(task.patient_id) == str(lookup.loc[event_id, "patient_id"])
        for event_id in event_ids
        for task in tasks[event_id]
    )
    complete_event_expansion = all(
        len(event_steps) == len(tasks[event_id])
        and {step.task.item_index for step in event_steps}
        == {task.item_index for task in tasks[event_id]}
        for event_id, event_steps in plans.items()
    )
    room_semantics = set(calendar.room_ids) == set(rooms) and all(
        step.room_id in step.task.compatible_rooms for step in steps
    )
    preparation_semantics = True
    deadline_semantics = True
    transfer_semantics = True
    workblock_semantics = True
    patient_timeline: dict[str, list[tuple[pd.Timestamp, pd.Timestamp, str]]] = {}
    for event_id, event_steps in plans.items():
        event = lookup.loc[event_id]
        ordered_steps = sorted(event_steps, key=lambda step: step.sequence_position)
        previous_end: pd.Timestamp | None = None
        previous_room: str | None = None
        for step in ordered_steps:
            start = pd.Timestamp(calendar.times[step.start_index])
            end = calendar.end_timestamp(step.start_index, step.task.duration_slots)
            release = max(pd.Timestamp(event.release_dt), step.task.bladder_ready_dt) if step.task.bladder else pd.Timestamp(event.release_dt)
            preparation_semantics &= start >= release
            if step.task.fasting:
                preparation_semantics &= start.hour < 10 and end <= start.normalize() + pd.Timedelta(hours=10)
            deadline_semantics &= end <= pd.Timestamp(event.deadline_dt)
            workblock_semantics &= calendar.fits_block(step.start_index, step.task.duration_slots)
            if previous_end is not None:
                required = previous_end
                expected_transfer = 0
                if previous_room != step.room_id:
                    expected_transfer = calendar.transfer_slots
                    required += pd.Timedelta(minutes=expected_transfer * scheduler.SLOT_MINUTES)
                transfer_semantics &= start >= required and step.transfer_slots_before == expected_transfer
            previous_end, previous_room = end, step.room_id
            patient_timeline.setdefault(str(step.task.patient_id), []).append((start, end, step.room_id))
    patient_nonoverlap = True
    for timeline in patient_timeline.values():
        timeline.sort()
        for left, right in zip(timeline, timeline[1:]):
            required = left[1]
            if left[2] != right[2]:
                required += pd.Timedelta(minutes=calendar.transfer_slots * scheduler.SLOT_MINUTES)
            patient_nonoverlap &= right[0] >= required
    return {
        "patient_event_identity": set(order) == set(event_ids) and len(order) == len(event_ids),
        "task_object_identity": bool(task_identity),
        "task_patient_identity": bool(task_patient_identity),
        "complete_event_task_expansion": bool(complete_event_expansion),
        "room_compatibility_and_choice": bool(room_semantics),
        "preparation_release": bool(preparation_semantics),
        "event_deadline": bool(deadline_semantics),
        "transfer": bool(transfer_semantics),
        "doctor_capacity": bool(np.all(calendar.doctor_load <= calendar.capacity)),
        "workblock": bool(workblock_semantics),
        "patient_nonoverlap": bool(patient_nonoverlap),
        "deterministic_tie_break": order == replay_order and _plan_signature(plans) == _plan_signature(replay_plans),
    }


def run_production_p2_heuristic(
    case: BenchmarkCase,
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    policy: str,
) -> tuple[int, dict[str, bool]]:
    """Run the unmodified production priority and scheduling functions."""

    event_ids = list(case.event_ids)
    subset = events[events["event_id"].isin(event_ids)].copy()
    calendar = make_calendar(case.date, rooms, capacity, policy=policy)
    order, plans, _ = scheduler.run_group_with_policy(
        calendar, subset, tasks, policy, "inpatient"
    )

    replay_calendar = make_calendar(case.date, rooms, capacity, policy=policy)
    replay_order, replay_plans, _ = scheduler.run_group_with_policy(
        replay_calendar, subset, tasks, policy, "inpatient"
    )
    audit = _heuristic_runtime_audit(
        plans,
        replay_plans,
        order,
        replay_order,
        event_ids,
        events,
        tasks,
        calendar,
        rooms,
    )
    return len(plans), audit


def solve_p2_case(
    case: BenchmarkCase,
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    policy: str,
    time_limit_seconds: float,
    solver_workers: int,
) -> dict[str, Any]:
    heuristic_value, equivalence = run_production_p2_heuristic(
        case, events, tasks, capacity, rooms, policy
    )
    exact = solve_exact_subset(
        case,
        events,
        tasks,
        capacity,
        rooms,
        policy=policy,
        time_limit_seconds=time_limit_seconds,
        solver_workers=solver_workers,
    )
    incumbent = exact.objective_value
    bound = exact.best_bound
    proved_optimal = exact.status == "OPTIMAL"
    has_incumbent = exact.status in {"OPTIMAL", "FEASIBLE"}
    incumbent_gap = (
        (incumbent - heuristic_value) / max(abs(incumbent), 1)
        if has_incumbent
        else float("nan")
    )
    row: dict[str, Any] = {
        "case": case.name,
        "date": str(case.date.date()),
        "policy": policy,
        "target_event_count": case.target_size,
        "event_count": len(case.event_ids),
        "heuristic_complete": heuristic_value,
        "exact_incumbent": incumbent,
        # Backward-compatible output fields used by the paper-table pipeline.
        # The legacy gap is populated only when optimality is actually proved.
        "exact_complete": incumbent,
        "best_bound": bound,
        "solver_relative_gap": (
            (bound - incumbent) / max(abs(bound), 1.0) if has_incumbent else float("nan")
        ),
        "heuristic_gap_to_incumbent": incumbent_gap,
        "heuristic_gap_to_exact": incumbent_gap if proved_optimal else float("nan"),
        "heuristic_gap_to_bound": (bound - heuristic_value) / max(abs(bound), 1.0),
        "solver_status": exact.status,
        "solve_seconds": exact.solve_seconds,
        "time_limit_seconds": time_limit_seconds,
        "exact_schedule_violations": int(sum(exact.violation_counts.values())),
    }
    row.update({f"equiv_{key}": value for key, value in equivalence.items()})
    return row


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = [
        "|" + "|".join(columns) + "|",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in frame.itertuples(index=False, name=None):
        lines.append("|" + "|".join(str(value).replace("|", "/") for value in row) + "|")
    return "\n".join(lines)


def _source_location(function: Any) -> str:
    path = Path(inspect.getsourcefile(function) or "unknown").resolve()
    line = inspect.getsourcelines(function)[1]
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        relative = path
    return f"`{relative.as_posix()}:{line}`"


def write_p2_reports(frame: pd.DataFrame) -> None:
    result_columns = [
        "case",
        "date",
        "event_count",
        "heuristic_complete",
        "exact_incumbent",
        "best_bound",
        "solver_status",
        "solver_relative_gap",
        "heuristic_gap_to_bound",
        "solve_seconds",
        "time_limit_seconds",
        "exact_schedule_violations",
    ]
    report_lines = [
        "# P2 Exact vs Heuristic Benchmark",
        "",
        "启发式结果由生产调度器直接生成；CP-SAT 在相同患者、项目、房间、准备、转运、医生容量和工作块下最大化48小时完整完成事件数。`FEASIBLE` 仅表示时限内可行 incumbent，未写作最优解。",
        f"生产策略：`{frame['policy'].iloc[0]}`。",
        "",
        _markdown_table(frame[result_columns]),
        "",
        f"OPTIMAL 场景数：{int(frame['solver_status'].eq('OPTIMAL').sum())}/{len(frame)}。",
        f"全部场景相对最好界的最大启发式差距上界：{frame['heuristic_gap_to_bound'].max():.4%}。",
        f"精确解提取后独立检查的违规总数：{int(frame['exact_schedule_violations'].sum())}。",
    ]
    (OUT / "EXACT_VS_HEURISTIC_REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")

    equivalence_columns = [column for column in frame if column.startswith("equiv_")]
    equivalence_ok = bool(frame[equivalence_columns].all(axis=None))
    audit_lines = [
        "# P2 精确基准与生产启发式实现等价性审计",
        "",
        f"P2_EXACT_IMPLEMENTATION_EQUIVALENCE = {'TRUE' if equivalence_ok else 'FALSE'}",
        "",
        "## 实现调用链",
        "",
        f"- P2生产策略解析：{_source_location(scheduler.resolve_authoritative_policy)}。",
        f"- 项目展开、能力、床旁与项目级准备：{_source_location(scheduler.load_inputs)}，基准直接复用其 `Task` 对象。",
        f"- 患者优先级：{_source_location(scheduler.event_priority)}。",
        f"- 共享调度入口：{_source_location(scheduler.run_group_with_policy)}。",
        f"- 完整事件构造：{_source_location(scheduler.schedule_group)} 调用 {_source_location(scheduler.plan_event)}。",
        f"- 项目排列候选：{_source_location(scheduler.task_order_candidates)}。",
        f"- 日历创建：{_source_location(scheduler.create_calendar)}；房间选择、医生容量与工作块：{_source_location(scheduler.WorkCalendar)}。",
        f"- 基准启发式入口：{_source_location(run_production_p2_heuristic)}，直接调用上述生产函数。",
        "",
        "## 逐项等价关系",
        "",
        "|项目|实现关系|运行期证据列|",
        "|---|---|---|",
        "|patient/event|基准不重建事件，直接使用 `events.event_id` 及原 `patient_id`|`equiv_patient_event_identity`|",
        "|task|启发式计划中的 `PlanStep.task` 必须是生产 `tasks[event_id]` 中同一对象|`equiv_task_object_identity`|",
        "|patient key|`Task.patient_id` 与事件 `patient_id` 一致，生产与精确模型均按该全局键互斥|`equiv_task_patient_identity`, `equiv_patient_nonoverlap`|",
        "|complete event|每个排入事件的项目索引集合与生产 `tasks[event_id]` 完全一致|`equiv_complete_event_task_expansion`|",
        "|room|直接使用完整生产房间集、兼容集合与 `WorkCalendar.room_choice`|`equiv_room_compatibility_and_choice`|",
        "|preparation|直接使用项目级 release、空腹和憋尿准备语义|`equiv_preparation_release`|",
        "|release/deadline|逐项目复核释放时刻及事件截止时刻|`equiv_preparation_release`, `equiv_event_deadline`|",
        "|transfer|生产 `patient_available` 与精确成对约束均在既有任务前、后双向检查；同室为0、跨室为10分钟|`equiv_transfer`, `equiv_patient_nonoverlap`|",
        "|doctor|直接使用 `capacity_main` 的星期×5分钟容量与生产占用数组|`equiv_doctor_capacity`|",
        "|workblock|直接使用 `WorkCalendar.fits_block` 的上午/下午块|`equiv_workblock`|",
        "|tie-break|同一空日历重复执行，比较事件顺序及完整计划签名|`equiv_deterministic_tie_break`|",
        "|patient non-overlap|按真实 `patient_id` 复核跨事件不重叠及跨室转运|`equiv_patient_nonoverlap`|",
        "",
        "## 运行期结果",
        "",
        _markdown_table(frame[["case", "event_count", *equivalence_columns]]),
        "",
        "该审计只证明基准启发式与当前生产实现共享同一语义和调用链；求解质量由各场景的 `solver_status`、incumbent、best bound 和 gap 单独说明。",
    ]
    (ROOT / "P2_EXACT_IMPLEMENTATION_EQUIVALENCE_AUDIT.md").write_text(
        "\n".join(audit_lines), encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--time-limit", type=float, default=DEFAULT_TIME_LIMIT_SECONDS)
    parser.add_argument("--parallel-cases", type=int, default=DEFAULT_CASE_WORKERS)
    parser.add_argument("--solver-workers", type=int, default=DEFAULT_SOLVER_WORKERS)
    parser.add_argument("--case", action="append", dest="case_names")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="solve the smallest case and print it without replacing official outputs",
    )
    args = parser.parse_args()
    events, tasks, capacity, rooms, _ = scheduler.load_inputs(
        "five_percent_upper", "hierarchical", 60, preparation_mode="item"
    )
    policy = scheduler.resolve_authoritative_policy(None)
    cases = representative_p2_cases(events, tasks)
    if args.case_names:
        wanted = set(args.case_names)
        cases = [case for case in cases if case.name in wanted]
        missing = wanted - {case.name for case in cases}
        if missing:
            parser.error(f"unknown cases: {sorted(missing)}")
    if args.validate_only:
        cases = [min(cases, key=lambda case: len(case.event_ids))]

    def solve(case: BenchmarkCase) -> dict[str, Any]:
        return solve_p2_case(
            case,
            events,
            tasks,
            capacity,
            rooms,
            policy,
            args.time_limit,
            args.solver_workers,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(args.parallel_cases, len(cases)))) as pool:
        rows = list(pool.map(solve, cases))
    frame = pd.DataFrame(rows)
    print(frame.to_string(index=False), flush=True)
    if args.validate_only:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT / "exact_vs_heuristic_metrics.csv", index=False, encoding="utf-8-sig")
    write_p2_reports(frame)


if __name__ == "__main__":
    main()
