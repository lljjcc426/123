"""Run the pre-freeze P2 and P3 scenarios on the audited scheduling kernel."""

from __future__ import annotations

import argparse
import json
import math
import shutil
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_unified_scheduler as scheduler


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "supporting_materials" / "results" / "final_frozen"
DEFAULT_COARSE_ALPHAS = tuple(i / 100 for i in range(0, 71, 5))
P3_DETAIL_FILES = (
    "final_patient_task_schedule.csv",
    "final_patient_outcomes.csv",
    "daily_service_metrics.csv",
    "room_utilization_daily.csv",
    "inpatient_recommended_schedule.csv",
    "epsilon_diagnostics.json",
)
P2_DETAIL_FILES = (
    "final_patient_task_schedule.csv",
    "final_patient_outcomes.csv",
    "daily_service_metrics.csv",
    "room_utilization_daily.csv",
    "inpatient_recommended_schedule.csv",
    "failure_reason_breakdown.csv",
)


def regular_alpha_grid(start: float, stop: float, step: float) -> list[float]:
    """Build an inclusive decimal grid without binary-float drift."""
    start_dec, stop_dec, step_dec = map(lambda value: Decimal(str(value)), (start, stop, step))
    if step_dec <= 0 or start_dec > stop_dec:
        raise ValueError("alpha grid requires 0 < step and start <= stop")
    values: list[float] = []
    value = start_dec
    while value <= stop_dec:
        values.append(float(value))
        value += step_dec
    return values


def alpha_token(alpha: float) -> str:
    """Use two decimals on the coarse grid and preserve finer local points."""
    if math.isclose(alpha * 100, round(alpha * 100), abs_tol=1e-9):
        return f"{alpha:.2f}"
    return f"{alpha:.4f}".rstrip("0")


def p3_shard(alpha: float) -> Path:
    return OUT / "p3_shards" / f"alpha_{alpha_token(alpha)}"


def p2_shard(policy: str) -> Path:
    return OUT / "p2_shards" / policy


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_p2_point(policy: str) -> dict[str, Any]:
    events, tasks, capacity, rooms, room_names = scheduler.load_inputs(
        "five_percent_upper", "hierarchical", 60, preparation_mode="item"
    )
    events = events[~events["mandatory_background"]].copy()
    tasks = {event_id: tasks[event_id] for event_id in events["event_id"]}
    shard = p2_shard(policy)
    shard.mkdir(parents=True, exist_ok=True)
    save_json(shard / "point_status.json", {"policy": policy, "detail_complete": False})
    schedule, outcomes, metrics, daily, utilization, _ = scheduler.run_policy(
        events, tasks, capacity, rooms, room_names, policy, "capacity_main",
        "P2_INPATIENT_ONLY", scheduler.TRANSFER_MINUTES,
    )
    pd.DataFrame([metrics]).to_csv(shard / "metrics.csv", index=False, encoding="utf-8-sig")
    schedule.to_csv(shard / "final_patient_task_schedule.csv", index=False, encoding="utf-8-sig")
    outcomes.to_csv(shard / "final_patient_outcomes.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(shard / "daily_service_metrics.csv", index=False, encoding="utf-8-sig")
    utilization.to_csv(shard / "room_utilization_daily.csv", index=False, encoding="utf-8-sig")
    scheduler.recommendation_table(schedule, outcomes).to_csv(
        shard / "inpatient_recommended_schedule.csv", index=False, encoding="utf-8-sig"
    )
    evaluated = scheduler.as_bool(outcomes["evaluation_cohort"])
    deadline_met = scheduler.as_bool(outcomes["deadline_met"])
    failure = (
        outcomes.loc[evaluated & ~deadline_met, "failure_reason"]
        .fillna("unknown")
        .value_counts()
        .rename_axis("failure_reason")
        .reset_index(name="event_count")
    )
    failure.to_csv(shard / "failure_reason_breakdown.csv", index=False, encoding="utf-8-sig")
    save_json(shard / "point_status.json", {"policy": policy, "detail_complete": True})
    return metrics


def finalize_p2() -> None:
    metric_rows: list[pd.Series] = []
    for policy in scheduler.P2_POLICY_CANDIDATES:
        shard = p2_shard(policy)
        status = json.loads((shard / "point_status.json").read_text(encoding="utf-8"))
        missing = [name for name in P2_DETAIL_FILES if not (shard / name).exists()]
        if status != {"policy": policy, "detail_complete": True} or missing:
            raise RuntimeError(f"incomplete P2 shard {policy}: missing={missing}, status={status}")
        frame = pd.read_csv(shard / "metrics.csv")
        if len(frame) != 1 or str(frame.iloc[0]["policy"]) != policy:
            raise RuntimeError(f"invalid P2 metrics shard: {policy}")
        metric_rows.append(frame.iloc[0])
    metrics = pd.DataFrame(metric_rows).reset_index(drop=True)
    selected_index = min(
        range(len(metrics)),
        key=lambda index: scheduler.p2_metrics_lexicographic_key(metrics.iloc[index]),
    )
    selected = metrics.iloc[selected_index]
    policy = str(selected["policy"])
    output = OUT / "p2_inpatient_only"
    output.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output / "policy_metrics.csv", index=False, encoding="utf-8-sig")
    for name in P2_DETAIL_FILES:
        shutil.copy2(p2_shard(policy) / name, output / name)
    selected_outcomes = pd.read_csv(
        output / "final_patient_outcomes.csv", low_memory=False
    )
    evaluated = scheduler.as_bool(selected_outcomes["evaluation_cohort"])
    deadline_met = scheduler.as_bool(selected_outcomes["deadline_met"])
    failure = (
        selected_outcomes.loc[evaluated & ~deadline_met, "failure_reason"]
        .fillna("unknown")
        .value_counts()
        .rename_axis("failure_reason")
        .reset_index(name="event_count")
    )
    failure.to_csv(
        output / "failure_reason_breakdown.csv", index=False, encoding="utf-8-sig"
    )
    save_json(
        output / "summary.json",
        {
            "scenario": "P2_INPATIENT_ONLY",
            "selected_policy": policy,
            "selection_rule": list(scheduler.P2_SELECTION_RULE),
            "candidate_policies": list(scheduler.P2_POLICY_CANDIDATES),
            "preparation_granularity": "item",
            "slack_definition": scheduler.INPATIENT_SLACK_DEFINITION,
            "patient_constraint_scope": scheduler.PATIENT_CONSTRAINT_SCOPE,
            "metrics": selected.to_dict(),
            "detail_materialized": True,
        },
    )


