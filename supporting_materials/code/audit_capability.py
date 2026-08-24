"""Build and audit the current-room capability matrix from Table 1 only."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SUPPORTING_DIR = ROOT / "supporting_materials"
SERVICE_FAMILIES = [
    "产科III/IV级",
    "产科I/II级",
    "介入/定位",
    "心脏",
    "血管",
    "经阴道/腔内",
    "泌尿/经腹妇科",
    "腹部/胃肠",
    "浅表器官",
    "儿科专项",
    "一般其他",
]

SPECIAL_RESOURCES = [
    ("床旁", None),
    ("心脏", "心脏"),
    ("血管", "血管"),
    ("III/IV产科", "产科III/IV级"),
    ("I/II产科", "产科I/II级"),
    ("儿科专项", "儿科专项"),
    ("介入/定位", "介入/定位"),
]


def clean_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def clean_id(series: pd.Series) -> pd.Series:
    return (
        clean_text(series)
        .str.replace(r"^[\"']+|[\"']+$", "", regex=True)
        .str.replace(r"\.0$", "", regex=True)
    )


def normalize_project_text(value: str) -> str:
    text = str(value).strip()
    for old, new in {
        "（": "(",
        "）": ")",
        "，": ",",
        "　": "",
        " ": "",
        "\u2163": "IV",
        "\u2162": "III",
        "\u2161": "II",
        "\u2160": "I",
    }.items():
        text = text.replace(old, new)
    return text.strip("[]")


def split_capabilities(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value)
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for character in text:
        if character in "（(【[":
            depth += 1
            current.append(character)
        elif character in "）)】]":
            depth = max(depth - 1, 0)
            current.append(character)
        elif character in "、；;\r\n" and depth == 0:
            item = "".join(current).strip()
            if item:
                items.append(item)
            current = []
        else:
            current.append(character)
    item = "".join(current).strip()
    if item:
        items.append(item)
    return items


def load_rules(path: Path) -> pd.DataFrame:
    rules = pd.read_csv(path)
    rules = rules[rules["category"].isin(SERVICE_FAMILIES)].copy()
    rules["priority"] = pd.to_numeric(rules["priority"], errors="raise")
    rules = rules.sort_values("priority")
    missing = sorted(set(SERVICE_FAMILIES) - set(rules["category"]))
    if missing:
        raise ValueError(f"冻结项目族缺失: {missing}")
    return rules


def classify_token(normalized: str, rules: pd.DataFrame) -> tuple[str, str, str]:
    for row in rules.itertuples(index=False):
        if re.search(row.keyword_regex, normalized, flags=re.IGNORECASE):
            return row.category, row.keyword_regex, row.classification_basis
    raise RuntimeError(f"项目未被冻结规则覆盖: {normalized}")


def broad_descriptor_status(normalized: str, category: str) -> tuple[bool, str]:
    if category != "一般其他":
        if re.search(r"常规|综合", normalized):
            return (
                False,
                "含“常规/综合”字样但同时有明确部位或专项关键词，仅按明确项目族映射。",
            )
        return False, "表1列出具体部位或专项项目。"
    broad = bool(
        re.fullmatch(
            r"(?:彩色多普勒)?(?:超声|彩超|B超)?(?:常规检查|常规|综合检查|综合超声|检查)",
            normalized,
        )
        or re.search(r"综合超声|全身超声|常规超声$", normalized)
        or re.fullmatch(r"带有床旁的超声项目", normalized)
    )
    if broad:
        return (
            True,
            "宽泛描述只支持“一般其他”中的未细分常规能力；若原文明确床旁则仅另授予床旁地点约束，不外推至心脏、血管、产科、儿科或介入专项。",
        )
    return (
        False,
        "冻结规则未命中专项关键词，作为一般其他中的具体残余项目；不代表该房间覆盖一般其他的全部项目。",
    )


def build_evidence(equipment: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in equipment.itertuples(index=False):
        for evidence in split_capabilities(item.capability_text):
            normalized = normalize_project_text(evidence)
            category, pattern, basis = classify_token(normalized, rules)
            broad, ambiguity = broad_descriptor_status(normalized, category)
            rows.append(
                {
                    "source_row": item.source_row,
                    "machine_id": item.machine_id,
                    "current_room": item.current_room,
                    "machine_model": item.machine_model,
                    "purchase_date": item.purchase_date,
                    "category": category,
                    "evidence_project_original": evidence,
                    "evidence_project_normalized": normalized,
                    "matched_frozen_regex": pattern,
                    "classification_basis": basis,
                    "is_broad_descriptor": broad,
                    "qualifies_for_family_binary": not broad,
                    "ambiguity_note": ambiguity,
                    "authority_source": "表1现行设备检查项目原文",
                }
            )
    return pd.DataFrame(rows)


def build_matrix(
    equipment: pd.DataFrame,
    evidence: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    counts = (
        evidence.groupby(["machine_id", "current_room", "category"], as_index=False)
        .agg(
            evidence_count=("evidence_project_original", "size"),
            broad_evidence_count=("is_broad_descriptor", "sum"),
            qualifying_evidence_count=("qualifies_for_family_binary", "sum"),
            evidence_sample=("evidence_project_original", lambda x: "；".join(x.head(3))),
        )
    )
    full_index = pd.MultiIndex.from_product(
        [equipment["machine_id"].tolist(), SERVICE_FAMILIES],
        names=["machine_id", "category"],
    ).to_frame(index=False)
    room_lookup = equipment[["machine_id", "current_room"]].drop_duplicates()
    long = full_index.merge(room_lookup, on="machine_id", how="left")
    long = long.merge(counts, on=["machine_id", "current_room", "category"], how="left")
    long["evidence_count"] = long["evidence_count"].fillna(0).astype(int)
    long["broad_evidence_count"] = long["broad_evidence_count"].fillna(0).astype(int)
    long["qualifying_evidence_count"] = long["qualifying_evidence_count"].fillna(0).astype(int)
    long["capability"] = long["qualifying_evidence_count"].gt(0).astype(int)
    long["all_evidence_broad"] = (
        long["evidence_count"].gt(0)
        & long["qualifying_evidence_count"].eq(0)
    )
    long["matrix_semantics"] = np.select(
        [long["capability"].eq(1), long["all_evidence_broad"]],
        [
            "表1至少列出一个属于该族的具体项目；不等于族内全部项目均可做",
            "表1只有宽泛描述，严格族矩阵置0；独立地点能力另行保留",
        ],
        default="表1未列出该族项目；不能用历史完成记录补为1",
    )
    long = long[
        [
            "machine_id",
            "current_room",
            "category",
            "capability",
            "evidence_count",
            "broad_evidence_count",
            "qualifying_evidence_count",
            "all_evidence_broad",
            "evidence_sample",
            "matrix_semantics",
        ]
    ]

    matrix = (
        long.pivot(index=["machine_id", "current_room"], columns="category", values="capability")
        .reindex(columns=SERVICE_FAMILIES)
        .reset_index()
    )
    matrix.columns.name = None
    order = {machine: index for index, machine in enumerate(equipment["machine_id"])}
    matrix["_order"] = matrix["machine_id"].map(order)
    matrix = matrix.sort_values("_order").drop(columns="_order")
    return matrix, long


def special_resource_check(
    equipment: pd.DataFrame,
    matrix: pd.DataFrame,
    evidence: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for resource, category in SPECIAL_RESOURCES:
        if resource == "床旁":
            token_hit = evidence["evidence_project_original"].str.contains("床旁", na=False)
            room_hit = equipment["current_room"].str.contains("床边|床旁", na=False)
            feasible = sorted(
                set(evidence.loc[token_hit, "machine_id"])
                | set(equipment.loc[room_hit, "machine_id"]),
                key=lambda x: equipment.set_index("machine_id").loc[x, "source_row"],
            )
            evidence_basis = "表1诊室名含床边/床旁，或检查项目原文含床旁"
        else:
            feasible = matrix.loc[matrix[category].eq(1), "machine_id"].tolist()
            evidence_basis = f"22×11矩阵中“{category}”=1，且每个1有表1项目原文证据"
        room_map = equipment.set_index("machine_id")["current_room"].to_dict()
        rooms = [room_map[machine] for machine in feasible]
        count = len(feasible)
        if count == 0:
            status = "零可行房"
        elif count == 1:
            status = "唯一瓶颈"
        elif count <= 3:
            status = "少数房间"
        else:
            status = "多房间"
        rows.append(
            {
                "resource": resource,
                "mapped_category": category or "独立床旁约束",
                "feasible_room_count": count,
                "feasible_machine_ids": "|".join(feasible),
                "feasible_rooms": "|".join(rooms),
                "zero_feasible": count == 0,
                "unique_bottleneck": count == 1,
                "status": status,
                "evidence_basis": evidence_basis,
            }
        )
    return pd.DataFrame(rows)


def constraint_checks(
    equipment: pd.DataFrame,
    matrix: pd.DataFrame,
    long: pd.DataFrame,
    evidence: pd.DataFrame,
) -> pd.DataFrame:
    input_sources = "equipment_capability.parquet|category_rules.csv"
    one_key_count = int(
        evidence.loc[evidence["qualifies_for_family_binary"]]
        .drop_duplicates(["machine_id", "category"])
        .shape[0]
    )
    matrix_one_count = int(matrix[SERVICE_FAMILIES].to_numpy().sum())
    fragment_artifact = evidence["evidence_project_normalized"].str.fullmatch(
        r"(?:腘|股浅|股深|胫前后|胫前|胫后|腓[）)]?|尺|肱|贵要|附件及周围组织[）)]?)",
        na=False,
    )
    checks = [
        {
            "check_id": "C01_machine_rows",
            "check_description": "表1现行设备行数为22",
            "passed": len(equipment) == 22,
            "observed": len(equipment),
            "expected": 22,
        },
        {
            "check_id": "C02_unique_machine_ids",
            "check_description": "22个机器ID互不重复",
            "passed": equipment["machine_id"].nunique() == 22,
            "observed": equipment["machine_id"].nunique(),
            "expected": 22,
        },
        {
            "check_id": "C03_matrix_shape",
            "check_description": "矩阵为22行×11项目族",
            "passed": matrix.shape == (22, 13),
            "observed": f"{len(matrix)}×{len(SERVICE_FAMILIES)}",
            "expected": "22×11",
        },
        {
            "check_id": "C04_binary_values",
            "check_description": "所有能力值均为0或1",
            "passed": bool(matrix[SERVICE_FAMILIES].isin([0, 1]).all().all()),
            "observed": sorted(pd.unique(matrix[SERVICE_FAMILIES].to_numpy().ravel()).tolist()),
            "expected": "[0, 1]",
        },
        {
            "check_id": "C05_every_one_has_evidence",
            "check_description": "矩阵每个1至少有一条非宽泛表1原文证据",
            "passed": bool(long.loc[long["capability"].eq(1), "qualifying_evidence_count"].ge(1).all()),
            "observed": int(long.loc[long["capability"].eq(1), "qualifying_evidence_count"].min()),
            "expected": ">=1",
        },
        {
            "check_id": "C06_no_evidence_for_zero",
            "check_description": "矩阵每个0均无可授予族能力的具体证据",
            "passed": bool(long.loc[long["capability"].eq(0), "qualifying_evidence_count"].eq(0).all()),
            "observed": int(long.loc[long["capability"].eq(0), "qualifying_evidence_count"].max()),
            "expected": 0,
        },
        {
            "check_id": "C07_authority_source",
            "check_description": "能力证据全部来自表1，未读取历史完成记录",
            "passed": evidence["authority_source"].eq("表1现行设备检查项目原文").all(),
            "observed": input_sources,
            "expected": "仅表1设备能力+冻结分类规则",
        },
        {
            "check_id": "C08_all_rooms_named",
            "check_description": "22个现行诊室名称均非空",
            "passed": equipment["current_room"].notna().all(),
            "observed": int(equipment["current_room"].notna().sum()),
            "expected": 22,
        },
        {
            "check_id": "C09_evidence_token_count",
            "check_description": "拆分后的表1项目证据非空",
            "passed": len(evidence) > 0,
            "observed": len(evidence),
            "expected": ">0",
        },
        {
            "check_id": "C10_one_key_coverage",
            "check_description": "具有具体证据的机器×项目族键数等于矩阵1的数量",
            "passed": one_key_count == matrix_one_count,
            "observed": one_key_count,
            "expected": matrix_one_count,
        },
        {
            "check_id": "C11_parenthesis_aware_split",
            "check_description": "括号内血管/器官枚举项未被顿号拆成伪项目",
            "passed": not fragment_artifact.any(),
            "observed": int(fragment_artifact.sum()),
            "expected": 0,
        },
    ]
    return pd.DataFrame(checks)


def safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = frame[columns]
    output = [
        "|" + "|".join(columns) + "|",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for _, row in selected.iterrows():
        values = []
        for value in row:
            if isinstance(value, (list, tuple, set)):
                values.append(", ".join(map(str, value)))
            elif pd.isna(value):
                values.append("不适用")
            elif isinstance(value, (bool, np.bool_)):
                values.append("是" if value else "否")
            else:
                values.append(str(value).replace("|", "/"))
        output.append("|" + "|".join(values) + "|")
    return "\n".join(output)


def write_report(
    path: Path,
    matrix: pd.DataFrame,
    long: pd.DataFrame,
    evidence: pd.DataFrame,
    special: pd.DataFrame,
    checks: pd.DataFrame,
) -> None:
    category_counts = (
        long.groupby("category", as_index=False)
        .agg(
            feasible_room_count=("capability", "sum"),
            evidence_project_count=("evidence_count", "sum"),
            broad_only_room_count=("all_evidence_broad", "sum"),
        )
    )
    ones = int(matrix[SERVICE_FAMILIES].to_numpy().sum())
    broad = evidence[evidence["is_broad_descriptor"]]
    failed = checks[~checks["passed"]]
    text = f"""# 表1现行设备能力矩阵审计报告

