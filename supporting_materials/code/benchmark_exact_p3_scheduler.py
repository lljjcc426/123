"""Exact-vs-production benchmark for the P3 joint epsilon scheduler."""

from __future__ import annotations

import argparse
import inspect
import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

import benchmark_exact_scheduler as exact_core
import run_pre_freeze_scenarios as p3_solver
import run_unified_scheduler as scheduler


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "supporting_materials" / "results" / "p3_exact_benchmark"
DEFAULT_TIME_LIMIT_SECONDS = 180.0
DEFAULT_CASE_WORKERS = 4
DEFAULT_SOLVER_WORKERS = 2
SOURCE_ORDER = ("住院", "门诊", "体检")


def _eligible_joint_events(
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
) -> pd.DataFrame:
    frame = exact_core._event_features(events[events["evaluation_cohort"]], tasks)
    frame["case_date"] = frame["order_dt"].dt.normalize()
    background = frame["mandatory_background"]
    frame.loc[background, "case_date"] = frame.loc[background, "planned_date"].dt.normalize()
    return frame


def _date_with_all_sources(daily: pd.DataFrame) -> pd.DataFrame:
    required = [f"source_{source}" for source in SOURCE_ORDER]
    eligible = daily.copy()
    for column in required:
        eligible = eligible[eligible[column].gt(0)]
    if eligible.empty:
        raise RuntimeError("no benchmark date contains inpatient, outpatient and physical-exam events")
    return eligible


def _source_targets(target_size: int, scene: str) -> dict[str, int]:
    if scene == "background_peak":
        shares = {"住院": 0.25, "门诊": 0.40, "体检": 0.35}
    elif scene == "inpatient_peak":
        shares = {"住院": 0.60, "门诊": 0.20, "体检": 0.20}
    else:
        shares = {"住院": 0.40, "门诊": 0.32, "体检": 0.28}
    counts = {source: max(1, int(math.floor(target_size * shares[source]))) for source in SOURCE_ORDER}
    while sum(counts.values()) < target_size:
        source = max(SOURCE_ORDER, key=lambda item: target_size * shares[item] - counts[item])
        counts[source] += 1
    while sum(counts.values()) > target_size:
        source = max(SOURCE_ORDER, key=lambda item: counts[item] if counts[item] > 1 else -1)
        counts[source] -= 1
    return counts


def _select_case_events(
    frame: pd.DataFrame,
    date: pd.Timestamp,
    target_size: int,
    scene: str,
    priority_column: str | None,
) -> tuple[str, ...]:
    group = frame[frame["case_date"].eq(date)].copy()
    targets = _source_targets(target_size, scene)
    selected_parts: list[pd.DataFrame] = []
    selected_ids: set[str] = set()
    for source in SOURCE_ORDER:
        local = group[group["source"].eq(source)].copy()
        sort_columns: list[str] = []
        ascending: list[bool] = []
        if priority_column is not None:
            sort_columns.append(priority_column)
            ascending.append(False)
            sort_columns.append("service_project_count")
            ascending.append(False)
        sort_columns.extend(["order_dt", "event_id"])
        ascending.extend([True, True])
        part = local.sort_values(sort_columns, ascending=ascending, kind="stable").head(targets[source])
        selected_parts.append(part)
        selected_ids.update(part["event_id"].astype(str))
    selected = pd.concat(selected_parts, ignore_index=False)
    if len(selected) < target_size:
        remainder = group[~group["event_id"].astype(str).isin(selected_ids)].copy()
        sort_columns = [] if priority_column is None else [priority_column]
        ascending = [] if priority_column is None else [False]
        if priority_column is not None:
            sort_columns.append("service_project_count")
            ascending.append(False)
        sort_columns.extend(["order_dt", "event_id"])
        ascending.extend([True, True])
        selected = pd.concat(
            [
                selected,
                remainder.sort_values(sort_columns, ascending=ascending, kind="stable").head(
                    target_size - len(selected)
                ),
            ],
            ignore_index=False,
        )
    selected = selected.drop_duplicates("event_id", keep="first").head(target_size)
    if selected["source"].nunique() != 3:
        raise RuntimeError(f"case {scene} does not contain all three patient sources")
    return tuple(selected["event_id"].astype(str))


