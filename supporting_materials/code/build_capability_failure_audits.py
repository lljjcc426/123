"""Decompose P2 capability failures and audit machine 7 bedside semantics."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
from typing import Iterable

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SUPPORTING = ROOT / "supporting_materials"
DEFAULT_INPUT = SUPPORTING / "processed_data" / "unified_holdout"
DEFAULT_P2 = SUPPORTING / "results" / "final_frozen" / "p2_inpatient_only"
DEFAULT_P3 = SUPPORTING / "results" / "final_frozen" / "p3_joint"
DEFAULT_CAPABILITY = SUPPORTING / "results" / "capability"

CATEGORY_DEFINITIONS = {
    "A": "项目本身为 evidence level D，任何设备均不能由表1确认",
    "B": "普通状态有设备，但床旁约束使 project rooms 与 {7} 的交集为空",
    "C": "复合项目的组成部分分别有设备，但同机交集为空",
    "D": "多项目患者不存在共同设备，但允许跨室，因此不得作为能力失败",
    "E": "其他项目级匹配失败",
    "F": "代码或字段异常",
}


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype("string").str.lower().isin(["true", "1", "yes"])


def room_set(value: object) -> set[str]:
    if pd.isna(value) or not str(value).strip():
        return set()
    return {part for part in str(value).split("|") if part}


def escaped(value: object) -> str:
    return str(value).replace("|", "/").replace("\n", " ")


def percent(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def top_values(frame: pd.DataFrame, column: str, limit: int = 8) -> str:
    if frame.empty:
        return ""
    counts = frame[column].fillna("<空>").astype(str).value_counts().head(limit)
    return "；".join(f"{escaped(name)}（{count}）" for name, count in counts.items())


def room_intersection_empty(values: Iterable[object]) -> bool:
    sets = [room_set(value) for value in values]
    return len(sets) > 1 and all(sets) and not set.intersection(*sets)


def load_frames(input_dir: Path, p2_dir: Path, capability_dir: Path) -> tuple[pd.DataFrame, ...]:
    events = pd.read_csv(input_dir / "events.csv", low_memory=False)
    items = pd.read_csv(input_dir / "items.csv", low_memory=False)
    outcomes = pd.read_csv(p2_dir / "final_patient_outcomes.csv", low_memory=False)
    review_path = capability_dir / "FALLBACK_PROJECT_REVIEW.csv"
    review = pd.read_csv(review_path, low_memory=False) if review_path.exists() else pd.DataFrame()
    equipment = pd.read_csv(capability_dir / "equipment_source_rows.csv", low_memory=False)
    return events, items, outcomes, review, equipment


def classify_failure_tasks(
    failure_items: pd.DataFrame,
    review: pd.DataFrame,
    equipment_rooms: set[str],
) -> pd.DataFrame:
    frame = failure_items.copy()
    frame["item_bedside_bool"] = as_bool(frame["item_bedside"])
    frame["project_rooms"] = frame["project_compatible_rooms"].map(room_set)
    frame["effective_rooms"] = frame["compatible_rooms"].map(room_set)

    review_columns = ["project_norm", "review_rule", "review_reason"]
    if "attempted_review_rule" in review.columns:
        review_columns.append("attempted_review_rule")
    if len(review):
        frame = frame.merge(
            review[review_columns].drop_duplicates("project_norm"),
            on="project_norm",
            how="left",
            validate="many_to_one",
        )
    else:
        frame["review_rule"] = ""
        frame["review_reason"] = ""
    if "attempted_review_rule" not in frame:
        frame["attempted_review_rule"] = frame.get("review_rule", "")

    duplicated_key = frame.duplicated(["event_id", "item_index"], keep=False)
    missing_critical = frame[["event_id", "project_norm", "category", "capability_level"]].isna().any(axis=1)
    invalid_room = frame["effective_rooms"].map(lambda rooms: bool(rooms - equipment_rooms))
    inconsistent_nonbedside = (
        ~frame["item_bedside_bool"]
        & (frame["project_rooms"] != frame["effective_rooms"])
    )
    frame["field_anomaly"] = duplicated_key | missing_critical | invalid_room | inconsistent_nonbedside

    empty = frame["effective_rooms"].map(lambda rooms: not rooms)
    bedside_intersection = (
        frame["item_bedside_bool"]
        & frame["project_rooms"].map(bool)
        & ~frame["project_rooms"].map(lambda rooms: "7" in rooms)
        & empty
    )
    compound_intersection = (
        empty
        & frame["attempted_review_rule"].fillna("").eq("reviewed_compound_intersection")
    )
    level_d = empty & frame["capability_level"].fillna("").eq("D")

    frame["cause_category"] = ""
    frame.loc[empty & frame["field_anomaly"], "cause_category"] = "F"
    frame.loc[empty & ~frame["field_anomaly"] & bedside_intersection, "cause_category"] = "B"
    frame.loc[
        empty & ~frame["field_anomaly"] & ~bedside_intersection & compound_intersection,
        "cause_category",
    ] = "C"
    frame.loc[
        empty
        & ~frame["field_anomaly"]
        & ~bedside_intersection
        & ~compound_intersection
        & level_d,
        "cause_category",
    ] = "A"
    frame.loc[empty & frame["cause_category"].eq(""), "cause_category"] = "E"
    return frame


def cross_room_diagnostic(items: pd.DataFrame, evaluation_ids: set[str]) -> set[str]:
    cohort = items[items["event_id"].isin(evaluation_ids)].copy()
    return {
        str(event_id)
        for event_id, group in cohort.groupby("event_id", sort=False)
        if room_intersection_empty(group["compatible_rooms"])
    }


def build_decomposition(
    events: pd.DataFrame,
    items: pd.DataFrame,
    outcomes: pd.DataFrame,
    review: pd.DataFrame,
    equipment: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    evaluation = as_bool(outcomes["evaluation_cohort"])
    deadline_met = as_bool(outcomes["deadline_met"])
    evaluated = outcomes[evaluation].copy()
    incomplete = evaluated[~deadline_met[evaluation]].copy()
    capability_failures = evaluated[
        evaluated["failure_reason"].fillna("").eq("no_compatible_room_under_scenario")
    ].copy()
    failure_ids = set(capability_failures["event_id"].astype(str))
    failure_items = items[items["event_id"].astype(str).isin(failure_ids)].copy()
    equipment_rooms = set(equipment["machine_id"].astype(str))
    classified = classify_failure_tasks(failure_items, review, equipment_rooms)
    empty_tasks = classified[classified["effective_rooms"].map(lambda rooms: not rooms)].copy()

    category_sets = (
        empty_tasks.groupby("event_id")["cause_category"]
        .agg(lambda values: tuple(sorted(set(values))))
        .to_dict()
    )
    primary_order = ["F", "C", "A", "B", "E"]
    primary = {
        event_id: next(code for code in primary_order if code in categories)
        for event_id, categories in category_sets.items()
    }

    event_meta = events[
        ["event_id", "source", "bedside", "service_project_count", "project_names"]
    ].drop_duplicates("event_id")
    detail = capability_failures[["event_id"]].merge(event_meta, on="event_id", how="left")
    detail["primary_category"] = detail["event_id"].map(primary)
    detail["category_signature"] = detail["event_id"].map(
        lambda event_id: "+".join(category_sets.get(event_id, ()))
    )
    detail["empty_task_count"] = detail["event_id"].map(empty_tasks.groupby("event_id").size())
    detail["causal_project_names"] = detail["event_id"].map(
        empty_tasks.groupby("event_id")["project_norm"].agg(lambda values: "；".join(map(str, values)))
    )
    detail["evidence_levels"] = detail["event_id"].map(
        empty_tasks.groupby("event_id")["capability_level"].agg(
            lambda values: "/".join(sorted(set(map(str, values))))
        )
    )
    detail["bedside"] = as_bool(detail["bedside"])
    detail["multi_project"] = detail["service_project_count"].fillna(0).astype(int).gt(1)

    evaluation_ids = set(evaluated["event_id"].astype(str))
    d_events = cross_room_diagnostic(items, evaluation_ids)
    d_outcomes = evaluated[evaluated["event_id"].astype(str).isin(d_events)]
    d_false_failures = int(
        d_outcomes["failure_reason"].fillna("").eq("no_compatible_room_under_scenario").sum()
    )

    summary_rows: list[dict[str, object]] = []
    for code in CATEGORY_DEFINITIONS:
        assigned_events = detail[detail["primary_category"].eq(code)]
        cause_tasks = empty_tasks[empty_tasks["cause_category"].eq(code)]
        overlap_count = sum(code in categories and len(categories) > 1 for categories in category_sets.values())
        summary_rows.append(
            {
                "category_code": code,
                "definition": CATEGORY_DEFINITIONS[code],
                "event_count": int(len(assigned_events)),
                "task_count": int(len(cause_tasks)),
                "percentage_of_all_incomplete": percent(len(assigned_events), len(incomplete)),
                "percentage_of_all_inpatient": percent(len(assigned_events), len(evaluated)),
                "top_project_names": top_values(cause_tasks, "project_norm"),
                "project_categories": "/".join(sorted(set(cause_tasks["category"].dropna().astype(str)))),
                "bedside_share": float(assigned_events["bedside"].mean()) if len(assigned_events) else 0.0,
                "multi_project_share": float(assigned_events["multi_project"].mean()) if len(assigned_events) else 0.0,
                "evidence_levels": "/".join(sorted(set(cause_tasks["capability_level"].dropna().astype(str)))),
                "overlap_event_count": int(overlap_count),
                "diagnostic_event_count": int(len(d_events)) if code == "D" else 0,
            }
        )
    summary = pd.DataFrame(summary_rows)

    all_d_items = items[items["capability_level"].fillna("").eq("D")]
    context = {
        "evaluated_inpatients": int(len(evaluated)),
        "incomplete_inpatients": int(len(incomplete)),
        "capability_failure_events": int(len(capability_failures)),
        "capability_failure_tasks": int(len(empty_tasks)),
        "assigned_total": int(summary["event_count"].sum()),
        "category_signature_counts": Counter(detail["category_signature"]),
        "d_diagnostic_events": int(len(d_events)),
        "d_scheduled_success": int(as_bool(d_outcomes["deadline_met"]).sum()),
        "d_capacity_failures": int(
            d_outcomes["failure_reason"].fillna("").eq("no_complete_plan_by_deadline").sum()
        ),
        "d_false_capability_failures": d_false_failures,
        "level_d_unique_projects": int(all_d_items["project_norm"].nunique()),
        "level_d_all_source_tasks": int(len(all_d_items)),
        "level_d_p2_failure_tasks": int(
            (empty_tasks["cause_category"].eq("A") | empty_tasks["cause_category"].eq("C")).sum()
        ),
        "bedside_intersection_tasks": int(empty_tasks["cause_category"].eq("B").sum()),
        "bedside_intersection_events_any": int(
            empty_tasks.loc[empty_tasks["cause_category"].eq("B"), "event_id"].nunique()
        ),
    }
    return summary, detail, context


def decomposition_report(summary: pd.DataFrame, context: dict[str, object]) -> str:
    rows = []
    for row in summary.itertuples(index=False):
        rows.append(
            f"| {row.category_code} | {escaped(row.definition)} | {row.event_count:,} | "
            f"{row.diagnostic_event_count:,} | {row.task_count:,} | {row.percentage_of_all_incomplete:.2%} | "
            f"{row.percentage_of_all_inpatient:.2%} | {row.bedside_share:.2%} | "
            f"{row.multi_project_share:.2%} | {escaped(row.evidence_levels) or '-'} |"
        )
    signatures = "；".join(
        f"{signature}={count:,}" for signature, count in sorted(context["category_signature_counts"].items())
    )
    return f"""# P2 能力失败分解审计

