"""Programmatic hard acceptance for the final LaTeX paper."""

from __future__ import annotations

import csv
import json
import re
import shutil
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PAPER_DIR = ROOT / "paper"
MAIN_TEX = PAPER_DIR / "main.tex"
FINAL_PDF = PAPER_DIR / "超声预约优化论文.pdf"
REPORT_PATH = ROOT / "qa" / "PAPER_HARD_ACCEPTANCE_REPORT.md"
CONSISTENCY_JSON_PATH = ROOT / "qa" / "MODEL_RESULT_FINAL_CONSISTENCY_AUDIT.json"
CONSISTENCY_REPORT_PATH = ROOT / "MODEL_RESULT_FINAL_CONSISTENCY_AUDIT.md"
FINAL_QA_PATH = ROOT / "qa" / "FINAL_QA_REPORT.md"
VISUAL_REPORT_PATH = ROOT / "qa" / "PAPER_VISUAL_INSPECTION_REPORT.md"
STRUCTURE_REPORT_PATH = ROOT / "PAPER_STRUCTURE_AUDIT.md"
TECHNICAL_AUDIT_PATH = ROOT / "SECOND_STAGE_FINAL_TECHNICAL_AUDIT.md"
MANIFEST_PATH = (
    ROOT / "supporting_materials/results/final_frozen/FINAL_RESULT_MANIFEST.json"
)

BODY_FILES = [
    PAPER_DIR / "sections/01_problem.tex",
    PAPER_DIR / "sections/02_analysis.tex",
    PAPER_DIR / "sections/03_assumptions.tex",
    PAPER_DIR / "sections/04_symbols.tex",
    PAPER_DIR / "sections/05_01_problem1.tex",
    PAPER_DIR / "sections/05_02_problem2.tex",
    PAPER_DIR / "sections/05_03_problem3.tex",
    PAPER_DIR / "sections/06_validation.tex",
    PAPER_DIR / "sections/07_evaluation.tex",
    PAPER_DIR / "sections/08_improvement_extension.tex",
    PAPER_DIR / "sections/09_references.tex",
]
APPENDIX_FILE = PAPER_DIR / "sections/appendix.tex"

EXPECTED_SECTIONS = [
    "问题重述",
    "问题分析",
    "模型假设",
    "符号说明",
    "模型的建立与求解",
    "模型的检验",
    "模型的评价",
    "模型的改进与推广",
    "参考文献",
]
EXPECTED_PDF_HEADINGS = [
    "一、问题重述",
    "二、问题分析",
    "三、模型假设",
    "四、符号说明",
    "五、模型的建立与求解",
    "六、模型的检验",
    "七、模型的评价",
    "八、模型的改进与推广",
    "九、参考文献",
]


@dataclass(frozen=True)
class AssertionResult:
    check_id: str
    requirement: str
    passed: bool
    evidence: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_pdf_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


def find_xelatex() -> str | None:
    located = shutil.which("xelatex")
    if located:
        return located
    fallback = (
        Path.home()
        / "AppData/Local/Programs/MiKTeX/miktex/bin/x64/xelatex.exe"
    )
    return str(fallback) if fallback.exists() else None


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def extract_pdf_text(pdf_path: Path) -> tuple[str, str]:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext or not pdf_path.exists():
        return "", "pdftotext不可用或PDF不存在"
    result = run_command([pdftotext, "-layout", str(pdf_path), "-"], PAPER_DIR)
    if result.returncode != 0:
        return "", f"pdftotext返回码{result.returncode}"
    return result.stdout, f"pdftotext成功，提取{len(result.stdout)}字符"


def extract_pdf_pages(pdf_path: Path) -> tuple[int | None, str]:
    pdfinfo = shutil.which("pdfinfo")
    if not pdfinfo or not pdf_path.exists():
        return None, "pdfinfo不可用或PDF不存在"
    result = run_command([pdfinfo, str(pdf_path)], PAPER_DIR)
    match = re.search(r"^Pages:\s+(\d+)\s*$", result.stdout, flags=re.MULTILINE)
    if result.returncode != 0 or not match:
        return None, f"pdfinfo返回码{result.returncode}，未取得页数"
    return int(match.group(1)), f"pdfinfo Pages={match.group(1)}"


def tex_subsections(text: str) -> list[str]:
    return re.findall(r"\\subsection\{([^{}]+)\}", text)


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "；")


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def truthy(value: object) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def int_group(value: object) -> list[str]:
    number = int(round(float(value)))
    comma = f"{number:,}"
    return [comma, comma.replace(",", r"\,")]


def percent_group(value: object, digits: int = 2) -> list[str]:
    number = 100 * float(value)
    if abs(number) < 0.5 * 10 ** (-digits):
        number = 0.0
    return [f"{number:.{digits}f}\\%"]


def decimal_group(value: object, digits: int = 2) -> list[str]:
    number = float(value)
    if abs(number) < 0.5 * 10 ** (-digits):
        number = 0.0
    return [f"{number:.{digits}f}"]


def alpha_group(value: object) -> list[str]:
    number = float(value)
    return [f"{number:.2f}", f"{number:.3f}".rstrip("0")]


def missing_groups(text: str, groups: list[list[str]]) -> list[list[str]]:
    return [group for group in groups if not any(token in text for token in group)]


def table_body_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    inside = False
    count = 0
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped == r"\midrule":
            inside = True
            continue
        if stripped == r"\bottomrule":
            break
        if inside and stripped.endswith(r"\\"):
            count += 1
    return count


def table_body_rows(path: Path) -> list[str]:
    if not path.exists():
        return []
    inside = False
    rows: list[str] = []
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped == r"\midrule":
            inside = True
            continue
        if stripped == r"\bottomrule":
            break
        if inside and stripped.endswith(r"\\"):
            rows.append(stripped)
    return rows


def row_missing_groups(
    rows: list[str],
    identifying_tokens: list[str],
    groups: list[list[str]],
) -> list[list[str]]:
    row = next(
        (candidate for candidate in rows if any(token in candidate for token in identifying_tokens)),
        "",
    )
    return missing_groups(row, groups)


def tex_subsubsection_block(text: str, title: str) -> str:
    marker = rf"\subsubsection{{{title}}}"
    start = text.find(marker)
    if start < 0:
        return ""
    end = text.find(r"\subsubsection{", start + len(marker))
    return text[start:] if end < 0 else text[start:end]