def representative_p3_cases(
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
) -> list[exact_core.BenchmarkCase]:
    """Build eight deterministic three-source stress windows at four scales."""

    frame = _eligible_joint_events(events, tasks)
    source_counts = (
        frame.assign(value=1)
        .pivot_table(index="case_date", columns="source", values="value", aggfunc="sum", fill_value=0)
        .rename(columns={source: f"source_{source}" for source in SOURCE_ORDER})
    )
    for source in SOURCE_ORDER:
        column = f"source_{source}"
        if column not in source_counts:
            source_counts[column] = 0
    daily_features = frame.groupby("case_date").agg(
        total=("event_id", "size"),
        background=("mandatory_background", "sum"),
        multi_count=("multi", "sum"),
        bedside_count=("bedside_task", "sum"),
        obstetric_count=("obstetric_task", "sum"),
        equipment_pressure_count=("equipment_pressure", "sum"),
    )
    daily = _date_with_all_sources(daily_features.join(source_counts, how="left").fillna(0))
    typical_date = exact_core._date_nearest(daily["total"], daily["total"].median())
    definitions = [
        ("ordinary_joint_n20", "ordinary", typical_date, 20, None),
        ("background_peak_n40", "background_peak", pd.Timestamp(daily["background"].idxmax()), 40, None),
        (
            "inpatient_peak_n60",
            "inpatient_peak",
            pd.Timestamp(daily["source_住院"].idxmax()),
            60,
            None,
        ),
        ("multi_project_peak_n40", "multi_project", pd.Timestamp(daily["multi_count"].idxmax()), 40, "multi"),
        ("bedside_pressure_n20", "bedside", pd.Timestamp(daily["bedside_count"].idxmax()), 20, "bedside_task"),
        (
            "obstetric_pressure_n40",
            "obstetric",
            pd.Timestamp(daily["obstetric_count"].idxmax()),
            40,
            "obstetric_task",
        ),
        (
            "equipment_competition_n60",
            "equipment",
            pd.Timestamp(daily["equipment_pressure_count"].idxmax()),
            60,
            "equipment_pressure",
        ),
        ("recommended_alpha_typical_n100", "recommended", typical_date, 100, None),
    ]
    cases: list[exact_core.BenchmarkCase] = []
    for name, scene, date, size, priority in definitions:
        event_ids = _select_case_events(frame, date, size, scene, priority)
        cases.append(exact_core.BenchmarkCase(name, pd.Timestamp(date), event_ids, size))
    return cases


def _compact_production_schedule(
    schedule: pd.DataFrame,
    calendar: scheduler.WorkCalendar,
) -> pd.DataFrame:
    if schedule.empty:
        return pd.DataFrame()
    result = schedule[
        ["event_id", "patient_id", "source", "item_index", "room_id", "start_dt", "end_dt"]
    ].copy()
    result["start_dt"] = pd.to_datetime(result["start_dt"])
    result["end_dt"] = pd.to_datetime(result["end_dt"])
    result["room_id"] = result["room_id"].astype(str)
    result["start_slot"] = result["start_dt"].map(lambda value: exact_core._actual_slot(calendar, value))
    result["end_slot"] = result["end_dt"].map(lambda value: exact_core._actual_slot(calendar, value))
    return result


def validate_production_candidate(
    case: exact_core.BenchmarkCase,
    selected: dict[str, Any],
    required_background: int,
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    policy: str,
) -> dict[str, int]:
    local_calendar = exact_core.make_calendar(case.date, rooms, capacity, policy=policy)
    schedule = _compact_production_schedule(selected["schedule"], local_calendar)
    outcomes = selected["outcomes"]
    selected_ids = set(outcomes.loc[outcomes["deadline_met"], "event_id"].astype(str))
    subset = events[events["event_id"].isin(case.event_ids)].copy()
    violations = exact_core.validate_exact_schedule(
        schedule,
        selected_ids,
        case.event_ids,
        subset,
        tasks,
        local_calendar,
        required_background,
    )
    actual_keys = [
        (str(row.event_id), int(row.item_index))
        for row in schedule.itertuples(index=False)
    ]
    expected_keys = {
        (event_id, int(task.item_index))
        for event_id in selected_ids
        for task in tasks[event_id]
    }
    task_lookup = {
        (event_id, int(task.item_index)): task
        for event_id in case.event_ids
        for task in tasks[event_id]
    }
    event_lookup = subset.set_index("event_id")
    patient_identity = 0
    duration = 0
    for row in schedule.itertuples(index=False):
        key = (str(row.event_id), int(row.item_index))
        task = task_lookup.get(key)
        if task is None or key[0] not in event_lookup.index:
            continue
        expected_patient = str(event_lookup.loc[key[0], "patient_id"])
        patient_identity += int(
            str(row.patient_id) != expected_patient
            or str(task.patient_id) != expected_patient
        )
        duration_minutes = (
            pd.Timestamp(row.end_dt) - pd.Timestamp(row.start_dt)
        ).total_seconds() / 60
        duration += int(
            int(row.end_slot) - int(row.start_slot) != int(task.duration_slots)
            or not math.isclose(
                duration_minutes,
                int(task.duration_slots) * scheduler.SLOT_MINUTES,
                abs_tol=1e-9,
            )
        )
    violations.update(
        {
            "task_key_unique": len(actual_keys) - len(set(actual_keys)),
            "task_identity": len(set(actual_keys).symmetric_difference(expected_keys)),
            "patient_identity": patient_identity,
            "duration": duration,
        }
    )
    return violations