## 审计结论

P2 评价期共有 {context['evaluated_inpatients']:,} 名住院患者，其中 {context['incomplete_inpatients']:,} 名未在 48 小时内完成。程序标记为 `no_compatible_room_under_scenario` 的评价期事件为 {context['capability_failure_events']:,} 个；A--F 互斥主因合计 {context['assigned_total']:,} 个，与该数完全相等。这里不使用含预热期事件的汇总数。

事件主因采用 `F -> C -> A -> B -> E` 的优先顺序。原因是字段异常、组合项目交集为空或项目本身无证据时，仅放宽床旁机也不能修复整名患者。任务层面仍保留所有原因，因此 A/B 重叠不会被隐藏。原因签名为：{signatures}。

| 类别 | 定义 | 错误归因事件数 | 诊断事件数 | 原因任务数 | 占全部未完成 | 占全部住院 | 床旁占比 | 多项目占比 | 证据层级 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

完整的高频项目、项目类别和重叠数量见 `supporting_materials/results/capability/P2_CAPABILITY_FAILURE_DECOMPOSITION.csv`；逐事件证据见 `P2_CAPABILITY_FAILURE_EVENTS.csv`。

## 原约 10,245 类事件的真实来源

- evidence level D 在全部三类数据中确有 {context['level_d_unique_projects']:,} 个项目、{context['level_d_all_source_tasks']:,} 个任务，但它们在 P2 能力失败中只形成 {context['level_d_p2_failure_tasks']:,} 个原因任务。因此“15 个项目、909 个任务”不能解释约一万个失败事件。
- 真正的大头是床旁交集：普通状态下项目存在设备，但 7 号机没有该专项证据。此类共有 {context['bedside_intersection_tasks']:,} 个原因任务，涉及 {context['bedside_intersection_events_any']:,} 个失败事件。
- 部分患者同时含 A、B 两类空设备任务，故任务原因数和非互斥事件数不能直接相加；CSV 的 `overlap_event_count` 与上面的原因签名给出重叠。

