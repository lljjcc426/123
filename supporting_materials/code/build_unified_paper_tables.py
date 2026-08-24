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
P3_EXACT = ROOT / "supporting_materials/results/p3_exact_benchmark"
CAL = ROOT / "supporting_materials/results/calibration"
CAPABILITY = ROOT / "supporting_materials/results/capability"
OUT = ROOT / "paper/tables"
POLICY_NAMES = {
    "FCFS_SHARED": "FCFS--最低编号",
    "SLACK_GUARD_SHARED": "最小松弛度--最低编号",
    "FCFS_LOAD_BALANCED": "FCFS--负荷均衡",
    "SLACK_LOAD_BALANCED": "最小松弛度--负荷均衡",
    "FCFS_SCARCITY_PRESERVING": "FCFS--稀缺能力保护",
    "SLACK_SCARCITY_PRESERVING": "最小松弛度--稀缺能力保护",
}

def esc(value: object) -> str:
    text = str(value)
    for old, new in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"), ("#", r"\#")]:
        text = text.replace(old, new)
    return text

def pct(value: float) -> str: return f"{100 * float(value):.2f}\\%"
def as_bool(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "yes"})
def alpha_label(value: float) -> str:
    text = f"{float(value):.3f}"
    return text[:-1] if text.endswith("0") else text