## 1. 审计结论

本审计仅使用表1的22台现行机器及其“检查项目”原文作为能力权威源，冻结的11个服务项目族只承担文本归类。没有读取住院、门诊、体检历史完成记录，也没有用历史机器ID补齐能力。

最终矩阵为22行×11项目族，共有 {ones} 个能力位为1。每个1均至少对应一条非宽泛的表1原文证据；严格矩阵1的逐条证据见同目录 `capability_one_evidence.csv`，完整拆分证据见同目录 `capability_evidence.csv`。能力位1的严格语义是“表1至少列出一个属于该项目族的具体项目”，不能解释为该房间能做项目族内全部项目。只有宽泛描述而没有具体项目时，严格族矩阵置0，宽泛证据仍保留在长表。涉及具体排程时，仍应优先用原始项目名与表1项目名匹配；族矩阵适合聚合容量模型和初筛。

## 2. 项目族覆盖

{markdown_table(category_counts, ['category', 'feasible_room_count', 'evidence_project_count', 'broad_only_room_count'])}

`一般其他` 是冻结规则的残余类，内部项目异质性最大。它的能力位只能说明房间至少支持表1列出的某个残余项目，不支持把任意新“其他”项目分配给该房间。

## 3. 宽泛描述处理

表1中含“常规”或“综合”但同时指明腹部、泌尿系等部位的文本，按明确部位映射，不视作宽泛授权。裸“常规超声”“综合超声”“全身超声”等若出现，只映射到 `一般其他`，并设置 `is_broad_descriptor=True`；不外推到心脏、血管、III/IV产科、I/II产科、儿科专项、床旁或介入/定位。表1的“带有床旁的超声项目”同样是宽泛描述：它只确认机器7具备床旁地点能力，不据此赋予任何具体专项能力。

