"""Independent semantic checks for the frozen scheduling inputs."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import analyze_p1 as p1


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "supporting_materials" / "processed_data" / "unified_holdout"
CAP = ROOT / "supporting_materials" / "results" / "capability"
OUT = ROOT / "supporting_materials" / "results" / "validation"
RAW = ROOT / "supporting_materials" / "processed_data" / "raw_parquet"


def room_set(value: object) -> set[str]:
    if pd.isna(value) or not str(value):
        return set()
    result: set[str] = set()
    for part in str(value).split("|"):
        if not part:
            continue
        number = float(part)
        result.add(str(int(number)) if number.is_integer() else part)
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(INPUT / "events.csv", encoding="utf-8-sig", low_memory=False)
    items = pd.read_csv(INPUT / "items.csv", encoding="utf-8-sig", low_memory=False)
    evidence = pd.read_csv(INPUT / "project_machine_evidence.csv", encoding="utf-8-sig", dtype={"machine_id": "string"})
    summary = pd.read_csv(INPUT / "project_machine_summary.csv", encoding="utf-8-sig")
    review = pd.read_csv(CAP / "LEGACY_50_FALLBACK_PROJECT_AUDIT.csv", encoding="utf-8-sig")
    bedside = pd.read_csv(CAP / "bedside_project_capability_audit.csv", encoding="utf-8-sig")
    checks: dict[str, dict[str, object]] = {}

    def record(name: str, violations: int, detail: object) -> None:
        checks[name] = {"passed": int(violations) == 0, "violation_count": int(violations), "detail": detail}

    valid_evidence = evidence[evidence["match_level"].isin(["A", "B", "C"])]
    evidence_rooms = valid_evidence.groupby("project_norm")["machine_id"].agg(lambda values: set(values.astype(str))).to_dict()
    invalid_room_rows = 0
    for row in items.itertuples(index=False):
        allowed = evidence_rooms.get(row.project_norm, set())
        if not room_set(row.project_compatible_rooms).issubset(allowed):
            invalid_room_rows += 1
    record("compatible_rooms_trace_to_A_B_C_evidence", invalid_room_rows, "每个项目房间均追溯到表1的A/B/C级证据")
    record("no_blanket_category_fallback", int(evidence["match_rule"].eq("same_category_without_project_text_match").sum()), "不得按整个项目族授权")
    d_projects = set(summary.loc[summary["evidence_level"].eq("D"), "project_norm"])
    d_with_rooms = items[items["project_norm"].isin(d_projects)]["project_compatible_rooms"].fillna("").ne("").sum()
    record("level_D_excluded_from_hard_capability", int(d_with_rooms), f"D级项目数={len(d_projects)}")
    bedside_bad = 0
    for row in items[items["item_bedside"].astype(str).str.lower().eq("true")].itertuples(index=False):
        rooms = room_set(row.bedside_compatible_rooms)
        if rooms and rooms != {"7"}:
            bedside_bad += 1
        if rooms and "7" not in evidence_rooms.get(row.project_norm, set()):
            bedside_bad += 1
    record("bedside_is_project_capability_intersection", bedside_bad, "床旁可行集只能是项目能力与7号机地点能力的交集")
    duplicate_legacy_projects = int(review["legacy_project"].duplicated().sum())
    missing_dispositions = int(
        review["current_disposition"].fillna("").astype(str).str.strip().eq("").sum()
    )
    retained_category_fallbacks = int(
        review["category_fallback_retained"]
        .fillna(False)
        .astype(str)
        .str.strip()
        .str.lower()
        .isin({"true", "1", "yes"})
        .sum()
    )
    record(
        "all_former_fallback_projects_reviewed",
        abs(len(review) - 50) + duplicate_legacy_projects,
        f"review_rows={len(review)}; duplicate_legacy_projects={duplicate_legacy_projects}",
    )
    record(
        "review_has_explicit_treatment",
        missing_dispositions,
        "每个原回退项目都有最终处理",
    )
    record(
        "legacy_category_fallback_removed",
        retained_category_fallbacks,
        "旧版50个项目均不得保留整类设备兜底",
    )
    record("event_keys_unique", int(events["event_id"].duplicated().sum()), "事件ID唯一")
    record("item_keys_unique", int(items.duplicated(["event_id", "item_index"]).sum()), "事件内项目序号唯一")
    evaluation = events[events["evaluation_cohort"].astype(str).str.lower().eq("true")].copy()
    ip_bad = (pd.to_datetime(evaluation.loc[evaluation["source"].eq("住院"), "order_dt"], errors="coerce") < pd.Timestamp("2024-04-01")).sum()
    bg_bad = (pd.to_datetime(evaluation.loc[~evaluation["source"].eq("住院"), "planned_date"], errors="coerce") < pd.Timestamp("2024-04-01")).sum()
    record("train_holdout_boundary", int(ip_bad + bg_bad), "住院按开单日、背景按计划日代理进入留出期")

    doctor_frame = p1.load_detail(RAW / "inpatient.parquet", "住院")
    doctor_frame = doctor_frame[
        doctor_frame["order_dt"].dt.normalize().lt(pd.Timestamp("2024-04-01"))
        & doctor_frame["exam_doctor_id"].notna()
        & ~doctor_frame["non_service_item"]
    ]
    doctor_category = (
        doctor_frame.groupby(["exam_doctor_id", "category"]).size().rename("historical_project_rows").reset_index()
    )
    doctor_category.to_csv(OUT / "doctor_category_historical_evidence.csv", index=False, encoding="utf-8-sig")

    report = {
        "passed": all(entry["passed"] for entry in checks.values()),
        "checks": checks,
        "semantic_counts": {
            "events": len(events),
            "items": len(items),
            "projects": int(summary["project_norm"].nunique()),
            "evidence_levels": summary["evidence_level"].value_counts().to_dict(),
            "former_fallback_review_rows": len(review),
            "bedside_audit_rows": len(bedside),
        },
        "doctor_qualification_boundary": "历史医生-项目族证据可生成，但题面33名未来医生与历史ID无法一一映射，故主模型只使用总并发容量并假设同一时隙内资质可替代，不伪造实名资质矩阵。",
        "report_completion_boundary": "数据无扫查结束字段；最后任务结束仅作为排程层报告完成代理。",
    }
    (OUT / "input_semantic_verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    provenance = """# TRAIN_HOLDOUT_PROVENANCE_AUDIT

|参数|使用的数据区间|是否允许|是否泄漏|修复状态|
|---|---|---|---|---|
|峰平阈值与代表日|2019-03-01至2024-03-31|是|否|已改为训练期分位数，留出期只评价|
|日历岭回归系数|2019-03-01至2024-03-31|是|否|保持|
|滚动季节朴素预测|每个预测时点以前的已观测数据|是|否|明确为rolling-origin|
|项目分类正则与题给时长|题面及训练期项目目录|是|否|保持；留出项目只按冻结规则分类|
|项目—设备能力|表1现行设备原文|是|否|不读取留出期完成机房|
|医生时隙容量|2019-03-01至2024-03-31表6|是|否|保持|
|房间稀缺权重|2019-03-01至2024-03-31项目目录|是|否|保持|
|特殊病例比例|题面5%，身份由固定种子抽样|是|否|多seed检验|
|调度策略与参数|题面、训练期及预先声明情景|是|否|留出期不反向调参|
|最终指标|2024-04-01至2025-03-31|仅评价|否|保持|
"""
    (OUT / "TRAIN_HOLDOUT_PROVENANCE_AUDIT.md").write_text(provenance, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