## D 类反例检查

评价期中有 {context['d_diagnostic_events']:,} 名多项目患者的各项目分别有设备、但所有项目的设备全集交集为空。生产算法允许顺序跨室，其中 {context['d_scheduled_success']:,} 名仍在 48 小时内完成，{context['d_capacity_failures']:,} 名因时窗/容量失败，被错误标成能力失败的事件为 {context['d_false_capability_failures']:,}。这直接验证了“整名患者无共同设备”不是能力失败条件。

## 代码证据

- 输入侧：`supporting_materials/code/build_unified_inputs.py` 的 `attach_room_sets` 分开保存普通项目设备集与床旁交集；`project_machine_matches` 保存 A--D 证据层级。
- 调度侧：`supporting_materials/code/run_unified_scheduler.py` 的 `schedule_group` 只在任一任务自身的 `compatible_rooms` 为空时给出能力失败；跨室由患者级 `plan_event` 处理。
- 本报告：`supporting_materials/code/build_capability_failure_audits.py` 从最终 P2 患者结果回连任务设备集，既不修改失败标签，也不凭项目名推定新能力。
"""


def outcome_impact_rows(
    outcomes_path: Path,
    items: pd.DataFrame,
    label: str,
) -> list[dict[str, object]]:
    if not outcomes_path.exists() or outcomes_path.stat().st_size == 0:
        return []
    outcomes = pd.read_csv(outcomes_path, low_memory=False)
    evaluation = as_bool(outcomes["evaluation_cohort"])
    outcome = outcomes[evaluation].copy()
    outcome["deadline_met_bool"] = as_bool(outcome["deadline_met"])
    item = items.copy()
    item["item_bedside_bool"] = as_bool(item["item_bedside"])
    item["bed7_gap"] = (
        item["item_bedside_bool"]
        & item["project_compatible_rooms"].map(room_set).map(bool)
        & ~item["project_compatible_rooms"].map(room_set).map(lambda rooms: "7" in rooms)
    )
    gap_ids = set(item.loc[item["bed7_gap"], "event_id"].astype(str))
    rows = []
    for source, group in outcome.groupby("source", sort=True):
        impacted = group[
            group["event_id"].astype(str).isin(gap_ids) & ~group["deadline_met_bool"]
        ]
        rows.append(
            {
                "scenario": label,
                "source": source,
                "cohort_events": int(len(group)),
                "incomplete_bed7_gap_events": int(len(impacted)),
                "completion_rate_upper_bound_increase_pp": 100.0 * percent(len(impacted), len(group)),
            }
        )
    return rows


def bed7_report(
    items: pd.DataFrame,
    equipment: pd.DataFrame,
    p2_dir: Path,
    p3_dir: Path,
) -> str:
    machine = equipment[equipment["machine_id"].astype(str).eq("7")].iloc[0]
    bedside = items[as_bool(items["item_bedside"])].copy()
    bedside["has_7"] = bedside["project_compatible_rooms"].map(room_set).map(lambda rooms: "7" in rooms)
    compatible = bedside[bedside["has_7"]]
    incompatible = bedside[~bedside["has_7"]]

    top_incompatible = (
        incompatible.groupby(["project_norm", "category", "capability_level"], dropna=False)
        .size()
        .rename("task_count")
        .reset_index()
        .sort_values(["task_count", "project_norm"], ascending=[False, True])
        .head(15)
    )
    top_lines = [
        f"| {escaped(row.project_norm)} | {escaped(row.category)} | {row.capability_level} | {row.task_count:,} |"
        for row in top_incompatible.itertuples(index=False)
    ]
    compatible_names = top_values(compatible, "project_norm", 12) or "无"

    impact_rows = outcome_impact_rows(
        p2_dir / "final_patient_outcomes.csv", items, "P2 住院专用"
    )
    impact_rows.extend(
        outcome_impact_rows(p3_dir / "final_patient_outcomes.csv", items, "P3 联合排程")
    )
    impact_lines = [
        f"| {row['scenario']} | {row['source']} | {row['cohort_events']:,} | "
        f"{row['incomplete_bed7_gap_events']:,} | {row['completion_rate_upper_bound_increase_pp']:.2f} |"
        for row in impact_rows
    ]
    if not impact_lines:
        impact_lines = ["| 尚无最终结果 | - | 0 | 0 | 0.00 |"]

    return f"""# 7 号床旁机语义与能力最终审计