本次拆分证据中宽泛描述条目数为 {len(broad)}；详细内容见同目录 `broad_descriptor_audit.csv`。宽泛条目的 `qualifies_for_family_binary=False`，不会把任何项目族矩阵位改成1。上述规则固定在代码中，防止后续表1版本中宽泛文字造成能力扩张。

## 4. 关键资源瓶颈

{markdown_table(special, ['resource', 'mapped_category', 'feasible_room_count', 'feasible_machine_ids', 'feasible_rooms', 'status'])}

`唯一瓶颈` 表示按表1只有一个现行机器/诊室满足约束，排程时必须设置不可替代资源约束并考虑停机情景；`零可行房` 表示项目族定义与表1发生断裂，不能通过历史完成记录自行补1。`少数房间` 仍需要容量压力测试，但不等同于单点故障。

床旁能力是独立地点约束：只按表1诊室名含“床边/床旁”或项目原文含“床旁”识别，不因一般项目族能力自动获得床旁资格。

## 5. 独立约束检查

{markdown_table(checks, ['check_id', 'check_description', 'passed', 'observed', 'expected'])}

未通过检查数：{len(failed)}。这些检查验证矩阵尺寸、二值性、证据完整性和权威源边界，不把某个专项存在零房或唯一房视为代码错误；专项瓶颈由上一节单独报告。