def run_p2() -> None:
    """Compatibility entry; formal full runs should dispatch p2-point in parallel."""
    for policy in scheduler.P2_POLICY_CANDIDATES:
        run_p2_point(policy)
    finalize_p2()


def schedule_background_until_target(
    calendar: scheduler.WorkCalendar,
    event_ids: list[str],
    lookup: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    required_background: int,
) -> tuple[dict[str, list[scheduler.PlanStep]], dict[str, str], list[str], dict[str, Any]]:
    """Reserve only the annual epsilon count; no per-day target is imposed."""
    plans: dict[str, list[scheduler.PlanStep]] = {}
    failure: dict[str, str] = {}
    attempted = 0
    for event_id in event_ids:
        if len(plans) >= required_background:
            break
        event = lookup.loc[event_id]
        if not bool(event.evaluation_cohort):
            continue
        steps = scheduler.plan_event(calendar, tasks[event_id], event.release_dt, event.deadline_dt)
        attempted += 1
        if steps is None:
            failure[event_id] = "no_compatible_room_under_scenario" if any(
                not task.compatible_rooms for task in tasks[event_id]
            ) else "no_complete_plan_by_deadline"
        else:
            plans[event_id] = steps
        if attempted % 25000 == 0:
            print(
                f"  global epsilon pass attempted={attempted:,}, completed={len(plans):,}/"
                f"{required_background:,}",
                flush=True,
            )
    remaining = [
        event_id for event_id in event_ids
        if event_id not in plans and event_id not in failure
    ]
    diagnostics = {
        "formal_constraint_scope": "entire evaluation year",
        "daily_quota_used": False,
        "required_background_events": required_background,
        "reserved_background_events_before_inpatient": len(plans),
        "background_attempts_before_inpatient": attempted,
        "reservation_target_met": len(plans) >= required_background,
    }
    return plans, failure, remaining, diagnostics


