"""Run the staged historical-to-model calibration decomposition."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd

import analyze_p1 as p1
import run_unified_scheduler as scheduler


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "supporting_materials" / "processed_data" / "raw_parquet"
OUT = ROOT / "supporting_materials" / "results" / "calibration"


def historical_holdout_rate() -> tuple[int, int, float]:
    frame = p1.load_detail(RAW / "inpatient.parquet", "住院")
    frame = frame[
        frame["order_dt"].between(pd.Timestamp("2024-04-01"), pd.Timestamp("2025-04-01"), inclusive="left")
    ].copy()
    frame = frame.sort_values("source_row", kind="stable")
    duplicate_columns = ["patient_id", "order_dt", "ordered_project", "report_dt", "exam_doctor_id", "machine_id"]
    frame = frame[~frame.duplicated(duplicate_columns, keep="first")]
    grouped = frame.groupby(["patient_id", "order_dt"], dropna=False).agg(
        rows=("source_row", "size"), reports=("report_dt", "count"), completion=("report_dt", "max")
    ).reset_index()
    grouped["complete"] = grouped["reports"].eq(grouped["rows"]) & grouped["completion"].le(
        grouped["order_dt"] + pd.Timedelta(hours=48)
    ) & grouped["completion"].ge(grouped["order_dt"])
    return len(grouped), int(grouped["complete"].sum()), float(grouped["complete"].mean())


def run_variant(name: str) -> None:
    events, tasks, capacity, rooms, room_names = scheduler.load_inputs(
        "five_percent_upper", "hierarchical", 60, preparation_mode="item"
    )
    events = events[~events["mandatory_background"]].copy()
    tasks = {event_id: tasks[event_id] for event_id in events["event_id"]}
    if name in {"C2_standard_hours", "C3_doctor_capacity"}:
        tasks = {
            event_id: [
                replace(task, compatible_rooms=tuple(rooms), fasting=False, bladder=False, bedside=False)
                for task in event_tasks
            ]
            for event_id, event_tasks in tasks.items()
        }
    elif name == "C4_project_capability":
        tasks = {
            event_id: [replace(task, fasting=False, bladder=False) for task in event_tasks]
            for event_id, event_tasks in tasks.items()
        }
    if name == "C2_standard_hours":
        capacity = capacity.copy()
        capacity["capacity_main"] = len(rooms)
    schedule, outcomes, metrics, _, _, _ = scheduler.run_policy(
        events, tasks, capacity, rooms, room_names, "SLACK_GUARD_SHARED",
        "capacity_main", name, scheduler.TRANSFER_MINUTES,
    )
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([metrics]).to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8-sig")


def finalize() -> None:
    total, completed, rate = historical_holdout_rate()
    events = pd.read_csv(
        ROOT / "supporting_materials" / "processed_data" / "unified_holdout" / "events.csv",
        encoding="utf-8-sig",
    )
    inpatient = events[(events["source"] == "住院") & events["evaluation_cohort"].astype(str).str.lower().eq("true")]
    c1_complete = int((inpatient["upper_minutes"] <= 48 * 60).sum())
    rows = [
        {"scenario": "C0_historical_report", "completed": completed, "total": total, "rate": rate, "added_constraint": "observed order-to-report result"},
        {"scenario": "C1_duration_only", "completed": c1_complete, "total": len(inpatient), "rate": c1_complete / len(inpatient), "added_constraint": "problem upper durations only"},
    ]
    labels = {
        "C2_standard_hours": "8-12 and 13-17 work blocks; all rooms interchangeable; 22-doctor cap",
        "C3_doctor_capacity": "training-derived weekday-slot doctor capacity",
        "C4_project_capability": "reviewed project-machine compatibility without preparation",
    }
    for name, description in labels.items():
        metric = pd.read_csv(OUT / f"{name}.csv").iloc[0]
        rows.append({
            "scenario": name,
            "completed": int(metric["inpatient_complete_48h"]),
            "total": int(metric["inpatient_events"]),
            "rate": float(metric["inpatient_48h_rate"]),
            "added_constraint": description,
        })
    p2 = json.loads((ROOT / "supporting_materials" / "results" / "final_frozen" / "p2_inpatient_only" / "summary.json").read_text(encoding="utf-8"))
    rows.append({
        "scenario": "C5_item_preparation",
        "completed": p2["metrics"]["inpatient_complete_48h"],
        "total": p2["metrics"]["inpatient_events"],
        "rate": p2["metrics"]["inpatient_48h_rate"],
        "added_constraint": "item-level fasting, bladder readiness and bedside semantics",
    })
    selection = json.loads((ROOT / "supporting_materials" / "results" / "final_frozen" / "p3_joint" / "selection.json").read_text(encoding="utf-8"))
    selected = selection["selected_metrics"]
    rows.append({
        "scenario": "C6_joint_background",
        "completed": int(selected["inpatient_complete_48h"]),
        "total": int(selected["inpatient_events"]),
        "rate": float(selected["inpatient_48h_rate"]),
        "added_constraint": f"outpatient/physical-exam epsilon target alpha={selection['selected_alpha']}",
    })
    rows.append({
        "scenario": "C7_formal_heuristic",
        "completed": int(selected["inpatient_complete_48h"]),
        "total": int(selected["inpatient_events"]),
        "rate": float(selected["inpatient_48h_rate"]),
        "added_constraint": "selected deterministic large-scale construction policy",
    })
    frame = pd.DataFrame(rows)
    frame["change_from_previous_pp"] = frame["rate"].diff() * 100
    frame.to_csv(OUT / "calibration_metrics.csv", index=False, encoding="utf-8-sig")
    frame[["scenario", "change_from_previous_pp"]].to_csv(
        OUT / "calibration_waterfall.csv", index=False, encoding="utf-8-sig"
    )
    columns = list(frame.columns)
    markdown = [
        "|" + "|".join(columns) + "|",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in frame.itertuples(index=False, name=None):
        markdown.append("|" + "|".join(str(value).replace("|", "/") for value in row) + "|")
    text = [
        "# 历史现实校准报告", "",
        "历史报告完成率与标准化排程率口径不同。下表在同一留出期事件定义上逐层加入题给时长、标准班次、医生并发、设备能力、准备条件和背景负荷。", "",
        "\n".join(markdown), "",
        "C0使用真实报告提交时刻；C1-C7使用排程中最后任务结束作为报告完成代理。两者不能直接作因果比较，分层结果用于定位模型下降来自哪一类约束。",
    ]
    (OUT / "CALIBRATION_REPORT.md").write_text("\n".join(text), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=["C2_standard_hours", "C3_doctor_capacity", "C4_project_capability", "finalize"], required=True)
    args = parser.parse_args()
    if args.scenario == "finalize":
        finalize()
    else:
        run_variant(args.scenario)


if __name__ == "__main__":
    main()
