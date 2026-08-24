"""Run the pre-freeze P2 and P3 scenarios on the audited scheduling kernel."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import run_unified_scheduler as scheduler


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "supporting_materials" / "results" / "final_frozen"
ALPHAS = [0.0, 0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70]


def save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_p2() -> None:
    events, tasks, capacity, rooms, room_names = scheduler.load_inputs(
        "five_percent_upper", "hierarchical", 60, preparation_mode="item"
    )
    events = events[~events["mandatory_background"]].copy()
    tasks = {event_id: tasks[event_id] for event_id in events["event_id"]}
    output = OUT / "p2_inpatient_only"
    output.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[str, pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame, pd.DataFrame]] = []
    for policy in ["FCFS_SHARED", "SLACK_GUARD_SHARED"]:
        schedule, outcomes, metrics, daily, utilization, _ = scheduler.run_policy(
            events, tasks, capacity, rooms, room_names, policy, "capacity_main",
            "P2_INPATIENT_ONLY", scheduler.TRANSFER_MINUTES,
        )
        candidates.append((policy, schedule, outcomes, metrics, daily, utilization))
    selected = max(
        candidates,
        key=lambda item: (
            item[3]["inpatient_complete_48h"],
            -item[3]["inpatient_wait_p90_hours_conditional"],
        ),
    )
    policy, schedule, outcomes, metrics, daily, utilization = selected
    pd.DataFrame([item[3] for item in candidates]).to_csv(
        output / "policy_metrics.csv", index=False, encoding="utf-8-sig"
    )
    schedule.to_csv(output / "final_patient_task_schedule.csv", index=False, encoding="utf-8-sig")
    outcomes.to_csv(output / "final_patient_outcomes.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(output / "daily_service_metrics.csv", index=False, encoding="utf-8-sig")
    utilization.to_csv(output / "room_utilization_daily.csv", index=False, encoding="utf-8-sig")
    scheduler.recommendation_table(schedule, outcomes).to_csv(
        output / "inpatient_recommended_schedule.csv", index=False, encoding="utf-8-sig"
    )
    failure = (
        outcomes.loc[~outcomes["deadline_met"], "failure_reason"]
        .fillna("unknown")
        .value_counts()
        .rename_axis("failure_reason")
        .reset_index(name="event_count")
    )
    failure.to_csv(output / "failure_reason_breakdown.csv", index=False, encoding="utf-8-sig")
    save_json(
        output / "summary.json",
        {
            "scenario": "P2_INPATIENT_ONLY",
            "selected_policy": policy,
            "preparation_granularity": "item",
            "metrics": metrics,
        },
    )


def schedule_quota(
    calendar: scheduler.WorkCalendar,
    event_ids: list[str],
    lookup: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    alpha: float,
) -> tuple[dict[str, list[scheduler.PlanStep]], dict[str, str], list[str], dict[str, Any]]:
    plans: dict[str, list[scheduler.PlanStep]] = {}
    failure: dict[str, str] = {}
    remaining: list[str] = []
    frame = lookup.loc[event_ids].copy()
    warmup_ids = frame.index[~frame["evaluation_cohort"]].tolist()
    warmup_plans, warmup_failure = scheduler.schedule_group(calendar, warmup_ids, lookup, tasks)
    plans.update(warmup_plans)
    failure.update(warmup_failure)

    daily_rows: list[dict[str, Any]] = []
    evaluation = frame[frame["evaluation_cohort"]].copy()
    evaluation["quota_date"] = evaluation["planned_date"].dt.normalize()
    order_rank = {event_id: rank for rank, event_id in enumerate(event_ids)}
    for date, group in evaluation.groupby("quota_date", sort=True):
        ids = sorted(group.index.tolist(), key=order_rank.get)
        target = int(math.ceil(alpha * len(ids)))
        achieved = 0
        attempted = 0
        for position, event_id in enumerate(ids):
            if achieved >= target:
                remaining.extend(ids[position:])
                break
            event = lookup.loc[event_id]
            steps = scheduler.plan_event(calendar, tasks[event_id], event.release_dt, event.deadline_dt)
            attempted += 1
            if steps is None:
                failure[event_id] = "no_compatible_room_under_scenario" if any(
                    not task.compatible_rooms for task in tasks[event_id]
                ) else "no_complete_plan_by_deadline"
            else:
                plans[event_id] = steps
                achieved += 1
        else:
            remaining.extend([])
        daily_rows.append(
            {
                "date": str(pd.Timestamp(date).date()),
                "events": len(ids),
                "target": target,
                "achieved_before_inpatient": achieved,
                "attempted": attempted,
                "target_met": achieved >= target,
            }
        )
    daily = pd.DataFrame(daily_rows)
    diagnostics = {
        "alpha": alpha,
        "quota_days": int(len(daily)),
        "quota_shortfall_days": int((~daily["target_met"]).sum()) if len(daily) else 0,
        "quota_target_events": int(daily["target"].sum()) if len(daily) else 0,
        "quota_achieved_before_inpatient": int(daily["achieved_before_inpatient"].sum()) if len(daily) else 0,
        "daily_rows": daily_rows,
    }
    return plans, failure, remaining, diagnostics


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
) -> None:
    p2_summary = json.loads((OUT / "p2_inpatient_only" / "summary.json").read_text(encoding="utf-8"))
    policy = p2_summary["selected_policy"]
    events, tasks, capacity, rooms, room_names = scheduler.load_inputs(
        "five_percent_upper", capability_mode, bladder_minutes,
        preparation_mode=preparation_mode, special_seed=special_seed,
    )
    lookup = events.set_index("event_id")
    scarcity = scheduler.task_room_scarcity()
    calendar = scheduler.WorkCalendar(
        scheduler.source_config.SIMULATION_START,
        scheduler.source_config.HOLDOUT_END_EXCLUSIVE + pd.Timedelta(days=scheduler.FOLLOWUP_DAYS),
        rooms, capacity, capacity_column, scarcity, "scarcity", transfer_minutes,
    )
    background_order = scheduler.event_priority(events, tasks, "background", "scarcity")
    background_plans, background_failure, remaining, quota = schedule_quota(
        calendar, background_order, lookup, tasks, alpha
    )
    inpatient_order = scheduler.event_priority(
        events, tasks, "inpatient", scheduler.POLICIES[policy]["inpatient"]
    )
    inpatient_plans, inpatient_failure = scheduler.schedule_group(
        calendar, inpatient_order, lookup, tasks
    )
    residual_plans, residual_failure = scheduler.schedule_group(
        calendar, remaining, lookup, tasks
    )
    plans = {**background_plans, **inpatient_plans, **residual_plans}
    failure = {**background_failure, **inpatient_failure, **residual_failure}
    schedule = scheduler.plan_to_schedule(calendar, plans, events, policy, room_names)
    outcomes = scheduler.outcomes_from_schedule(events, schedule, failure, policy)
    metrics = scheduler.metrics_from_outcomes(
        outcomes, schedule, calendar, policy, f"P3_ALPHA_{alpha:.2f}"
    )
    metrics.update(
        {
            "background_target_alpha": alpha,
            "quota_shortfall_days": quota["quota_shortfall_days"],
            "quota_target_events": quota["quota_target_events"],
            "quota_achieved_before_inpatient": quota["quota_achieved_before_inpatient"],
            "preparation_granularity": preparation_mode,
            "special_seed": special_seed if special_seed is not None else scheduler.source_config.SEED,
            "capability_mode": capability_mode,
            "capacity_column": capacity_column,
            "bladder_minutes": bladder_minutes,
            "transfer_minutes": transfer_minutes,
        }
    )
    shard = (
        OUT / "p3_shards" / f"alpha_{alpha:.2f}"
        if label is None
        else OUT / "sensitivity_shards" / label
    )
    shard.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics]).to_csv(shard / "metrics.csv", index=False, encoding="utf-8-sig")
    save_json(shard / "quota_diagnostics.json", quota)
    if save_detail:
        schedule.to_csv(shard / "final_patient_task_schedule.csv", index=False, encoding="utf-8-sig")
        outcomes.to_csv(shard / "final_patient_outcomes.csv", index=False, encoding="utf-8-sig")
        daily, utilization = scheduler.daily_outputs(outcomes, schedule, calendar, policy)
        daily.to_csv(shard / "daily_service_metrics.csv", index=False, encoding="utf-8-sig")
        utilization.to_csv(shard / "room_utilization_daily.csv", index=False, encoding="utf-8-sig")
        scheduler.recommendation_table(schedule, outcomes).to_csv(
            shard / "inpatient_recommended_schedule.csv", index=False, encoding="utf-8-sig"
        )


def finalize_p3() -> None:
    parts = [
        pd.read_csv(OUT / "p3_shards" / f"alpha_{alpha:.2f}" / "metrics.csv")
        for alpha in ALPHAS
    ]
    metrics = pd.concat(parts, ignore_index=True).sort_values("background_target_alpha")
    # The epsilon constraint is defined on the holdout-wide background
    # completion rate, matching the competition KPI.  Daily quota shortfalls
    # remain a diagnostic for heterogeneous demand/capability and are not a
    # reason to discard a point that satisfies the declared annual epsilon.
    feasible = metrics[
        metrics["background_on_time_rate"] + 1e-12
        >= metrics["background_target_alpha"]
    ].copy()
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
    output = OUT / "p3_joint"
    output.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(output / "pareto_metrics.csv", index=False, encoding="utf-8-sig")
    save_json(
        output / "selection.json",
        {
            "selection_rule": "minimum normalized Euclidean distance to the attainable Pareto ideal",
            "selected_alpha": float(selected["background_target_alpha"]),
            "selected_metrics": selected.to_dict(),
        },
    )
    print(f"SELECTED_ALPHA={selected['background_target_alpha']:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["p2", "p3-point", "finalize-p3"], required=True)
    parser.add_argument("--alpha", type=float)
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
    elif args.stage == "p3-point":
        if args.alpha is None:
            parser.error("--alpha is required for p3-point")
        run_p3_point(
            args.alpha, args.save_detail, args.preparation_mode, args.special_seed,
            args.label, args.capability_mode, args.capacity_column,
            args.bladder_minutes, args.transfer_minutes,
        )
    else:
        finalize_p3()


if __name__ == "__main__":
    main()