def build_p3_candidate(
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    room_names: dict[str, str],
    policy: str,
    capacity_column: str,
    transfer_minutes: int,
    required_background: int,
    construction_method: str,
    background_strategy: str,
) -> dict[str, Any]:
    """Construct one joint solution around the shared P2 scheduling kernel."""
    calendar = scheduler.create_calendar(
        capacity, rooms, policy, capacity_column, transfer_minutes,
    )
    lookup = events.set_index("event_id")
    if construction_method == "inpatient_first":
        _, inpatient_plans, inpatient_failure = scheduler.run_group_with_policy(
            calendar, events, tasks, policy, "inpatient",
        )
        _, background_plans, background_failure = scheduler.run_group_with_policy(
            calendar, events, tasks, policy, "background",
            strategy_override=background_strategy,
        )
        reservation = {
            "formal_constraint_scope": "entire evaluation year",
            "daily_quota_used": False,
            "required_background_events": required_background,
            "reserved_background_events_before_inpatient": 0,
            "background_attempts_before_inpatient": 0,
            "reservation_target_met": required_background == 0,
        }
    elif construction_method == "global_deficit_repair":
        background_order = scheduler.event_priority(
            events, tasks, "background", background_strategy,
        )
        reserved_plans, reserved_failure, remaining, reservation = (
            schedule_background_until_target(
                calendar, background_order, lookup, tasks, required_background,
            )
        )
        _, inpatient_plans, inpatient_failure = scheduler.run_group_with_policy(
            calendar, events, tasks, policy, "inpatient",
        )
        residual_plans, residual_failure = scheduler.schedule_group(
            calendar, remaining, lookup, tasks,
        )
        background_plans = {**reserved_plans, **residual_plans}
        background_failure = {**reserved_failure, **residual_failure}
    else:
        raise ValueError(f"unknown P3 construction method: {construction_method}")

    plans = {**background_plans, **inpatient_plans}
    failure = {**background_failure, **inpatient_failure}
    schedule = scheduler.plan_to_schedule(calendar, plans, events, policy, room_names)
    outcomes = scheduler.outcomes_from_schedule(events, schedule, failure, policy)
    metrics = scheduler.metrics_from_outcomes(
        outcomes, schedule, calendar, policy, "P3_CANDIDATE",
    )
    background_completed = int(metrics["background_on_planned_day"])
    diagnostics = {
        **reservation,
        "construction_method": construction_method,
        "background_order_strategy": background_strategy,
        "background_completed_events": background_completed,
        "background_deficit_events": max(0, required_background - background_completed),
        "epsilon_constraint_satisfied": background_completed >= required_background,
        "inpatient_completed_events": int(metrics["inpatient_complete_48h"]),
    }
    return {
        "schedule": schedule,
        "outcomes": outcomes,
        "calendar": calendar,
        "metrics": metrics,
        "diagnostics": diagnostics,
    }


def p3_candidate_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    metrics = candidate["metrics"]
    diagnostics = candidate["diagnostics"]
    return scheduler.p2_metrics_lexicographic_key(metrics) + (
        str(diagnostics["construction_method"]),
        str(diagnostics["background_order_strategy"]),
    )