def write_result_consistency_report(
    main_tex: str,
    body_texts: dict[str, str],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []

    def add(
        check_id: str,
        requirement: str,
        passed: bool,
        paper_evidence: str,
        result_evidence: str,
        source_files: list[Path],
    ) -> None:
        checks.append(
            {
                "id": check_id,
                "requirement": requirement,
                "passed": bool(passed),
                "paper_evidence": paper_evidence,
                "result_evidence": result_evidence,
                "source_files": [
                    str(path.relative_to(ROOT)).replace("\\", "/")
                    for path in source_files
                ],
            }
        )

    results = ROOT / "supporting_materials/results"
    frozen = results / "final_frozen"
    processed = ROOT / "supporting_materials/processed_data/unified_holdout"
    paths = {
        "p1_peak": results / "p1/peak_flat_summary.csv",
        "p1_forecast": results / "p1/chronological_validation.csv",
        "p1_department": results / "p1/department_demand_overview_train.csv",
        "p1_multi": results / "p1/multiproject_coefficient_sensitivity.csv",
        "p1_monthly": results / "p1/monthly_trends.csv",
        "p1_daily": results / "p1/daily_trends.csv",
        "p1_annual": results / "p1/annual_trends.csv",
        "p1_summary": results / "p1/analysis_summary.json",
        "p1_gap": results / "p1/report_gap_proxy_by_category.csv",
        "p1_duration": results / "p1/service_duration_parameters.csv",
        "unified_summary": processed / "summary.json",
        "events": processed / "events.csv",
        "items": processed / "items.csv",
        "doctor_capacity": processed / "doctor_slot_capacity.csv",
        "capability_summary": processed / "project_machine_summary.csv",
        "p2_summary": frozen / "p2_inpatient_only/summary.json",
        "p2_policy": frozen / "p2_inpatient_only/policy_metrics.csv",
        "p2_failure": results / "capability/P2_CAPABILITY_FAILURE_DECOMPOSITION.csv",
        "p2_room": frozen / "p2_inpatient_only/room_utilization_daily.csv",
        "p2_recommendation": frozen / "p2_inpatient_only/inpatient_recommended_schedule.csv",
        "p3_selection": frozen / "p3_joint/selection.json",
        "p3_pareto": frozen / "p3_joint/pareto_metrics.csv",
        "p3_daily": frozen / "p3_joint/daily_service_metrics.csv",
        "p3_schedule": frozen / "p3_joint/final_patient_task_schedule.csv",
        "p2_exact": results / "exact_benchmark/exact_vs_heuristic_metrics.csv",
        "p3_exact": results / "p3_exact_benchmark/p3_exact_vs_heuristic_metrics.csv",
        "p3_repair": results / "p3_exact_benchmark/p3_repair_path_audit.json",
        "p2_verify": frozen / "p2_inpatient_only/independent_verification.json",
        "p3_verify": frozen / "p3_joint/independent_verification.json",
        "calibration": results / "calibration/calibration_metrics.csv",
        "sensitivity": frozen / "sensitivity_metrics.csv",
        "preparation": frozen / "preparation_granularity_sensitivity.csv",
        "seed": frozen / "special_seed_summary.json",
    }
    missing_inputs = [name for name, path in paths.items() if not path.exists()]
    add(
        "I01",
        "最终论文所依赖的权威结果文件齐备",
        not missing_inputs,
        "论文引用P1、P2、P3、精确对照、校准、敏感性和稳健性结果",
        f"缺失={missing_inputs}",
        list(paths.values()),
    )

    p1_text = main_tex + "\n" + body_texts["05_01_problem1.tex"]
    if paths["p1_peak"].exists() and paths["p1_forecast"].exists():
        peak_rows = csv_rows(paths["p1_peak"])
        peak = next(
            (
                row
                for row in peak_rows
                if row.get("source") == "三类合计" and row.get("basis") == "开单日"
            ),
            None,
        )
        forecast_rows = csv_rows(paths["p1_forecast"])

        def best_wape(source: str) -> float | None:
            row = next(
                (
                    item
                    for item in forecast_rows
                    if item.get("source") == source
                    and item.get("basis") == "开单日"
                    and truthy(item.get("best_WAPE_within_series"))
                ),
                None,
            )
            return float(row["WAPE"]) if row else None

        wapes = {source: best_wape(source) for source in ["住院", "门诊", "体检", "三类合计"]}
        if peak and all(value is not None for value in wapes.values()):
            groups = [
                decimal_group(peak["median_flat_level"], 0),
                decimal_group(peak["q90_peak_threshold"], 0),
                decimal_group(peak["q95_stress_threshold"], 2),
                percent_group(wapes["住院"]),
                percent_group(wapes["门诊"]),
                percent_group(wapes["体检"]),
                percent_group(wapes["三类合计"]),
            ]
            missing = missing_groups(p1_text, groups)
            add(
                "P101",
                "问题一阈值与四类留出WAPE来自最新P1结果",
                not missing,
                f"缺失格式组={missing}",
                f"peak={peak['median_flat_level']}/{peak['q90_peak_threshold']}/{peak['q95_stress_threshold']}；WAPE={wapes}",
                [paths["p1_peak"], paths["p1_forecast"]],
            )
        else:
            add("P101", "问题一阈值与四类留出WAPE来自最新P1结果", False, "未能定位论文对照值", "P1结果缺少目标行", [paths["p1_peak"], paths["p1_forecast"]])
    else:
        add("P101", "问题一阈值与四类留出WAPE来自最新P1结果", False, "未检查", "P1结果文件缺失", [paths["p1_peak"], paths["p1_forecast"]])

    forecast_table = PAPER_DIR / "tables/forecast_comparison.tex"
    if paths["p1_forecast"].exists() and forecast_table.exists():
        forecast_rows = [
            row for row in csv_rows(paths["p1_forecast"])
            if row.get("basis") == "开单日"
        ]
        table_rows = table_body_rows(forecast_table)
        missing_sources: list[str] = []
        for source in ["住院", "门诊", "体检", "三类合计"]:
            source_rows = [row for row in forecast_rows if row.get("source") == source]
            groups = [percent_group(row["WAPE"]) for row in source_rows]
            if len(source_rows) != 3 or row_missing_groups(table_rows, [source], groups):
                missing_sources.append(source)
        add(
            "P102",
            "问题一预测比较表逐来源匹配三种留出WAPE",
            len(table_rows) == 4 and not missing_sources,
            f"表行数={len(table_rows)}；不匹配来源={missing_sources}",
            f"开单日结果行数={len(forecast_rows)}",
            [paths["p1_forecast"], forecast_table],
        )
    else:
        add("P102", "问题一预测比较表逐来源匹配三种留出WAPE", False, "表或CSV缺失", "未检查", [paths["p1_forecast"], forecast_table])

    p1_structure_table = PAPER_DIR / "tables/p1_structure.tex"
    if (
        paths["p1_department"].exists()
        and paths["p1_multi"].exists()
        and p1_structure_table.exists()
    ):
        department_rows = csv_rows(paths["p1_department"])
        multi_rows = csv_rows(paths["p1_multi"])
        table_rows = table_body_rows(p1_structure_table)
        mismatched: list[str] = []
        for source in ["住院", "门诊", "体检"]:
            department = next(row for row in department_rows if row["source"] == source)
            multi = next(
                row for row in multi_rows
                if row["source"] == source
                and row["basis"] == "开单事件"
                and abs(float(row["multiproject_coefficient"]) - 1.0) < 1e-12
            )
            groups = [
                int_group(department["service_event_count"]),
                int_group(department["known_department_count"]),
                percent_group(department["top_6_event_share"]),
                percent_group(multi["multiproject_episode_share"]),
            ]
            if row_missing_groups(table_rows, [source], groups):
                mismatched.append(source)
        add(
            "P103",
            "问题一科室与多项目结构表匹配训练期及全期结果",
            len(table_rows) == 3 and not mismatched,
            f"表行数={len(table_rows)}；不匹配来源={mismatched}",
            "科室列取训练期，多项目列取全观察期开单事件",
            [paths["p1_department"], paths["p1_multi"], p1_structure_table],
        )
    else:
        add("P103", "问题一科室与多项目结构表匹配训练期及全期结果", False, "表或CSV缺失", "未检查", [paths["p1_department"], paths["p1_multi"], p1_structure_table])

    if paths["unified_summary"].exists() and paths["p3_selection"].exists():
        unified = json.loads(read_text(paths["unified_summary"]))
        event_count = sum(int(value) for value in unified["events"].values())
        item_count = sum(int(value) for value in unified["items"].values())
        warmup_count = int(unified["events"]["住院"]) - 70_771
        scope_selection = json.loads(read_text(paths["p3_selection"]))
        background_count = int(
            scope_selection["selected_metrics"]["background_events"]
        )
        event_block = tex_subsubsection_block(p1_text, "事件—项目两层数据结构")
        capability_block = tex_subsubsection_block(p1_text, "项目—设备兼容模型")
        capacity_block = tex_subsubsection_block(p1_text, "项目时长与医生效率边界")
        data_groups = [
            int_group(event_count),
            int_group(item_count),
            int_group(warmup_count),
            int_group(background_count),
        ]
        capability_groups = [
            int_group(unified["capability"]["unique_projects"]),
            *[
                int_group(unified["capability"]["projects_by_evidence_level"][level])
                for level in ["A", "B", "C", "D"]
            ],
        ]
        capacity_groups = [
            int_group(unified["doctor_capacity"]["current_doctor_count_from_problem"]),
            int_group(unified["doctor_capacity"]["room_cap"]),
            [
                f"{unified['doctor_capacity']['main_capacity_min']}--"
                f"{unified['doctor_capacity']['main_capacity_max']}"
            ],
        ]
        missing_data = missing_groups(event_block, data_groups)
        missing_capability = missing_groups(capability_block, capability_groups)
        missing_capacity = missing_groups(capacity_block, capacity_groups)
        add(
            "P104",
            "问题一数据规模、设备能力分类与医生容量正文匹配统一输入",
            not missing_data and not missing_capability and not missing_capacity,
            f"数据缺失={missing_data}；能力缺失={missing_capability}；容量缺失={missing_capacity}",
            f"事件/任务={event_count}/{item_count}；预热/背景={warmup_count}/{background_count}；"
            f"能力={unified['capability']['projects_by_evidence_level']}；"
            f"容量={unified['doctor_capacity']['main_capacity_min']}--{unified['doctor_capacity']['main_capacity_max']}",
            [paths["unified_summary"], paths["p3_selection"]],
        )
    else:
        add("P104", "问题一数据规模、设备能力分类与医生容量正文匹配统一输入", False, "结果缺失", "未检查", [paths["unified_summary"], paths["p3_selection"]])

    if paths["p1_peak"].exists() and paths["p1_annual"].exists():
        combined_peak = next(
            row for row in csv_rows(paths["p1_peak"])
            if row["source"] == "三类合计" and row["basis"] == "开单日"
        )
        annual_rows = [
            row for row in csv_rows(paths["p1_annual"])
            if row["source"] == "住院"
            and row["basis"] == "开单日"
            and 2020 <= int(row["period"][:4]) <= 2024
        ]
        trend_block = tex_subsubsection_block(p1_text, "需求趋势与峰平阈值")
        groups = [
            *[decimal_group(row["mean_daily_episodes"]) for row in annual_rows],
            decimal_group(combined_peak["q45"]),
            decimal_group(combined_peak["median_flat_level"], 0),
            decimal_group(combined_peak["q55"], 0),
            decimal_group(combined_peak["q90_peak_threshold"], 0),
            decimal_group(combined_peak["q95_stress_threshold"]),
            [
                "{}年{}月{}日".format(
                    *[
                        int(part)
                        for part in combined_peak["representative_peak_date"].split("-")
                    ]
                )
            ],
            [
                "{}年{}月{}日".format(
                    *[
                        int(part)
                        for part in combined_peak["representative_flat_date"].split("-")
                    ]
                )
            ],
            percent_group(combined_peak["holdout_peak_day_share"]),
            percent_group(combined_peak["holdout_stress_day_share"]),
        ]
        missing = missing_groups(trend_block, groups)
        add(
            "P105",
            "问题一年度住院需求与峰平阈值正文匹配训练期结果",
            len(annual_rows) == 5 and not missing,
            f"年度行={len(annual_rows)}；缺失格式组={missing}",
            f"年度均值={[row['mean_daily_episodes'] for row in annual_rows]}；峰平行={combined_peak}",
            [paths["p1_annual"], paths["p1_peak"]],
        )
    else:
        add("P105", "问题一年度住院需求与峰平阈值正文匹配训练期结果", False, "结果缺失", "未检查", [paths["p1_annual"], paths["p1_peak"]])

    if all(paths[name].exists() for name in ["p1_summary", "p1_multi", "p1_gap"]):
        analysis = json.loads(read_text(paths["p1_summary"]))
        multi_rows = csv_rows(paths["p1_multi"])
        inpatient_multi = [
            row for row in multi_rows
            if row["source"] == "住院" and row["basis"] == "开单事件"
        ]
        obstetric_gap = next(
            row for row in csv_rows(paths["p1_gap"])
            if row["primary_category"] == "产科III/IV级"
        )
        structure_block = tex_subsubsection_block(p1_text, "科室需求与多项目结构")
        proxy_block = tex_subsubsection_block(p1_text, "项目时长与医生效率边界")
        structure_groups = [
            *[
                percent_group(row["multiproject_episode_share"])
                for row in multi_rows
                if row["basis"] == "开单事件"
                and float(row["multiproject_coefficient"]) == 1.0
            ],
            *[
                decimal_group(row["mean_nominal_workload_per_episode_min"])
                for row in inpatient_multi
            ],
        ]
        proxy_groups = [
            int_group(analysis["report_gap_proxy"]["single_project_valid_gap_proxy_count"]),
            decimal_group(analysis["report_gap_proxy"]["overall_single_project_valid_gap_median_min"], 0),
            decimal_group(obstetric_gap["proxy_median_min"], 0),
        ]
        missing_structure = missing_groups(structure_block, structure_groups)
        missing_proxy = missing_groups(proxy_block, proxy_groups)
        add(
            "P106",
            "问题一多项目敏感性与报告间隔代理正文匹配分析结果",
            not missing_structure and not missing_proxy,
            f"多项目缺失={missing_structure}；代理缺失={missing_proxy}",
            f"住院多项目均值={[row['mean_nominal_workload_per_episode_min'] for row in inpatient_multi]}；"
            f"代理样本={analysis['report_gap_proxy']['single_project_valid_gap_proxy_count']}；"
            f"产科III/IV中位数={obstetric_gap['proxy_median_min']}",
            [paths["p1_summary"], paths["p1_multi"], paths["p1_gap"]],
        )
    else:
        add("P106", "问题一多项目敏感性与报告间隔代理正文匹配分析结果", False, "结果缺失", "未检查", [paths["p1_summary"], paths["p1_multi"], paths["p1_gap"]])

    p2_text = main_tex + "\n" + body_texts["05_02_problem2.tex"]
    p2_summary: dict[str, object] | None = None
    if paths["p2_summary"].exists():
        p2_summary = json.loads(read_text(paths["p2_summary"]))
        metrics = p2_summary["metrics"]
        selected_policy_labels = {
            "FCFS_SHARED": "FCFS--最低编号",
            "SLACK_GUARD_SHARED": "最小松弛度--最低编号",
            "FCFS_LOAD_BALANCED": "FCFS--负荷均衡",
            "SLACK_LOAD_BALANCED": "最小松弛度--负荷均衡",
            "FCFS_SCARCITY_PRESERVING": "FCFS--稀缺能力保护",
            "SLACK_SCARCITY_PRESERVING": "最小松弛度--稀缺能力保护",
        }
        selected_policy = str(p2_summary.get("selected_policy", ""))
        selected_policy_label = selected_policy_labels.get(
            selected_policy, selected_policy
        )
        groups = [
            int_group(metrics["inpatient_complete_48h"]),
            percent_group(metrics["inpatient_48h_rate"]),
            decimal_group(metrics["inpatient_wait_p50_hours_conditional"]),
            decimal_group(metrics["inpatient_wait_p90_hours_conditional"]),
            decimal_group(metrics["inpatient_wait_p95_hours_conditional"]),
            percent_group(metrics["inpatient_room_switch_rate_multi"]),
            int_group(metrics["scheduled_minutes"]),
            percent_group(metrics["staffed_capacity_utilization"]),
            int_group(metrics["inpatient_unscheduled"]),
        ]
        missing = missing_groups(p2_text, groups)
        add(
            "P201",
            "问题二摘要与正文关键指标匹配最终summary",
            not missing and selected_policy_label in p2_text,
            f"缺失格式组={missing}；推荐策略写入正文={selected_policy_label in p2_text}",
            f"selected_policy={p2_summary.get('selected_policy')}；metrics={metrics}",
            [paths["p2_summary"]],
        )
    else:
        add("P201", "问题二摘要与正文关键指标匹配最终summary", False, "未检查", "P2 summary缺失", [paths["p2_summary"]])

    p2_table = PAPER_DIR / "tables/p2_policy.tex"
    if paths["p2_policy"].exists() and p2_table.exists():
        policy_rows = csv_rows(paths["p2_policy"])
        table_rows = table_body_rows(p2_table)
        policy_labels = {
            "FCFS_SHARED": "FCFS--最低编号",
            "SLACK_GUARD_SHARED": "最小松弛度--最低编号",
            "FCFS_LOAD_BALANCED": "FCFS--负荷均衡",
            "SLACK_LOAD_BALANCED": "最小松弛度--负荷均衡",
            "FCFS_SCARCITY_PRESERVING": "FCFS--稀缺能力保护",
            "SLACK_SCARCITY_PRESERVING": "最小松弛度--稀缺能力保护",
        }
        missing_policy_rows: list[str] = []
        for row in policy_rows:
            groups = [
                [policy_labels.get(row["policy"], row["policy"])],
                int_group(row["inpatient_complete_48h"]),
                percent_group(row["inpatient_48h_rate"]),
                decimal_group(row["inpatient_wait_p50_hours_conditional"]),
                decimal_group(row["inpatient_wait_p90_hours_conditional"]),
                percent_group(row["inpatient_room_switch_rate_multi"]),
            ]
            label = policy_labels.get(row["policy"], row["policy"])
            if row_missing_groups(table_rows, [label], groups):
                missing_policy_rows.append(row["policy"])
        actual_rows = table_body_row_count(p2_table)
        add(
            "P202",
            "问题二六策略表逐行匹配policy_metrics",
            len(policy_rows) == 6 and actual_rows == len(policy_rows) and not missing_policy_rows,
            f"表行数={actual_rows}；缺失策略={missing_policy_rows}",
            f"CSV行数={len(policy_rows)}",
            [paths["p2_policy"], p2_table],
        )
    else:
        add("P202", "问题二六策略表逐行匹配policy_metrics", False, "表或CSV缺失", "未检查", [paths["p2_policy"], p2_table])

    p2_failure_table = PAPER_DIR / "tables/p2_failure.tex"
    if (
        p2_summary is not None
        and paths["p2_failure"].exists()
        and p2_failure_table.exists()
    ):
        incomplete = int(p2_summary["metrics"]["inpatient_unscheduled"])
        decomposition_rows = csv_rows(paths["p2_failure"])
        capability_count = sum(
            int(row["event_count"]) for row in decomposition_rows
        )
        capacity_count = incomplete - capability_count
        table_rows = table_body_rows(p2_failure_table)
        expected = [
            ("项目设备能力不满足", capability_count),
            ("具备项目能力但48小时内未形成完整计划", capacity_count),
            ("合计", incomplete),
        ]
        mismatched = [
            label for label, count in expected
            if row_missing_groups(
                table_rows,
                [label],
                [int_group(count), percent_group(count / incomplete)],
            )
        ]
        nonzero_detail_missing = [
            row["category_code"]
            for row in decomposition_rows
            if int(row["event_count"]) > 0
            and missing_groups(p2_text, [int_group(row["event_count"])])
        ]
        add(
            "P203",
            "问题二未完成主因表只使用评价期分母并匹配A至F能力分解",
            capacity_count >= 0
            and len(decomposition_rows) == 6
            and len(table_rows) == 3
            and not mismatched
            and not nonzero_detail_missing,
            f"表行数={len(table_rows)}；不匹配={mismatched}；"
            f"正文缺失非零A--F类别={nonzero_detail_missing}",
            f"未完成={incomplete}；能力失败={capability_count}；其余={capacity_count}；"
            f"A--F={[(row['category_code'], row['event_count']) for row in decomposition_rows]}",
            [paths["p2_summary"], paths["p2_failure"], p2_failure_table],
        )
    else:
        add("P203", "问题二未完成主因表只使用评价期分母并匹配A至F能力分解", False, "表或结果缺失", "未检查", [paths["p2_summary"], paths["p2_failure"], p2_failure_table])

    p2_room_table = PAPER_DIR / "tables/p2_room_load.tex"
    if paths["p2_room"].exists() and p2_room_table.exists():
        aggregate: dict[tuple[str, str], dict[str, float]] = {}
        for row in csv_rows(paths["p2_room"]):
            key = (row["room_id"], row["room_name"])
            state = aggregate.setdefault(key, {"minutes": 0.0, "util_sum": 0.0, "days": 0.0})
            state["minutes"] += float(row["duration_minutes"])
            state["util_sum"] += float(row["room_utilization"])
            state["days"] += 1
        ranked = sorted(
            aggregate.items(),
            key=lambda item: (-item[1]["minutes"], int(item[0][0])),
        )[:6]
        table_rows = table_body_rows(p2_room_table)
        mismatched_rooms: list[str] = []
        for (_, room_name), state in ranked:
            groups = [
                int_group(state["minutes"]),
                percent_group(state["util_sum"] / state["days"]),
            ]
            if row_missing_groups(table_rows, [room_name], groups):
                mismatched_rooms.append(room_name)
        add(
            "P204",
            "问题二高负荷诊室表匹配最终排程的前六个诊室",
            len(table_rows) == 6 and not mismatched_rooms,
            f"表行数={len(table_rows)}；不匹配诊室={mismatched_rooms}",
            f"最终排程诊室数={len(aggregate)}",
            [paths["p2_room"], p2_room_table],
        )
    else:
        add("P204", "问题二高负荷诊室表匹配最终排程的前六个诊室", False, "表或CSV缺失", "未检查", [paths["p2_room"], p2_room_table])

    p3_text = main_tex + "\n" + body_texts["05_03_problem3.tex"]
    p3_selection: dict[str, object] | None = None
    if paths["p3_selection"].exists():
        p3_selection = json.loads(read_text(paths["p3_selection"]))
        selected = p3_selection["selected_metrics"]
        completed_background = selected.get(
            "background_completed_events", selected.get("background_on_planned_day")
        )
        groups = [
            alpha_group(p3_selection["selected_alpha"]),
            int_group(selected["inpatient_complete_48h"]),
            percent_group(selected["inpatient_48h_rate"]),
            int_group(completed_background),
            percent_group(selected["background_on_time_rate"]),
            decimal_group(selected["inpatient_wait_p50_hours_conditional"]),
            decimal_group(selected["inpatient_wait_p90_hours_conditional"]),
            decimal_group(selected["inpatient_wait_p95_hours_conditional"]),
            percent_group(selected["inpatient_room_switch_rate_multi"]),
        ]
        missing = missing_groups(p3_text, groups)
        add(
            "P301",
            "问题三摘要与正文推荐点指标匹配最终selection",
            not missing,
            f"缺失格式组={missing}",
            f"selected_alpha={p3_selection['selected_alpha']}；selected_metrics={selected}",
            [paths["p3_selection"]],
        )
        semantics_pass = (
            selected.get("daily_quota_used") is False
            and truthy(selected.get("epsilon_constraint_satisfied"))
            and "不设置逐日配额" in p3_text
            and "全评价期" in p3_text
        )
        add(
            "P302",
            "问题三论文与结果均采用全期epsilon约束且不使用逐日配额",
            semantics_pass,
            "正文含全评价期约束与不设置逐日配额",
            f"daily_quota_used={selected.get('daily_quota_used')}；epsilon_constraint_satisfied={selected.get('epsilon_constraint_satisfied')}",
            [paths["p3_selection"]],
        )
    else:
        add("P301", "问题三摘要与正文推荐点指标匹配最终selection", False, "未检查", "P3 selection缺失", [paths["p3_selection"]])
        add("P302", "问题三论文与结果均采用全期epsilon约束且不使用逐日配额", False, "未检查", "P3 selection缺失", [paths["p3_selection"]])

    p3_table = PAPER_DIR / "tables/p3_pareto.tex"
    if paths["p3_pareto"].exists() and p3_table.exists():
        pareto_rows = [
            row
            for row in csv_rows(paths["p3_pareto"])
            if truthy(row.get("epsilon_feasible")) and truthy(row.get("pareto_nondominated"))
        ]
        table_rows = table_body_rows(p3_table)
        missing_alphas: list[str] = []
        for row in pareto_rows:
            groups = [
                alpha_group(row["background_target_alpha"]),
                int_group(row["background_completed_events"]),
                percent_group(row["background_on_time_rate"]),
                int_group(row["inpatient_complete_48h"]),
                percent_group(row["inpatient_48h_rate"]),
                decimal_group(row["inpatient_wait_p90_hours_conditional"]),
            ]
            if row_missing_groups(
                table_rows,
                alpha_group(row["background_target_alpha"]),
                groups,
            ):
                missing_alphas.append(row["background_target_alpha"])
        actual_rows = table_body_row_count(p3_table)
        add(
            "P303",
            "问题三Pareto表逐行匹配可行非支配结果",
            actual_rows == len(pareto_rows) and not missing_alphas,
            f"表行数={actual_rows}；缺失alpha={missing_alphas}",
            f"可行非支配行数={len(pareto_rows)}",
            [paths["p3_pareto"], p3_table],
        )
    else:
        add("P303", "问题三Pareto表逐行匹配可行非支配结果", False, "表或CSV缺失", "未检查", [paths["p3_pareto"], p3_table])

    scenario_table = PAPER_DIR / "tables/scenario_operation.tex"
    p3_metrics_for_table = (
        p3_selection.get("selected_metrics", {})
        if isinstance(p3_selection, dict)
        else {}
    )
    required_scenario_fields = {
        "background_required_events",
        "background_completed_events",
        "scheduled_minutes",
        "staffed_capacity_utilization",
        "inpatient_wait_p95_hours_conditional",
        "inpatient_room_switch_rate_multi",
    }
    missing_scenario_fields = sorted(
        required_scenario_fields - set(p3_metrics_for_table)
    )
    if (
        p2_summary is not None
        and p3_selection is not None
        and scenario_table.exists()
        and not missing_scenario_fields
    ):
        p2_metrics = p2_summary["metrics"]
        p3_metrics = p3_metrics_for_table
        required = int(p3_metrics["background_required_events"])
        completed = int(p3_metrics["background_completed_events"])
        rows = table_body_rows(scenario_table)
        specifications = [
            (
                "排入检查分钟",
                [int_group(p2_metrics["scheduled_minutes"]), int_group(p3_metrics["scheduled_minutes"])],
            ),
            (
                "人员在岗容量利用率",
                [percent_group(p2_metrics["staffed_capacity_utilization"]), percent_group(p3_metrics["staffed_capacity_utilization"])],
            ),
            (
                "住院等待P95",
                [decimal_group(p2_metrics["inpatient_wait_p95_hours_conditional"]), decimal_group(p3_metrics["inpatient_wait_p95_hours_conditional"])],
            ),
            (
                "多项目需求跨室率",
                [percent_group(p2_metrics["inpatient_room_switch_rate_multi"]), percent_group(p3_metrics["inpatient_room_switch_rate_multi"])],
            ),
            ("背景全期下限/完成数", [[f"{required:,}/{completed:,}"]]),
        ]
        mismatched = [
            label for label, groups in specifications
            if row_missing_groups(rows, [label], groups)
        ]
        add(
            "P304",
            "P2与P3运行表现表匹配两份最终摘要且不使用逐日配额指标",
            len(rows) == 5
            and not mismatched
            and "日配额" not in read_text(scenario_table),
            f"表行数={len(rows)}；不匹配={mismatched}；含日配额={'日配额' in read_text(scenario_table)}",
            f"背景全期下限/完成数={required}/{completed}",
            [paths["p2_summary"], paths["p3_selection"], scenario_table],
        )
        scheduled_increase = (
            float(p3_metrics["scheduled_minutes"])
            / float(p2_metrics["scheduled_minutes"])
            - 1
        )
        operation_text = body_texts["05_03_problem3.tex"]
        operation_groups = [
            percent_group(scheduled_increase),
            percent_group(p2_metrics["staffed_capacity_utilization"]),
            percent_group(p3_metrics["staffed_capacity_utilization"]),
            decimal_group(p2_metrics["inpatient_wait_p95_hours_conditional"]),
            decimal_group(p3_metrics["inpatient_wait_p95_hours_conditional"]),
            percent_group(p3_metrics["inpatient_room_switch_rate_multi"]),
        ]
        operation_missing = missing_groups(operation_text, operation_groups)
        add(
            "P305",
            "问题三运行解释中的P2/P3变化量匹配最终结果",
            not operation_missing,
            f"缺失格式组={operation_missing}",
            f"排入分钟增幅={scheduled_increase}；P2={p2_metrics}；P3={p3_metrics}",
            [paths["p2_summary"], paths["p3_selection"]],
        )
    else:
        add(
            "P304",
            "P2与P3运行表现表匹配两份最终摘要且不使用逐日配额指标",
            False,
            f"表或结果缺失；P3缺失字段={missing_scenario_fields}",
            "未检查",
            [paths["p2_summary"], paths["p3_selection"], scenario_table],
        )
        add(
            "P305",
            "问题三运行解释中的P2/P3变化量匹配最终结果",
            False,
            f"结果缺失；P3缺失字段={missing_scenario_fields}",
            "未检查",
            [paths["p2_summary"], paths["p3_selection"]],
        )

    for check_id, result_key, table_name, label in [
        ("V201", "p2_exact", "exact_benchmark.tex", "P2精确对照"),
        ("V301", "p3_exact", "p3_exact_benchmark.tex", "P3精确对照"),
    ]:
        table_path = PAPER_DIR / "tables" / table_name
        if paths[result_key].exists() and table_path.exists():
            rows = csv_rows(paths[result_key])
            table_rows = table_body_row_count(table_path)
            rendered_rows = table_body_rows(table_path)
            statuses = sorted({row.get("solver_status", "") for row in rows})
            table_text = read_text(table_path)
            missing_statuses = [status for status in statuses if status not in table_text]
            required_headers = (
                [r"\makecell{求解器\\间隙}", r"\makecell{H至界\\差距}"]
                if result_key == "p3_exact"
                else []
            )
            missing_headers = [
                header for header in required_headers if header not in table_text
            ]
            case_labels = {
                "normal_weekday": "普通工作日",
                "peak_weekday": "高峰工作日",
                "weekend": "周末",
                "multi_project_peak": "多项目高峰",
                "bedside_peak": "床旁高峰",
                "obstetric_peak": "产科高峰",
                "ordinary_joint_n20": "普通联合",
                "background_peak_n40": "背景高峰",
                "inpatient_peak_n60": "住院高峰",
                "multi_project_peak_n40": "多项目高峰",
                "bedside_pressure_n20": "床旁压力",
                "obstetric_pressure_n40": "产科压力",
                "equipment_competition_n60": "设备竞争",
                "recommended_alpha_typical_n100": "推荐点典型窗",
            }
            mismatched_cases: list[str] = []
            for row in rows:
                if result_key == "p2_exact":
                    groups = [
                        int_group(row["event_count"]),
                        int_group(row["heuristic_complete"]),
                        decimal_group(row["best_bound"], 0),
                        [row["solver_status"]],
                        percent_group(row["heuristic_gap_to_bound"]),
                    ]
                    if row.get("exact_complete", ""):
                        groups.append(int_group(row["exact_complete"]))
                else:
                    groups = [
                        alpha_group(row["alpha"]),
                        int_group(row["event_count"]),
                        int_group(row["heuristic_background_complete"]),
                        int_group(row["exact_background_complete"]),
                        int_group(row["heuristic_inpatient_complete"]),
                        decimal_group(row["best_bound"], 0),
                        [row["solver_status"]],
                    ]
                    if row.get("exact_inpatient_incumbent", ""):
                        groups.append(int_group(row["exact_inpatient_incumbent"]))
                    if row.get("solver_relative_gap", ""):
                        groups.append(percent_group(row["solver_relative_gap"]))
                    if row.get("heuristic_gap_to_bound", ""):
                        groups.append(percent_group(row["heuristic_gap_to_bound"]))
                label_token = case_labels.get(row["case"], row["case"])
                if row_missing_groups(rendered_rows, [label_token], groups):
                    mismatched_cases.append(row["case"])
            add(
                check_id,
                f"{label}表逐行匹配最终CSV数值及求解状态",
                table_rows == len(rows)
                and not missing_statuses
                and not missing_headers
                and not mismatched_cases,
                f"表行数={table_rows}；缺失状态={missing_statuses}；"
                f"缺失表头={missing_headers}；不匹配场景={mismatched_cases}",
                f"CSV行数={len(rows)}；状态={statuses}",
                [paths[result_key], table_path],
            )
        else:
            add(check_id, f"{label}表逐行匹配最终CSV数值及求解状态", False, "表或CSV缺失", "未检查", [paths[result_key], table_path])

    validation_text = body_texts["06_validation.tex"]
    for check_id, result_key, problem_label in [
        ("V202", "p2_exact", "问题二"),
        ("V302", "p3_exact", "问题三"),
    ]:
        if paths[result_key].exists():
            rows = csv_rows(paths[result_key])
            max_gap = max(float(row["heuristic_gap_to_bound"]) for row in rows)
            optimal_count = sum(row["solver_status"] == "OPTIMAL" for row in rows)
            gap_token = percent_group(max_gap)[0]
            status_token = f"{optimal_count}/{len(rows)}"
            problem_position = validation_text.find(problem_label)
            evidence_window = (
                validation_text[problem_position : problem_position + 1800]
                if problem_position >= 0
                else ""
            )
            add(
                check_id,
                f"{problem_label}正文报告精确对照的最大保守差距和OPTIMAL场景数",
                gap_token in evidence_window and status_token in evidence_window,
                f"目标窗口含gap={gap_token in evidence_window}；含OPTIMAL计数={status_token in evidence_window}",
                f"最大heuristic_gap_to_bound={max_gap:.6f}；OPTIMAL={status_token}",
                [paths[result_key], PAPER_DIR / "sections/06_validation.tex"],
            )
        else:
            add(check_id, f"{problem_label}正文报告精确对照的最大保守差距和OPTIMAL场景数", False, "结果缺失", "未检查", [paths[result_key], PAPER_DIR / "sections/06_validation.tex"])

    if paths["p3_repair"].exists() and paths["p3_exact"].exists():
        repair_audit = json.loads(read_text(paths["p3_repair"]))
        exact_rows = csv_rows(paths["p3_exact"])
        baseline = next(
            (
                row for row in repair_audit.get("candidates", [])
                if row.get("construction_method") == "inpatient_first"
            ),
            {},
        )
        date = datetime.strptime(repair_audit["date"], "%Y-%m-%d")
        repair_groups = [
            [f"{date.year}年{date.month}月{date.day}日"],
            int_group(repair_audit["event_count"]),
            int_group(baseline.get("background_completed_events", -1)),
            int_group(repair_audit["required_background"]),
            int_group(repair_audit["selected_background_complete"]),
            int_group(repair_audit["selected_inpatient_complete"]),
        ]
        repair_missing = missing_groups(validation_text, repair_groups)
        exact_repair_count = sum(
            truthy(row.get("repair_triggered")) for row in exact_rows
        )
        repair_violations = repair_audit.get("validation_violations", {})
        repair_semantics = (
            repair_audit.get("repair_triggered") is True
            and repair_audit.get("selected_epsilon_satisfied") is True
            and int(repair_audit.get("validation_violation_count", -1)) == 0
            and len(repair_violations) == 14
            and all(int(value) == 0 for value in repair_violations.values())
            and repair_audit.get("repair_branch_optimality_claimed") is False
            and exact_repair_count == 0
            and "14项独立检查的违规数均为0" in validation_text
            and "不是修复分支的精确最优性证明" in validation_text
            and "没有触发全局缺口重构" in validation_text
        )
        add(
            "V303",
            "真实峰值日修复路径数值、零违规及最优性边界匹配当前审计",
            repair_semantics and not repair_missing,
            f"缺失格式组={repair_missing}；边界措辞匹配={repair_semantics}",
            f"date={repair_audit.get('date')}；baseline={baseline}; selected="
            f"{repair_audit.get('selected_background_complete')}/"
            f"{repair_audit.get('selected_inpatient_complete')}；"
            f"exact窗口触发修复数={exact_repair_count}",
            [paths["p3_repair"], paths["p3_exact"], PAPER_DIR / "sections/06_validation.tex"],
        )
    else:
        add(
            "V303",
            "真实峰值日修复路径数值、零违规及最优性边界匹配当前审计",
            False,
            "修复路径审计或P3精确CSV缺失",
            "未检查",
            [paths["p3_repair"], paths["p3_exact"], PAPER_DIR / "sections/06_validation.tex"],
        )

    if paths["p2_verify"].exists() and paths["p3_verify"].exists():
        verification = [
            json.loads(read_text(paths["p2_verify"])),
            json.loads(read_text(paths["p3_verify"])),
        ]
        groups = [int_group(report["schedule_rows"]) for report in verification]
        missing = missing_groups(validation_text, groups)
        all_zero = all(
            report.get("passed") is True
            and all(int(item["violation_count"]) == 0 for item in report["checks"].values())
            for report in verification
        )
        add(
            "V401",
            "P2/P3独立验证均为零违规且任务数写入正文",
            all_zero and not missing,
            f"缺失任务数组={missing}",
            f"passed={[report.get('passed') for report in verification]}；schedule_rows={[report['schedule_rows'] for report in verification]}",
            [paths["p2_verify"], paths["p3_verify"]],
        )
    else:
        add("V401", "P2/P3独立验证均为零违规且任务数写入正文", False, "未检查", "独立验证文件缺失", [paths["p2_verify"], paths["p3_verify"]])

    calibration_table = PAPER_DIR / "tables/calibration.tex"
    if paths["calibration"].exists() and calibration_table.exists():
        labels = {
            "C0_historical_report": "历史开单至报告",
            "C1_duration_only": "仅题给时长",
            "C2_standard_hours": "加入标准班次",
            "C3_doctor_capacity": "加入医生并发",
            "C4_project_capability": "加入项目设备能力",
            "C5_item_preparation": "加入项目级准备",
            "C6_joint_background": "加入门诊/体检竞争",
            "C7_formal_heuristic": "正式构造策略",
        }
        rows = csv_rows(paths["calibration"])
        rendered_rows = table_body_rows(calibration_table)
        mismatched: list[str] = []
        for row in rows:
            delta = (
                "--"
                if not row.get("change_from_previous_pp")
                else f"{float(row['change_from_previous_pp']):+.2f}"
            )
            groups = [
                [f"{int(float(row['completed'])):,}/{int(float(row['total'])):,}"],
                percent_group(row["rate"]),
                [delta],
            ]
            if row_missing_groups(rendered_rows, [labels[row["scenario"]]], groups):
                mismatched.append(row["scenario"])
        add(
            "V402",
            "现实校准表逐层匹配最终校准CSV",
            len(rendered_rows) == len(rows) == 8 and not mismatched,
            f"表行数={len(rendered_rows)}；不匹配层={mismatched}",
            f"CSV行数={len(rows)}",
            [paths["calibration"], calibration_table],
        )
        calibration_by_id = {row["scenario"]: row for row in rows}
        calibration_groups = [
            percent_group(calibration_by_id["C0_historical_report"]["rate"]),
            percent_group(calibration_by_id["C1_duration_only"]["rate"], 0),
            percent_group(calibration_by_id["C3_doctor_capacity"]["rate"], 0),
            percent_group(calibration_by_id["C4_project_capability"]["rate"]),
            percent_group(calibration_by_id["C5_item_preparation"]["rate"]),
            percent_group(calibration_by_id["C6_joint_background"]["rate"]),
            decimal_group(abs(float(calibration_by_id["C1_duration_only"]["change_from_previous_pp"]))),
            decimal_group(abs(float(calibration_by_id["C4_project_capability"]["change_from_previous_pp"]))),
            decimal_group(abs(float(calibration_by_id["C5_item_preparation"]["change_from_previous_pp"]))),
            decimal_group(abs(float(calibration_by_id["C6_joint_background"]["change_from_previous_pp"]))),
            decimal_group(float(calibration_by_id["C7_formal_heuristic"]["change_from_previous_pp"])),
        ]
        calibration_missing = missing_groups(validation_text, calibration_groups)
        calibration_ids_complete = set(calibration_by_id) == set(labels)
        calibration_semantics = (
            "C7仍为64.80\\%" in validation_text
            and "没有再次改变可行域" in validation_text
        )
        add(
            "V405",
            "现实校准C0--C7关键完成率、相邻变化及C7语义匹配最终结果",
            calibration_ids_complete and not calibration_missing and calibration_semantics,
            f"层级齐全={calibration_ids_complete}；缺失格式组={calibration_missing}；"
            f"C7语义匹配={calibration_semantics}",
            f"C0--C7={[(scenario, calibration_by_id[scenario]['rate'], calibration_by_id[scenario].get('change_from_previous_pp')) for scenario in labels]}",
            [paths["calibration"], PAPER_DIR / "sections/06_validation.tex"],
        )
    else:
        add("V402", "现实校准表逐层匹配最终校准CSV", False, "表或CSV缺失", "未检查", [paths["calibration"], calibration_table])
        add("V405", "现实校准C0--C7关键完成率、相邻变化及C7语义匹配最终结果", False, "表或CSV缺失", "未检查", [paths["calibration"], PAPER_DIR / "sections/06_validation.tex"])

    sensitivity_table = PAPER_DIR / "tables/sensitivity_metrics.tex"
    if paths["sensitivity"].exists() and paths["preparation"].exists() and sensitivity_table.exists():
        labels = {
            "preparation_item": "主设定：项目级准备",
            "preparation_event": "事件级准备",
            "doctor_low": "医生容量下四分位",
            "capability_AB": "仅直接/语义匹配",
            "bladder45": "憋尿45分钟",
            "bladder90": "憋尿90分钟",
            "transfer5": "跨室5分钟",
            "transfer15": "跨室15分钟",
        }
        result_rows = [
            row for row in csv_rows(paths["sensitivity"]) if row["audit_scenario"] in labels
        ]
        rendered_rows = table_body_rows(sensitivity_table)
        mismatched: list[str] = []
        for row in result_rows:
            groups = [
                percent_group(row["inpatient_48h_rate"]),
                percent_group(row["background_on_time_rate"]),
                decimal_group(row["inpatient_wait_p90_hours_conditional"]),
                ["是" if truthy(row["epsilon_constraint_satisfied"]) else "否"],
                int_group(row["background_deficit_events"]),
                int_group(row["scheduled_minutes"]),
            ]
            if row_missing_groups(rendered_rows, [labels[row["audit_scenario"]]], groups):
                mismatched.append(row["audit_scenario"])
        add(
            "V403",
            "八个单因素灵敏度情景逐行匹配最终结果",
            len(rendered_rows) == len(result_rows) == 8 and not mismatched,
            f"表行数={len(rendered_rows)}；不匹配情景={mismatched}",
            f"目标结果行数={len(result_rows)}",
            [paths["sensitivity"], sensitivity_table],
        )
        sensitivity_by_id = {row["audit_scenario"]: row for row in result_rows}
        preparation_rows = csv_rows(paths["preparation"])
        preparation_by_id = {
            row["audit_scenario"]: row for row in preparation_rows
        }
        preparation_columns = [
            "inpatient_48h_rate",
            "background_on_time_rate",
            "inpatient_wait_p90_hours_conditional",
            "background_required_events",
            "background_completed_events",
            "background_deficit_events",
        ]
        preparation_matches = (
            set(preparation_by_id) == {"preparation_item", "preparation_event"}
            and all(
                abs(
                    float(preparation_by_id[name][column])
                    - float(sensitivity_by_id[name][column])
                ) <= 1e-12
                for name in preparation_by_id
                for column in preparation_columns
            )
            and all(
                truthy(preparation_by_id[name]["epsilon_constraint_satisfied"])
                == truthy(sensitivity_by_id[name]["epsilon_constraint_satisfied"])
                for name in preparation_by_id
            )
        )
        main_sensitivity = sensitivity_by_id["preparation_item"]
        boundary_rows = [
            sensitivity_by_id[name]
            for name in ["bladder45", "bladder90", "transfer5", "transfer15"]
        ]
        maximum_boundary_change_pp = 100 * max(
            abs(float(row[column]) - float(main_sensitivity[column]))
            for row in boundary_rows
            for column in ["inpatient_48h_rate", "background_on_time_rate"]
        )
        sensitivity_groups = [
            percent_group(sensitivity_by_id["doctor_low"]["inpatient_48h_rate"]),
            percent_group(sensitivity_by_id["doctor_low"]["background_on_time_rate"]),
            percent_group(sensitivity_by_id["capability_AB"]["inpatient_48h_rate"]),
            percent_group(sensitivity_by_id["capability_AB"]["background_on_time_rate"]),
            decimal_group(maximum_boundary_change_pp),
        ]
        sensitivity_missing = missing_groups(validation_text, sensitivity_groups)
        all_sensitivity_epsilon = all(
            truthy(row["epsilon_constraint_satisfied"]) for row in result_rows
        )
        all_sensitivity_deficits_zero = all(
            int(round(float(row["background_deficit_events"]))) == 0
            for row in result_rows
        )
        sensitivity_status_in_prose = (
            "八个单因素情景均满足" in validation_text
            and "达标数为8/8" in validation_text
            and "背景缺口均为0" in validation_text
        )
        add(
            "V406",
            "灵敏度正文、准备粒度文件及全部epsilon状态匹配最终结果",
            not sensitivity_missing
            and preparation_matches
            and all_sensitivity_epsilon
            and all_sensitivity_deficits_zero
            and sensitivity_status_in_prose,
            f"缺失格式组={sensitivity_missing}；准备文件匹配={preparation_matches}；"
            f"全达标={all_sensitivity_epsilon}；全零缺口={all_sensitivity_deficits_zero}；"
            f"正文状态匹配={sensitivity_status_in_prose}",
            f"doctor_low={sensitivity_by_id['doctor_low']}；capability_AB={sensitivity_by_id['capability_AB']}；"
            f"最大憋尿/转运变化={maximum_boundary_change_pp:.6f}个百分点",
            [paths["sensitivity"], paths["preparation"], PAPER_DIR / "sections/06_validation.tex"],
        )
    else:
        add("V403", "八个单因素灵敏度情景逐行匹配最终结果", False, "表或CSV缺失", "未检查", [paths["sensitivity"], paths["preparation"], sensitivity_table])
        add("V406", "灵敏度正文、准备粒度文件及全部epsilon状态匹配最终结果", False, "表或CSV缺失", "未检查", [paths["sensitivity"], paths["preparation"], PAPER_DIR / "sections/06_validation.tex"])

    seed_table = PAPER_DIR / "tables/seed_robustness.tex"
    if paths["sensitivity"].exists() and paths["seed"].exists() and seed_table.exists():
        seed_rows = [
            row for row in csv_rows(paths["sensitivity"])
            if row["audit_scenario"].startswith("seed_")
        ]
        rendered_rows = table_body_rows(seed_table)
        specifications = [
            ("住院48小时率", "inpatient_48h_rate", "rate"),
            ("背景服务率", "background_on_time_rate", "rate"),
            ("等待P90/小时", "inpatient_wait_p90_hours_conditional", "decimal"),
            ("排入分钟", "scheduled_minutes", "integer"),
        ]
        mismatched: list[str] = []
        for label, column, kind in specifications:
            values = [float(row[column]) for row in seed_rows]
            summary = [
                statistics.mean(values),
                statistics.stdev(values),
                min(values),
                max(values),
            ]
            if kind == "rate":
                groups = [
                    [f"{100 * summary[0]:.4f}\\%"],
                    [f"{100 * summary[1]:.4f}个百分点"],
                    [f"{100 * summary[2]:.4f}\\%"],
                    [f"{100 * summary[3]:.4f}\\%"],
                ]
            elif kind == "integer":
                groups = [[f"{value:,.0f}"] for value in summary]
            else:
                groups = [[f"{value:.2f}"] for value in summary]
            if row_missing_groups(rendered_rows, [label], groups):
                mismatched.append(label)
        add(
            "V404",
            "五随机种子统计表由最终种子情景重新汇总",
            len(seed_rows) == 5 and len(rendered_rows) == 4 and not mismatched,
            f"种子数={len(seed_rows)}；表行数={len(rendered_rows)}；不匹配={mismatched}",
            "均值、样本标准差、最小值和最大值由五个seed行计算",
            [paths["sensitivity"], seed_table],
        )
        inpatient_rates = [float(row["inpatient_48h_rate"]) for row in seed_rows]
        background_rates = [float(row["background_on_time_rate"]) for row in seed_rows]
        waiting_p90 = [
            float(row["inpatient_wait_p90_hours_conditional"])
            for row in seed_rows
        ]
        seed_prose_groups = [
            [f"{100 * statistics.stdev(inpatient_rates):.4f}"],
            [f"{100 * statistics.stdev(background_rates):.4f}"],
            decimal_group(min(waiting_p90)),
            decimal_group(max(waiting_p90)),
        ]
        seed_prose_missing = missing_groups(validation_text, seed_prose_groups)
        seed_summary = json.loads(read_text(paths["seed"]))
        seed_summary_matches = (
            int(seed_summary.get("seed_count", -1)) == len(seed_rows) == 5
            and sorted(seed_summary.get("seed_scenarios", []))
            == sorted(row["audit_scenario"] for row in seed_rows)
            and all(
                abs(
                    float(seed_summary[column][stat]) - expected
                ) <= 1e-12
                for column, values in [
                    ("inpatient_48h_rate", inpatient_rates),
                    ("background_on_time_rate", background_rates),
                ]
                for stat, expected in [
                    ("mean", statistics.mean(values)),
                    ("std", statistics.stdev(values)),
                    ("min", min(values)),
                    ("max", max(values)),
                ]
            )
        )
        all_seed_epsilon = all(
            truthy(row["epsilon_constraint_satisfied"]) for row in seed_rows
        )
        all_seed_deficits_zero = all(
            int(round(float(row["background_deficit_events"]))) == 0
            for row in seed_rows
        )
        seed_status_in_prose = (
            "五次运行均满足" in validation_text
            and "达标数为5/5" in validation_text
            and "背景缺口均为0" in validation_text
        )
        add(
            "V407",
            "多随机种子正文、汇总JSON及全部epsilon状态匹配最终结果",
            len(seed_rows) == 5
            and not seed_prose_missing
            and seed_summary_matches
            and all_seed_epsilon
            and all_seed_deficits_zero
            and seed_status_in_prose,
            f"缺失格式组={seed_prose_missing}；汇总JSON匹配={seed_summary_matches}；"
            f"全达标={all_seed_epsilon}；全零缺口={all_seed_deficits_zero}；"
            f"正文状态匹配={seed_status_in_prose}",
            f"住院/背景样本标准差={statistics.stdev(inpatient_rates)}/{statistics.stdev(background_rates)}；"
            f"P90范围={min(waiting_p90)}--{max(waiting_p90)}",
            [paths["sensitivity"], paths["seed"], PAPER_DIR / "sections/06_validation.tex"],
        )
    else:
        add("V404", "五随机种子统计表由最终种子情景重新汇总", False, "表或CSV缺失", "未检查", [paths["sensitivity"], paths["seed"], seed_table])
        add("V407", "多随机种子正文、汇总JSON及全部epsilon状态匹配最终结果", False, "表或CSV缺失", "未检查", [paths["sensitivity"], paths["seed"], PAPER_DIR / "sections/06_validation.tex"])

    freshness_pairs = [
        (paths["events"], PAPER_DIR / "tables/data_scope.tex"),
        (paths["items"], PAPER_DIR / "tables/data_scope.tex"),
        (paths["p1_duration"], PAPER_DIR / "tables/duration_parameters.tex"),
        (paths["capability_summary"], PAPER_DIR / "tables/capability_evidence.tex"),
        (paths["items"], PAPER_DIR / "tables/capability_evidence.tex"),
        (paths["p1_peak"], PAPER_DIR / "tables/peak_configuration.tex"),
        (paths["p1_daily"], PAPER_DIR / "tables/peak_configuration.tex"),
        (paths["doctor_capacity"], PAPER_DIR / "tables/peak_configuration.tex"),
        (paths["p1_forecast"], PAPER_DIR / "tables/forecast_comparison.tex"),
        (paths["p1_department"], PAPER_DIR / "tables/p1_structure.tex"),
        (paths["p1_multi"], PAPER_DIR / "tables/p1_structure.tex"),
        (paths["p2_policy"], p2_table),
        (paths["p2_failure"], p2_failure_table),
        (paths["p2_summary"], p2_failure_table),
        (paths["p2_room"], p2_room_table),
        (paths["p3_pareto"], p3_table),
        (paths["p2_summary"], scenario_table),
        (paths["p3_selection"], scenario_table),
        (paths["p2_exact"], PAPER_DIR / "tables/exact_benchmark.tex"),
        (paths["p3_exact"], PAPER_DIR / "tables/p3_exact_benchmark.tex"),
        (paths["p2_verify"], PAPER_DIR / "tables/verification.tex"),
        (paths["p3_verify"], PAPER_DIR / "tables/verification.tex"),
        (paths["calibration"], PAPER_DIR / "tables/calibration.tex"),
        (paths["sensitivity"], PAPER_DIR / "tables/sensitivity_metrics.tex"),
        (paths["seed"], PAPER_DIR / "tables/seed_robustness.tex"),
        (paths["sensitivity"], PAPER_DIR / "tables/seed_robustness.tex"),
        (paths["p2_recommendation"], PAPER_DIR / "tables/recommendation_sample.tex"),
    ]
    stale_tables = [
        str(table.relative_to(ROOT)).replace("\\", "/")
        for source, table in freshness_pairs
        if not source.exists() or not table.exists() or table.stat().st_mtime < source.stat().st_mtime
    ]
    add(
        "T501",
        "论文关键结果表均在对应最终结果之后重新生成",
        not stale_tables,
        f"过期或缺失表={stale_tables}",
        "按文件修改时间核对结果到表格的生成顺序，不使用哈希自证",
        [path for pair in freshness_pairs for path in pair],
    )

    figure_dir = ROOT / "supporting_materials/figures/paper_final"
    figure_pairs = [
        (paths["p1_monthly"], figure_dir / "fig01_monthly_demand.pdf"),
        (paths["doctor_capacity"], figure_dir / "fig02_doctor_capacity.pdf"),
        (paths["capability_summary"], figure_dir / "fig03_capability_coverage.pdf"),
        (paths["items"], figure_dir / "fig03_capability_coverage.pdf"),
        (paths["events"], figure_dir / "fig03_capability_coverage.pdf"),
        (paths["p2_policy"], figure_dir / "fig04_p2_policy.pdf"),
        (paths["p3_pareto"], figure_dir / "fig05_pareto.pdf"),
        (paths["p3_selection"], figure_dir / "fig05_pareto.pdf"),
        (paths["calibration"], figure_dir / "fig06_calibration.pdf"),
        (paths["sensitivity"], figure_dir / "fig07_sensitivity.pdf"),
        (paths["p3_daily"], figure_dir / "fig08_daily_performance.pdf"),
        (paths["p3_schedule"], figure_dir / "fig09_representative_gantt.pdf"),
    ]
    stale_figures = [
        str(figure.relative_to(ROOT)).replace("\\", "/")
        for source, figure in figure_pairs
        if not source.exists()
        or not figure.exists()
        or figure.stat().st_mtime < source.stat().st_mtime
    ]
    add(
        "T502",
        "论文结果图均在对应最终结果之后重新生成",
        not stale_figures,
        f"过期或缺失图={sorted(set(stale_figures))}",
        "按文件修改时间核对结果到图的生成顺序，不重复计算哈希",
        [path for pair in figure_pairs for path in pair],
    )

    passed = all(bool(check["passed"]) for check in checks)
    failed_ids = [str(check["id"]) for check in checks if not check["passed"]]
    payload: dict[str, object] = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": passed,
        "checks": checks,
        "failed_check_ids": failed_ids,
        "authoritative_inputs": {
            name: str(path.relative_to(ROOT)).replace("\\", "/")
            for name, path in paths.items()
        },
    }
    CONSISTENCY_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONSISTENCY_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 模型—代码—结果—论文最终一致性审计",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 检查数：{len(checks)}",
        f"- 失败项：{len(failed_ids)}",
        f"- `MODEL_RESULT_FINAL_CONSISTENCY = {'TRUE' if passed else 'FALSE'}`",
        "",
        "| ID | 结果 | 检查内容 | 论文证据 | 结果证据 |",
        "|---|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['id']} | {'PASS' if check['passed'] else 'FAIL'} | "
            f"{markdown_cell(str(check['requirement']))} | "
            f"{markdown_cell(str(check['paper_evidence']))} | "
            f"{markdown_cell(str(check['result_evidence']))} |"
        )
    lines.extend(["", "## 当前失败项", ""])
    if failed_ids:
        for check in checks:
            if not check["passed"]:
                lines.append(f"- `{check['id']}` {check['requirement']}")
    else:
        lines.append("- 无。")
    CONSISTENCY_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return payload