def write(name: str, lines: list[str]) -> None: (OUT / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

def forecast_comparison() -> None:
    frame = pd.read_csv(P1 / "chronological_validation.csv", encoding="utf-8-sig")
    frame = frame[(frame["basis"].eq("开单日"))]
    source_order = ["住院", "门诊", "体检", "三类合计"]
    model_order = ["7日季节朴素", "过去8周同星期中位数", "日历趋势对数岭回归"]
    lines = [
        r"\begin{tabular}{lrrr}", r"\toprule",
        r"来源 & 7日季节朴素 & 8周同星期中位数 & 日历趋势岭回归 \\",
        r"\midrule",
    ]
    for source in source_order:
        rows = frame[frame["source"].eq(source)].set_index("model")
        values = []
        for model in model_order:
            value = pct(rows.loc[model, "WAPE"])
            if bool(rows.loc[model, "best_WAPE_within_series"]):
                value = rf"\textbf{{{value}}}"
            values.append(value)
        lines.append(f"{source} & {' & '.join(values)} " + r"\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("forecast_comparison.tex", lines)

def peak_configuration() -> None:
    peak = pd.read_csv(P1 / "peak_flat_summary.csv", encoding="utf-8-sig")
    daily = pd.read_csv(P1 / "daily_trends.csv", encoding="utf-8-sig")
    total = peak[
        peak["source"].eq("三类合计") & peak["basis"].eq("开单日")
    ].iloc[0]
    daily = daily[daily["basis"].eq("开单日")]

    def source_counts(date: str) -> list[int]:
        rows = daily[daily["date"].eq(date)].set_index("source")
        return [int(rows.loc[source, "episode_count"]) for source in ["住院", "门诊", "体检"]]

    flat_count = int(round(float(total["median_flat_level"])))
    peak_count = int(round(float(total["q90_peak_threshold"])))
    flat_sources = source_counts(str(total["representative_flat_date"]))
    peak_sources = source_counts(str(total["representative_peak_date"]))
    stress = float(total["q95_stress_threshold"])
    capacity = pd.read_csv(INPUT / "doctor_slot_capacity.csv", encoding="utf-8-sig")
    max_doctors = int(capacity["capacity_main"].max())
    lines = [
        r"\begin{tabularx}{\textwidth}{lrrrrX}", r"\toprule",
        r"状态 & 合计/日 & 住院 & 门诊 & 体检 & 机器与预约配置 \\", r"\midrule",
        f"平峰代表日 & {flat_count:,} & {flat_sources[0]:,} & {flat_sources[1]:,} & {flat_sources[2]:,} & 专项项目固定进入相容诊室；综合项目按最早空闲分配，多项目优先共同设备。 " + r"\\",
        f"高峰代表日 & {peak_count:,} & {peak_sources[0]:,} & {peak_sources[1]:,} & {peak_sources[2]:,} & 同时开放数不超过时隙医生容量（最高{max_doctors}）；保留专项机容量，综合机承担可替代项目，体检批次分时进入。 " + r"\\",
        f"压力状态 & $\\ge {stress:.2f}$ & -- & -- & -- & 标准班次内先满足政策服务下限；其余背景预约移日或扩展工作时段，不改变设备项目资质。 " + r"\\",
        r"\bottomrule", r"\end{tabularx}",
    ]
    write("peak_configuration.tex", lines)

def p1_structure() -> None:
    department = pd.read_csv(P1 / "department_demand_overview_train.csv", encoding="utf-8-sig")
    multiproject = pd.read_csv(P1 / "multiproject_coefficient_sensitivity.csv", encoding="utf-8-sig")
    multiproject = multiproject[
        multiproject["basis"].eq("开单事件")
        & multiproject["multiproject_coefficient"].eq(1.0)
    ].set_index("source")
    department = department.set_index("source")
    lines = [
        r"\begin{tabular}{lrrrr}", r"\toprule",
        r"来源 & 训练期事件数 & 已知科室数 & 前6科室占比 & 全期多项目占比 \\", r"\midrule",
    ]
    for source in ["住院", "门诊", "体检"]:
        row = department.loc[source]
        lines.append(
            f"{source} & {int(row.service_event_count):,} & {int(row.known_department_count)} & "
            f"{pct(row.top_6_event_share)} & {pct(multiproject.loc[source, 'multiproject_episode_share'])} "
            + r"\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("p1_structure.tex", lines)

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
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule", "策略 & 48h完成数 & 完成率 & P50/h & P90/h & 多项目需求跨室率 \\\\", r"\midrule"]
    for row in frame.itertuples(index=False): lines.append(f"{POLICY_NAMES[row.policy]} & {row.inpatient_complete_48h:,} & {pct(row.inpatient_48h_rate)} & {row.inpatient_wait_p50_hours_conditional:.2f} & {row.inpatient_wait_p90_hours_conditional:.2f} & {pct(row.inpatient_room_switch_rate_multi)} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("p2_policy.tex", lines)

def p2_failure() -> None:
    summary = json.loads(
        (FROZEN / "p2_inpatient_only/summary.json").read_text(encoding="utf-8")
    )
    decomposition = pd.read_csv(
        CAPABILITY / "P2_CAPABILITY_FAILURE_DECOMPOSITION.csv",
        encoding="utf-8-sig",
    )
    incomplete = int(summary["metrics"]["inpatient_unscheduled"])
    capability_count = int(decomposition["event_count"].sum())
    capacity_count = incomplete - capability_count
    rows = [
        ("项目设备能力不满足（A--F分解）", capability_count),
        ("具备项目能力但48小时内未形成完整计划", capacity_count),
    ]
    lines = [
        r"\begin{tabular}{lrr}", r"\toprule",
        r"未完成主因 & 事件数 & 占全部未完成 \\", r"\midrule",
    ]
    lines += [f"{label} & {count:,} & {pct(count / incomplete)} " + r"\\" for label, count in rows]
    lines += [r"\midrule", f"合计 & {incomplete:,} & 100.00\\% " + r"\\", r"\bottomrule", r"\end{tabular}"]
    write("p2_failure.tex", lines)

def p2_room_load() -> None:
    frame = pd.read_csv(
        FROZEN / "p2_inpatient_only/room_utilization_daily.csv",
        encoding="utf-8-sig",
    )
    grouped = (
        frame.groupby(["room_id", "room_name"], as_index=False)
        .agg(
            scheduled_minutes=("duration_minutes", "sum"),
            active_day_mean_utilization=("room_utilization", "mean"),
        )
        .sort_values(["scheduled_minutes", "room_id"], ascending=[False, True])
        .head(6)
    )
    lines = [
        r"\begin{tabular}{lrr}", r"\toprule",
        r"诊室 & 排入分钟 & 有任务日平均利用率 \\", r"\midrule",
    ]
    for row in grouped.itertuples(index=False):
        lines.append(
            f"{esc(row.room_name)} & {int(row.scheduled_minutes):,} & "
            f"{pct(row.active_day_mean_utilization)} " + r"\\"
        )
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("p2_room_load.tex", lines)

def scenario_operation() -> None:
    p2 = json.loads(
        (FROZEN / "p2_inpatient_only/summary.json").read_text(encoding="utf-8")
    )["metrics"]
    selection = json.loads(
        (FROZEN / "p3_joint/selection.json").read_text(encoding="utf-8")
    )
    p3 = selection["selected_metrics"]
    required = int(p3["background_required_events"])
    completed = int(p3["background_completed_events"])
    lines = [
        r"\begin{tabular}{lrr}", r"\toprule",
        r"运行指标 & P2纯住院 & P3推荐联合方案 \\", r"\midrule",
        f"排入检查分钟 & {int(p2['scheduled_minutes']):,} & {int(p3['scheduled_minutes']):,} " + r"\\",
        f"人员在岗容量利用率 & {pct(p2['staffed_capacity_utilization'])} & {pct(p3['staffed_capacity_utilization'])} " + r"\\",
        f"住院等待P95/小时 & {float(p2['inpatient_wait_p95_hours_conditional']):.2f} & {float(p3['inpatient_wait_p95_hours_conditional']):.2f} " + r"\\",
        f"多项目需求跨室率 & {pct(p2['inpatient_room_switch_rate_multi'])} & {pct(p3['inpatient_room_switch_rate_multi'])} " + r"\\",
        f"背景全期下限/完成数 & -- & {required:,}/{completed:,} " + r"\\",
        r"\bottomrule", r"\end{tabular}",
    ]
    write("scenario_operation.tex", lines)

def seed_robustness() -> None:
    frame = pd.read_csv(
        FROZEN / "sensitivity_metrics.csv", encoding="utf-8-sig"
    )
    frame = frame[frame["audit_scenario"].astype(str).str.startswith("seed_")]
    specifications = [
        ("住院48小时率", "inpatient_48h_rate", "rate"),
        ("背景服务率", "background_on_time_rate", "rate"),
        ("等待P90/小时", "inpatient_wait_p90_hours_conditional", "decimal"),
        ("排入分钟", "scheduled_minutes", "integer"),
    ]
    lines = [
        r"\begin{tabular}{lrrrr}", r"\toprule",
        r"指标 & 均值 & 标准差 & 最小值 & 最大值 \\", r"\midrule",
    ]
    for label, column, kind in specifications:
        values = frame[column].astype(float)
        mean, std = values.mean(), values.std(ddof=1)
        minimum, maximum = values.min(), values.max()
        if kind == "rate":
            rendered = [
                f"{100 * mean:.4f}\\%", f"{100 * std:.4f}个百分点",
                f"{100 * minimum:.4f}\\%", f"{100 * maximum:.4f}\\%",
            ]
        elif kind == "integer":
            rendered = [f"{value:,.0f}" for value in [mean, std, minimum, maximum]]
        else:
            rendered = [f"{value:.2f}" for value in [mean, std, minimum, maximum]]
        lines.append(f"{label} & {' & '.join(rendered)} " + r"\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("seed_robustness.tex", lines)

def p3_pareto() -> None:
    frame = pd.read_csv(FROZEN / "p3_joint/pareto_metrics.csv", encoding="utf-8-sig")
    frame = frame[
        frame["epsilon_feasible"].eq(True) & frame["pareto_nondominated"].eq(True)
    ].sort_values(["background_on_time_rate", "inpatient_48h_rate"]).copy()
    selected = float(json.loads((FROZEN / "p3_joint/selection.json").read_text(encoding="utf-8"))["selected_alpha"])
    lines = [r"\begin{tabular}{rrrrrr}", r"\toprule", "$\\alpha$ & 背景完成数 & 背景率 & 住院完成数 & 住院率 & P90/h \\\\", r"\midrule"]
    for row in frame.itertuples(index=False):
        pre, suf = (r"\textbf{", "}") if abs(row.background_target_alpha-selected)<1e-9 else ("", "")
        lines.append(f"{pre}{alpha_label(row.background_target_alpha)}{suf} & {pre}{row.background_completed_events:,}{suf} & {pre}{pct(row.background_on_time_rate)}{suf} & {pre}{row.inpatient_complete_48h:,}{suf} & {pre}{pct(row.inpatient_48h_rate)}{suf} & {pre}{row.inpatient_wait_p90_hours_conditional:.2f}{suf} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("p3_pareto.tex", lines)

def calibration() -> None:
    frame = pd.read_csv(CAL / "calibration_metrics.csv", encoding="utf-8-sig")
    scenario_order = [
        "C0_historical_report", "C1_duration_only", "C2_standard_hours",
        "C3_doctor_capacity", "C4_project_capability", "C5_item_preparation",
        "C6_joint_background", "C7_formal_heuristic",
    ]
    frame = frame.set_index("scenario").loc[scenario_order].reset_index()
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
    lines = [
        r"\begin{tabularx}{\textwidth}{Xrrrrrr}",
        r"\toprule",
        r"情景 & 住院率 & 背景率 & P90/h & $\varepsilon$满足 & 背景缺口 & 排入分钟 \\",
        r"\midrule",
    ]
    for name in order:
        row = frame.loc[name]
        epsilon_ok = bool(
            as_bool(pd.Series([row.epsilon_constraint_satisfied])).iloc[0]
        )
        lines.append(
            f"{names[name]} & {pct(row.inpatient_48h_rate)} & "
            f"{pct(row.background_on_time_rate)} & "
            f"{row.inpatient_wait_p90_hours_conditional:.2f} & "
            f"{'是' if epsilon_ok else '否'} & "
            f"{int(row.background_deficit_events):,} & "
            f"{int(row.scheduled_minutes):,} " + r"\\"
        )
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("sensitivity_metrics.tex", lines)

def exact_benchmark() -> None:
    frame = pd.read_csv(EXACT / "exact_vs_heuristic_metrics.csv", encoding="utf-8-sig")
    names = {"normal_weekday":"普通工作日", "peak_weekday":"高峰工作日", "weekend":"周末", "multi_project_peak":"多项目高峰", "bedside_peak":"床旁高峰", "obstetric_peak":"产科高峰"}
    lines = [r"\begin{tabular}{lrrrrlr}", r"\toprule", "验证子问题 & 事件数 & 构造解 & 精确可行值 & 最好界 & 状态 & 至界差距 \\\\", r"\midrule"]
    for row in frame.itertuples(index=False):
        incumbent = "--" if pd.isna(row.exact_complete) else f"{int(row.exact_complete)}"
        lines.append(
            f"{names[row.case]} & {int(row.event_count)} & {int(row.heuristic_complete)} & "
            f"{incumbent} & {float(row.best_bound):g} & {row.solver_status} & "
            f"{pct(row.heuristic_gap_to_bound)} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("exact_benchmark.tex", lines)

def p3_exact_benchmark() -> None:
    frame = pd.read_csv(
        P3_EXACT / "p3_exact_vs_heuristic_metrics.csv", encoding="utf-8-sig"
    )
    names = {
        "ordinary_joint_n20": "普通联合",
        "background_peak_n40": "背景高峰",
        "inpatient_peak_n60": "住院高峰",
        "multi_project_peak_n40": "多项目高峰",
        "bedside_pressure_n20": "床旁压力",
        "obstetric_pressure_n40": "产科压力",
        "equipment_competition_n60": "设备竞争",
        "recommended_alpha_typical_n100": "推荐点典型窗",
    }
    lines = [
        r"\begingroup", r"\setlength{\tabcolsep}{3pt}",
        r"\begin{tabularx}{\textwidth}{>{\raggedright\arraybackslash}Xrrrrllrr}",
        r"\toprule",
        r"验证子问题 & $\alpha$ & 事件数 & \makecell{背景\\H/E} & \makecell{H\\住院} & \makecell{E住院值\\最好界} & 状态 & \makecell{求解器\\间隙} & \makecell{H至界\\差距} \\",
        r"\midrule",
    ]
    for row in frame.itertuples(index=False):
        exact_background = (
            "--" if pd.isna(row.exact_background_complete)
            else f"{int(row.exact_background_complete)}"
        )
        incumbent = (
            "--" if pd.isna(row.exact_inpatient_incumbent)
            else f"{int(row.exact_inpatient_incumbent)}"
        )
        bound_value = float(row.best_bound) if not pd.isna(row.best_bound) else None
        if bound_value is not None and abs(bound_value) < 5e-12:
            bound_value = 0.0
        bound = "--" if bound_value is None else f"{bound_value:g}"
        solver_gap = (
            "--" if pd.isna(row.solver_relative_gap)
            else pct(0.0 if abs(float(row.solver_relative_gap)) < 5e-12 else row.solver_relative_gap)
        )
        heuristic_gap = (
            "--" if pd.isna(row.heuristic_gap_to_bound)
            else pct(0.0 if abs(float(row.heuristic_gap_to_bound)) < 5e-12 else row.heuristic_gap_to_bound)
        )
        lines.append(
            f"{names.get(row.case, esc(row.case))} & {alpha_label(row.alpha)} & "
            f"{int(row.event_count)} & {int(row.heuristic_background_complete)}/{exact_background} & "
            f"{int(row.heuristic_inpatient_complete)} & {incumbent}/{bound} & "
            f"{row.solver_status} & {solver_gap} & {heuristic_gap} " + r"\\"
        )
    lines += [r"\bottomrule", r"\end{tabularx}", r"\endgroup"]
    write("p3_exact_benchmark.tex", lines)

def verification() -> None:
    reports = [json.loads((FROZEN / path).read_text(encoding="utf-8")) for path in ["p2_inpatient_only/independent_verification.json","p3_joint/independent_verification.json"]]
    groups = {"键、输入与时长":["unique_exported_task_key","scheduled_task_exists_in_input","duration_matches_5pct_scenario"], "设备能力与床旁":["project_room_compatibility","bedside_uses_room_7"], "时间窗与准备":["task_not_before_release","task_complete_by_event_deadline","inside_single_work_block","fasting_complete_by_10","bladder_task_after_readiness"], "互斥与转运":["no_room_overlap","no_same_event_task_overlap","within_event_cross_room_transfer_at_least_configured_minutes","no_patient_task_overlap_across_events","adjacent_patient_cross_room_transfer_at_least_configured_minutes"], "医生容量":["doctor_capacity_defined","doctor_concurrency_within_capacity"], "结果聚合":["outcome_complete_flag_consistency","outcome_deadline_flag_consistency"]}
    lines = [r"\begin{tabular}{lrrl}", r"\toprule", "核验组 & P2违规 & P3违规 & 结论 \\\\", r"\midrule"]
    for label, keys in groups.items():
        values = [sum(int(report["checks"][key]["violation_count"]) for key in keys) for report in reports]
        lines.append(f"{label} & {values[0]} & {values[1]} & {'通过' if sum(values)==0 else '未通过'} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    write("verification.tex", lines)

def recommendation_sample() -> None:
    frame = pd.read_csv(
        FROZEN / "p2_inpatient_only/inpatient_recommended_schedule.csv",
        encoding="utf-8-sig",
        low_memory=False,
    )
    sample = frame[frame["event_id"].isin(frame["event_id"].drop_duplicates().head(6))].head(14)
    lines = [r"\begin{tabularx}{\textwidth}{r l r X l l}", r"\toprule", "序位 & 事件 & 项目序位 & 项目族 & 时段 & 设备 \\\\", r"\midrule"]
    for row in sample.itertuples(index=False):
        start, end = pd.Timestamp(row.start_dt).strftime("%m-%d %H:%M"), pd.Timestamp(row.end_dt).strftime("%H:%M")
        lines.append(f"{row.recommended_patient_rank} & {esc(row.event_id)} & {row.sequence_position} & {esc(row.category)} & {start}--{end} & {esc(row.room_name)}({row.room_id}) \\\\")
    lines += [r"\bottomrule", r"\end{tabularx}"]
    write("recommendation_sample.tex", lines)

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    forecast_comparison()
    peak_configuration()
    p1_structure()
    data_scope()
    duration_parameters()
    capability_evidence()
    p2_policy()
    p2_failure()
    p2_room_load()
    p3_pareto()
    scenario_operation()
    calibration()
    sensitivity()
    seed_robustness()
    exact_benchmark()
    p3_exact_benchmark()
    verification()
    recommendation_sample()
    print("created 18 authoritative LaTeX tables")

if __name__ == "__main__": main()
