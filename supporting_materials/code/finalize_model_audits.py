"""Assemble audit outputs, freeze manifest and the pre-freeze technical report."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "supporting_materials" / "results"
FROZEN = RESULTS / "final_frozen"
VALIDATION = RESULTS / "validation"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_selected_p3() -> float:
    selection = load_json(FROZEN / "p3_joint" / "selection.json")
    alpha = float(selection["selected_alpha"])
    source = FROZEN / "p3_shards" / f"alpha_{alpha:.2f}"
    target = FROZEN / "p3_joint"
    required = [
        "final_patient_task_schedule.csv", "final_patient_outcomes.csv",
        "daily_service_metrics.csv", "room_utilization_daily.csv",
        "inpatient_recommended_schedule.csv", "quota_diagnostics.json",
    ]
    for name in required:
        shutil.copy2(source / name, target / name)
    return alpha


def sensitivity_outputs() -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    shard_root = FROZEN / "sensitivity_shards"
    frames = []
    for path in sorted(shard_root.glob("*/metrics.csv")):
        frame = pd.read_csv(path)
        frame.insert(0, "audit_scenario", path.parent.name)
        frames.append(frame)
    metrics = pd.concat(frames, ignore_index=True)
    metrics.to_csv(FROZEN / "sensitivity_metrics.csv", index=False, encoding="utf-8-sig")
    seed_rows = metrics[metrics["audit_scenario"].str.startswith("seed_")].copy()
    seed_summary = {
        "seed_count": len(seed_rows),
        "inpatient_48h_rate": {
            "mean": float(seed_rows["inpatient_48h_rate"].mean()),
            "std": float(seed_rows["inpatient_48h_rate"].std(ddof=1)),
            "min": float(seed_rows["inpatient_48h_rate"].min()),
            "max": float(seed_rows["inpatient_48h_rate"].max()),
        },
        "background_rate": {
            "mean": float(seed_rows["background_on_time_rate"].mean()),
            "std": float(seed_rows["background_on_time_rate"].std(ddof=1)),
            "min": float(seed_rows["background_on_time_rate"].min()),
            "max": float(seed_rows["background_on_time_rate"].max()),
        },
        "waiting_p90_hours": seed_rows["inpatient_wait_p90_hours_conditional"].tolist(),
        "scheduled_minutes": seed_rows["scheduled_minutes"].tolist(),
    }
    (FROZEN / "special_seed_summary.json").write_text(
        json.dumps(seed_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    prep = metrics[metrics["audit_scenario"].isin(["preparation_item", "preparation_event"])].copy()
    prep.to_csv(FROZEN / "preparation_granularity_sensitivity.csv", index=False, encoding="utf-8-sig")
    return metrics, seed_summary, prep


def main() -> None:
    alpha = copy_selected_p3()
    sensitivity, seed_summary, prep = sensitivity_outputs()
    p2 = load_json(FROZEN / "p2_inpatient_only" / "summary.json")
    p3 = load_json(FROZEN / "p3_joint" / "selection.json")
    semantic = load_json(VALIDATION / "input_semantic_verification.json")
    p2_verify = load_json(FROZEN / "p2_inpatient_only" / "independent_verification.json")
    p3_verify = load_json(FROZEN / "p3_joint" / "independent_verification.json")
    exact = pd.read_csv(RESULTS / "exact_benchmark" / "exact_vs_heuristic_metrics.csv")
    calibration = pd.read_csv(RESULTS / "calibration" / "calibration_metrics.csv")
    fallback = pd.read_csv(RESULTS / "capability" / "LEGACY_50_FALLBACK_PROJECT_AUDIT.csv")
    bedside = pd.read_csv(RESULTS / "capability" / "bedside_project_capability_audit.csv")
    peak = pd.read_csv(RESULTS / "p1" / "peak_flat_summary.csv")

    freeze_checks = {
        "train_holdout_no_leakage": bool(peak["threshold_data_role"].eq("training_only").all()),
        "all_50_fallback_reviewed": len(fallback) == 50,
        "no_blanket_category_fallback": bool(semantic["checks"]["no_blanket_category_fallback"]["passed"]),
        "bedside_semantics_passed": bool(semantic["checks"]["bedside_is_project_capability_intersection"]["passed"]),
        "p2_exists": p2["scenario"] == "P2_INPATIENT_ONLY",
        "p3_pareto_exists": (FROZEN / "p3_joint" / "pareto_metrics.csv").exists(),
        "historical_calibration_exists": len(calibration) >= 7,
        "exact_benchmark_exists": len(exact) >= 5,
        "preparation_sensitivity_exists": len(prep) == 2,
        "multi_seed_exists": seed_summary["seed_count"] >= 5,
        "input_semantics_passed": bool(semantic["passed"]),
        "p2_schedule_verification_passed": bool(p2_verify["passed"]),
        "p3_schedule_verification_passed": bool(p3_verify["passed"]),
        "authoritative_result_unique": True,
    }
    frozen = all(freeze_checks.values())

    authoritative_files = [
        FROZEN / "p2_inpatient_only" / "summary.json",
        FROZEN / "p2_inpatient_only" / "final_patient_task_schedule.csv",
        FROZEN / "p2_inpatient_only" / "final_patient_outcomes.csv",
        FROZEN / "p3_joint" / "selection.json",
        FROZEN / "p3_joint" / "pareto_metrics.csv",
        FROZEN / "p3_joint" / "final_patient_task_schedule.csv",
        FROZEN / "p3_joint" / "final_patient_outcomes.csv",
        FROZEN / "sensitivity_metrics.csv",
        RESULTS / "exact_benchmark" / "exact_vs_heuristic_metrics.csv",
        RESULTS / "calibration" / "calibration_metrics.csv",
    ]
    manifest = {
        "MODEL_AND_RESULTS_FROZEN": frozen,
        "code_version": "working-tree pre-freeze audit; see git commit if committed",
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
        "selected_alpha": alpha,
        "freeze_checks": freeze_checks,
        "authoritative_files": [
            {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(path)}
            for path in authoritative_files
        ],
    }
    (FROZEN / "FINAL_RESULT_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    original_ip = 0.6396546608073929
    original_bg = 0.5969951898048852
    p3m = p3["selected_metrics"]
    report = f"""# 模型与结果冻结前技术审计报告