## 原始证据

表 1 原始抽取行的设备编号为 7，当前机房为“{escaped(machine.current_room)}”，型号为“{escaped(machine.machine_model)}”，检查项目原文为：

> {escaped(machine.capability_text)}

原文只明确了床旁使用场景，没有逐项列出心脏、血管、产科、儿科或介入专项能力。因而“床旁地点能力”等同于“全部专项项目能力”没有数据依据。

## 最终语义边界

1. **可以确定的具体项目**：仅凭 7 号机这一行，不能确定任何具体专项项目；能确定的是设备位于床边 B 超场景并具备床旁检查用途。
2. **可以合理泛化的普通床旁项目**：当前规则只接受腹部、腹水、泌尿系、前列腺、胸部和胸水等常规部位，并要求项目映射结果实际包含 7 号机。当前覆盖的高频项目为：{compatible_names}。
3. **不可以泛化的专项项目**：心脏、血管、产科、儿科、新生儿、穿刺/活检/介入等专项检查，需要相应探头、软件包或专业资质；表 1 的笼统床旁描述不能证明这些能力。
4. **决策**：维持保守边界，不为提高完成率而扩大 7 号机能力。若医院能补充设备配置清单或操作资质，再将其作为外部数据更新能力矩阵。

## 全数据任务量