def marker_is_true(path: Path, marker: str) -> bool:
    if not path.exists():
        return False
    pattern = (
        rf"(?mi)^\s*(?:[-*]\s*)?`?{re.escape(marker)}\s*=\s*TRUE`?[。.]?\s*$"
    )
    return re.search(pattern, read_text(path)) is not None


def write_structure_report(
    checks: list[AssertionResult],
    body_pages: int | None,
    total_pages: int | None,
    section_names: list[str],
    assumption_numbers: list[int],
    symbol_rows: int,
    chapter6_subsections: list[str],
    chapter7_subsections: list[str],
    chapter8_subsections: list[str],
    chinese_refs: int,
    english_refs: int,
    appendix_sections: list[str],
) -> bool:
    structure_ids = {
        "A01", "A02", "S01", "S02", "S03", "S04", "S05", "S06",
        "S07", "S08", "S09", "S10", "S11", "S12", "S13", "S14",
        "S15", "S16", "A03", "A04", "F01", "T01", "R01", "R02",
        "R03", "N01", "L01", "L02", "L03", "L04", "C01", "C02",
        "P01", "P02", "P03", "P04", "P05", "P06",
    }
    selected = [check for check in checks if check.check_id in structure_ids]
    failed = [check for check in selected if not check.passed]
    passed = not failed
    lines = [
        "# 论文章节与版式结构机器审计",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 一级章节：{'；'.join(section_names)}",
        f"- 模型假设：{len(assumption_numbers)}条，编号={assumption_numbers}",
        f"- 符号表：{symbol_rows}行",
        f"- 第六章二级标题：{'；'.join(chapter6_subsections)}",
        f"- 第七章二级标题：{'；'.join(chapter7_subsections)}",
        f"- 第八章二级标题：{'；'.join(chapter8_subsections)}",
        f"- 参考文献：中文{chinese_refs}篇、英文{english_refs}篇",
        f"- 附录：{len(appendix_sections)}节（A--F）",
        f"- 正文页数：{body_pages if body_pages is not None else '未取得'}页；参考文献和附录不计入30页上限",
        f"- PDF总页数：{total_pages if total_pages is not None else '未取得'}页",
        f"- `PAPER_STRUCTURE_AUDIT = {'TRUE' if passed else 'FALSE'}`",
        "",
        "## 机器证据",
        "",
        "| ID | 结果 | 条件 | 实际证据 |",
        "|---|---|---|---|",
    ]
    for check in selected:
        lines.append(
            f"| {check.check_id} | {'PASS' if check.passed else 'FAIL'} | "
            f"{markdown_cell(check.requirement)} | {markdown_cell(check.evidence)} |"
        )
    lines.extend(["", "## 当前失败项", ""])
    if failed:
        lines.extend(f"- `{check.check_id}` {check.requirement}" for check in failed)
    else:
        lines.append("- 无。")
    STRUCTURE_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return passed