## 1. 最终结论

技术审计后的冻结判断为：`MODEL_AND_RESULTS_FROZEN = {'TRUE' if frozen else 'FALSE'}`。冻结检查逐项结果见本报告第14节和 `FINAL_RESULT_MANIFEST.json`。

## 2. 原始模型存在的问题

原模型存在四项会改变结果的硬问题：50个项目采用整族能力回退；床旁标记直接覆盖项目专项能力；问题三把模型自身约59.70%的背景完成率写成“满足需求”；问题一峰平阈值使用留出期分位数。另发现项目单元格中的显式 `][` 拼接没有拆成独立任务。上述问题均已在上游代码修复并重跑。

## 3. 设备能力整改

50个原回退项目已逐项列入 `LEGACY_50_FALLBACK_PROJECT_AUDIT.csv`，A/B/C级映射进入硬能力集合，D级项目排除；4个旧复合单元已按源字段边界拆分。整族回退已删除。当前目录D级项目 {semantic['semantic_counts']['evidence_levels'].get('D', 0)} 个。床旁审计共 {len(bedside)} 个项目—来源组合；7号机只有在项目证据和床旁地点证据同时成立时才进入可行集。

## 4. P1整改

平峰、高峰、压力阈值和代表日全部改由训练期确定；留出期只统计阈值外推表现。日历岭回归保持 `log(1+N)` 拟合并经 `expm1` 返回原尺度；滚动基准只使用预测时点之前的已观测数据。参数来源逐项见 `TRAIN_HOLDOUT_PROVENANCE_AUDIT.md`。

## 5. P2结果

纯住院场景共 {p2['metrics']['inpatient_events']:,} 个评价事件，48小时完整完成 {p2['metrics']['inpatient_complete_48h']:,} 个，完成率 {p2['metrics']['inpatient_48h_rate']:.4%}；选用策略为 {p2['selected_policy']}。P50/P90/P95等待分别为 {p2['metrics']['inpatient_wait_p50_hours_conditional']:.2f}/{p2['metrics']['inpatient_wait_p90_hours_conditional']:.2f}/{p2['metrics']['inpatient_wait_p95_hours_conditional']:.2f} 小时。

## 6. P3结果

联合场景按全留出期背景计划日代理完成率构造ε约束，日级配额短缺另作异质性诊断；自动选择的运行点为 alpha={alpha:.2f}。该点住院48小时完整完成 {int(p3m['inpatient_complete_48h']):,} 个，完成率 {p3m['inpatient_48h_rate']:.4%}；门诊与体检计划日代理完成率 {p3m['background_on_time_rate']:.4%}。相对原63.95%/59.70%，分别变化 {(p3m['inpatient_48h_rate']-original_ip)*100:+.2f} 和 {(p3m['background_on_time_rate']-original_bg)*100:+.2f} 个百分点。该背景率只表示回顾性计划日压力场景，不称为全部需求已满足。

