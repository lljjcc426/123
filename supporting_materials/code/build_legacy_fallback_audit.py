"""Close the audit loop for the 50 projects formerly assigned by category fallback."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

import analyze_p1 as p1


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "supporting_materials" / "processed_data" / "unified_holdout"
CAP = ROOT / "supporting_materials" / "results" / "capability"

LEGACY_FALLBACK_PROJECTS = [
    "B", "临床操作的彩色多普勒超声引导(超声科)", "前列腺彩超", "双乳腺及腋窝淋巴结",
    "双肾彩超", "妇科B超(经腹)", "子宫、输卵管超声造影检查", "左肾胡桃夹现象,主任检查",
    "床旁前列腺彩超", "床旁彩超介入引导(半小时)", "床旁泌尿系彩超(双肾、输尿管、膀胱)",
    "床旁泌尿系彩超(双肾、输尿管、膀胱),床旁彩超][床旁腹部常规(肝胆胰脾),床旁彩超][床旁腹水,床旁彩超][床旁胸部(床旁胸水),床旁彩超",
    "床旁经腹诊断性羊膜腔穿刺术(羊水穿刺)", "床旁经腹诊断性羊膜腔穿刺术(羊水穿刺)(减免)",
    "床旁肺部超声(新生儿)", "床旁腹水", "床旁腹水加定位", "床旁腹部常规(肝胆胰脾)",
    "彩色多普勒超声常规检查(腹膜后肿物加收)", "彩色多普勒超声常规检查(腹膜后间隙软组织)",
    "彩超：肝、胆、胰、脾、肾", "泌尿系B超", "泌尿系彩超(双肾输尿管膀胱),男性：前列腺",
    "浅表器官彩色多普勒超声检查(上肢或下肢软组织)", "浅表器官彩色多普勒超声检查(关节)",
    "浅表器官彩色多普勒超声检查(双眼及附属器)", "甲状腺B超", "甲状腺及周围淋巴结B超",
    "男性B超(腹部+泌尿系+前列腺)", "男性B超(腹部、膀胱、前列腺)", "精囊彩超",
    "经阴道妇科(子宫、附件)", "经阴道妇科(子宫、附件)彩超", "肺部超声(新生儿)",
    "胃十二指肠充盈声学造影", "胃肠道、阑尾彩超", "腹水", "腹水加定位", "腹膜后组织",
    "腹部(肝胆胰脾肾)彩超", "腹部(肝胆胰脾肾)彩超,彩超][双乳腺及腋窝淋巴结",
    "腹部(肝胆胰脾肾)彩超,彩超][甲状腺及颈部淋巴结", "腹部+泌尿系",
    "腹部+泌尿系,彩超][前列腺B超", "腹部常规(肝、胆、胰、脾、肾)", "腹部常规(肝胆胰脾)",
    "超声引导下浅表器官穿刺活检术(每处)(超声诊断科)", "超声引导下肾脏穿刺活检术(超声诊断科)",
    "超声引导下肿瘤穿刺活检术(超声诊断科)", "阴道彩超",
]


def split_legacy(value: str) -> list[str]:
    parts = re.split(r"\]\s*\[", value)
    return p1.normalize_project(pd.Series(parts, dtype="string")).dropna().astype(str).tolist()


def main() -> None:
    CAP.mkdir(parents=True, exist_ok=True)
    summary = pd.read_csv(INPUT / "project_machine_summary.csv", encoding="utf-8-sig")
    evidence = pd.read_csv(INPUT / "project_machine_evidence.csv", encoding="utf-8-sig", dtype={"machine_id": "string"})
    items = pd.read_csv(INPUT / "items.csv", encoding="utf-8-sig", low_memory=False)
    current_review_path = CAP / "CURRENT_UNMATCHED_PROJECT_REVIEW.csv"
    if not current_review_path.exists():
        current_review_path = CAP / "FALLBACK_PROJECT_REVIEW.csv"
    current_review = pd.read_csv(current_review_path, encoding="utf-8-sig")
    summary_by_project = summary.set_index("project_norm")
    counts = items["project_norm"].value_counts().to_dict()
    rows: list[dict[str, object]] = []

    for legacy in LEGACY_FALLBACK_PROJECTS:
        components = split_legacy(legacy)
        component_rows = summary[summary["project_norm"].isin(components)]
        if len(components) > 1:
            disposition = "split_source_bundle_into_items"
            levels = "|".join(
                f"{row.project_norm}:{row.evidence_level}" for row in component_rows.itertuples(index=False)
            )
            rooms = " || ".join(
                f"{row.project_norm}:{row.final_rooms}" for row in component_rows.itertuples(index=False)
            )
            rationale = "旧字段把多个收费项目串成一个名称；已按][边界拆为独立任务并逐项使用A/B/C/D证据。"
        elif legacy in summary_by_project.index:
            row = summary_by_project.loc[legacy]
            level = str(row["evidence_level"])
            disposition = "exclude_level_D" if level == "D" else "use_project_level_A_B_C"
            levels = level
            rooms = "" if pd.isna(row["final_rooms"]) else str(row["final_rooms"])
            matched = evidence[evidence["project_norm"].eq(legacy)]
            rules = ",".join(sorted(matched["match_rule"].dropna().astype(str).unique()))
            rationale = f"当前项目级证据规则：{rules or 'D级无充分表1证据'}。"
        else:
            disposition = "not_in_holdout_after_cleaning"
            levels = "not_applicable"
            rooms = ""
            rationale = "清洗后的留出期任务中不再出现；不再给予任何类别级设备授权。"

        rows.append(
            {
                "legacy_project": legacy,
                "legacy_issue": "same_category_blanket_fallback",
                "current_disposition": disposition,
                "components_after_source_fix": "|".join(components),
                "current_evidence_level": levels,
                "current_rooms": rooms,
                "current_holdout_item_count": int(sum(counts.get(component, 0) for component in components)),
                "category_fallback_retained": False,
                "audit_rationale": rationale,
            }
        )

    frame = pd.DataFrame(rows)
    if len(frame) != 50 or frame["legacy_project"].duplicated().any():
        raise RuntimeError("legacy fallback audit must contain 50 unique projects")
    frame.to_csv(CAP / "LEGACY_50_FALLBACK_PROJECT_AUDIT.csv", index=False, encoding="utf-8-sig")
    view_columns = ["legacy_project", "current_disposition", "current_evidence_level", "current_holdout_item_count"]
    markdown_rows = [
        "|" + "|".join(view_columns) + "|",
        "|" + "|".join(["---"] * len(view_columns)) + "|",
    ]
    for row in frame[view_columns].itertuples(index=False, name=None):
        markdown_rows.append("|" + "|".join(str(value).replace("|", "/") for value in row) + "|")
    report = [
        "# 旧版50个类别回退项目逐项审计",
        "",
        "旧版同类设备兜底已全部撤销。项目只允许A/B/C级项目证据；D级不进入硬约束排程。旧字段中含][的复合单元按源系统边界拆为独立项目。",
        "",
        "\n".join(markdown_rows),
    ]
    (CAP / "LEGACY_50_FALLBACK_PROJECT_AUDIT.md").write_text("\n".join(report), encoding="utf-8")
    print(frame["current_disposition"].value_counts().to_string())


if __name__ == "__main__":
    main()