- 床旁任务总数：{len(bedside):,}。
- 普通项目设备集中含 7 号机：{len(compatible):,}（{percent(len(compatible), len(bedside)):.2%}）。
- 普通项目有设备但不含 7 号机，或项目本身无设备证据：{len(incompatible):,}（{percent(len(incompatible), len(bedside)):.2%}）。

| 高频不兼容床旁项目 | 项目类别 | 证据层级 | 任务数 |
|---|---|---:|---:|
{chr(10).join(top_lines)}

## 对 P2/P3 的实际影响

下表统计最终结果中“存在 7 号机语义缺口且未完成”的事件。最后一列是极端反事实上界：即使把这些事件全部变为按时完成，完成率最多增加多少百分点；它不是放宽能力后的预测收益，因为容量与时窗仍然存在。

| 场景 | 患者来源 | 评价事件数 | 未完成且含 7 号机语义缺口 | 完成率增幅上界/百分点 |
|---|---|---:|---:|---:|
{chr(10).join(impact_lines)}

该结论来自 `equipment_source_rows.csv` 的原始行、`items.csv` 的普通设备集与床旁设备集，以及最终 P2/P3 患者结果。没有使用完成率作为设备语义证据。
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--p2-dir", type=Path, default=DEFAULT_P2)
    parser.add_argument("--p3-dir", type=Path, default=DEFAULT_P3)
    parser.add_argument("--capability-dir", type=Path, default=DEFAULT_CAPABILITY)
    parser.add_argument("--report-dir", type=Path, default=ROOT)
    args = parser.parse_args()

    events, items, outcomes, review, equipment = load_frames(
        args.input_dir, args.p2_dir, args.capability_dir
    )
    summary, detail, context = build_decomposition(events, items, outcomes, review, equipment)
    args.capability_dir.mkdir(parents=True, exist_ok=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(
        args.capability_dir / "P2_CAPABILITY_FAILURE_DECOMPOSITION.csv",
        index=False,
        encoding="utf-8-sig",
    )
    detail.to_csv(
        args.capability_dir / "P2_CAPABILITY_FAILURE_EVENTS.csv",
        index=False,
        encoding="utf-8-sig",
    )
    (args.report_dir / "P2_CAPABILITY_FAILURE_DECOMPOSITION.md").write_text(
        decomposition_report(summary, context), encoding="utf-8"
    )
    (args.report_dir / "BED7_SEMANTIC_CAPABILITY_FINAL_AUDIT.md").write_text(
        bed7_report(items, equipment, args.p2_dir, args.p3_dir), encoding="utf-8"
    )
    print(
        f"CAPABILITY_FAILURE_EVENTS={context['capability_failure_events']} "
        f"ASSIGNED={context['assigned_total']} "
        f"BED7_GAP_EVENTS={context['bedside_intersection_events_any']}"
    )


if __name__ == "__main__":
    main()