def solve_p3_case(
    case: exact_core.BenchmarkCase,
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    room_names: dict[str, str],
    policy: str,
    alpha: float,
    time_limit_seconds: float,
    solver_workers: int,
) -> dict[str, Any]:
    subset = events[events["event_id"].isin(case.event_ids)].copy()
    source_counts = subset["source"].value_counts().to_dict()
    missing_sources = [source for source in SOURCE_ORDER if int(source_counts.get(source, 0)) == 0]
    if missing_sources:
        raise ValueError(f"case {case.name} is missing patient sources: {missing_sources}")
    if not subset["mandatory_background"].eq(~subset["source"].eq("住院")).all():
        raise ValueError(f"case {case.name} has inconsistent source/background labels")
    production = p3_solver.solve_p3_epsilon(
        subset,
        tasks,
        capacity,
        rooms,
        room_names,
        policy,
        alpha,
    )
    selected = production["selected"]
    heuristic_metrics = selected["metrics"]
    required_background = int(production["background_required_events"])
    expected_background = int(math.ceil(alpha * int(subset["mandatory_background"].sum())))
    if required_background != expected_background:
        raise RuntimeError(
            f"production P3 background lower bound {required_background} != {expected_background}"
        )
    heuristic_violations = validate_production_candidate(
        case,
        selected,
        required_background,
        events,
        tasks,
        capacity,
        rooms,
        policy,
    )
    exact = exact_core.solve_exact_subset(
        case,
        events,
        tasks,
        capacity,
        rooms,
        alpha=alpha,
        policy=policy,
        time_limit_seconds=time_limit_seconds,
        solver_workers=solver_workers,
    )
    if exact.required_background != expected_background:
        raise RuntimeError(
            f"exact P3 background lower bound {exact.required_background} != {expected_background}"
        )
    heuristic_inpatient = int(heuristic_metrics["inpatient_complete_48h"])
    heuristic_background = int(heuristic_metrics["background_on_planned_day"])
    incumbent = exact.inpatient_completed
    bound = exact.best_bound
    has_incumbent = exact.status in {"OPTIMAL", "FEASIBLE"}
    return {
        "case": case.name,
        "date": str(case.date.date()),
        "policy": policy,
        "target_event_count": case.target_size,
        "event_count": len(case.event_ids),
        "inpatient_events": int(source_counts.get("住院", 0)),
        "outpatient_events": int(source_counts.get("门诊", 0)),
        "physical_exam_events": int(source_counts.get("体检", 0)),
        "all_three_sources": all(int(source_counts.get(source, 0)) > 0 for source in SOURCE_ORDER),
        "alpha": alpha,
        "background_events": int(production["background_total_events"]),
        "required_background": required_background,
        "heuristic_background_complete": heuristic_background,
        "heuristic_inpatient_complete": heuristic_inpatient,
        "heuristic_epsilon_satisfied": bool(
            selected["diagnostics"]["epsilon_constraint_satisfied"]
        ),
        "heuristic_construction": str(selected["diagnostics"]["construction_method"]),
        "repair_triggered": bool(production["repair_triggered"]),
        "exact_background_complete": exact.background_completed,
        "exact_inpatient_incumbent": incumbent,
        "best_bound": bound,
        "solver_status": exact.status,
        "solver_relative_gap": (
            (bound - incumbent) / max(abs(bound), 1.0) if has_incumbent else float("nan")
        ),
        "heuristic_gap_to_incumbent": (
            (incumbent - heuristic_inpatient) / max(abs(incumbent), 1)
            if has_incumbent
            else float("nan")
        ),
        "heuristic_gap_to_bound": (bound - heuristic_inpatient) / max(abs(bound), 1.0),
        "solve_seconds": exact.solve_seconds,
        "time_limit_seconds": time_limit_seconds,
        "exact_schedule_violations": int(sum(exact.violation_counts.values())),
        "heuristic_schedule_violations": int(sum(heuristic_violations.values())),
    }