def write_final_qa_report(
    consistency: dict[str, object],
    body_pages: int | None,
    total_pages: int | None,
) -> bool:
    checks: list[dict[str, object]] = []

    def add(check_id: str, requirement: str, passed: bool, evidence: str) -> None:
        checks.append(
            {
                "id": check_id,
                "requirement": requirement,
                "passed": bool(passed),
                "evidence": evidence,
            }
        )

    manifest: dict[str, object] | None = None
    manifest_error = ""
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(read_text(MANIFEST_PATH))
        except (json.JSONDecodeError, OSError) as exc:
            manifest_error = str(exc)
    else:
        manifest_error = "文件不存在"

    add(
        "Q01",
        "最终结果清单存在且可解析",
        manifest is not None,
        f"路径={MANIFEST_PATH.relative_to(ROOT)}；错误={manifest_error or '无'}",
    )

    manifest_frozen = bool(
        manifest and manifest.get("MODEL_AND_RESULTS_FROZEN") is True
    )
    freeze_checks = manifest.get("freeze_checks", {}) if manifest else {}
    if not isinstance(freeze_checks, dict):
        freeze_checks = {}
    required_freeze_checks = {
        "train_holdout_no_leakage",
        "all_50_fallback_reviewed",
        "no_blanket_category_fallback",
        "bedside_semantics_passed",
        "input_semantics_passed",
        "p2_pure_inpatient_scenario",
        "p2_policy_selection_matches_code",
        "p2_slack_definition_matches_code",
        "p2_exact_implementation_equivalent",
        "p2_high_load_benchmark_passed",
        "p2_capability_failure_decomposed",
        "p3_global_epsilon_semantics_passed",
        "p3_no_daily_quota",
        "p3_alpha_grid_dense",
        "p3_local_refinement_completed",
        "p3_exact_benchmark_exists",
        "p3_repair_path_audit_passed",
        "p2_p3_kernel_equivalent",
        "p2_schedule_verification_passed",
        "p3_schedule_verification_passed",
        "historical_calibration_exists",
        "preparation_sensitivity_exists",
        "sensitivity_scenarios_complete",
        "multi_seed_exists",
        "paper_numbers_match_final_results",
        "authoritative_result_unique",
        "all_authoritative_files_present",
    }
    missing_freeze_checks = sorted(required_freeze_checks - set(freeze_checks))
    false_freeze_checks = sorted(
        str(key) for key, value in freeze_checks.items() if value is not True
    )
    freeze_conditions_pass = (
        manifest_frozen
        and not missing_freeze_checks
        and not false_freeze_checks
    )
    add(
        "Q02",
        "技术结果清单明确冻结且其中全部冻结条件为真",
        freeze_conditions_pass,
        f"MODEL_AND_RESULTS_FROZEN={manifest_frozen}；冻结条件数={len(freeze_checks)}；"
        f"缺失条件={missing_freeze_checks}；非真条件={false_freeze_checks}",
    )
    paper_freeze = freeze_checks.get("paper_numbers_match_final_results") is True
    add(
        "Q03",
        "最终清单单列确认论文全部数值匹配新结果",
        paper_freeze,
        "freeze_checks.paper_numbers_match_final_results="
        f"{freeze_checks.get('paper_numbers_match_final_results')}",
    )

    hard_pass = marker_is_true(REPORT_PATH, "PAPER_HARD_ACCEPTANCE")
    add(
        "Q04",
        "本轮论文机器硬验收全部通过",
        hard_pass,
        f"{REPORT_PATH.relative_to(ROOT)}中的PAPER_HARD_ACCEPTANCE={hard_pass}",
    )
    consistency_pass = consistency.get("passed") is True and marker_is_true(
        CONSISTENCY_REPORT_PATH, "MODEL_RESULT_FINAL_CONSISTENCY"
    )
    add(
        "Q05",
        "本轮模型—代码—结果—论文一致性检查全部通过",
        consistency_pass,
        f"JSON passed={consistency.get('passed')}；"
        f"失败项={consistency.get('failed_check_ids', [])}",
    )

    technical_pass = marker_is_true(
        TECHNICAL_AUDIT_PATH, "MODEL_AND_RESULTS_FROZEN"
    )
    add(
        "Q06",
        "第二阶段最终技术审计明确给出冻结结论",
        technical_pass,
        f"路径={TECHNICAL_AUDIT_PATH.relative_to(ROOT)}；"
        f"MODEL_AND_RESULTS_FROZEN={technical_pass}",
    )
    technical_frozen = freeze_conditions_pass and technical_pass
    visual_pass = marker_is_true(VISUAL_REPORT_PATH, "PAPER_VISUAL_INSPECTION")
    add(
        "Q07",
        "最终PDF已逐页渲染并完成视觉检查",
        visual_pass,
        f"路径={VISUAL_REPORT_PATH.relative_to(ROOT)}；"
        f"PAPER_VISUAL_INSPECTION={visual_pass}",
    )
    add(
        "Q08",
        "最终PDF存在、页数可读取且正文不超过30页",
        FINAL_PDF.exists()
        and total_pages is not None
        and body_pages is not None
        and body_pages <= 30,
        f"PDF存在={FINAL_PDF.exists()}；正文={body_pages}页；总页数={total_pages}页",
    )

    required_reports = [
        TECHNICAL_AUDIT_PATH,
        ROOT / "P3_EPSILON_MODEL_ALGORITHM_AUDIT.md",
        ROOT / "P2_EXACT_IMPLEMENTATION_EQUIVALENCE_AUDIT.md",
        ROOT / "P2_CAPABILITY_FAILURE_DECOMPOSITION.md",
        ROOT / "BED7_SEMANTIC_CAPABILITY_FINAL_AUDIT.md",
        ROOT / "P2_P3_KERNEL_EQUIVALENCE_AUDIT.md",
        ROOT / "P3_EXACT_VS_HEURISTIC_REPORT.md",
        CONSISTENCY_REPORT_PATH,
        STRUCTURE_REPORT_PATH,
        REPORT_PATH,
    ]
    missing_reports = [
        str(path.relative_to(ROOT)).replace("\\", "/")
        for path in required_reports
        if not path.exists()
    ]
    add(
        "Q09",
        "第二阶段十份前置审计与验收报告均已重新生成",
        not missing_reports,
        f"缺失={missing_reports}",
    )

    p3_manifest = manifest.get("p3", {}) if manifest else {}
    selected_metrics = (
        p3_manifest.get("selected_metrics", {})
        if isinstance(p3_manifest, dict)
        else {}
    )
    p3_semantics = (
        isinstance(p3_manifest, dict)
        and isinstance(selected_metrics, dict)
        and p3_manifest.get("daily_quota_used") is False
        and selected_metrics.get("daily_quota_used") is False
        and truthy(selected_metrics.get("epsilon_constraint_satisfied"))
    )
    add(
        "Q10",
        "最终清单中的P3为全期epsilon约束且未使用逐日配额",
        p3_semantics,
        f"p3.daily_quota_used={p3_manifest.get('daily_quota_used') if isinstance(p3_manifest, dict) else None}；"
        f"selected.daily_quota_used={selected_metrics.get('daily_quota_used') if isinstance(selected_metrics, dict) else None}；"
        f"epsilon_constraint_satisfied={selected_metrics.get('epsilon_constraint_satisfied') if isinstance(selected_metrics, dict) else None}",
    )

    passed = all(bool(check["passed"]) for check in checks)
    failed = [check for check in checks if not check["passed"]]
    lines = [
        "# 第二阶段最终综合验收报告",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 技术冻结：{'TRUE' if technical_frozen else 'FALSE'}",
        f"- 论文硬验收：{'TRUE' if hard_pass else 'FALSE'}",
        f"- 结果—论文一致性：{'TRUE' if consistency_pass else 'FALSE'}",
        f"- PDF视觉检查：{'TRUE' if visual_pass else 'FALSE'}",
        f"- 正文页数：{body_pages if body_pages is not None else '未取得'}页；PDF总页数：{total_pages if total_pages is not None else '未取得'}页",
        f"- `FINAL_QA_ACCEPTANCE = {'TRUE' if passed else 'FALSE'}`",
        "",
        "## 逐项结论",
        "",
        "| ID | 结果 | 条件 | 实际证据 |",
        "|---|---|---|---|",
    ]
    for check in checks:
        lines.append(
            f"| {check['id']} | {'PASS' if check['passed'] else 'FAIL'} | "
            f"{markdown_cell(str(check['requirement']))} | "
            f"{markdown_cell(str(check['evidence']))} |"
        )
    lines.extend(["", "## 当前阻断项", ""])
    if failed:
        lines.extend(f"- `{check['id']}` {check['requirement']}" for check in failed)
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "## 判定边界",
            "",
            "本报告不继承旧版PASS。技术结果、结果—论文一致性、LaTeX/PDF硬验收和逐页视觉检查四部分必须同时为真，最终综合验收才为真。清单中的哈希不作为本报告的重复验收手段。",
            "",
        ]
    )
    FINAL_QA_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINAL_QA_PATH.write_text("\n".join(lines), encoding="utf-8")
    return passed


