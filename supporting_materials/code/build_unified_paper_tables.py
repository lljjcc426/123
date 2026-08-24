"""Build reproducible LaTeX tables used by the final paper."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
P1 = ROOT / "supporting_materials" / "results" / "p1"
CAP = ROOT / "supporting_materials" / "results" / "capability"
INPUT = ROOT / "supporting_materials" / "processed_data" / "unified_holdout"
UNIFIED = ROOT / "supporting_materials" / "results" / "unified_schedule"
OUT = ROOT / "paper" / "tables"


def esc(value: object) -> str:
    text = str(value)
    for old, new in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("_", r"\_"),
        ("#", r"\#"),
    ]:
        text = text.replace(old, new)
    return text


def write(name: str, lines: list[str]) -> None:
    (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def pct(value: float) -> str:
    return f"{float(value) * 100:.2f}\\%"


def table_data_scope() -> None:
    summary = json.loads((INPUT / "summary.json").read_text(encoding="utf-8"))
    events = pd.read_csv(INPUT / "events.csv")
    items = pd.read_csv(INPUT / "items.csv", low_memory=False)
    rows = []
    for source in ["住院", "门诊", "体检"]:
        event_count = int(events[events["source"].eq(source)]["event_id"].nunique())
        item_count = int(items[items["event_id"].isin(events.loc[events["source"].eq(source), "event_id"])].shape[0])
        evaluation = int(
            events[events["source"].eq(source)]["evaluation_cohort"]
            .astype(str)
            .str.lower()
            .eq("true")
            .sum()
        )
        rows.append((source, event_count, item_count, evaluation))
    lines = [
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"患者来源 & 连续模拟事件数 & 项目任务数 & 留出期评价事件数 \\",
        r"\midrule",
    ]
    lines += [f"{source} & {events_:,} & {items_:,} & {evaluation:,} \\\\" for source, events_, items_, evaluation in rows]
    row_end = r"\\"
    lines += [
        r"\midrule",
        f"合计 & {len(events):,} & {len(items):,} & {int(events['evaluation_cohort'].astype(str).str.lower().eq('true').sum()):,} {row_end}",
        r"\bottomrule",
        r"\end{tabular}",
    ]
    write("data_scope.tex", lines)


def table_department() -> None:
    frame = pd.read_csv(P1 / "department_demand_overview_train.csv")
    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"来源 & 训练期事件数 & 可识别科室数 & 前6科室占比 & 前12科室占比 \\",
        r"\midrule",
    ]
    for row in frame.itertuples(index=False):
        lines.append(
            f"{row.source} & {row.service_event_count:,} & {row.known_department_count:,} & "
            f"{pct(row.top_6_event_share)} & {pct(row.top_12_event_share)} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("department_demand.tex", lines)


def table_duration() -> None:
    frame = pd.read_csv(P1 / "service_duration_parameters.csv")
    frame = frame[~frame["category"].astype(str).str.startswith("非服务")]
    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"项目族 & 下界/min & 名义/min & 上界/min & 训练期代理样本数 \\",
        r"\midrule",
    ]
    for row in frame.itertuples(index=False):
        proxy = "--" if pd.isna(row.proxy_n) else f"{int(row.proxy_n):,}"
        lines.append(
            f"{esc(row.category)} & {row.duration_lower_min:g} & {row.duration_nominal_min:g} & "
            f"{row.duration_upper_min:g} & {proxy} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("duration_parameters.tex", lines)


def table_capability() -> None:
    frame = pd.read_csv(CAP / "special_resource_bottlenecks.csv")
    lines = [
        r"\begin{tabularx}{\textwidth}{l r X l}",
        r"\toprule",
        r"关键资源 & 可用设备数 & 设备编号 & 结构判断 \\",
        r"\midrule",
    ]
    for row in frame.itertuples(index=False):
        lines.append(
            f"{esc(row.resource)} & {row.feasible_room_count} & {esc(row.feasible_machine_ids)} & {esc(row.status)} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("capability_bottlenecks.tex", lines)


def table_doctor_capacity() -> None:
    frame = pd.read_csv(INPUT / "doctor_slot_capacity.csv")
    labels = {0: "周一", 1: "周二", 2: "周三", 3: "周四", 4: "周五", 5: "周六", 6: "周日"}
    rows = []
    for weekday, group in frame.groupby("weekday"):
        rows.append(
            (
                labels[int(weekday)],
                int(group["capacity_main"].min()),
                float(group["capacity_main"].median()),
                int(group["capacity_main"].max()),
                int(group["capacity_low"].min()),
                float(group["capacity_low"].median()),
                int(group["capacity_low"].max()),
            )
        )
    lines = [
        r"\begin{tabular}{lrrrrrr}",
        r"\toprule",
        r" & \multicolumn{3}{c}{主情景} & \multicolumn{3}{c}{偏紧情景} \\",
        r"\cmidrule(lr){2-4}\cmidrule(lr){5-7}",
        r"星期 & 最小 & 中位 & 最大 & 最小 & 中位 & 最大 \\",
        r"\midrule",
    ]
    lines += [f"{day} & {a} & {b:g} & {c} & {d} & {e:g} & {f} \\\\" for day, a, b, c, d, e, f in rows]
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("doctor_capacity.tex", lines)


def table_policy() -> None:
    frame = pd.read_csv(UNIFIED / "policy_scenario_metrics.csv")
    frame = frame[frame["scenario"].eq("main_5pct_upper")]
    names = {
        "FCFS_SHARED": "共享 FCFS",
        "SLACK_GUARD_SHARED": "松弛度保护",
        "JOINT_SCARCITY": "联合稀缺度",
    }
    lines = [
        r"\begin{tabular}{lrrrrr}",
        r"\toprule",
        r"策略 & 住院48h完成数 & 住院率 & 背景完成数 & 背景率 & 等待P90/h \\",
        r"\midrule",
    ]
    for row in frame.itertuples(index=False):
        marker = r"\textbf{" if row.policy == "FCFS_SHARED" else ""
        end = "}" if marker else ""
        lines.append(
            f"{marker}{names[row.policy]}{end} & {row.inpatient_complete_48h:,} & {pct(row.inpatient_48h_rate)} & "
            f"{row.background_on_planned_day:,} & {pct(row.background_on_time_rate)} & "
            f"{row.inpatient_wait_p90_hours_conditional:.2f} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("policy_metrics.tex", lines)


def table_sensitivity() -> None:
    frame = pd.read_csv(UNIFIED / "policy_scenario_metrics.csv")
    frame = frame[frame["policy"].eq("FCFS_SHARED")]
    names = {
        "main_5pct_upper": "主情景：5\%上界时长",
        "nominal_no_special": "无特殊时长上浮",
        "low_doctor_q25": "医生容量下四分位",
        "strict_capability": "仅严格设备兼容",
        "bladder_45min": "憋尿准备45分钟",
        "bladder_90min": "憋尿准备90分钟",
        "transfer_5min": "跨室转运5分钟",
        "transfer_15min": "跨室转运15分钟",
    }
    lines = [
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"情景 & 住院48h率 & 背景预约日率 & 条件等待P90/h & 排入分钟 \\",
        r"\midrule",
    ]
    for row in frame.itertuples(index=False):
        lines.append(
            f"{names[row.scenario]} & {pct(row.inpatient_48h_rate)} & {pct(row.background_on_time_rate)} & "
            f"{row.inpatient_wait_p90_hours_conditional:.2f} & {int(row.scheduled_minutes):,} \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("sensitivity_metrics.tex", lines)


def table_verification() -> None:
    report = json.loads((UNIFIED / "independent_verification.json").read_text(encoding="utf-8"))
    groups = [
        ("任务键、输入对应、时长", ["unique_exported_task_key", "scheduled_task_exists_in_input", "duration_matches_5pct_scenario"]),
        ("设备兼容、床旁位置", ["project_room_compatibility", "bedside_uses_room_7"]),
        ("释放、截止、工作时段", ["task_not_before_release", "task_complete_by_event_deadline", "inside_single_work_block"]),
        ("房间、患者、转运冲突", ["no_room_overlap", "no_same_patient_task_overlap", "cross_room_transfer_at_least_10min"]),
        ("医生并发容量", ["doctor_capacity_defined", "doctor_concurrency_within_capacity"]),
        ("结果表聚合一致性", ["outcome_complete_flag_consistency", "outcome_deadline_flag_consistency"]),
    ]
    lines = [
        r"\begin{tabularx}{\textwidth}{X r l}",
        r"\toprule",
        r"核验项目 & 违规数 & 结论 \\",
        r"\midrule",
    ]
    for label, keys in groups:
        violations = sum(int(report["checks"][key]["violation_count"]) for key in keys)
        lines.append(f"{label} & {violations} & {'通过' if violations == 0 else '未通过'} \\\\")
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("verification.tex", lines)


def table_assumption_provenance() -> None:
    rows = [
        ("住院48小时全项目完成", "赛题直接给定", "事件硬截止时刻"),
        ("5\%特殊检查取上界时长", "赛题直接给定比例；附件无个体标签", "评价/预热分别按最近整数抽取5\%"),
        ("项目时长区间与空腹10点窗口", "赛题直接给定", "名义/上界时长与硬时窗"),
        ("平峰$Q_{0.45}$--$Q_{0.55}$、高峰$Q_{0.90}$", "运营分位阈值，非赛题指定日期", "用真实日需求识别代表性容量水平"),
        ("22台设备能力、床旁7号机", "附件表1与设备表文本证据", "项目--设备兼容集"),
        ("50个项目采用类别级能力回退", "项目名称与表1逐字/语义核心匹配失败时，仅沿用表1同项目族具体证据", "主情景逐项留痕；严格证据情景禁用回退"),
        ("08:00--12:00、13:00--17:00日班模板", "附件表6训练期首末报告活动重建", "可复现容量模板，非未来正式排班"),
        ("星期--5分钟医生并发容量", "训练日重构活动区间的同刻人数中位数", "仅为总并发代理；不声称掌握未来实名班表或专项资质"),
        ("相邻报告间隔$(0,60]$分钟", "扫查起止缺失下的局部代理阈值", "只用于问题一相对吞吐证据，不进入主排程时长"),
        ("5分钟时间网格", "计算离散化，附件无此字段", "时长向上取整，不缩短检查"),
        ("跨室转运10分钟", "附件无转运时间", "主情景；5/15分钟边界检验"),
        ("憋尿准备60分钟", "附件无时长；医院公开流程建议提前1小时\\cite{hrhospital2025}", "主情景；45/90分钟边界检验"),
        ("门诊/体检报告日作为计划日", "附件无历史预约日", "回溯压力情景，不声称还原历史预约"),
        ("最后任务结束代理报告提交", "附件无扫查起止与报告书写时长", "官方KPI的乐观代理，明示适用边界"),
        ("2日预热与2日截止尾窗", "由最大48小时截止期推出", "只携入跨边界在制任务并覆盖3月31日开单截止"),
    ]
    lines = [
        r"\begin{tabularx}{\textwidth}{p{0.24\textwidth} p{0.35\textwidth} X}",
        r"\toprule",
        r"设定/参数 & 事实来源 & 模型中的限定 \\",
        r"\midrule",
    ]
    for setting, source, boundary in rows:
        lines.append(f"{setting} & {source} & {boundary} \\\\")
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("assumption_provenance.tex", lines)


def table_recommendation_sample() -> None:
    frame = pd.read_csv(UNIFIED / "inpatient_recommended_schedule.csv", low_memory=False)
    sample_events = frame["event_id"].drop_duplicates().head(8)
    sample = frame[frame["event_id"].isin(sample_events)].head(16)
    lines = [
        r"\begin{tabularx}{\textwidth}{r l r X l l}",
        r"\toprule",
        r"患者序位 & 事件编号 & 项目序位 & 项目族 & 时段 & 设备 \\",
        r"\midrule",
    ]
    for row in sample.itertuples(index=False):
        start = pd.Timestamp(row.start_dt).strftime("%m-%d %H:%M")
        end = pd.Timestamp(row.end_dt).strftime("%H:%M")
        lines.append(
            f"{row.recommended_patient_rank} & {esc(row.event_id)} & {row.sequence_position} & "
            f"{esc(row.category)} & {start}--{end} & {esc(row.room_name)}({esc(row.room_id)}) \\\\"
        )
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("recommendation_sample.tex", lines)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    table_data_scope()
    table_department()
    table_duration()
    table_capability()
    table_doctor_capacity()
    table_assumption_provenance()
    table_policy()
    table_sensitivity()
    table_verification()
    table_recommendation_sample()
    print(f"created 10 LaTeX tables in {OUT}")


if __name__ == "__main__":
    main()
