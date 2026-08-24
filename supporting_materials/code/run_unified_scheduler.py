"""Shared patient-, task- and room-level scheduling kernel for P2 and P3.

Policy dimensions are explicit: patient order, background order and room
tie-break.  P2 and P3 call the same calendar constructor and group scheduler;
P3 only adds the annual background epsilon controller around this kernel.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import build_unified_inputs as source_config


ROOT = Path(__file__).resolve().parents[2]
SUPPORTING = ROOT / "supporting_materials"
INPUT = SUPPORTING / "processed_data" / "unified_holdout"
OUT = SUPPORTING / "results" / "unified_schedule"

SLOT_MINUTES = 5
TRANSFER_MINUTES = 10
# The holdout closes at 2025-04-01 00:00.  Two calendar days are sufficient
# to represent the latest admissible 48-hour inpatient deadline (April 2);
# no arbitrary extra scheduling horizon is added.
FOLLOWUP_DAYS = 2

POLICIES = {
    "FCFS_SHARED": {
        "background": "fcfs", "inpatient": "fcfs", "room_mode": "lowest_id",
    },
    "SLACK_GUARD_SHARED": {
        "background": "fcfs", "inpatient": "slack", "room_mode": "lowest_id",
    },
    "FCFS_LOAD_BALANCED": {
        "background": "fcfs", "inpatient": "fcfs", "room_mode": "current_load",
    },
    "SLACK_LOAD_BALANCED": {
        "background": "fcfs", "inpatient": "slack", "room_mode": "current_load",
    },
    "FCFS_SCARCITY_PRESERVING": {
        "background": "scarcity", "inpatient": "fcfs", "room_mode": "scarcity_preserving",
    },
    "SLACK_SCARCITY_PRESERVING": {
        "background": "scarcity", "inpatient": "slack", "room_mode": "scarcity_preserving",
    },
    # Retained for backward-compatible replay of the previous joint candidate.
    "JOINT_SCARCITY": {
        "background": "scarcity", "inpatient": "slack", "room_mode": "scarcity_preserving",
    },
}
P2_POLICY_CANDIDATES = (
    "FCFS_SHARED",
    "SLACK_GUARD_SHARED",
    "FCFS_LOAD_BALANCED",
    "SLACK_LOAD_BALANCED",
    "FCFS_SCARCITY_PRESERVING",
    "SLACK_SCARCITY_PRESERVING",
)
P2_SUMMARY = SUPPORTING / "results" / "final_frozen" / "p2_inpatient_only" / "summary.json"

# Fixed before the second-stage rerun.  The tuple is minimized in this order.
P2_SELECTION_RULE = (
    "maximize inpatient_complete_48h",
    "minimize inpatient_wait_p90_hours_conditional",
    "minimize inpatient_wait_p50_hours_conditional",
    "minimize inpatient_room_switch_rate_multi",
    "minimize scheduled_minutes",
    "ascending stable policy id",
)
INPATIENT_SLACK_DEFINITION = (
    "arrival_window_slack_minutes=(deadline_dt-order_dt)-work_slots*5"
)
PATIENT_CONSTRAINT_SCOPE = (
    "patient_id across all events: no overlap; different-room adjacent tasks "
    "require configured transfer minutes in both temporal directions"
)


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype("string").str.lower().isin(["true", "1", "yes"])


def resolve_authoritative_policy(explicit_policy: str | None) -> str:
    """Resolve the production policy from CLI input or the frozen P2 selection."""
    if explicit_policy is not None:
        return explicit_policy
    if not P2_SUMMARY.exists():
        raise FileNotFoundError(
            "authoritative P2 policy is unavailable; run the P2 selection first "
            "or pass --main-policy explicitly"
        )
    policy = str(json.loads(P2_SUMMARY.read_text(encoding="utf-8"))["selected_policy"])
    if policy not in P2_POLICY_CANDIDATES:
        raise ValueError(f"unsupported selected P2 policy: {policy}")
    return policy


def room_tuple(value: Any) -> tuple[str, ...]:
    if pd.isna(value) or not str(value).strip():
        return ()
    normalized: set[str] = set()
    for part in str(value).split("|"):
        if not part:
            continue
        number = float(part)
        normalized.add(str(int(number)) if number.is_integer() else part)
    return tuple(sorted(normalized, key=int))


@dataclass(frozen=True)
class Task:
    event_id: str
    patient_id: str
    item_index: int
    project_norm: str
    category: str
    duration_slots: int
    compatible_rooms: tuple[str, ...]
    capability_level: str
    fasting: bool
    bladder: bool
    bedside: bool
    bladder_ready_dt: pd.Timestamp


@dataclass
class PlanStep:
    task: Task
    start_index: int
    room_id: str
    sequence_position: int
    transfer_slots_before: int


class WorkCalendar:
    def __init__(
        self,
        start_date: pd.Timestamp,
        end_date_exclusive: pd.Timestamp,
        room_ids: list[str],
        slot_capacity: pd.DataFrame,
        capacity_column: str,
        room_scarcity: dict[str, float],
        room_mode: str,
        transfer_minutes: int,
    ) -> None:
        dates = pd.date_range(start_date, end_date_exclusive - pd.Timedelta(days=1), freq="D")
        timestamps: list[pd.Timestamp] = []
        slot_in_day: list[int] = []
        block: list[int] = []
        for date in dates:
            for offset in range(48):
                timestamps.append(date + pd.Timedelta(hours=8, minutes=offset * SLOT_MINUTES))
                slot_in_day.append(offset)
                block.append(0)
            for offset in range(48):
                timestamps.append(date + pd.Timedelta(hours=13, minutes=offset * SLOT_MINUTES))
                slot_in_day.append(48 + offset)
                block.append(1)
        self.times = pd.DatetimeIndex(timestamps)
        self.slot_in_day = np.asarray(slot_in_day, dtype=np.int16)
        self.block = np.asarray(block, dtype=np.int8)
        self.day_values = self.times.normalize().to_numpy()
        self.room_ids = room_ids
        self.room_index = {room: index for index, room in enumerate(room_ids)}
        self.room_busy = np.zeros((len(room_ids), len(self.times)), dtype=bool)
        self.doctor_load = np.zeros(len(self.times), dtype=np.int16)
        self.capacity = self._capacity_array(slot_capacity, capacity_column)
        self.room_work_slots = {room: 0 for room in room_ids}
        self.room_scarcity = room_scarcity
        self.room_mode = room_mode
        self.transfer_slots = transfer_minutes // SLOT_MINUTES
        self.transfer_delta = pd.Timedelta(minutes=self.transfer_slots * SLOT_MINUTES)
        self.patient_intervals: dict[
            str, list[tuple[pd.Timestamp, pd.Timestamp, str]]
        ] = {}

    def clone(self) -> "WorkCalendar":
        """Copy mutable allocation state while sharing immutable calendar axes."""
        other = object.__new__(WorkCalendar)
        other.times = self.times
        other.slot_in_day = self.slot_in_day
        other.block = self.block
        other.day_values = self.day_values
        other.room_ids = self.room_ids
        other.room_index = self.room_index
        other.room_busy = self.room_busy.copy()
        other.doctor_load = self.doctor_load.copy()
        other.capacity = self.capacity
        other.room_work_slots = self.room_work_slots.copy()
        other.room_scarcity = self.room_scarcity
        other.room_mode = self.room_mode
        other.transfer_slots = self.transfer_slots
        other.transfer_delta = self.transfer_delta
        other.patient_intervals = {
            patient_id: list(intervals)
            for patient_id, intervals in self.patient_intervals.items()
        }
        return other

    def _capacity_array(self, frame: pd.DataFrame, column: str) -> np.ndarray:
        lookup = {
            (int(row.weekday), int(row.slot_index)): int(getattr(row, column))
            for row in frame.itertuples(index=False)
        }
        return np.asarray(
            [lookup[(int(timestamp.dayofweek), int(slot))] for timestamp, slot in zip(self.times, self.slot_in_day)],
            dtype=np.int16,
        )

    def search_start(self, timestamp: pd.Timestamp) -> int:
        return int(self.times.searchsorted(timestamp, side="left"))

    def end_timestamp(self, start_index: int, duration_slots: int) -> pd.Timestamp:
        return self.times[start_index] + pd.Timedelta(minutes=duration_slots * SLOT_MINUTES)

    def fits_block(self, start_index: int, duration_slots: int) -> bool:
        if start_index < 0 or start_index + duration_slots > len(self.times):
            return False
        end_index = start_index + duration_slots - 1
        return (
            self.day_values[start_index] == self.day_values[end_index]
            and self.block[start_index] == self.block[end_index]
        )

    def available(self, room_id: str, start_index: int, duration_slots: int) -> bool:
        if not self.fits_block(start_index, duration_slots):
            return False
        room_index = self.room_index[room_id]
        interval = slice(start_index, start_index + duration_slots)
        return (
            not self.room_busy[room_index, interval].any()
            and np.all(self.doctor_load[interval] < self.capacity[interval])
        )

    def reserve(self, step: PlanStep) -> None:
        room_index = self.room_index[step.room_id]
        interval = slice(step.start_index, step.start_index + step.task.duration_slots)
        self.room_busy[room_index, interval] = True
        self.doctor_load[interval] += 1
        self.room_work_slots[step.room_id] += step.task.duration_slots
        start = self.times[step.start_index]
        end = self.end_timestamp(step.start_index, step.task.duration_slots)
        self.patient_intervals.setdefault(step.task.patient_id, []).append(
            (start, end, step.room_id)
        )

    def release(self, step: PlanStep) -> None:
        room_index = self.room_index[step.room_id]
        interval = slice(step.start_index, step.start_index + step.task.duration_slots)
        self.room_busy[room_index, interval] = False
        self.doctor_load[interval] -= 1
        self.room_work_slots[step.room_id] -= step.task.duration_slots
        start = self.times[step.start_index]
        end = self.end_timestamp(step.start_index, step.task.duration_slots)
        intervals = self.patient_intervals[step.task.patient_id]
        intervals.remove((start, end, step.room_id))
        if not intervals:
            del self.patient_intervals[step.task.patient_id]

    def patient_available(
        self,
        patient_id: str,
        starts: pd.DatetimeIndex,
        ends: pd.DatetimeIndex,
        room_id: str,
    ) -> np.ndarray:
        """Check sparse cross-event patient occupancy and bidirectional transfer."""
        feasible = np.ones(len(starts), dtype=bool)
        for prior_start, prior_end, prior_room in self.patient_intervals.get(patient_id, []):
            if prior_room == room_id:
                separated = (ends <= prior_start) | (starts >= prior_end)
            else:
                separated = (
                    (ends + self.transfer_delta <= prior_start)
                    | (starts >= prior_end + self.transfer_delta)
                )
            feasible &= np.asarray(separated, dtype=bool)
        return feasible

    def room_priority_key(self, room: str) -> tuple[float | int, ...]:
        """Return the declared deterministic room tie-break for one policy."""
        if self.room_mode == "lowest_id":
            return (int(room),)
        if self.room_mode == "current_load":
            return (self.room_work_slots[room], int(room))
        if self.room_mode == "scarcity_preserving":
            # Lower training demand means the room is less scarce for other jobs.
            return (
                self.room_scarcity.get(room, 0.0),
                self.room_work_slots[room],
                int(room),
            )
        raise ValueError(f"unknown room mode: {self.room_mode}")

    def room_choice(self, rooms: list[str], last_room: str | None) -> str:
        if last_room in rooms:
            return str(last_room)
        return min(rooms, key=self.room_priority_key)

    def find_task(
        self,
        task: Task,
        release: pd.Timestamp,
        latest_end: pd.Timestamp,
        last_room: str | None,
        room_override: str | None = None,
    ) -> tuple[int, str, int] | None:
        rooms = [room_override] if room_override is not None else list(task.compatible_rooms)
        rooms = [room for room in rooms if room in self.room_index]
        if not rooms:
            return None
        start_index = self.search_start(release)
        stop_index = min(
            int(self.times.searchsorted(latest_end, side="left")),
            len(self.times) - task.duration_slots + 1,
        )
        if stop_index <= start_index:
            return None
        indices = np.arange(start_index, stop_index, dtype=np.int64)
        end_indices = indices + task.duration_slots - 1
        starts = self.times[indices]
        ends = starts + pd.Timedelta(minutes=task.duration_slots * SLOT_MINUTES)
        valid = (
            (self.day_values[indices] == self.day_values[end_indices])
            & (self.block[indices] == self.block[end_indices])
            & (ends <= latest_end)
        )
        if task.fasting:
            valid &= np.asarray(
                (starts.hour < 10)
                & (ends <= starts.normalize() + pd.Timedelta(hours=10)),
                dtype=bool,
            )

        span_end = stop_index + task.duration_slots - 1
        doctor_blocked = (
            self.doctor_load[start_index:span_end] >= self.capacity[start_index:span_end]
        ).astype(np.int16)
        doctor_prefix = np.concatenate(([0], np.cumsum(doctor_blocked)))
        valid &= (
            doctor_prefix[task.duration_slots:] - doctor_prefix[:-task.duration_slots] == 0
        )

        earliest_by_room: dict[str, int] = {}
        for room in rooms:
            room_index = self.room_index[room]
            room_blocked = self.room_busy[room_index, start_index:span_end].astype(np.int16)
            room_prefix = np.concatenate(([0], np.cumsum(room_blocked)))
            room_free = room_prefix[task.duration_slots:] - room_prefix[:-task.duration_slots] == 0
            transfer_slots = 0 if last_room is None or room == last_room else self.transfer_slots
            transfer_release = release + pd.Timedelta(minutes=transfer_slots * SLOT_MINUTES)
            patient_free = self.patient_available(task.patient_id, starts, ends, room)
            feasible = (
                valid
                & room_free
                & patient_free
                & np.asarray(starts >= transfer_release, dtype=bool)
            )
            positions = np.flatnonzero(feasible)
            if positions.size:
                earliest_by_room[room] = int(indices[positions[0]])
        if earliest_by_room:
            earliest = min(earliest_by_room.values())
            feasible_rooms = [room for room, index in earliest_by_room.items() if index == earliest]
            room = self.room_choice(feasible_rooms, last_room)
            transfer_slots = 0 if last_room is None or room == last_room else self.transfer_slots
            return earliest, room, transfer_slots
        return None


def load_inputs(
    special_mode: str,
    capability_mode: str,
    bladder_minutes: int,
    preparation_mode: str = "item",
    special_seed: int | None = None,
) -> tuple[pd.DataFrame, dict[str, list[Task]], pd.DataFrame, list[str], dict[str, str]]:
    events = pd.read_csv(
        INPUT / "events.csv",
        encoding="utf-8-sig",
        parse_dates=["order_dt", "planned_date", "base_release_dt", "bladder_ready_dt", "release_dt", "deadline_dt"],
    )
    for column in [
        "mandatory_background",
        "special_case",
        "evaluation_cohort",
        "bedside",
        "fasting",
        "bladder",
    ]:
        events[column] = as_bool(events[column])
    if special_seed is not None:
        events["special_case"] = False
        rng = np.random.default_rng(special_seed)
        for cohort_value in [False, True]:
            eligible = events.index[events["evaluation_cohort"].eq(cohort_value)].to_numpy()
            count = int(round(0.05 * len(eligible)))
            if count:
                events.loc[rng.choice(eligible, size=count, replace=False), "special_case"] = True
    events["bladder_ready_dt"] = (
        events["order_dt"] + pd.Timedelta(minutes=bladder_minutes)
    ).map(source_config.round_up_slot)
    if preparation_mode == "event":
        events["release_dt"] = source_config.release_times(events, bladder_minutes, True)
    elif preparation_mode == "item":
        events["release_dt"] = source_config.release_times(events, bladder_minutes, False)
    else:
        raise ValueError(f"unknown preparation mode: {preparation_mode}")

    items = pd.read_csv(INPUT / "items.csv", encoding="utf-8-sig")
    for column in [
        "item_bedside", "item_fasting", "item_bladder",
        "event_bedside", "event_fasting", "event_bladder",
        "uses_fallback_if_nonbedside",
    ]:
        items[column] = as_bool(items[column])
    event_special = events.set_index("event_id")["special_case"].to_dict()
    event_bladder_ready = events.set_index("event_id")["bladder_ready_dt"].to_dict()
    event_patient = events.set_index("event_id")["patient_id"].astype(str).to_dict()
    tasks: dict[str, list[Task]] = {}
    for event_id, group in items.groupby("event_id", sort=False):
        event_tasks: list[Task] = []
        use_upper = special_mode == "five_percent_upper" and bool(event_special[event_id])
        event_ready = pd.Timestamp(event_bladder_ready[event_id])
        for row in group.sort_values("item_index", kind="stable").itertuples(index=False):
            bedside = bool(row.event_bedside) if preparation_mode == "event" else bool(row.item_bedside)
            fasting = bool(row.event_fasting) if preparation_mode == "event" else bool(row.item_fasting)
            bladder = bool(row.event_bladder) if preparation_mode == "event" else bool(row.item_bladder)
            room_text = row.bedside_compatible_rooms if bedside else row.project_compatible_rooms
            if capability_mode == "strict" and str(row.capability_level) == "C":
                rooms: tuple[str, ...] = ()
            else:
                rooms = room_tuple(room_text)
            duration = row.duration_upper_min if use_upper else row.duration_nominal_min
            event_tasks.append(
                Task(
                    event_id=str(event_id),
                    patient_id=event_patient[event_id],
                    item_index=int(row.item_index),
                    project_norm=str(row.project_norm),
                    category=str(row.category),
                    duration_slots=max(1, int(math.ceil(float(duration) / SLOT_MINUTES))),
                    compatible_rooms=rooms,
                    capability_level=str(row.capability_level),
                    fasting=fasting,
                    bladder=bladder,
                    bedside=bedside,
                    bladder_ready_dt=event_ready,
                )
            )
        tasks[str(event_id)] = event_tasks

    equipment = pd.read_csv(
        SUPPORTING / "results" / "capability" / "equipment_source_rows.csv",
        encoding="utf-8-sig",
    )
    equipment["machine_id"] = equipment["machine_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    room_names = dict(zip(equipment["machine_id"], equipment["current_room"]))
    room_ids = sorted(room_names, key=int)
    slot_capacity = pd.read_csv(INPUT / "doctor_slot_capacity.csv", encoding="utf-8-sig")
    return events, tasks, slot_capacity, room_ids, room_names


def task_room_scarcity() -> dict[str, float]:
    """Read room pressure estimated only from the frozen training catalog."""
    frame = pd.read_csv(INPUT / "room_scarcity_training.csv", encoding="utf-8-sig")
    return {
        str(row.room_id): float(row.training_weighted_demand_minutes)
        for row in frame.itertuples(index=False)
    }


def task_order_candidates(event_tasks: list[Task]) -> list[list[Task]]:
    keys = [
        lambda task: (not task.fasting, len(task.compatible_rooms), -task.duration_slots, task.item_index),
        lambda task: (not task.fasting, -task.duration_slots, len(task.compatible_rooms), task.item_index),
        lambda task: (len(task.compatible_rooms), not task.fasting, task.item_index),
        lambda task: (task.item_index,),
    ]
    candidates: list[list[Task]] = []
    seen: set[tuple[int, ...]] = set()
    for key in keys:
        ordered = sorted(event_tasks, key=key)
        signature = tuple(task.item_index for task in ordered)
        if signature not in seen:
            candidates.append(ordered)
            seen.add(signature)
    return candidates


def tentative_plan(
    calendar: WorkCalendar,
    ordered_tasks: list[Task],
    release: pd.Timestamp,
    latest_end: pd.Timestamp,
    room_override: str | None,
) -> list[PlanStep] | None:
    steps: list[PlanStep] = []
    cursor = release
    last_room: str | None = None
    for position, task in enumerate(ordered_tasks, start=1):
        task_release = max(cursor, task.bladder_ready_dt) if task.bladder else cursor
        found = calendar.find_task(
            task,
            task_release,
            latest_end,
            last_room,
            room_override=room_override,
        )
        if found is None:
            for step in reversed(steps):
                calendar.release(step)
            return None
        start_index, room_id, transfer_slots = found
        step = PlanStep(task, start_index, room_id, position, transfer_slots)
        calendar.reserve(step)
        steps.append(step)
        cursor = calendar.end_timestamp(start_index, task.duration_slots)
        last_room = room_id
    return steps


def plan_event(
    calendar: WorkCalendar,
    event_tasks: list[Task],
    release: pd.Timestamp,
    latest_end: pd.Timestamp,
) -> list[PlanStep] | None:
    if any(not task.compatible_rooms for task in event_tasks):
        return None
    orders = task_order_candidates(event_tasks)
    common = set(event_tasks[0].compatible_rooms)
    for task in event_tasks[1:]:
        common &= set(task.compatible_rooms)
    if common:
        candidate_rooms = sorted(
            common,
            key=calendar.room_priority_key,
        )[:3]
        for room in candidate_rooms:
            steps = tentative_plan(calendar, orders[0], release, latest_end, room)
            if steps is not None:
                return steps
    for ordered in orders:
        steps = tentative_plan(calendar, ordered, release, latest_end, None)
        if steps is not None:
            return steps
    return None


def event_priority(
    events: pd.DataFrame,
    tasks: dict[str, list[Task]],
    group: str,
    strategy: str,
) -> list[str]:
    subset = events[events["mandatory_background"] if group == "background" else ~events["mandatory_background"]].copy()
    subset["work_slots"] = subset["event_id"].map(
        lambda event_id: sum(task.duration_slots for task in tasks[event_id])
    )
    subset["minimum_room_count"] = subset["event_id"].map(
        lambda event_id: min((len(task.compatible_rooms) for task in tasks[event_id]), default=0)
    )
    subset["has_fasting_task"] = subset["event_id"].map(
        lambda event_id: any(task.fasting for task in tasks[event_id])
    )
    if group == "background" and strategy == "scarcity":
        subset = subset.sort_values(
            ["deadline_dt", "has_fasting_task", "minimum_room_count", "work_slots", "release_dt", "event_id"],
            ascending=[True, False, True, False, True, True],
            kind="stable",
        )
    elif group == "inpatient" and strategy == "slack":
        # Static arrival-window slack: (deadline - order time) - processing.
        # This is distinct from the former absolute key deadline-processing.
        subset["arrival_slack_minutes"] = (
            (subset["deadline_dt"] - subset["order_dt"]).dt.total_seconds() / 60
            - subset["work_slots"] * SLOT_MINUTES
        )
        subset = subset.sort_values(
            ["arrival_slack_minutes", "release_dt", "minimum_room_count", "deadline_dt", "event_id"],
            kind="stable",
        )
    else:
        subset = subset.sort_values(["release_dt", "event_id"], kind="stable")
    return subset["event_id"].tolist()


def create_calendar(
    slot_capacity: pd.DataFrame,
    room_ids: list[str],
    policy: str,
    capacity_column: str,
    transfer_minutes: int = TRANSFER_MINUTES,
    *,
    start_date: pd.Timestamp | None = None,
    end_date_exclusive: pd.Timestamp | None = None,
    room_scarcity: dict[str, float] | None = None,
) -> WorkCalendar:
    """Construct the calendar used by both production P2 and production P3."""
    config = POLICIES[policy]
    return WorkCalendar(
        source_config.SIMULATION_START if start_date is None else start_date,
        (
            source_config.HOLDOUT_END_EXCLUSIVE + pd.Timedelta(days=FOLLOWUP_DAYS)
            if end_date_exclusive is None
            else end_date_exclusive
        ),
        room_ids,
        slot_capacity,
        capacity_column,
        task_room_scarcity() if room_scarcity is None else room_scarcity,
        config["room_mode"],
        transfer_minutes,
    )


def run_group_with_policy(
    calendar: WorkCalendar,
    events: pd.DataFrame,
    tasks: dict[str, list[Task]],
    policy: str,
    group: str,
    *,
    strategy_override: str | None = None,
) -> tuple[list[str], dict[str, list[PlanStep]], dict[str, str]]:
    """Apply the shared patient order and event planner for one demand group."""
    config = POLICIES[policy]
    strategy = config[group] if strategy_override is None else strategy_override
    event_ids = event_priority(events, tasks, group, strategy)
    lookup = events.set_index("event_id")
    plans, failure = schedule_group(calendar, event_ids, lookup, tasks)
    return event_ids, plans, failure


def p2_metrics_lexicographic_key(metrics: dict[str, Any] | pd.Series) -> tuple[Any, ...]:
    """Fixed P2 policy selection key; smaller tuples are preferred."""
    return (
        -int(metrics["inpatient_complete_48h"]),
        float(metrics["inpatient_wait_p90_hours_conditional"]),
        float(metrics["inpatient_wait_p50_hours_conditional"]),
        float(metrics["inpatient_room_switch_rate_multi"]),
        float(metrics["scheduled_minutes"]),
        str(metrics["policy"]),
    )


def schedule_group(
    calendar: WorkCalendar,
    event_ids: list[str],
    event_lookup: pd.DataFrame,
    tasks: dict[str, list[Task]],
) -> tuple[dict[str, list[PlanStep]], dict[str, str]]:
    plans: dict[str, list[PlanStep]] = {}
    failure: dict[str, str] = {}
    for count, event_id in enumerate(event_ids, start=1):
        event = event_lookup.loc[event_id]
        steps = plan_event(calendar, tasks[event_id], event.release_dt, event.deadline_dt)
        if steps is None:
            if any(not task.compatible_rooms for task in tasks[event_id]):
                failure[event_id] = "no_compatible_room_under_scenario"
            else:
                failure[event_id] = "no_complete_plan_by_deadline"
        else:
            plans[event_id] = steps
        if count % 25000 == 0:
            print(f"  on-time pass {count:,}/{len(event_ids):,}", flush=True)
    print(
        f"  deadline pass complete: scheduled={len(plans):,}, unallocated={len(failure):,}",
        flush=True,
    )
    return plans, failure


def plan_to_schedule(
    calendar: WorkCalendar,
    plans: dict[str, list[PlanStep]],
    events: pd.DataFrame,
    policy: str,
    room_names: dict[str, str],
) -> pd.DataFrame:
    event_meta = events.set_index("event_id")
    rows: list[dict[str, Any]] = []
    for event_id, steps in plans.items():
        event = event_meta.loc[event_id]
        ordered = sorted(steps, key=lambda step: step.sequence_position)
        for step in ordered:
            start = calendar.times[step.start_index]
            end = calendar.end_timestamp(step.start_index, step.task.duration_slots)
            rows.append(
                {
                    "policy": policy,
                    "event_id": event_id,
                    "source": event.source,
                    "patient_id": event.patient_id,
                    "item_index": step.task.item_index,
                    "sequence_position": step.sequence_position,
                    "project_norm": step.task.project_norm,
                    "category": step.task.category,
                    "start_dt": start,
                    "end_dt": end,
                    "room_id": step.room_id,
                    "room_name": room_names.get(step.room_id, step.room_id),
                    "duration_minutes": step.task.duration_slots * SLOT_MINUTES,
                    "transfer_minutes_before": step.transfer_slots_before * SLOT_MINUTES,
                    "room_switch_from_previous": step.transfer_slots_before > 0,
                    "capability_level": step.task.capability_level,
                    "fasting": step.task.fasting,
                    "bladder": step.task.bladder,
                    "bedside": step.task.bedside,
                    "release_dt": event.release_dt,
                    "deadline_dt": event.deadline_dt,
                    "evaluation_cohort": event.evaluation_cohort,
                }
            )
    return pd.DataFrame(rows)


def outcomes_from_schedule(
    events: pd.DataFrame,
    schedule: pd.DataFrame,
    failure: dict[str, str],
    policy: str,
) -> pd.DataFrame:
    if schedule.empty:
        aggregates = pd.DataFrame(columns=["event_id"])
    else:
        aggregates = (
            schedule.groupby("event_id", as_index=False)
            .agg(
                scheduled_items=("item_index", "size"),
                first_start_dt=("start_dt", "min"),
                completion_dt=("end_dt", "max"),
                room_count=("room_id", "nunique"),
                room_switch_count=("room_switch_from_previous", "sum"),
                transfer_minutes=("transfer_minutes_before", "sum"),
                fallback_task_count=("capability_level", lambda values: values.eq("category_fallback").sum()),
            )
        )
    result = events.merge(aggregates, on="event_id", how="left", validate="one_to_one")
    result["scheduled_items"] = result["scheduled_items"].fillna(0).astype(int)
    result["complete_event"] = result["scheduled_items"].eq(result["service_project_count"])
    result["deadline_met"] = result["complete_event"] & result["completion_dt"].le(result["deadline_dt"])
    result["waiting_hours"] = (
        result["first_start_dt"] - result["release_dt"]
    ).dt.total_seconds() / 3600
    result["failure_reason"] = result["event_id"].map(failure).astype("string")
    result.loc[
        ~result["deadline_met"] & result["failure_reason"].isna(), "failure_reason"
    ] = "completed_after_deadline"
    result.loc[result["deadline_met"], "failure_reason"] = ""
    result["policy"] = policy
    return result


def metrics_from_outcomes(
    outcomes: pd.DataFrame,
    schedule: pd.DataFrame,
    calendar: WorkCalendar,
    policy: str,
    scenario: str,
) -> dict[str, Any]:
    cohort = outcomes[outcomes["evaluation_cohort"]]
    inpatient = cohort[cohort["source"].eq("住院")]
    background = cohort[~cohort["source"].eq("住院")]
    scheduled_wait = inpatient["waiting_hours"].dropna()
    room_minutes = float(schedule["duration_minutes"].sum()) if not schedule.empty else 0.0
    staffed_minutes = float(calendar.capacity.sum() * SLOT_MINUTES)
    return {
        "scenario": scenario,
        "policy": policy,
        "inpatient_events": int(len(inpatient)),
        "inpatient_complete_48h": int(inpatient["deadline_met"].sum()),
        "inpatient_48h_rate": float(inpatient["deadline_met"].mean()),
        "inpatient_scheduled_complete": int(inpatient["complete_event"].sum()),
        "inpatient_unscheduled": int((~inpatient["complete_event"]).sum()),
        "inpatient_wait_p50_hours_conditional": float(scheduled_wait.quantile(0.50)),
        "inpatient_wait_p90_hours_conditional": float(scheduled_wait.quantile(0.90)),
        "inpatient_wait_p95_hours_conditional": float(scheduled_wait.quantile(0.95)),
        "inpatient_room_switch_rate_multi": float(
            inpatient.loc[inpatient["service_project_count"].gt(1), "room_switch_count"].fillna(0).gt(0).mean()
        ),
        "background_events": int(len(background)),
        "background_on_planned_day": int(background["deadline_met"].sum()),
        "background_on_time_rate": float(background["deadline_met"].mean()),
        "background_scheduled_complete": int(background["complete_event"].sum()),
        "fallback_scheduled_task_share": float(schedule["capability_level"].eq("category_fallback").mean()),
        "scheduled_minutes": room_minutes,
        "staffed_capacity_utilization": room_minutes / staffed_minutes if staffed_minutes else np.nan,
    }


def daily_outputs(
    outcomes: pd.DataFrame,
    schedule: pd.DataFrame,
    calendar: WorkCalendar,
    policy: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    working = outcomes[outcomes["evaluation_cohort"]].copy()
    working["metric_date"] = working["order_dt"].where(
        working["source"].eq("住院"), working["planned_date"]
    ).dt.normalize()
    daily = (
        working.groupby(["metric_date", "source"], as_index=False)
        .agg(
            events=("event_id", "size"),
            deadline_met=("deadline_met", "sum"),
            scheduled_complete=("complete_event", "sum"),
            demand_nominal_minutes=("nominal_minutes", "sum"),
            demand_upper_minutes=("upper_minutes", "sum"),
        )
    )
    daily["deadline_rate"] = daily["deadline_met"] / daily["events"]
    daily["policy"] = policy

    if schedule.empty:
        utilization = pd.DataFrame()
    else:
        schedule = schedule.copy()
        schedule["date"] = schedule["start_dt"].dt.normalize()
        utilization = (
            schedule.groupby(["date", "room_id", "room_name"], as_index=False)["duration_minutes"]
            .sum()
        )
        utilization["room_utilization"] = utilization["duration_minutes"] / (8 * 60)
        utilization["policy"] = policy
    return daily, utilization


def run_policy(
    events: pd.DataFrame,
    tasks: dict[str, list[Task]],
    slot_capacity: pd.DataFrame,
    room_ids: list[str],
    room_names: dict[str, str],
    policy: str,
    capacity_column: str,
    scenario: str,
    transfer_minutes: int = TRANSFER_MINUTES,
    background_state: tuple[WorkCalendar, dict[str, list[PlanStep]], dict[str, str]] | None = None,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    dict[str, Any],
    pd.DataFrame,
    pd.DataFrame,
    tuple[WorkCalendar, dict[str, list[PlanStep]], dict[str, str]],
]:
    if background_state is None:
        calendar = create_calendar(
            slot_capacity, room_ids, policy, capacity_column, transfer_minutes,
        )
        background_order, background_plans, background_failure = run_group_with_policy(
            calendar, events, tasks, policy, "background",
        )
        print(f"{policy}: processed {len(background_order):,} outpatient/physical-exam events", flush=True)
        reusable_background = (
            calendar.clone(),
            background_plans,
            background_failure,
        )
    else:
        stored_calendar, background_plans, background_failure = background_state
        calendar = stored_calendar.clone()
        reusable_background = background_state
        print(f"{policy}: reusing identical background allocation", flush=True)
    inpatient_order, inpatient_plans, inpatient_failure = run_group_with_policy(
        calendar, events, tasks, policy, "inpatient",
    )
    print(f"{policy}: processed {len(inpatient_order):,} inpatient events", flush=True)
    plans = {**background_plans, **inpatient_plans}
    failure = {**background_failure, **inpatient_failure}
    schedule = plan_to_schedule(calendar, plans, events, policy, room_names)
    outcomes = outcomes_from_schedule(events, schedule, failure, policy)
    metrics = metrics_from_outcomes(outcomes, schedule, calendar, policy, scenario)
    metrics["transfer_minutes_assumption"] = transfer_minutes
    daily, utilization = daily_outputs(outcomes, schedule, calendar, policy)
    print(
        f"{policy}: inpatient48h={metrics['inpatient_48h_rate']:.4%}, "
        f"background={metrics['background_on_time_rate']:.4%}, tasks={len(schedule):,}",
        flush=True,
    )
    return schedule, outcomes, metrics, daily, utilization, reusable_background


def recommendation_table(schedule: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    evaluation = as_bool(outcomes["evaluation_cohort"])
    inpatient_ids = set(
        outcomes.loc[outcomes["source"].eq("住院") & evaluation, "event_id"]
    )
    result = schedule[schedule["event_id"].isin(inpatient_ids)].copy()
    result = result.sort_values(["start_dt", "room_id", "event_id", "sequence_position"], kind="stable")
    event_rank = (
        result[["event_id"]]
        .drop_duplicates()
        .assign(first_start=result.groupby("event_id", sort=False)["start_dt"].first().values)
        .sort_values(["first_start", "event_id"], kind="stable")
    )
    event_rank["recommended_patient_rank"] = np.arange(1, len(event_rank) + 1)
    result = result.merge(
        event_rank[["event_id", "recommended_patient_rank"]], on="event_id", how="left"
    )
    columns = [
        "recommended_patient_rank",
        "event_id",
        "patient_id",
        "sequence_position",
        "project_norm",
        "category",
        "start_dt",
        "end_dt",
        "room_id",
        "room_name",
        "transfer_minutes_before",
        "fasting",
        "bladder",
        "bedside",
        "capability_level",
    ]
    return result[columns].sort_values(
        ["recommended_patient_rank", "sequence_position"], kind="stable"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT)
    parser.add_argument("--main-only", action="store_true")
    parser.add_argument("--sensitivity-only", action="store_true")
    parser.add_argument("--main-policy", choices=list(POLICIES))
    parser.add_argument("--sensitivity-scenario")
    args = parser.parse_args()
    if args.main_only and args.sensitivity_only:
        parser.error("--main-only and --sensitivity-only cannot be used together")
    if args.sensitivity_scenario and not args.sensitivity_only:
        parser.error("--sensitivity-scenario requires --sensitivity-only")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    authoritative_policy = resolve_authoritative_policy(args.main_policy)

    metrics_rows: list[dict[str, Any]] = []
    daily_rows: list[pd.DataFrame] = []
    authoritative_schedule: pd.DataFrame | None = None
    authoritative_outcomes: pd.DataFrame | None = None
    authoritative_utilization: pd.DataFrame | None = None
    if args.sensitivity_only:
        existing_metrics = pd.read_csv(args.output_dir / "policy_scenario_metrics.csv")
        existing_metrics = existing_metrics[existing_metrics["scenario"].eq("main_5pct_upper")]
        metrics_rows.extend(existing_metrics.to_dict(orient="records"))
        existing_daily = pd.read_csv(args.output_dir / "daily_service_metrics.csv", low_memory=False)
        if "scenario" not in existing_daily.columns:
            existing_daily["scenario"] = "main_5pct_upper"
        existing_daily["scenario"] = existing_daily["scenario"].fillna("main_5pct_upper")
        daily_rows.append(existing_daily[existing_daily["scenario"].eq("main_5pct_upper")])
    else:
        main_events, main_tasks, slot_capacity, room_ids, room_names = load_inputs(
            "five_percent_upper", "hierarchical", source_config.BLADDER_PREPARATION_MINUTES
        )
        background_cache: dict[
            tuple[str, str], tuple[WorkCalendar, dict[str, list[PlanStep]], dict[str, str]]
        ] = {}
        selected_policies = [args.main_policy] if args.main_policy else list(P2_POLICY_CANDIDATES)
        for policy in selected_policies:
            background_key = (
                POLICIES[policy]["background"], POLICIES[policy]["room_mode"],
            )
            schedule, outcomes, metrics, daily, utilization, reusable_background = run_policy(
                main_events,
                main_tasks,
                slot_capacity,
                room_ids,
                room_names,
                policy,
                "capacity_main",
                "main_5pct_upper",
                TRANSFER_MINUTES,
                background_cache.get(background_key),
            )
            background_cache.setdefault(background_key, reusable_background)
            metrics_rows.append(metrics)
            daily_rows.append(daily.assign(scenario="main_5pct_upper"))
            if policy == authoritative_policy:
                authoritative_schedule = schedule
                authoritative_outcomes = outcomes
                authoritative_utilization = utilization

    sensitivity_specs = [] if args.main_only else [
        ("nominal_no_special", "five_percent_upper", "hierarchical", "capacity_main", 60, False, 10),
        ("low_doctor_q25", "five_percent_upper", "hierarchical", "capacity_low", 60, True, 10),
        ("strict_capability", "five_percent_upper", "strict", "capacity_main", 60, True, 10),
        ("bladder_45min", "five_percent_upper", "hierarchical", "capacity_main", 45, True, 10),
        ("bladder_90min", "five_percent_upper", "hierarchical", "capacity_main", 90, True, 10),
        ("transfer_5min", "five_percent_upper", "hierarchical", "capacity_main", 60, True, 5),
        ("transfer_15min", "five_percent_upper", "hierarchical", "capacity_main", 60, True, 15),
    ]
    if args.sensitivity_scenario:
        sensitivity_specs = [
            spec for spec in sensitivity_specs if spec[0] == args.sensitivity_scenario
        ]
        if not sensitivity_specs:
            parser.error(f"unknown sensitivity scenario: {args.sensitivity_scenario}")
    # The first tuple uses a flag to switch all events to nominal duration.
    for name, special_mode, capability_mode, capacity_column, bladder_minutes, use_special, transfer_minutes in sensitivity_specs:
        effective_special = special_mode if use_special else "all_nominal"
        events, tasks, capacity, rooms, names = load_inputs(
            effective_special, capability_mode, bladder_minutes
        )
        _, _, metrics, daily, _, _ = run_policy(
            events,
            tasks,
            capacity,
            rooms,
            names,
            authoritative_policy,
            capacity_column,
            name,
            transfer_minutes,
        )
        metrics_rows.append(metrics)
        daily_rows.append(daily.assign(scenario=name))

    metrics_frame = pd.DataFrame(metrics_rows)
    metrics_frame.to_csv(args.output_dir / "policy_scenario_metrics.csv", index=False, encoding="utf-8-sig")
    pd.concat(daily_rows, ignore_index=True).to_csv(
        args.output_dir / "daily_service_metrics.csv", index=False, encoding="utf-8-sig"
    )
    if not args.sensitivity_only:
        assert authoritative_schedule is not None
        assert authoritative_outcomes is not None
        assert authoritative_utilization is not None
        authoritative_schedule.to_csv(
            args.output_dir / "final_patient_task_schedule.csv", index=False, encoding="utf-8-sig"
        )
        authoritative_outcomes.to_csv(
            args.output_dir / "final_patient_outcomes.csv", index=False, encoding="utf-8-sig"
        )
        authoritative_utilization.to_csv(
            args.output_dir / "final_room_utilization_daily.csv", index=False, encoding="utf-8-sig"
        )
        recommendation_table(authoritative_schedule, authoritative_outcomes).to_csv(
            args.output_dir / "inpatient_recommended_schedule.csv", index=False, encoding="utf-8-sig"
        )
    summary = {
        "authoritative_policy": authoritative_policy,
        "annual_state_reset_count": 1,
        "simulation_start": str(source_config.SIMULATION_START.date()),
        "simulation_end_exclusive": str(
            (source_config.HOLDOUT_END_EXCLUSIVE + pd.Timedelta(days=FOLLOWUP_DAYS)).date()
        ),
        "evaluation_start": str(source_config.HOLDOUT_START.date()),
        "evaluation_end_exclusive": str(source_config.HOLDOUT_END_EXCLUSIVE.date()),
        "background_interpretation": "retrospective plan-day scenario reconstructed from report date, with release no earlier than the observed order time; report time/room/doctor dispatch are excluded",
        "official_kpi_boundary": "scheduled service completion is used as report-submission completion proxy because scan-end timestamp is absent",
        "transfer_minutes_between_rooms": TRANSFER_MINUTES,
        "metrics": metrics_frame.to_dict(orient="records"),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(metrics_frame.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