def main() -> int:
    checks: list[AssertionResult] = []

    def add(check_id: str, requirement: str, passed: bool, evidence: str) -> None:
        checks.append(AssertionResult(check_id, requirement, bool(passed), evidence))

    main_tex = read_text(MAIN_TEX)
    body_texts = {path.name: read_text(path) for path in BODY_FILES}
    appendix_text = read_text(APPENDIX_FILE)
    full_body = "\n".join([main_tex, *body_texts.values()])
    full_paper_source = full_body + "\n" + appendix_text

    build_log = ""
    aux_text = ""
    compile_outputs: list[str] = []
    xelatex = find_xelatex()
    pass_codes: list[int] = []

    if xelatex:
        with tempfile.TemporaryDirectory(prefix="paper_hard_acceptance_") as temp_name:
            temp_dir = Path(temp_name)
            command = [
                xelatex,
                "-interaction=nonstopmode",
                "-file-line-error",
                "-halt-on-error",
                f"-output-directory={temp_dir}",
                MAIN_TEX.name,
            ]
            for _ in range(2):
                result = run_command(command, PAPER_DIR)
                pass_codes.append(result.returncode)
                compile_outputs.append(result.stdout[-4000:])
                if result.returncode != 0:
                    break
            log_path = temp_dir / "main.log"
            aux_path = temp_dir / "main.aux"
            built_pdf = temp_dir / "main.pdf"
            if log_path.exists():
                build_log = read_text(log_path)
            if aux_path.exists():
                aux_text = read_text(aux_path)
            if len(pass_codes) == 2 and pass_codes == [0, 0] and built_pdf.exists():
                shutil.copy2(built_pdf, FINAL_PDF)

    add(
        "A01",
        "XeLaTeX连续编译两遍且两遍均成功",
        pass_codes == [0, 0],
        f"xelatex={xelatex or 'MISSING'}；return_codes={pass_codes}",
    )
    latex_errors = [
        line.strip()
        for line in build_log.splitlines()
        if line.startswith("!") or "LaTeX Error" in line
    ]
    add(
        "A02",
        "编译日志无LaTeX错误",
        bool(build_log) and not latex_errors,
        "未发现LaTeX错误" if build_log and not latex_errors else "; ".join(latex_errors[:5]),
    )

    section_names: list[str] = []
    for path in BODY_FILES:
        section_names.extend(re.findall(r"\\section\{([^{}]+)\}", body_texts[path.name]))
    add(
        "S01",
        "一级章节恰好为规定的九章且顺序正确",
        section_names == EXPECTED_SECTIONS,
        f"实际={section_names}",
    )
    add(
        "S02",
        "源码不生成目录",
        "\\tableofcontents" not in full_paper_source,
        "未发现\\tableofcontents" if "\\tableofcontents" not in full_paper_source else "发现\\tableofcontents",
    )
    add(
        "S03",
        "不存在独立结论章",
        not any("结论" in title for title in section_names),
        f"一级章节={section_names}",
    )

    chapter1_subsections = tex_subsections(body_texts["01_problem.tex"])
    add(
        "S04",
        "第一章二级标题恰好为问题背景、问题重述",
        chapter1_subsections == ["问题背景", "问题重述"],
        f"实际={chapter1_subsections}",
    )

    assumptions_text = body_texts["03_assumptions.tex"]
    assumption_matches = re.findall(r"(?m)^\s*(\d+)、假设[^\n]+", assumptions_text)
    assumption_numbers = [int(value) for value in assumption_matches]
    add(
        "S05",
        "模型假设条数为5至10条",
        5 <= len(assumption_numbers) <= 10,
        f"实际条数={len(assumption_numbers)}",
    )
    add(
        "S06",
        "每条假设均为连续的数字、假设格式",
        assumption_numbers == list(range(1, len(assumption_numbers) + 1)),
        f"实际编号={assumption_numbers}",
    )
    forbidden_assumption = re.findall(
        r"(?m)^\s*(?:A[12]\b|假设[一二三四五六七八九十]+)", assumptions_text
    )
    add(
        "S07",
        "假设中不出现A1/A2或假设一/假设二格式",
        not forbidden_assumption,
        f"命中={forbidden_assumption}",
    )

    symbols_text = body_texts["04_symbols.tex"]
    symbol_block_match = re.search(
        r"\\midrule(?P<body>.*?)\\bottomrule", symbols_text, flags=re.DOTALL
    )
    symbol_rows = 0
    if symbol_block_match:
        symbol_rows = len(re.findall(r"\\\\\s*$", symbol_block_match.group("body"), re.MULTILINE))
    add(
        "S08",
        "符号表包含20至28个主要符号",
        20 <= symbol_rows <= 28,
        f"实际符号行数={symbol_rows}",
    )

    chapter5_subsections = []
    for name in ["05_01_problem1.tex", "05_02_problem2.tex", "05_03_problem3.tex"]:
        chapter5_subsections.extend(tex_subsections(body_texts[name]))
    expected_chapter5 = [
        "问题一模型的建立与求解",
        "问题二模型的建立与求解",
        "问题三模型的建立与求解",
    ]
    add(
        "S09",
        "第五章只含三个规定的二级标题",
        chapter5_subsections == expected_chapter5,
        f"实际={chapter5_subsections}",
    )

    chapter6_text = body_texts["06_validation.tex"]
    chapter6_subsections = tex_subsections(chapter6_text)
    expected_chapter6 = [
        "需求预测模型检验",
        "调度模型有效性检验",
        "灵敏度分析",
        "稳健性分析",
    ]
    add(
        "S10",
        "第六章保持3至4节并覆盖预测、调度、灵敏度和稳健性",
        chapter6_subsections == expected_chapter6,
        f"实际={chapter6_subsections}",
    )
    p3_exact_table = PAPER_DIR / "tables/p3_exact_benchmark.tex"
    add(
        "S11",
        "第六章调度有效性同时包含P2精确对照、P3精确对照、独立验证和现实校准",
        all(
            token in chapter6_text
            for token in [
                "tables/exact_benchmark.tex",
                "tables/p3_exact_benchmark.tex",
                "tables/verification.tex",
                "tables/calibration.tex",
            ]
        )
        and p3_exact_table.exists(),
        f"P3精确表存在={p3_exact_table.exists()}；四类证据引用="
        + str(
            [
                token
                for token in [
                    "tables/exact_benchmark.tex",
                    "tables/p3_exact_benchmark.tex",
                    "tables/verification.tex",
                    "tables/calibration.tex",
                ]
                if token in chapter6_text
            ]
        ),
    )

    chapter7_subsections = tex_subsections(body_texts["07_evaluation.tex"])
    add(
        "S12",
        "第七章二级标题恰好为模型的优点、模型的不足",
        chapter7_subsections == ["模型的优点", "模型的不足"],
        f"实际={chapter7_subsections}",
    )
    chapter8_subsections = tex_subsections(body_texts["08_improvement_extension.tex"])
    add(
        "S13",
        "第八章二级标题恰好为模型的改进、模型的推广",
        chapter8_subsections == ["模型的改进", "模型的推广"],
        f"实际={chapter8_subsections}",
    )

    appendix_sections = re.findall(r"\\section\{([^{}]+)\}", appendix_text)
    expected_appendices = [
        "支撑材料文件说明",
        "数据预处理程序",
        "问题一程序",
        "问题二程序",
        "问题三程序",
        "模型验证程序",
    ]
    add(
        "S14",
        "正式附录恰好按A至F组织",
        appendix_sections == expected_appendices,
        f"实际={appendix_sections}",
    )
    forbidden_appendix_tokens = [
        "FINAL_RESULT_MANIFEST",
        "SHA256",
        "finalize_model_audits.py",
        "make_unified_figures.py",
        "build_unified_paper_tables.py",
        "build_latex.py",
        "paper_hard_acceptance.py",
    ]
    appendix_hits = [token for token in forbidden_appendix_tokens if token in appendix_text]
    add(
        "S15",
        "附录不打印清单、哈希、生产脚本或QA脚本",
        not appendix_hits,
        f"命中={appendix_hits}",
    )

    listing_specs = re.findall(
        r"\\lstinputlisting\[([^]]+)\]\{([^{}]+)\}", appendix_text
    )
    listing_errors: list[str] = []
    excerpt_texts: list[str] = []
    for options, raw_path in listing_specs:
        source_path = (PAPER_DIR / raw_path).resolve()
        first_match = re.search(r"firstline=(\d+)", options)
        last_match = re.search(r"lastline=(\d+)", options)
        if not source_path.exists() or not first_match or not last_match:
            listing_errors.append(f"{raw_path}:文件或行范围缺失")
            continue
        first_line = int(first_match.group(1))
        last_line = int(last_match.group(1))
        source_lines = read_text(source_path).splitlines()
        if first_line < 1 or last_line < first_line or last_line > len(source_lines):
            listing_errors.append(
                f"{raw_path}:{first_line}-{last_line}/总行数{len(source_lines)}"
            )
            continue
        excerpt_texts.append("\n".join(source_lines[first_line - 1 : last_line]))
    excerpt_text = "\n".join(excerpt_texts)
    required_excerpt_tokens = [
        "def expand_embedded_project_lists",
        'event_keys = ["source", "patient_id", "order_dt"]',
        "def chronological_validation",
        "def tentative_plan",
        "def plan_event",
        "def build_p3_candidate",
        '"global_deficit_repair"',
        "def solve_p3_epsilon",
        'record("no_room_overlap"',
        '"doctor_concurrency_within_capacity"',
    ]
    missing_excerpt_tokens = [
        token for token in required_excerpt_tokens if token not in excerpt_text
    ]
    add(
        "S16",
        "附录程序均直接摘录实际源码且关键接口完整",
        len(listing_specs) == 10
        and "\\begin{lstlisting}" not in appendix_text
        and not listing_errors
        and not missing_excerpt_tokens,
        f"直接源码段={len(listing_specs)}；行范围错误={listing_errors}；"
        f"关键接口缺失={missing_excerpt_tokens}",
    )

    abstract_match = re.search(
        r"\\end\{center\}(?P<abstract>.*?)\\vspace\{7pt\}",
        main_tex,
        flags=re.DOTALL,
    )
    abstract_text = abstract_match.group("abstract") if abstract_match else ""
    required_abstract = ["针对问题一", "针对问题二", "针对问题三"]
    forbidden_abstract = ["对于问题一", "对于问题二", "对于问题三"]
    add(
        "A03",
        "摘要使用针对问题一、二、三且不使用对于问题一、二、三",
        all(token in abstract_text for token in required_abstract)
        and not any(token in abstract_text for token in forbidden_abstract),
        f"必需命中={[token for token in required_abstract if token in abstract_text]}；"
        f"禁用命中={[token for token in forbidden_abstract if token in abstract_text]}",
    )
    abstract_tail = re.sub(r"\s+", "", abstract_text)[-260:]
    disclaimer_tokens = ["由于附件没有", "不作临床因果推断", "不能解释为"]
    add(
        "A04",
        "摘要结尾不是局限性免责声明",
        not any(token in abstract_tail for token in disclaimer_tokens),
        f"摘要末尾260字符={abstract_tail}",
    )

    numberless_hits: list[str] = []
    numberless_patterns = [
        (r"\\\[", "\\["),
        (r"\$\$", "$$"),
        (r"\\begin\{(?:equation\*|align\*|displaymath)\}", "starred display"),
    ]
    for path in [MAIN_TEX, *BODY_FILES]:
        text = read_text(path)
        for pattern, label in numberless_patterns:
            for match in re.finditer(pattern, text):
                line = text.count("\n", 0, match.start()) + 1
                numberless_hits.append(f"{path.relative_to(ROOT)}:{line}:{label}")
    add(
        "F01",
        "正文独立公式全部使用编号环境",
        not numberless_hits,
        f"无编号展示公式命中={numberless_hits[:20]}",
    )

    vertical_table_hits: list[str] = []
    for path in PAPER_DIR.rglob("*.tex"):
        for line_number, line in enumerate(read_text(path).splitlines(), start=1):
            if (
                "\\begin{tabular" in line or "\\begin{longtable" in line
            ) and "|" in line:
                vertical_table_hits.append(f"{path.relative_to(ROOT)}:{line_number}")
            if "\\multicolumn" in line and re.search(r"\}\{[^}]*\|", line):
                vertical_table_hits.append(f"{path.relative_to(ROOT)}:{line_number}")
    add(
        "T01",
        "表格列格式不含竖线",
        not vertical_table_hits,
        f"命中={vertical_table_hits}",
    )

    citation_keys: set[str] = set()
    for citation in re.findall(r"\\cite\{([^{}]+)\}", full_body):
        citation_keys.update(key.strip() for key in citation.split(",") if key.strip())
    bibliography_text = body_texts["09_references.tex"]
    bib_keys = set(re.findall(r"\\bibitem\{([^{}]+)\}", bibliography_text))
    add(
        "R01",
        "所有正文引用key均存在",
        citation_keys <= bib_keys,
        f"缺失key={sorted(citation_keys - bib_keys)}",
    )
    add(
        "R02",
        "所有参考文献均在正文实际引用",
        bib_keys <= citation_keys,
        f"未引用key={sorted(bib_keys - citation_keys)}",
    )
    bib_entries = re.findall(
        r"\\bibitem\{[^{}]+\}(.*?)(?=\\bibitem|\\end\{thebibliography\})",
        bibliography_text,
        flags=re.DOTALL,
    )
    chinese_refs = sum(bool(re.search(r"[\u4e00-\u9fff]", entry)) for entry in bib_entries)
    english_refs = len(bib_entries) - chinese_refs
    add(
        "R03",
        "参考文献中文7至8篇、英文8至10篇",
        7 <= chinese_refs <= 8 and 8 <= english_refs <= 10,
        f"中文={chinese_refs}；英文={english_refs}；合计={len(bib_entries)}",
    )

    identity_patterns = [
        r"(?m)^\s*姓名\s*[：:]",
        r"(?m)^\s*学校(?:名称)?\s*[：:]",
        r"(?m)^\s*学号\s*[：:]",
        r"(?m)^\s*队号\s*[：:]",
        r"(?m)^\s*队员\s*[：:]",
        r"(?m)^\s*指导教师\s*[：:]",
        r"\\author\{\s*[^}]\S[^}]*\}",
    ]
    identity_hits = [pattern for pattern in identity_patterns if re.search(pattern, full_paper_source)]
    add(
        "N01",
        "源码无姓名、学校、学号、队号或指导教师信息",
        not identity_hits,
        f"命中模式={identity_hits}",
    )

    geometry_match = re.search(r"\\usepackage\[([^]]+)\]\{geometry\}", main_tex)
    margins: dict[str, float] = {}
    if geometry_match:
        for key, value in re.findall(
            r"(top|bottom|left|right)\s*=\s*([0-9.]+)cm", geometry_match.group(1)
        ):
            margins[key] = float(value)
    add(
        "L01",
        "A4且四边页边距均不小于2.5cm",
        "a4paper" in main_tex
        and set(margins) == {"top", "bottom", "left", "right"}
        and all(value >= 2.5 for value in margins.values()),
        f"a4paper={'a4paper' in main_tex}；margins={margins}",
    )
    add(
        "L02",
        "无页眉且页脚居中显示页码",
        "\\fancyhf{}" in main_tex
        and "\\headrulewidth}{0pt}" in main_tex
        and "\\cfoot{\\zihao{5}\\thepage}" in main_tex,
        "检查\\fancyhf{}、0pt页眉线与\\cfoot页码设置",
    )
    add(
        "L03",
        "题目为三号黑体居中，正文小四宋体，西文Times New Roman",
        "\\begin{center}" in main_tex
        and "\\heiti\\zihao{3}\\bfseries" in main_tex
        and "\\songti\\zihao{-4}" in main_tex
        and "\\setmainfont{Times New Roman}" in main_tex,
        "标题、正文和西文字体命令均从main.tex直接核对",
    )
    add(
        "L04",
        "正文为单倍行距，图题和表题为五号黑体",
        "\\setstretch{1.0}" in main_tex
        and "\\DeclareCaptionFont{wuhaoheiti}{\\zihao{5}\\heiti" in main_tex
        and "font=wuhaoheiti" in main_tex
        and "labelfont=wuhaoheiti" in main_tex,
        "检查\\setstretch{1.0}与caption五号黑体设置",
    )

    undefined_patterns = [
        r"There were undefined references",
        r"Citation [`'][^`']+['`] on page .* undefined",
        r"Reference [`'][^`']+['`] on page .* undefined",
        r"undefined citations",
    ]
    undefined_hits = [pattern for pattern in undefined_patterns if re.search(pattern, build_log, re.I)]
    add(
        "C01",
        "编译日志无undefined reference或undefined citation",
        bool(build_log) and not undefined_hits,
        f"命中模式={undefined_hits}",
    )
    overfull_lines = [
        line.strip()
        for line in build_log.splitlines()
        if "Overfull \\hbox" in line or "Overfull \\vbox" in line
    ]
    add(
        "C02",
        "编译日志无横向或纵向溢出",
        bool(build_log) and not overfull_lines,
        "未发现Overfull box" if build_log and not overfull_lines else "; ".join(overfull_lines[:8]),
    )

    body_page_match = re.search(
        r"\\newlabel\{body:lastpage\}\{\{.*?\}\{(\d+)\}", aux_text
    )
    body_pages = int(body_page_match.group(1)) if body_page_match else None
    add(
        "P01",
        "仅按摘要至第八章计算正文页数且正文不超过30页",
        body_pages is not None and body_pages <= 30,
        f"aux标签body:lastpage={body_pages}；上限=30；参考文献和附录不计入",
    )

    total_pages, page_evidence = extract_pdf_pages(FINAL_PDF)
    add(
        "P02",
        "最终PDF存在且可读取总页数",
        total_pages is not None,
        f"{page_evidence}；PDF={FINAL_PDF.relative_to(ROOT)}",
    )
    pdf_text, pdf_text_evidence = extract_pdf_text(FINAL_PDF)
    normalized_pdf = normalize_pdf_text(pdf_text)
    heading_positions = [normalized_pdf.find(normalize_pdf_text(value)) for value in EXPECTED_PDF_HEADINGS]
    add(
        "P03",
        "最终PDF显示中文数字一级标题且顺序正确",
        all(position >= 0 for position in heading_positions)
        and heading_positions == sorted(heading_positions),
        f"heading_positions={heading_positions}；{pdf_text_evidence}",
    )
    pdf_pages = pdf_text.split("\f") if pdf_text else []
    if pdf_pages and not pdf_pages[-1].strip():
        pdf_pages.pop()
    first_page = normalize_pdf_text(pdf_pages[0]) if pdf_pages else ""
    second_page = normalize_pdf_text(pdf_pages[1]) if len(pdf_pages) > 1 else ""
    add(
        "P04",
        "摘要和关键词完整位于第1页，第一章从第2页开始",
        "摘要" in first_page
        and "关键词" in first_page
        and "一、问题重述" not in first_page
        and "一、问题重述" in second_page,
        f"PDF文本页数={len(pdf_pages)}；第1页含摘要={'摘要' in first_page}；"
        f"第1页含第一章={'一、问题重述' in first_page}；第2页含第一章={'一、问题重述' in second_page}",
    )
    missing_page_numbers: list[int] = []
    for page_number, page_text in enumerate(pdf_pages, start=1):
        if not re.search(rf"(?m)^\s*{page_number}\s*$", page_text):
            missing_page_numbers.append(page_number)
    add(
        "P05",
        "PDF页码从摘要页起连续且页脚可抽取",
        bool(pdf_pages) and not missing_page_numbers,
        f"缺失页码页={missing_page_numbers[:20]}",
    )

    appendix_pdf_headings = [
        "附录A支撑材料文件说明",
        "附录B数据预处理程序",
        "附录C问题一程序",
        "附录D问题二程序",
        "附录E问题三程序",
        "附录F模型验证程序",
    ]
    appendix_positions = [normalized_pdf.find(value) for value in appendix_pdf_headings]
    add(
        "P06",
        "最终PDF显示附录A至F且顺序正确",
        all(position >= 0 for position in appendix_positions)
        and appendix_positions == sorted(appendix_positions),
        f"appendix_positions={appendix_positions}",
    )

    passed = sum(check.passed for check in checks)
    failed = [check for check in checks if not check.passed]
    status = "TRUE" if not failed else "FALSE"
    lines = [
        "# 论文机器硬验收报告",
        "",
        f"- 生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- LaTeX入口：`{MAIN_TEX.relative_to(ROOT)}`",
        f"- 最终PDF：`{FINAL_PDF.relative_to(ROOT)}`",
        f"- 正文页数口径：摘要页至第八章末，共{body_pages if body_pages is not None else '未取得'}页；参考文献与附录不计入30页上限。",
        f"- PDF总页数：{total_pages if total_pages is not None else '未取得'}页。",
        f"- 断言统计：{passed}/{len(checks)}通过，{len(failed)}项失败。",
        f"- `PAPER_HARD_ACCEPTANCE = {status}`",
        "",
        "## 逐项断言",
        "",
        "| ID | 结果 | 硬性条件 | 实际证据 |",
        "|---|---|---|---|",
    ]
    for check in checks:
        result = "PASS" if check.passed else "FAIL"
        lines.append(
            f"| {check.check_id} | {result} | {markdown_cell(check.requirement)} | "
            f"{markdown_cell(check.evidence)} |"
        )
    lines.extend(["", "## 当前失败项", ""])
    if failed:
        for check in failed:
            lines.append(
                f"- `{check.check_id}` {check.requirement}。证据：{check.evidence}"
            )
    else:
        lines.append("- 无。")
    lines.extend(
        [
            "",
            "## 验收边界",
            "",
            "本报告验证论文结构、公式环境、引用闭合、编译日志、正文页数与PDF文本特征。模型数值是否来自最新最终运行，由模型—代码—结果一致性报告另行确认；本报告不会用排版通过替代技术结果冻结。",
            "",
        ]
    )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    consistency = write_result_consistency_report(main_tex, body_texts)
    structure_pass = write_structure_report(
        checks=checks,
        body_pages=body_pages,
        total_pages=total_pages,
        section_names=section_names,
        assumption_numbers=assumption_numbers,
        symbol_rows=symbol_rows,
        chapter6_subsections=chapter6_subsections,
        chapter7_subsections=chapter7_subsections,
        chapter8_subsections=chapter8_subsections,
        chinese_refs=chinese_refs,
        english_refs=english_refs,
        appendix_sections=appendix_sections,
    )
    final_qa_pass = write_final_qa_report(
        consistency=consistency,
        body_pages=body_pages,
        total_pages=total_pages,
    )

    print(f"PAPER_HARD_ACCEPTANCE = {status}")
    print(f"assertions_passed = {passed}/{len(checks)}")
    print(
        "MODEL_RESULT_FINAL_CONSISTENCY = "
        + ("TRUE" if consistency.get("passed") is True else "FALSE")
    )
    print(f"PAPER_STRUCTURE_AUDIT = {'TRUE' if structure_pass else 'FALSE'}")
    print(f"FINAL_QA_ACCEPTANCE = {'TRUE' if final_qa_pass else 'FALSE'}")
    print(f"report = {REPORT_PATH}")
    if failed:
        print("failed_assertions = " + ",".join(check.check_id for check in failed))
    if compile_outputs and pass_codes != [0, 0]:
        print(compile_outputs[-1])
    return 0 if not failed and consistency.get("passed") is True and final_qa_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