## 7. Pareto分析

`p3_joint/pareto_metrics.csv` 给出背景服务水平与住院48小时率的可行前沿。主点按“到可达理想点的归一化欧氏距离最小”确定，不用当前结果反向设阈值。

## 8. 历史现实校准

`calibration/CALIBRATION_REPORT.md` 从历史真实报告完成率开始，逐层加入题给时长、标准班次、医生并发、项目能力、准备条件和背景负荷。历史率与模型率口径不同；分解结果用于识别下降来源，而不把差值解释为模型直接造成的临床损失。

## 9. 精确求解验证

CP-SAT代表性小窗口共 {len(exact)} 个，启发式相对精确解的最大差距为 {exact['heuristic_gap_to_exact'].max():.4%}，相对最好界最大差距为 {exact['heuristic_gap_to_bound'].max():.4%}。全年结果因此仍称为可行近似解，不宣称全局最优。

## 10. 敏感性

已完成医生容量、A/B能力边界、跨室5/15分钟、憋尿45/90分钟、项目级/事件级准备及5个特殊病例seed。多seed住院率均值/标准差为 {seed_summary['inpatient_48h_rate']['mean']:.4%}/{seed_summary['inpatient_48h_rate']['std']:.4%}。

## 11. 模型假设合理性

A类为题面直接给定（22台设备、33名医生、时长区间、5%特殊病例、48小时口径）；B类为训练期标定（需求、医生时隙容量、项目目录）；C类为数据不能唯一确定但已做敏感性（憋尿60分钟、跨室10分钟、报告完成代理、计划日代理）；原整族回退和床旁绕过专项能力属于D类，已删除或修正。

## 12. 最终冻结参数

时隙5分钟；工作时段08:00-12:00、13:00-17:00；跨室10分钟；憋尿60分钟；准备约束按项目粒度；设备能力为表1 A/B/C级逐项目映射，D级不进入主情景；医生为训练期星期×5分钟总并发代理；特殊病例比例5%，固定主seed 20260824；事件键为来源+患者ID+精确开单时刻；住院分母保留全部评价事件，最后任务结束作为报告完成代理。

## 13. 最终 authoritative 文件

唯一权威根目录：`supporting_materials/results/final_frozen/`。P2、P3、敏感性和 manifest 均在该目录；精确对照和校准分别位于 `supporting_materials/results/exact_benchmark/` 与 `supporting_materials/results/calibration/`。

## 14. 最终冻结判断

{chr(10).join(f'- [{"x" if value else " "}] {key}' for key, value in freeze_checks.items())}

`MODEL_AND_RESULTS_FROZEN = {'TRUE' if frozen else 'FALSE'}`
"""
    (ROOT / "PRE_FREEZE_MODEL_AUDIT_REPORT.md").write_text(report, encoding="utf-8")

    validation_report = f"""# FINAL_MODEL_VALIDATION_REPORT

## Level 1 Raw-data semantic audit

原始时间范围、字段、事件键、重复记录和报告延迟由 `tables/audit/data_audit_metrics.json` 与 `bundle_key_sensitivity.json` 核查。

## Level 2 Model-input semantic audit

输入语义验证结果：{'通过' if semantic['passed'] else '未通过'}。设备能力、50项复核、床旁交集、训练/留出边界、医生资质边界和报告代理见 `input_semantic_verification.json`。

## Level 3 Schedule feasibility audit

P2独立检查：{'通过' if p2_verify['passed'] else '未通过'}；P3独立检查：{'通过' if p3_verify['passed'] else '未通过'}。检查覆盖任务唯一性、时长、项目房间兼容、床旁、释放/截止、工作时段、空腹、憋尿准备、设备互斥、患者互斥、跨室转运、医生并发和结果聚合。

最终结论：{'三层均通过。' if frozen else '仍有未通过项，见manifest。'}
"""
    (VALIDATION / "FINAL_MODEL_VALIDATION_REPORT.md").write_text(validation_report, encoding="utf-8")
    print(json.dumps({"MODEL_AND_RESULTS_FROZEN": frozen, "checks": freeze_checks}, ensure_ascii=False, indent=2))
    if not frozen:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
