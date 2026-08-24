"""Generate authoritative LaTeX tables for the rebuilt paper."""
from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P1 = ROOT / "supporting_materials/results/p1"
INPUT = ROOT / "supporting_materials/processed_data/unified_holdout"
FROZEN = ROOT / "supporting_materials/results/final_frozen"
EXACT = ROOT / "supporting_materials/results/exact_benchmark"
CAL = ROOT / "supporting_materials/results/calibration"
OUT = ROOT / "paper/tables"

def esc(value: object) -> str:
    text = str(value)
    for old, new in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#")]:
        text = text.replace(old, new)
    return text

def pct(value: float) -> str: return f"{100 * float(value):.2f}\\%"
def write(name: str, lines: list[str]) -> None: (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

def data_scope() -> None:
    events = pd.read_csv(INPUT / "events.csv", encoding="utf-8-sig")
    items = pd.read_csv(INPUT / "items.csv", encoding="utf-8-sig", low_memory=False)
    eval_flag = events["evaluation_cohort"].astype(str).str.lower().eq("true")
    rows = []
    for source in ["住院", "门诊", "体检"]:
        ids = set(events.loc[events["source"].eq(source), "event_id"])
        rows.append((source, len(ids), int(items["event_id"].isin(ids).sum()), int((eval_flag & events["source"].eq(source)).sum())))
    lines = [r"\begin{tabular}{lrrr}", r"\toprule", "来源 & 连续模拟事件 & 项目任务 & 留出期评价事件 \\\\", r"\midrule"]
    lines += [f"{s} & {e:,} & {i:,} & {v:,} \\\\" for s, e, i, v in rows]
    lines += [r"\midrule", f"合计 & {len(events):,} & {len(items):,} & {int(eval_flag.sum()):,} \\\\" , r"\bottomrule", r"\end{tabular}"]
    write("data_scope.tex", lines)

def duration_parameters() -> None:
    frame = pd.read_csv(P1 / "service_duration_parameters.csv")
    frame = frame[~frame["category"].astype(str).str.startswith("非服务")]
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule", "项目族 & 下界/min & 名义/min & 上界/min & 训练代理数 \\\\", r"\midrule"]
    for row in frame.itertuples(index=False):
        n = "--" if pd.isna(row.proxy_n) else f"{int(row.proxy_n):,}"
        lines.append(f"{esc(row.category)} & {row.duration_lower_min:g} & {row.duration_nominal_min:g} & {row.duration_upper_min:g} & {n} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("duration_parameters.tex", lines)

def capability_evidence() -> None:
    summary = pd.read_csv(INPUT / "project_machine_summary.csv", encoding="utf-8-sig")
    items = pd.read_csv(INPUT / "items.csv", encoding="utf-8-sig", low_memory=False)
    joined = items[["project_norm"]].merge(summary[["project_norm", "evidence_level"]], on="project_norm", how="left", validate="many_to_one")
    pc, ic = summary["evidence_level"].value_counts(), joined["evidence_level"].value_counts()
    labels = {"A":"直接匹配", "B":"语义匹配", "C":"明确广义", "D":"未确认"}
    desc = {"A":"表1项目文本直接命中", "B":"同义、包含或复合部位交集", "C":"表1中的广义项目描述覆盖", "D":"表1无法确认，主模型排除"}
    lines = [r"\begin{tabularx}{\textwidth}{lrrX}", r"\toprule", "匹配方式 & 项目数 & 项目任务数 & 使用规则 \\\\", r"\midrule"]
    for level in "ABCD": lines.append(f"{labels[level]} & {int(pc.get(level,0))} & {int(ic.get(level,0)):,} & {desc[level]} \\\\")
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("capability_evidence.tex", lines)

def p2_policy() -> None:
    frame = pd.read_csv(FROZEN / "p2_inpatient_only/policy_metrics.csv", encoding="utf-8-sig")
    names = {"FCFS_SHARED":"共享FCFS", "SLACK_GUARD_SHARED":"最小松弛度保护"}
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule", "策略 & 48h完成数 & 完成率 & P50/h & P90/h & 多项目跨室率 \\\\", r"\midrule"]
    for row in frame.itertuples(index=False): lines.append(f"{names[row.policy]} & {row.inpatient_complete_48h:,} & {pct(row.inpatient_48h_rate)} & {row.inpatient_wait_p50_hours_conditional:.2f} & {row.inpatient_wait_p90_hours_conditional:.2f} & {pct(row.inpatient_room_switch_rate_multi)} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("p2_policy.tex", lines)

def p3_pareto() -> None:
    frame = pd.read_csv(FROZEN / "p3_joint/pareto_metrics.csv", encoding="utf-8-sig")
    selected = float(json.loads((FROZEN / "p3_joint/selection.json").read_text(encoding="utf-8"))["selected_alpha"])
    lines = [r"\begin{tabular}{rrrrrr}", r"\toprule", "$\\alpha$ & 背景完成数 & 背景率 & 住院完成数 & 住院率 & P90/h \\\\", r"\midrule"]
    for row in frame.itertuples(index=False):
        pre, suf = (r"\textbf{", "}") if abs(row.background_target_alpha-selected)<1e-9 else ("", "")
        lines.append(f"{pre}{row.background_target_alpha:.2f}{suf} & {pre}{row.background_on_planned_day:,}{suf} & {pre}{pct(row.background_on_time_rate)}{suf} & {pre}{row.inpatient_complete_48h:,}{suf} & {pre}{pct(row.inpatient_48h_rate)}{suf} & {pre}{row.inpatient_wait_p90_hours_conditional:.2f}{suf} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("p3_pareto.tex", lines)

def calibration() -> None:
    frame = pd.read_csv(CAL / "calibration_metrics.csv", encoding="utf-8-sig")
    names = {"C0_historical_report":"历史开单至报告", "C1_duration_only":"仅题给时长", "C2_standard_hours":"加入标准班次", "C3_doctor_capacity":"加入医生并发", "C4_project_capability":"加入项目设备能力", "C5_item_preparation":"加入项目级准备", "C6_joint_background":"加入门诊/体检竞争", "C7_formal_heuristic":"正式构造策略"}
    lines = [r"\begin{tabular}{lrrr}", r"\toprule", "校准层 & 完成数/分母 & 完成率 & 较上一层/百分点 \\\\", r"\midrule"]
    for row in frame.itertuples(index=False):
        delta = "--" if pd.isna(row.change_from_previous_pp) else f"{row.change_from_previous_pp:+.2f}"
        lines.append(f"{names[row.scenario]} & {int(row.completed):,}/{int(row.total):,} & {pct(row.rate)} & {delta} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("calibration.tex", lines)

def sensitivity() -> None:
    frame = pd.read_csv(FROZEN / "sensitivity_metrics.csv", encoding="utf-8-sig").set_index("audit_scenario")
    order = ["preparation_item","preparation_event","doctor_low","capability_AB","bladder45","bladder90","transfer5","transfer15"]
    names = {"preparation_item":"主设定：项目级准备", "preparation_event":"事件级准备", "doctor_low":"医生容量下四分位", "capability_AB":"仅直接/语义匹配", "bladder45":"憋尿45分钟", "bladder90":"憋尿90分钟", "transfer5":"跨室5分钟", "transfer15":"跨室15分钟"}
    lines = [r"\begin{tabular}{lrrrr}", r"\toprule", "情景 & 住院率 & 背景率 & P90/h & 排入分钟 \\\\", r"\midrule"]
    for name in order:
        row = frame.loc[name]
        lines.append(f"{names[name]} & {pct(row.inpatient_48h_rate)} & {pct(row.background_on_time_rate)} & {row.inpatient_wait_p90_hours_conditional:.2f} & {int(row.scheduled_minutes):,} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("sensitivity_metrics.tex", lines)

def exact_benchmark() -> None:
    frame = pd.read_csv(EXACT / "exact_vs_heuristic_metrics.csv", encoding="utf-8-sig")
    names = {"normal_weekday":"普通工作日", "peak_weekday":"高峰工作日", "weekend":"周末", "multi_project_peak":"多项目高峰", "bedside_peak":"床旁高峰", "obstetric_peak":"产科高峰"}
    lines = [r"\begin{tabular}{lrrrrl}", r"\toprule", "窗口 & 事件数 & 构造解 & CP-SAT & 最好界 & 状态 \\\\", r"\midrule"]
    for row in frame.itertuples(index=False): lines.append(f"{names[row.case]} & {row.event_count} & {row.heuristic_complete} & {row.exact_complete} & {row.best_bound:g} & {row.solver_status} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("exact_benchmark.tex", lines)

def verification() -> None:
    reports = [json.loads((FROZEN / path).read_text(encoding="utf-8")) for path in ["p2_inpatient_only/independent_verification.json","p3_joint/independent_verification.json"]]
    groups = {"键、输入与时长":["unique_exported_task_key","scheduled_task_exists_in_input","duration_matches_5pct_scenario"], "设备能力与床旁":["project_room_compatibility","bedside_uses_room_7"], "时间窗与准备":["task_not_before_release","task_complete_by_event_deadline","inside_single_work_block","fasting_complete_by_10","bladder_task_after_readiness"], "互斥与转运":["no_room_overlap","no_same_patient_task_overlap","cross_room_transfer_at_least_10min"], "医生容量":["doctor_capacity_defined","doctor_concurrency_within_capacity"], "结果聚合":["outcome_complete_flag_consistency","outcome_deadline_flag_consistency"]}
    lines = [r"\begin{tabular}{lrrl}", r"\toprule", "核验组 & P2违规 & P3违规 & 结论 \\\\", r"\midrule"]
    for label, keys in groups.items():
        values = [sum(int(report["checks"][key]["violation_count"]) for key in keys) for report in reports]
        lines.append(f"{label} & {values[0]} & {values[1]} & {'通过' if sum(values)==0 else '未通过'} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("verification.tex", lines)

def recommendation_sample() -> None:
    frame = pd.read_csv(FROZEN / "p3_joint/inpatient_recommended_schedule.csv", encoding="utf-8-sig", low_memory=False)
    sample = frame[frame["event_id"].isin(frame["event_id"].drop_duplicates().head(6))].head(14)
    lines = [r"\begin{tabularx}{\textwidth}{r l r X l l}", r"\toprule", "序位 & 事件 & 项目序位 & 项目族 & 时段 & 设备 \\\\", r"\midrule"]
    for row in sample.itertuples(index=False):
        start, end = pd.Timestamp(row.start_dt).strftime("%m-%d %H:%M"), pd.Timestamp(row.end_dt).strftime("%H:%M")
        lines.append(f"{row.recommended_patient_rank} & {esc(row.event_id)} & {row.sequence_position} & {esc(row.category)} & {start}--{end} & {esc(row.room_name)}({row.room_id}) \\\\")
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("recommendation_sample.tex", lines)

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    data_scope(); duration_parameters(); capability_evidence(); p2_policy(); p3_pareto(); calibration(); sensitivity(); exact_benchmark(); verification(); recommendation_sample()
    print("created 10 frozen-result LaTeX tables")

if __name__ == "__main__": main()