def _source_location(function: Any) -> str:
    path = Path(inspect.getsourcefile(function) or "unknown").resolve()
    line = inspect.getsourcelines(function)[1]
    try:
        path = path.relative_to(ROOT)
    except ValueError:
        pass
    return f"`{path.as_posix()}:{line}`"


def audit_real_peak_repair_path(
    events: pd.DataFrame,
    tasks: dict[str, list[scheduler.Task]],
    capacity: pd.DataFrame,
    rooms: list[str],
    room_names: dict[str, str],
    policy: str,
    alpha: float,
    alpha_source: str,
) -> dict[str, Any]:
    """Exercise the production repair branch on a deterministic real peak day."""

    frame = _eligible_joint_events(events, tasks)
    daily = (
        frame.groupby("case_date", as_index=False)
        .agg(event_count=("event_id", "size"), upper_minutes_total=("upper_minutes", "sum"))
        .sort_values(
            ["upper_minutes_total", "case_date"],
            ascending=[False, True],
            kind="stable",
        )
    )
    peak_date = pd.Timestamp(daily.iloc[0]["case_date"])
    peak = frame[frame["case_date"].eq(peak_date)].copy()
    event_ids = tuple(peak["event_id"].astype(str))
    subset = events[events["event_id"].isin(event_ids)].copy()
    solution = p3_solver.solve_p3_epsilon(
        subset,
        tasks,
        capacity,
        rooms,
        room_names,
        policy,
        alpha,
    )
    selected = solution["selected"]
    required_background = int(solution["background_required_events"])
    case = exact_core.BenchmarkCase(
        "real_upper_minutes_peak_repair_path",
        peak_date,
        event_ids,
        len(event_ids),
    )
    violations = validate_production_candidate(
        case,
        selected,
        required_background,
        events,
        tasks,
        capacity,
        rooms,
        policy,
    )
    candidate_rows = []
    for candidate in solution["candidates"]:
        diagnostics = candidate["diagnostics"]
        candidate_rows.append(
            {
                "construction_method": str(diagnostics["construction_method"]),
                "background_order_strategy": str(diagnostics["background_order_strategy"]),
                "background_completed_events": int(
                    diagnostics["background_completed_events"]
                ),
                "background_deficit_events": int(
                    diagnostics["background_deficit_events"]
                ),
                "inpatient_completed_events": int(
                    diagnostics["inpatient_completed_events"]
                ),
                "epsilon_constraint_satisfied": bool(
                    diagnostics["epsilon_constraint_satisfied"]
                ),
            }
        )
    selected_diagnostics = selected["diagnostics"]
    source_counts = subset["source"].value_counts().to_dict()
    return {
        "selection_rule": (
            "evaluation case_date maximizing sum(upper_minutes); "
            "ties resolved by earliest case_date"
        ),
        "date": str(peak_date.date()),
        "event_count": len(event_ids),
        "inpatient_events": int(source_counts.get("住院", 0)),
        "outpatient_events": int(source_counts.get("门诊", 0)),
        "physical_exam_events": int(source_counts.get("体检", 0)),
        "upper_minutes_total": int(peak["upper_minutes"].sum()),
        "policy": policy,
        "alpha": alpha,
        "alpha_source": alpha_source,
        "background_events": int(solution["background_total_events"]),
        "required_background": required_background,
        "repair_triggered": bool(solution["repair_triggered"]),
        "candidates": candidate_rows,
        "selected_construction_method": str(
            selected_diagnostics["construction_method"]
        ),
        "selected_background_order_strategy": str(
            selected_diagnostics["background_order_strategy"]
        ),
        "selected_background_complete": int(
            selected_diagnostics["background_completed_events"]
        ),
        "selected_inpatient_complete": int(
            selected_diagnostics["inpatient_completed_events"]
        ),
        "selected_epsilon_satisfied": bool(
            selected_diagnostics["epsilon_constraint_satisfied"]
        ),
        "validation_violations": {
            key: int(value) for key, value in violations.items()
        },
        "validation_violation_count": int(sum(violations.values())),
        "evidence_scope": "repair trigger and production-schedule feasibility",
        "repair_branch_optimality_claimed": False,
    }