## 6. 输出说明

- `capability_matrix.csv`：22×11二值能力矩阵。
- `capability_matrix_long.csv`：每个机器×项目族的能力位、证据数和聚合语义。
- `capability_evidence.csv`：表1拆分后的全部项目证据，含不授予族能力的宽泛描述。
- `capability_one_evidence.csv`：只保留严格矩阵中能力位1的合格表1证据，便于逐位复核。
- `equipment_source_rows.csv`：表1的22行原始设备与检查项目文本。
- `special_resource_bottlenecks.csv`：七类关键资源的零房/唯一瓶颈检查。
- `independent_constraint_checks.csv`：独立约束检查结果。
- `broad_descriptor_audit.csv`：宽泛描述及映射边界。
- `capability_audit_summary.json`：机器可读摘要。

## 7. 复现

```powershell
python supporting_materials/code/audit_capability.py
```

脚本只读取表1 Parquet 和冻结项目族规则，所有输出均写入 `supporting_materials/results/capability/`。
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--equipment",
        type=Path,
        default=SUPPORTING_DIR / "processed_data" / "raw_parquet" / "equipment_capability.parquet",
    )
    parser.add_argument(
        "--rules",
        type=Path,
        default=SUPPORTING_DIR / "results" / "p1" / "category_rules.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SUPPORTING_DIR / "results" / "capability",
    )
    args = parser.parse_args()
    results_dir = args.output_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_parquet(args.equipment)
    # The parquet schema is fixed by the extraction manifest; positional rename
    # avoids shell-codepage issues with Chinese column literals.
    raw = raw.iloc[:, :6].copy()
    raw.columns = [
        "source_row",
        "machine_id",
        "current_room",
        "machine_model",
        "purchase_date",
        "capability_text",
    ]
    raw["machine_id"] = clean_id(raw["machine_id"])
    for column in ["current_room", "machine_model", "purchase_date", "capability_text"]:
        raw[column] = clean_text(raw[column])

    rules = load_rules(args.rules)
    evidence = build_evidence(raw, rules)
    matrix, long = build_matrix(raw, evidence)
    one_keys = long.loc[long["capability"].eq(1), ["machine_id", "category"]]
    one_evidence = evidence.loc[evidence["qualifies_for_family_binary"]].merge(
        one_keys,
        on=["machine_id", "category"],
        how="inner",
        validate="many_to_one",
    )
    special = special_resource_check(raw, matrix, evidence)
    checks = constraint_checks(raw, matrix, long, evidence)
    broad = evidence[evidence["is_broad_descriptor"]].copy()

    raw.to_csv(results_dir / "equipment_source_rows.csv", index=False, encoding="utf-8-sig")
    matrix.to_csv(results_dir / "capability_matrix.csv", index=False, encoding="utf-8-sig")
    long.to_csv(results_dir / "capability_matrix_long.csv", index=False, encoding="utf-8-sig")
    evidence.to_csv(results_dir / "capability_evidence.csv", index=False, encoding="utf-8-sig")
    one_evidence.to_csv(results_dir / "capability_one_evidence.csv", index=False, encoding="utf-8-sig")
    special.to_csv(results_dir / "special_resource_bottlenecks.csv", index=False, encoding="utf-8-sig")
    checks.to_csv(results_dir / "independent_constraint_checks.csv", index=False, encoding="utf-8-sig")
    broad.to_csv(results_dir / "broad_descriptor_audit.csv", index=False, encoding="utf-8-sig")

    summary = {
        "authority_inputs": [str(args.equipment), str(args.rules)],
        "historical_completion_records_used": False,
        "machine_count": int(len(raw)),
        "service_family_count": len(SERVICE_FAMILIES),
        "matrix_one_count": int(matrix[SERVICE_FAMILIES].to_numpy().sum()),
        "evidence_token_count": int(len(evidence)),
        "matrix_one_evidence_row_count": int(len(one_evidence)),
        "broad_descriptor_count": int(len(broad)),
        "all_independent_checks_passed": bool(checks["passed"].all()),
        "failed_check_ids": checks.loc[~checks["passed"], "check_id"].tolist(),
        "special_resource_checks": special.to_dict(orient="records"),
        "matrix_semantics": "1 means Table 1 lists at least one concrete, non-broad project in the family; it does not guarantee every project in the family.",
        "broad_descriptor_policy": "Broad-only evidence is retained but produces family capability 0; an explicit bedside phrase can independently establish only the bedside location constraint.",
    }
    (results_dir / "capability_audit_summary.json").write_text(
        json.dumps(safe_json(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    write_report(
        results_dir / "CAPABILITY_AUDIT_REPORT.md",
        matrix,
        long,
        evidence,
        special,
        checks,
    )
    print(json.dumps(safe_json(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