def solve_p3_epsilon(
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    room_names: dict[str, str],
    policy: str,
    alpha: float,
    capacity_column: str = "capacity_main",
    transfer_minutes: int = scheduler.TRANSFER_MINUTES,
) -> dict[str, Any]:
    """Run the production P3 heuristic on a full year or benchmark subset."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must lie in [0, 1]")
    background_mask = events["evaluation_cohort"] & events["mandatory_background"]
    total_background = int(background_mask.sum())
    required_background = int(math.ceil(alpha * total_background))
    baseline = build_p3_candidate(
        events, tasks, capacity, rooms, room_names, policy, capacity_column,
        transfer_minutes, required_background, "inpatient_first", "scarcity",
    )
    candidates = [baseline]
    repair_triggered = not baseline["diagnostics"]["epsilon_constraint_satisfied"]
    if repair_triggered:
        def build_repair(background_strategy: str) -> dict[str, Any]:
            return build_p3_candidate(
                events, tasks, capacity, rooms, room_names, policy, capacity_column,
                transfer_minutes, required_background, "global_deficit_repair",
                background_strategy,
            )

        # The two repair calendars are independent and read only the shared
        # event/task inputs, so they can use separate CPU cores safely.
        with ThreadPoolExecutor(max_workers=2) as pool:
            candidates.extend(pool.map(build_repair, ("scarcity", "fcfs")))
    feasible_candidates = [
        candidate for candidate in candidates
        if candidate["diagnostics"]["epsilon_constraint_satisfied"]
    ]
    if feasible_candidates:
        selected = min(feasible_candidates, key=p3_candidate_key)
    else:
        selected = min(
            candidates,
            key=lambda candidate: (
                -candidate["diagnostics"]["background_completed_events"],
                *p3_candidate_key(candidate),
            ),
        )
    return {
        "selected": selected,
        "candidates": candidates,
        "repair_triggered": repair_triggered,
        "background_total_events": total_background,
        "background_required_events": required_background,
    }


def run_p3_point(
    alpha: float,
    save_detail: bool,
    preparation_mode: str = "item",
    special_seed: int | None = None,
    label: str | None = None,
    capability_mode: str = "hierarchical",
    capacity_column: str = "capacity_main",
    bladder_minutes: int = 60,
    transfer_minutes: int = scheduler.TRANSFER_MINUTES,
) -> dict[str, Any]:
    p2_summary = json.loads((OUT / "p2_inpatient_only" / "summary.json").read_text(encoding="utf-8"))
    policy = p2_summary["selected_policy"]
    events, tasks, capacity, rooms, room_names = scheduler.load_inputs(
        "five_percent_upper", capability_mode, bladder_minutes,
        preparation_mode=preparation_mode, special_seed=special_seed,
    )
    solution = solve_p3_epsilon(
        events, tasks, capacity, rooms, room_names, policy, alpha,
        capacity_column, transfer_minutes,
    )
    selected = solution["selected"]
    candidates = solution["candidates"]
    repair_triggered = solution["repair_triggered"]
    total_background = solution["background_total_events"]
    required_background = solution["background_required_events"]
    schedule = selected["schedule"]
    outcomes = selected["outcomes"]
    calendar = selected["calendar"]
    metrics = selected["metrics"]
    diagnostics = selected["diagnostics"]
    metrics["scenario"] = f"P3_ALPHA_{alpha_token(alpha)}"
    p2_complete = int(p2_summary["metrics"]["inpatient_complete_48h"])
    metrics.update(
        {
            "background_target_alpha": alpha,
            "background_total_events": total_background,
            "background_required_events": required_background,
            "background_completed_events": diagnostics["background_completed_events"],
            "background_deficit_events": diagnostics["background_deficit_events"],
            "epsilon_constraint_satisfied": diagnostics["epsilon_constraint_satisfied"],
            "construction_method": diagnostics["construction_method"],
            "background_order_strategy": diagnostics["background_order_strategy"],
            "daily_quota_used": False,
            "repair_triggered": repair_triggered,
            "p2_room_mode": scheduler.POLICIES[policy]["room_mode"],
            "alpha_zero_p2_complete_match": (
                int(metrics["inpatient_complete_48h"]) == p2_complete
                if math.isclose(alpha, 0.0, abs_tol=1e-12)
                else None
            ),
            "preparation_granularity": preparation_mode,
            "special_seed": special_seed if special_seed is not None else scheduler.source_config.SEED,
            "capability_mode": capability_mode,
            "capacity_column": capacity_column,
            "bladder_minutes": bladder_minutes,
            "transfer_minutes": transfer_minutes,
            "detail_saved": False,
        }
    )
    shard = (
        p3_shard(alpha)
        if label is None
        else OUT / "sensitivity_shards" / label
    )
    shard.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics]).to_csv(shard / "metrics.csv", index=False, encoding="utf-8-sig")
    candidate_diagnostics = []
    for candidate in candidates:
        row = dict(candidate["diagnostics"])
        row.update(
            {
                "inpatient_wait_p50_hours": candidate["metrics"]["inpatient_wait_p50_hours_conditional"],
                "inpatient_wait_p90_hours": candidate["metrics"]["inpatient_wait_p90_hours_conditional"],
                "inpatient_room_switch_rate": candidate["metrics"]["inpatient_room_switch_rate_multi"],
                "scheduled_minutes": candidate["metrics"]["scheduled_minutes"],
                "selected": candidate is selected,
            }
        )
        candidate_diagnostics.append(row)
    save_json(
        shard / "epsilon_diagnostics.json",
        {
            "alpha": alpha,
            "formal_constraint": (
                "background_completed_events >= ceil(alpha * background_total_events)"
            ),
            "background_total_events": total_background,
            "background_required_events": required_background,
            "repair_triggered": repair_triggered,
            "daily_quota_used": False,
            "candidates": candidate_diagnostics,
        },
    )
    if save_detail:
        schedule.to_csv(shard / "final_patient_task_schedule.csv", index=False, encoding="utf-8-sig")
        outcomes.to_csv(shard / "final_patient_outcomes.csv", index=False, encoding="utf-8-sig")
        daily, utilization = scheduler.daily_outputs(outcomes, schedule, calendar, policy)
        daily.to_csv(shard / "daily_service_metrics.csv", index=False, encoding="utf-8-sig")
        utilization.to_csv(shard / "room_utilization_daily.csv", index=False, encoding="utf-8-sig")
        scheduler.recommendation_table(schedule, outcomes).to_csv(
            shard / "inpatient_recommended_schedule.csv", index=False, encoding="utf-8-sig"
        )
        metrics["detail_saved"] = True
        pd.DataFrame([metrics]).to_csv(shard / "metrics.csv", index=False, encoding="utf-8-sig")
    return selected


def local_refinement_suggestions(
    front: pd.DataFrame,
    feasible: pd.DataFrame | None = None,
    scanned_alphas: list[float] | None = None,
) -> list[float]:
    """Suggest unscanned points near the attained front, including 1-2 point fronts."""
    ordered = front.sort_values("background_target_alpha").reset_index(drop=True)
    existing = {
        round(float(value), 10)
        for value in (
            scanned_alphas
            if scanned_alphas is not None
            else ordered["background_target_alpha"].tolist()
        )
    }

    def interval_points(left: float, right: float) -> list[float]:
        proposed = [
            round(left + (right - left) * fraction, 6)
            for fraction in (0.5, 0.25, 0.75)
        ]
        return [
            value for value in proposed
            if 0.0 <= value <= 1.0 and round(value, 10) not in existing
        ][:1]

    if len(ordered) == 1:
        alpha = float(ordered.iloc[0]["background_target_alpha"])
        pool = feasible if feasible is not None else ordered
        neighbors = [
            float(value) for value in pool["background_target_alpha"]
            if not math.isclose(float(value), alpha, abs_tol=1e-12)
        ]
        if not neighbors:
            neighbors = [
                value for value in DEFAULT_COARSE_ALPHAS
                if not math.isclose(value, alpha, abs_tol=1e-12)
            ]
        neighbor = min(neighbors, key=lambda value: (abs(value - alpha), value))
        return interval_points(min(alpha, neighbor), max(alpha, neighbor))
    if len(ordered) == 2:
        return interval_points(
            float(ordered.iloc[0]["background_target_alpha"]),
            float(ordered.iloc[1]["background_target_alpha"]),
        )
    x = ordered["background_on_time_rate"].to_numpy(dtype=float)
    y = ordered["inpatient_48h_rate"].to_numpy(dtype=float)
    x = (x - x.min()) / max(x.max() - x.min(), 1e-12)
    y = (y - y.min()) / max(y.max() - y.min(), 1e-12)
    x0, y0, x1, y1 = x[0], y[0], x[-1], y[-1]
    denominator = max(math.hypot(y1 - y0, x1 - x0), 1e-12)
    distances = np.abs(
        (y1 - y0) * x - (x1 - x0) * y + x1 * y0 - y1 * x0
    ) / denominator
    knee = int(np.argmax(distances[1:-1])) + 1
    alphas = ordered["background_target_alpha"].to_numpy(dtype=float)
    proposed = interval_points(alphas[knee - 1], alphas[knee])
    proposed.extend(interval_points(alphas[knee], alphas[knee + 1]))
    return sorted(set(proposed))


def has_local_refinement(alphas: list[float]) -> bool:
    coarse = {round(value, 10) for value in DEFAULT_COARSE_ALPHAS}
    return any(round(value, 10) not in coarse for value in alphas)


def materialize_selected_p3(alpha: float, output: Path) -> tuple[bool, list[str]]:
    shard = p3_shard(alpha)
    point_metrics = pd.read_csv(shard / "metrics.csv")
    detail_saved = str(point_metrics.iloc[0].get("detail_saved", False)).lower() == "true"
    if not detail_saved:
        return False, ["metrics.csv: detail_saved=false"]
    missing = [name for name in P3_DETAIL_FILES if not (shard / name).exists()]
    if missing:
        return False, missing
    for name in P3_DETAIL_FILES:
        shutil.copy2(shard / name, output / name)
    return True, []


def finalize_p3(alphas: list[float]) -> None:
    alphas = sorted(set(alphas))
    missing = [str(p3_shard(alpha) / "metrics.csv") for alpha in alphas if not (p3_shard(alpha) / "metrics.csv").exists()]
    if missing:
        raise FileNotFoundError("missing P3 point outputs:\n" + "\n".join(missing))
    parts = [
        pd.read_csv(p3_shard(alpha) / "metrics.csv") for alpha in alphas
    ]
    metrics = pd.concat(parts, ignore_index=True).sort_values("background_target_alpha")
    metrics["epsilon_feasible"] = (
        metrics["background_completed_events"] >= metrics["background_required_events"]
    )
    feasible = metrics[metrics["epsilon_feasible"]].copy()
    if feasible.empty:
        raise RuntimeError("all P3 epsilon constraints are infeasible")
    nondominated = []
    for row in feasible.itertuples(index=False):
        dominated = (
            (feasible["background_on_time_rate"] >= row.background_on_time_rate)
            & (feasible["inpatient_48h_rate"] >= row.inpatient_48h_rate)
            & (
                (feasible["background_on_time_rate"] > row.background_on_time_rate)
                | (feasible["inpatient_48h_rate"] > row.inpatient_48h_rate)
            )
        ).any()
        nondominated.append(not dominated)
    feasible["pareto_nondominated"] = nondominated
    front = feasible[feasible["pareto_nondominated"]].copy()
    bg_min, bg_max = front["background_on_time_rate"].min(), front["background_on_time_rate"].max()
    ip_min, ip_max = front["inpatient_48h_rate"].min(), front["inpatient_48h_rate"].max()
    front["distance_to_ideal"] = np.sqrt(
        ((bg_max - front["background_on_time_rate"]) / max(bg_max - bg_min, 1e-12)) ** 2
        + ((ip_max - front["inpatient_48h_rate"]) / max(ip_max - ip_min, 1e-12)) ** 2
    )
    selected = front.sort_values(
        ["distance_to_ideal", "background_on_time_rate", "inpatient_48h_rate"],
        ascending=[True, False, False],
    ).iloc[0]
    metrics = metrics.merge(
        feasible[["background_target_alpha", "pareto_nondominated"]],
        on="background_target_alpha", how="left",
    )
    metrics = metrics.merge(
        front[["background_target_alpha", "distance_to_ideal"]],
        on="background_target_alpha", how="left",
    )
    output = OUT / "p3_joint"
    output.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output / "pareto_metrics.csv", index=False, encoding="utf-8-sig")
    refinement_completed = has_local_refinement(alphas)
    suggestions = (
        []
        if refinement_completed
        else local_refinement_suggestions(front, feasible, alphas)
    )
    requires_new_point_runs = not refinement_completed
    selected_alpha = float(selected["background_target_alpha"])
    detail_materialized, missing_detail_files = materialize_selected_p3(selected_alpha, output)
    selected_metrics = {
        key: None if pd.isna(value) else value
        for key, value in selected.to_dict().items()
    }
    save_json(
        output / "local_refinement_suggestion.json",
        {
            "method": (
                "unscanned interval midpoints; maximum normalized chord-distance "
                "knee when at least three front points exist"
            ),
            "coarse_or_combined_alpha_grid": alphas,
            "local_refinement_completed": refinement_completed,
            "suggested_alpha_values": suggestions,
            "requires_new_point_runs_before_final_selection": requires_new_point_runs,
        },
    )
    save_json(
        output / "selection.json",
        {
            "formal_constraint": "background_completed >= ceil(alpha * total_background)",
            "candidate_set": "feasible attained nondominated heuristic solutions",
            "selection_rule": "minimum normalized Euclidean distance to the attained ideal",
            "normalization": {
                "background_min": float(bg_min),
                "background_max": float(bg_max),
                "inpatient_min": float(ip_min),
                "inpatient_max": float(ip_max),
                "formula": (
                    "sqrt(((background_max-background_rate)/(background_max-background_min))^2"
                    "+((inpatient_max-inpatient_rate)/(inpatient_max-inpatient_min))^2)"
                ),
            },
            "nondominated_alpha_values": [
                float(value)
                for value in front.sort_values("background_target_alpha")[
                    "background_target_alpha"
                ]
            ],
            "alpha_grid": alphas,
            "selected_alpha": selected_alpha,
            "selected_metrics": selected_metrics,
            "p2_policy": str(selected["policy"]),
            "slack_definition": scheduler.INPATIENT_SLACK_DEFINITION,
            "patient_constraint_scope": scheduler.PATIENT_CONSTRAINT_SCOPE,
            "global_epsilon_algorithm": "inpatient_first_then_global_deficit_repair",
            "daily_quota_used": False,
            "local_refinement_completed": refinement_completed,
            "requires_new_point_runs_before_final_selection": requires_new_point_runs,
            "detail_materialized": detail_materialized,
            "missing_detail_files": missing_detail_files,
            "selection_ready_for_freeze": (
                detail_materialized
                and refinement_completed
                and not requires_new_point_runs
            ),
        },
    )
    print(f"SELECTED_ALPHA={alpha_token(selected_alpha)}")
    print(f"DETAIL_MATERIALIZED={str(detail_materialized).upper()}")


def configured_alpha_grid(args: argparse.Namespace) -> list[float]:
    if args.alpha_grid:
        values = [float(value.strip()) for value in args.alpha_grid.split(",") if value.strip()]
    else:
        values = regular_alpha_grid(args.alpha_start, args.alpha_stop, args.alpha_step)
    refinement = (args.refine_start, args.refine_stop, args.refine_step)
    if any(value is not None for value in refinement):
        if not all(value is not None for value in refinement):
            raise ValueError("refinement requires --refine-start, --refine-stop and --refine-step")
        values.extend(regular_alpha_grid(*refinement))
    values = sorted(set(round(value, 10) for value in values))
    if not values or values[0] < 0 or values[-1] > 1:
        raise ValueError("all alpha values must lie in [0, 1]")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage",
        choices=["p2", "p2-point", "finalize-p2", "p3-point", "list-p3-grid", "finalize-p3"],
        required=True,
    )
    parser.add_argument("--policy", choices=list(scheduler.P2_POLICY_CANDIDATES))
    parser.add_argument("--alpha", type=float)
    parser.add_argument("--alpha-grid", help="comma-separated alpha values; overrides the regular coarse grid")
    parser.add_argument("--alpha-start", type=float, default=DEFAULT_COARSE_ALPHAS[0])
    parser.add_argument("--alpha-stop", type=float, default=DEFAULT_COARSE_ALPHAS[-1])
    parser.add_argument(
        "--alpha-step", type=float,
        default=DEFAULT_COARSE_ALPHAS[1] - DEFAULT_COARSE_ALPHAS[0],
    )
    parser.add_argument("--refine-start", type=float)
    parser.add_argument("--refine-stop", type=float)
    parser.add_argument("--refine-step", type=float)
    parser.add_argument("--save-detail", action="store_true")
    parser.add_argument("--preparation-mode", choices=["item", "event"], default="item")
    parser.add_argument("--special-seed", type=int)
    parser.add_argument("--label")
    parser.add_argument("--capability-mode", choices=["hierarchical", "strict"], default="hierarchical")
    parser.add_argument("--capacity-column", choices=["capacity_main", "capacity_low"], default="capacity_main")
    parser.add_argument("--bladder-minutes", type=int, default=60)
    parser.add_argument("--transfer-minutes", type=int, default=scheduler.TRANSFER_MINUTES)
    args = parser.parse_args()
    if args.stage == "p2":
        run_p2()
    elif args.stage == "p2-point":
        if args.policy is None:
            parser.error("--policy is required for p2-point")
        run_p2_point(args.policy)
    elif args.stage == "finalize-p2":
        finalize_p2()
    elif args.stage == "p3-point":
        if args.alpha is None:
            parser.error("--alpha is required for p3-point")
        run_p3_point(
            args.alpha, args.save_detail, args.preparation_mode, args.special_seed,
            args.label, args.capability_mode, args.capacity_column,
            args.bladder_minutes, args.transfer_minutes,
        )
    elif args.stage == "list-p3-grid":
        for alpha in configured_alpha_grid(args):
            print(alpha_token(alpha))
    else:
        finalize_p3(configured_alpha_grid(args))


if __name__ == "__main__":
    main()