def write_report(
    frame: pd.DataFrame,
    alpha: float,
    repair_audit: dict[str, Any],
) -> None:
    display_columns = [
        "case",
        "event_count",
        "inpatient_events",
        "outpatient_events",
        "physical_exam_events",
        "required_background",
        "heuristic_background_complete",
        "heuristic_inpatient_complete",
        "repair_triggered",
        "exact_inpatient_incumbent",
        "best_bound",
        "solver_status",
        "solver_relative_gap",
        "heuristic_gap_to_bound",
        "solve_seconds",
        "time_limit_seconds",
    ]
    optimal = frame[frame["solver_status"].eq("OPTIMAL")]
    optimal_gap_text = (
        f"{float(optimal['heuristic_gap_to_bound'].max()):.4%}"
        if not optimal.empty
        else "无已证最优场景"
    )
    repair_window_count = int(frame["repair_triggered"].map(bool).sum())
    lines = [
        "# P3 精确求解与生产启发式对照报告",
        "",
        f"基准服务下限为 alpha={alpha:.4f}，来源为 `{frame['alpha_source'].iloc[0]}`；生产策略为 `{frame['policy'].iloc[0]}`。每个子问题同时包含住院、门诊和体检事件，正式约束为 `background_completed >= ceil(alpha * background_events)`；逐日配额不在精确模型中。",
        "",
        "## 模型与实现",
        "",
        f"- P2生产策略解析：{_source_location(scheduler.resolve_authoritative_policy)}，P3不另设房间或住院排序策略。",
        f"- 项目展开、能力、床旁与项目级准备：{_source_location(scheduler.load_inputs)}，两侧共用同一 `Task` 集合。",
        f"- 生产 P3 入口：{_source_location(p3_solver.solve_p3_epsilon)}，与全年 P3 共用。",
        f"- 生产调度内核：{_source_location(scheduler.run_group_with_policy)} 与 {_source_location(scheduler.plan_event)}。",
        f"- 精确子问题：{_source_location(exact_core.solve_exact_subset)}。",
        "- 精确模型包含完整事件选择、项目设备兼容、床旁设备交集、项目级准备、空腹与憋尿、患者互斥、跨室转运、设备互斥、星期×5分钟医生容量、上午/下午工作块、住院48小时截止、背景计划日截止及背景最低完成数。",
        "",
        "## 八类代表窗口",
        "",
        exact_core._markdown_table(frame[display_columns]),
        "",
        "求解器相对间隙定义为 `(best_bound-incumbent)/max(|best_bound|,1)`；生产启发式相对最好界的差距按同一分母计算。",
        f"规模覆盖：{sorted(frame['event_count'].unique().tolist())}；三类患者同时存在：{bool(frame['all_three_sources'].all())}。",
        f"OPTIMAL 场景数：{int(frame['solver_status'].eq('OPTIMAL').sum())}/{len(frame)}；FEASIBLE 场景数：{int(frame['solver_status'].eq('FEASIBLE').sum())}/{len(frame)}。",
        f"所有场景相对最好界的最大启发式差距上界：{frame['heuristic_gap_to_bound'].max():.4%}。",
        f"仅在已证 OPTIMAL 场景中的最大启发式差距：{optimal_gap_text}。",
        f"CP-SAT 与生产启发式排程的独立约束检查违规数分别为 {int(frame['exact_schedule_violations'].sum())} 和 {int(frame['heuristic_schedule_violations'].sum())}。",
        "",
        "## 真实峰值日修复路径审计",
        "",
        f"按评估期 `case_date` 的 `upper_minutes` 总和最大且并列时日期最早的固定规则，选中 {repair_audit['date']}；共 {repair_audit['event_count']} 个事件（住院 {repair_audit['inpatient_events']}、门诊 {repair_audit['outpatient_events']}、体检 {repair_audit['physical_exam_events']}），项目时长区间上界汇总指标为 {repair_audit['upper_minutes_total']} 分钟。",
        f"基线完成背景事件 {repair_audit['candidates'][0]['background_completed_events']} 个，低于整数下限 {repair_audit['required_background']}，因此修复触发状态为 `{repair_audit['repair_triggered']}`。最终采用 `{repair_audit['selected_construction_method']}/{repair_audit['selected_background_order_strategy']}`，完成背景事件 {repair_audit['selected_background_complete']} 个、住院事件 {repair_audit['selected_inpatient_complete']} 个；ε约束满足状态为 `{repair_audit['selected_epsilon_satisfied']}`，独立约束检查违规数为 {repair_audit['validation_violation_count']}。",
        f"该审计只证明真实数据中修复分支会被自然触发，且输出排程满足正式约束；它不是修复分支的精确最优性证明。八个 CP-SAT 窗口中有 {repair_window_count} 个触发修复、{len(frame) - repair_window_count} 个采用基线构造，精确最优性结论只适用于各自被实际对照的子问题。",
        "",
        "## 结论边界",
        "",
        "`OPTIMAL` 只表示对应代表子问题在给定模型下已证最优；`FEASIBLE` 只报告 incumbent、best bound、gap 和时限。该基准用于量化生产启发式在代表窗口中的求解质量，不证明全年问题达到全局最优。",
    ]
    (ROOT / "P3_EXACT_VS_HEURISTIC_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def selected_alpha() -> tuple[float, str]:
    path = ROOT / "supporting_materials" / "results" / "final_frozen" / "p3_joint" / "selection.json"
    if not path.exists():
        raise FileNotFoundError(
            f"recommended-alpha file is absent: {path}; run P3 selection first or pass --alpha explicitly"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if "selected_alpha" not in data:
        raise KeyError(f"selected_alpha is absent from {path}")
    if (
        data.get("selection_ready_for_freeze") is not True
        or data.get("detail_materialized") is not True
        or data.get("requires_new_point_runs_before_final_selection") is not False
    ):
        raise RuntimeError(
            f"recommended alpha in {path} is provisional; finish local refinement "
            "and materialize the selected P3 detail before the formal exact benchmark"
        )
    return float(data["selected_alpha"]), path.relative_to(ROOT).as_posix()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alpha", type=float, default=None)
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
    if args.alpha is None:
        alpha, alpha_source = selected_alpha()
    else:
        alpha, alpha_source = float(args.alpha), "command_line:--alpha"
    if not 0.0 <= alpha <= 1.0:
        parser.error("--alpha must lie in [0, 1]")
    events, tasks, capacity, rooms, room_names = scheduler.load_inputs(
        "five_percent_upper", "hierarchical", 60, preparation_mode="item"
    )
    policy = scheduler.resolve_authoritative_policy(None)
    cases = representative_p3_cases(events, tasks)
    if args.case_names:
        wanted = set(args.case_names)
        cases = [case for case in cases if case.name in wanted]
        missing = wanted - {case.name for case in cases}
        if missing:
            parser.error(f"unknown cases: {sorted(missing)}")
    if args.validate_only:
        cases = [min(cases, key=lambda case: len(case.event_ids))]

    def solve(case: exact_core.BenchmarkCase) -> dict[str, Any]:
        row = solve_p3_case(
            case,
            events,
            tasks,
            capacity,
            rooms,
            room_names,
            policy,
            alpha,
            args.time_limit,
            args.solver_workers,
        )
        row["alpha_source"] = alpha_source
        return row

    with ThreadPoolExecutor(max_workers=max(1, min(args.parallel_cases, len(cases)))) as pool:
        rows = list(pool.map(solve, cases))
    frame = pd.DataFrame(rows)
    print(frame.to_string(index=False), flush=True)
    if args.validate_only:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUT / "p3_exact_vs_heuristic_metrics.csv", index=False, encoding="utf-8-sig")
    repair_audit = audit_real_peak_repair_path(
        events,
        tasks,
        capacity,
        rooms,
        room_names,
        policy,
        alpha,
        alpha_source,
    )
    (OUT / "p3_repair_path_audit.json").write_text(
        json.dumps(repair_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(frame, alpha, repair_audit)


if __name__ == "__main__":
    main()
