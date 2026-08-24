"""Compare the annual construction heuristic with CP-SAT on small P2 windows."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

import run_unified_scheduler as scheduler


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "supporting_materials" / "results" / "exact_benchmark"
MAX_EVENTS = 18
TIME_LIMIT_SECONDS = 60.0


def representative_cases(events: pd.DataFrame, tasks: dict[str, list[scheduler.Task]]) -> list[tuple[str, pd.Timestamp, list[str]]]:
    inpatient = events[
        (~events["mandatory_background"]) & events["evaluation_cohort"]
    ].copy()
    inpatient["date"] = inpatient["order_dt"].dt.normalize()
    inpatient["multi"] = inpatient["service_project_count"].gt(1)
    inpatient["bedside_task"] = inpatient["event_id"].map(
        lambda event_id: any(task.bedside for task in tasks[event_id])
    )
    inpatient["obstetric_task"] = inpatient["event_id"].map(
        lambda event_id: any(task.category == "产科III/IV级" for task in tasks[event_id])
    )
    daily = inpatient.groupby("date").agg(
        events=("event_id", "size"),
        multi_share=("multi", "mean"),
        bedside_count=("bedside_task", "sum"),
        obstetric_count=("obstetric_task", "sum"),
    )
    weekday = daily[daily.index.dayofweek < 5]
    weekend = daily[daily.index.dayofweek >= 5]
    normal_date = (weekday["events"] - weekday["events"].median()).abs().idxmin()
    dates = {
        "normal_weekday": normal_date,
        "peak_weekday": weekday["events"].idxmax(),
        "weekend": weekend["events"].idxmax(),
        "multi_project_peak": daily["multi_share"].idxmax(),
        "bedside_peak": daily["bedside_count"].idxmax(),
        "obstetric_peak": daily["obstetric_count"].idxmax(),
    }
    cases = []
    for name, date in dates.items():
        group = inpatient[inpatient["date"].eq(date)].copy()
        if name == "bedside_peak":
            group = group.sort_values(["bedside_task", "service_project_count", "order_dt"], ascending=[False, False, True])
        elif name == "obstetric_peak":
            group = group.sort_values(["obstetric_task", "service_project_count", "order_dt"], ascending=[False, False, True])
        elif name == "multi_project_peak":
            group = group.sort_values(["service_project_count", "order_dt"], ascending=[False, True])
        else:
            group = group.sort_values(["order_dt", "event_id"])
        case_limit = 10 if name == "multi_project_peak" else MAX_EVENTS
        cases.append((name, pd.Timestamp(date), group["event_id"].head(case_limit).tolist()))
    return cases


def feasible_options(
    calendar: scheduler.WorkCalendar,
    task: scheduler.Task,
    release: pd.Timestamp,
    deadline: pd.Timestamp,
) -> list[tuple[str, int]]:
    release = max(release, task.bladder_ready_dt) if task.bladder else release
    start = calendar.search_start(release)
    stop = min(
        int(calendar.times.searchsorted(deadline, side="left")),
        len(calendar.times) - task.duration_slots + 1,
    )
    options: list[tuple[str, int]] = []
    for index in range(start, stop):
        if not calendar.fits_block(index, task.duration_slots):
            continue
        end = calendar.end_timestamp(index, task.duration_slots)
        if end > deadline:
            continue
        if task.fasting and end > calendar.times[index].normalize() + pd.Timedelta(hours=10):
            continue
        for room in task.compatible_rooms:
            if room in calendar.room_index:
                options.append((room, index))
    return options


def solve_case(
    name: str,
    date: pd.Timestamp,
    event_ids: list[str],
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    policy: str,
) -> dict[str, object]:
    lookup = events.set_index("event_id")
    start_date = date
    end_date = date + pd.Timedelta(days=3)
    calendar = scheduler.WorkCalendar(
        start_date, end_date, rooms, capacity, "capacity_main", scheduler.task_room_scarcity(),
        "scarcity", scheduler.TRANSFER_MINUTES,
    )
    subset = events[events["event_id"].isin(event_ids)].copy()
    heuristic_order = scheduler.event_priority(
        subset, tasks, "inpatient", scheduler.POLICIES[policy]["inpatient"]
    )
    heuristic_calendar = calendar.clone()
    heuristic_plans, _ = scheduler.schedule_group(
        heuristic_calendar, heuristic_order, lookup, tasks
    )
    heuristic_value = len(heuristic_plans)

    model = cp_model.CpModel()
    event_selected: dict[str, cp_model.IntVar] = {}
    task_vars: dict[tuple[str, int], dict[str, object]] = {}
    room_intervals: dict[str, list[cp_model.IntervalVar]] = {room: [] for room in rooms}
    doctor_slot_vars: dict[int, list[cp_model.IntVar]] = {}

    for event_id in event_ids:
        event = lookup.loc[event_id]
        selected = model.new_bool_var(f"y_{event_id}")
        event_selected[event_id] = selected
        local_tasks = tasks[event_id]
        for task in local_tasks:
            options = feasible_options(calendar, task, event.release_dt, event.deadline_dt)
            option_vars: list[cp_model.IntVar] = []
            room_selected: dict[str, cp_model.IntVar] = {}
            start_var = model.new_int_var(0, len(calendar.times), f"s_{event_id}_{task.item_index}")
            for room in task.compatible_rooms:
                room_selected[room] = model.new_bool_var(f"r_{event_id}_{task.item_index}_{room}")
            by_room: dict[str, list[cp_model.IntVar]] = {room: [] for room in task.compatible_rooms}
            start_terms = []
            for room, start in options:
                x = model.new_bool_var(f"x_{event_id}_{task.item_index}_{room}_{start}")
                option_vars.append(x)
                by_room[room].append(x)
                start_terms.append(start * x)
                interval = model.new_optional_fixed_size_interval_var(
                    start, task.duration_slots, x,
                    f"iv_{event_id}_{task.item_index}_{room}_{start}",
                )
                room_intervals[room].append(interval)
                for slot in range(start, start + task.duration_slots):
                    doctor_slot_vars.setdefault(slot, []).append(x)
            if option_vars:
                model.add(sum(option_vars) == selected)
                model.add(start_var == sum(start_terms))
                for room, room_vars in by_room.items():
                    model.add(room_selected[room] == sum(room_vars))
            else:
                model.add(selected == 0)
                for room in room_selected:
                    model.add(room_selected[room] == 0)
            task_vars[(event_id, task.item_index)] = {
                "task": task,
                "start": start_var,
                "rooms": room_selected,
            }

        for left_index in range(len(local_tasks)):
            for right_index in range(left_index + 1, len(local_tasks)):
                left = task_vars[(event_id, local_tasks[left_index].item_index)]
                right = task_vars[(event_id, local_tasks[right_index].item_index)]
                left_before = model.new_bool_var(f"ord_{event_id}_{left_index}_{right_index}")
                for left_room, left_room_var in left["rooms"].items():
                    for right_room, right_room_var in right["rooms"].items():
                        gap = scheduler.TRANSFER_MINUTES // scheduler.SLOT_MINUTES if left_room != right_room else 0
                        model.add(
                            right["start"] >= left["start"] + left["task"].duration_slots + gap
                        ).only_enforce_if([selected, left_before, left_room_var, right_room_var])
                        model.add(
                            left["start"] >= right["start"] + right["task"].duration_slots + gap
                        ).only_enforce_if([selected, left_before.negated(), left_room_var, right_room_var])

    for room, intervals in room_intervals.items():
        if intervals:
            model.add_no_overlap(intervals)
    for slot, variables in doctor_slot_vars.items():
        model.add(sum(variables) <= int(calendar.capacity[slot]))
    model.maximize(sum(event_selected.values()))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIME_LIMIT_SECONDS
    # Three windows are solved concurrently below; two CP-SAT workers per
    # window keep aggregate CPU use bounded.
    solver.parameters.num_search_workers = 2
    started = time.perf_counter()
    status = solver.solve(model)
    elapsed = time.perf_counter() - started
    exact_value = int(round(solver.objective_value)) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else 0
    bound = float(solver.best_objective_bound) if status in (cp_model.OPTIMAL, cp_model.FEASIBLE) else float(len(event_ids))
    return {
        "case": name,
        "date": str(date.date()),
        "event_count": len(event_ids),
        "heuristic_complete": heuristic_value,
        "exact_complete": exact_value,
        "best_bound": bound,
        "heuristic_gap_to_exact": (exact_value - heuristic_value) / max(exact_value, 1),
        "heuristic_gap_to_bound": (bound - heuristic_value) / max(bound, 1),
        "solver_status": solver.status_name(status),
        "solve_seconds": elapsed,
    }


def write_report(frame: pd.DataFrame) -> None:
    columns = list(frame.columns)
    markdown = [
        "|" + "|".join(columns) + "|",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in frame.itertuples(index=False, name=None):
        markdown.append("|" + "|".join(str(value).replace("|", "/") for value in row) + "|")
    lines = [
        "# Exact vs Heuristic Benchmark",
        "",
        "代表性小规模住院窗口使用与主模型相同的项目时长、设备集合、医生总并发、准备条件、患者互斥和跨室转运约束。CP-SAT 在每个窗口内最大化48小时完整完成患者数；全年模型仍采用构造算法。",
        "",
        "\n".join(markdown),
        "",
        f"最大启发式相对精确解差距：{frame['heuristic_gap_to_exact'].max():.4%}。",
        f"最大启发式相对最好界差距：{frame['heuristic_gap_to_bound'].max():.4%}。",
    ]
    (OUT / "EXACT_VS_HEURISTIC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events, tasks, capacity, rooms, _ = scheduler.load_inputs(
        "five_percent_upper", "hierarchical", 60, preparation_mode="item"
    )
    p2 = json.loads(
        (ROOT / "supporting_materials" / "results" / "final_frozen" / "p2_inpatient_only" / "summary.json").read_text(encoding="utf-8")
    )
    policy = p2["selected_policy"]
    cases = representative_cases(events, tasks)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(
            pool.map(
                lambda case: solve_case(*case, events, tasks, capacity, rooms, policy),
                cases,
            )
        )
    frame = pd.DataFrame(rows)
    frame.to_csv(OUT / "exact_vs_heuristic_metrics.csv", index=False, encoding="utf-8-sig")
    write_report(frame)
    print(frame.to_string(index=False))


if __name__ == "__main__":
    main()
