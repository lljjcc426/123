"""Field-level audit of the ultrasound scheduling competition data."""

from __future__ import annotations

import argparse
import gc
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SUPPORTING_DIR = ROOT / "supporting_materials"
DEFAULT_RAW_DIR = SUPPORTING_DIR / "processed_data" / "raw_parquet"
DEFAULT_AUDIT_DIR = SUPPORTING_DIR / "tables" / "audit"
START_DATE = pd.Timestamp("2019-03-01")
END_DATE = pd.Timestamp("2025-03-31")
DETAIL_RENAME = {
    "开单日期（年月日）": "order_date_raw",
    "开单时间（00:00）": "order_time_raw",
    "患者类型": "patient_type",
    "病人ID": "patient_id",
    "开单医生ID": "order_doctor_id",
    "科室ID": "department_id",
    "医嘱系统开单内容": "ordered_project",
    "检查系统开单内容": "exam_project",
    "检查报告出具日期（年月日）": "report_date_raw",
    "检查报告出具时间（00:00）": "report_time_raw",
    "检查人ID": "exam_doctor_id",
    "检查超声的机器ID": "machine_id",
}


def clean_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def clean_id(series: pd.Series) -> pd.Series:
    return (
        clean_text(series)
        .str.replace(r"^[\"']+|[\"']+$", "", regex=True)
        .str.replace(r"\.0$", "", regex=True)
    )


def combine_datetime(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(date_series, errors="coerce", format="mixed").dt.normalize()
    parts = clean_text(time_series).str.extract(
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}(?:\.\d+)?))?",
        expand=True,
    )
    hours = pd.to_numeric(parts["hour"], errors="coerce")
    minutes = pd.to_numeric(parts["minute"], errors="coerce")
    seconds = pd.to_numeric(parts["second"], errors="coerce").fillna(0)
    elapsed = pd.to_timedelta(hours * 3600 + minutes * 60 + seconds, unit="s")
    return dates + elapsed


def normalize_project(series: pd.Series) -> pd.Series:
    normalized = clean_text(series).fillna("")
    replacements = {
        "（": "(",
        "）": ")",
        "，": ",",
        "　": "",
        " ": "",
        "\u2163": "IV",
        "\u2162": "III",
        "\u2161": "II",
        "\u2160": "I",
    }
    for old, new in replacements.items():
        normalized = normalized.str.replace(old, new, regex=False)
    normalized = normalized.str.replace(r"^\[|\]$", "", regex=True)
    normalized = normalized.str.replace(
        r",(?:憋尿彩超|心脏彩超|彩超|B超)$", "", regex=True
    )
    return normalized.replace("", pd.NA)


def missing_counts(frame: pd.DataFrame) -> dict[str, int]:
    result: dict[str, int] = {}
    for column in frame.columns:
        if column == "source_row":
            continue
        values = frame[column]
        missing = values.isna()
        if pd.api.types.is_string_dtype(values) or values.dtype == object:
            missing = missing | clean_text(values).eq("")
        result[column] = int(missing.sum())
    return result


def finite_float(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def quantiles(series: pd.Series, probabilities: list[float]) -> dict[str, float | None]:
    clean = series.dropna()
    if clean.empty:
        return {str(probability): None for probability in probabilities}
    values = clean.quantile(probabilities)
    return {str(probability): finite_float(values.loc[probability]) for probability in probabilities}


def top_values(series: pd.Series, limit: int, name: str) -> pd.DataFrame:
    counts = clean_text(series).fillna("<缺失>").value_counts(dropna=False).head(limit)
    return counts.rename_axis(name).reset_index(name="记录数")


def load_machine_map(raw_dir: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    mapping = pd.read_parquet(raw_dir / "machine_map.parquet")
    mapping = mapping.rename(
        columns={
            "检查超声的机器ID": "machine_id",
            "历史彩超诊室名称": "historical_room",
            "现行彩超诊室名称": "current_room",
        }
    )
    mapping["machine_id"] = clean_id(mapping["machine_id"])
    mapping = mapping[mapping["machine_id"].str.fullmatch(r"\d+", na=False)].copy()
    mapping = mapping.drop_duplicates("machine_id", keep="last")
    room_map = dict(zip(mapping["machine_id"], clean_text(mapping["current_room"])))
    return mapping, room_map


def audit_detail(
    label: str,
    path: Path,
    room_map: dict[str, str],
    tables_dir: Path,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    frame = pd.read_parquet(path).rename(columns=DETAIL_RENAME)
    for column in [
        "patient_type",
        "patient_id",
        "order_doctor_id",
        "department_id",
        "ordered_project",
        "exam_project",
        "exam_doctor_id",
        "machine_id",
    ]:
        frame[column] = clean_text(frame[column])
    for column in [
        "patient_id",
        "order_doctor_id",
        "department_id",
        "exam_doctor_id",
        "machine_id",
    ]:
        frame[column] = clean_id(frame[column])

    frame["order_dt"] = combine_datetime(frame["order_date_raw"], frame["order_time_raw"])
    frame["report_dt"] = combine_datetime(frame["report_date_raw"], frame["report_time_raw"])
    frame["order_date"] = frame["order_dt"].dt.normalize()
    frame["report_date"] = frame["report_dt"].dt.normalize()
    frame["delay_hours"] = (frame["report_dt"] - frame["order_dt"]).dt.total_seconds() / 3600
    frame["ordered_project_norm"] = normalize_project(frame["ordered_project"])
    frame["exam_project_norm"] = normalize_project(frame["exam_project"])
    frame["current_room"] = frame["machine_id"].map(room_map)
    frame["machine_mapped"] = frame["current_room"].notna()
    frame["machine_current_valid"] = frame["current_room"].notna() & ~frame[
        "current_room"
    ].str.contains("不能对应", na=False)

    official = frame["order_date"].between(START_DATE, END_DATE)
    valid_delay = frame["delay_hours"].notna()
    official_frame = frame.loc[official].copy()
    duplicate_subset = [column for column in frame.columns if column != "source_row"]
    duplicates = int(frame.duplicated(duplicate_subset, keep=False).sum())

    project_comparison = (
        frame["ordered_project_norm"].notna()
        & frame["exam_project_norm"].notna()
    )
    project_equal = frame["ordered_project_norm"].eq(frame["exam_project_norm"])

    valid_bundle_rows = official_frame[
        official_frame["patient_id"].notna() & official_frame["order_dt"].notna()
    ].copy()
    bundle_keys = ["patient_id", "order_dt", "order_doctor_id", "department_id"]
    bundles = (
        valid_bundle_rows.groupby(bundle_keys, dropna=False)
        .agg(
            project_rows=("source_row", "size"),
            report_rows=("report_dt", "count"),
            completion_dt=("report_dt", "max"),
            room_count=("machine_id", "nunique"),
            exam_doctor_count=("exam_doctor_id", "nunique"),
        )
        .reset_index()
    )
    bundles["completion_hours"] = (
        bundles["completion_dt"] - bundles["order_dt"]
    ).dt.total_seconds() / 3600
    bundles["all_rows_reported"] = bundles["report_rows"].eq(bundles["project_rows"])
    bundles["complete_48h"] = (
        bundles["all_rows_reported"]
        & bundles["completion_hours"].between(0, 48, inclusive="both")
    )
    multi = bundles["project_rows"].gt(1)

    daily_order = (
        official_frame.groupby("order_date")
        .agg(
            detail_rows=("source_row", "size"),
            unique_patients=("patient_id", "nunique"),
        )
        .reset_index()
    )
    daily_report = (
        frame[frame["report_date"].between(START_DATE, END_DATE)]
        .groupby("report_date")
        .agg(
            detail_rows=("source_row", "size"),
            unique_patients=("patient_id", "nunique"),
        )
        .reset_index()
        .rename(columns={"report_date": "date"})
    )
    bundle_daily = (
        bundles.assign(order_date=bundles["order_dt"].dt.normalize())
        .groupby("order_date")
        .agg(application_bundles=("patient_id", "size"), complete_48h=("complete_48h", "sum"))
        .reset_index()
    )
    daily_order = daily_order.merge(bundle_daily, on="order_date", how="left")

    top_values(frame["ordered_project"], 50, "医嘱系统开单内容").to_csv(
        tables_dir / f"audit_{label}_ordered_projects_top50.csv", index=False, encoding="utf-8-sig"
    )
    top_values(frame["exam_project"], 50, "检查系统开单内容").to_csv(
        tables_dir / f"audit_{label}_exam_projects_top50.csv", index=False, encoding="utf-8-sig"
    )
    top_values(frame["machine_id"], 100, "机器ID").to_csv(
        tables_dir / f"audit_{label}_machine_ids.csv", index=False, encoding="utf-8-sig"
    )
    if label == "inpatient":
        top_values(official_frame["department_id"], 500, "科室ID").to_csv(
            tables_dir / "audit_inpatient_department_demand.csv", index=False, encoding="utf-8-sig"
        )
        bundle_distribution = (
            bundles["project_rows"].value_counts().sort_index().rename_axis("项目记录数").reset_index(name="申请单数")
        )
        bundle_distribution.to_csv(
            tables_dir / "audit_inpatient_bundle_size_distribution.csv", index=False, encoding="utf-8-sig"
        )

    metrics: dict[str, Any] = {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "missing": missing_counts(frame[list(DETAIL_RENAME.values())]),
        "exact_duplicate_rows_including_all_copies": duplicates,
        "order_date_min": str(frame["order_date"].min().date()) if frame["order_date"].notna().any() else None,
        "order_date_max": str(frame["order_date"].max().date()) if frame["order_date"].notna().any() else None,
        "report_date_min": str(frame["report_date"].min().date()) if frame["report_date"].notna().any() else None,
        "report_date_max": str(frame["report_date"].max().date()) if frame["report_date"].notna().any() else None,
        "rows_in_official_order_period": int(official.sum()),
        "rows_outside_official_order_period": int((~official & frame["order_date"].notna()).sum()),
        "invalid_order_datetime": int(frame["order_dt"].isna().sum()),
        "invalid_report_datetime": int(frame["report_dt"].isna().sum()),
        "negative_report_delay_rows": int((frame["delay_hours"] < 0).sum()),
        "report_delay_over_30_days_rows": int((frame["delay_hours"] > 24 * 30).sum()),
        "delay_hours_quantiles_all_valid": quantiles(
            frame.loc[valid_delay & frame["delay_hours"].ge(0), "delay_hours"],
            [0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1],
        ),
        "delay_hours_quantiles_official_nonnegative": quantiles(
            official_frame.loc[official_frame["delay_hours"].ge(0), "delay_hours"],
            [0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1],
        ),
        "unique_patients_official_period": int(official_frame["patient_id"].nunique(dropna=True)),
        "unique_order_doctors_official_period": int(official_frame["order_doctor_id"].nunique(dropna=True)),
        "unique_exam_doctors_official_period": int(official_frame["exam_doctor_id"].nunique(dropna=True)),
        "unique_departments_official_period": int(official_frame["department_id"].nunique(dropna=True)),
        "unique_machine_ids_all": int(frame["machine_id"].nunique(dropna=True)),
        "machine_mapping_row_coverage": finite_float(frame["machine_mapped"].mean()),
        "valid_current_room_row_coverage": finite_float(frame["machine_current_valid"].mean()),
        "ordered_project_unique_raw": int(frame["ordered_project"].nunique(dropna=True)),
        "exam_project_unique_raw": int(frame["exam_project"].nunique(dropna=True)),
        "normalized_project_exact_match_rate_when_both_present": finite_float(
            project_equal.loc[project_comparison].mean()
        ),
        "official_application_bundles": int(len(bundles)),
        "official_bundle_48h_completion_rate": finite_float(bundles["complete_48h"].mean()),
        "official_bundle_negative_completion_hours": int((bundles["completion_hours"] < 0).sum()),
        "official_bundle_completion_hours_quantiles_nonnegative": quantiles(
            bundles.loc[bundles["completion_hours"].ge(0), "completion_hours"],
            [0, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99, 1],
        ),
        "multi_project_bundle_count": int(multi.sum()),
        "multi_project_single_room_rate": finite_float(bundles.loc[multi, "room_count"].le(1).mean()),
        "multi_project_single_exam_doctor_rate": finite_float(
            bundles.loc[multi, "exam_doctor_count"].le(1).mean()
        ),
        "patients_with_multiple_application_bundles": int(
            bundles.groupby("patient_id").size().gt(1).sum()
        ),
    }

    del official_frame, valid_bundle_rows
    gc.collect()
    return metrics, daily_order, daily_report


def audit_daily_counts(path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    frame = pd.read_parquet(path)
    frame["date"] = pd.to_datetime(frame["日期"], errors="coerce", format="mixed").dt.normalize()
    numeric_columns = [
        "住院病人数",
        "住院超声检查人次",
        "住院超声检查项目数",
        "门诊病人数",
        "门诊超声检查人次",
        "门诊超声检查项目数",
    ]
    for column in numeric_columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    expected = pd.date_range(START_DATE, END_DATE, freq="D")
    observed = pd.DatetimeIndex(frame["date"].dropna().unique())
    missing_dates = expected.difference(observed)
    metrics = {
        "rows": int(len(frame)),
        "date_min": str(frame["date"].min().date()),
        "date_max": str(frame["date"].max().date()),
        "duplicate_dates": int(frame["date"].duplicated(keep=False).sum()),
        "missing_dates_in_official_period": [str(value.date()) for value in missing_dates],
        "missing": missing_counts(frame),
        "numeric_quantiles": {
            column: quantiles(frame[column], [0, 0.25, 0.5, 0.75, 0.95, 1])
            for column in numeric_columns
        },
    }
    return metrics, frame


def audit_doctor_day(path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    frame = pd.read_parquet(path)
    frame["doctor_id"] = clean_id(frame["检查人ID"])
    frame["date"] = pd.to_datetime(frame["检查日期"], errors="coerce", format="mixed").dt.normalize()
    frame["first_dt"] = pd.to_datetime(frame["最早检查时间"], errors="coerce", format="mixed")
    frame["last_dt"] = pd.to_datetime(frame["最晚检查时间"], errors="coerce", format="mixed")
    frame["project_count"] = pd.to_numeric(frame["部位数"], errors="coerce")
    frame["span_hours"] = (frame["last_dt"] - frame["first_dt"]).dt.total_seconds() / 3600
    daily_staff = frame.groupby("date")["doctor_id"].nunique().rename("working_doctors").reset_index()
    metrics = {
        "rows": int(len(frame)),
        "date_min": str(frame["date"].min().date()),
        "date_max": str(frame["date"].max().date()),
        "unique_exam_doctors": int(frame["doctor_id"].nunique(dropna=True)),
        "duplicate_doctor_date_rows": int(frame.duplicated(["doctor_id", "date"], keep=False).sum()),
        "missing": missing_counts(frame[["doctor_id", "date", "project_count", "first_dt", "last_dt"]]),
        "negative_span_rows": int((frame["span_hours"] < 0).sum()),
        "zero_span_rows": int(frame["span_hours"].eq(0).sum()),
        "span_over_16_hours_rows": int((frame["span_hours"] > 16).sum()),
        "span_hours_quantiles": quantiles(frame["span_hours"], [0, 0.25, 0.5, 0.75, 0.95, 0.99, 1]),
        "project_count_quantiles": quantiles(frame["project_count"], [0, 0.25, 0.5, 0.75, 0.95, 0.99, 1]),
        "working_doctors_per_day_quantiles": quantiles(
            daily_staff["working_doctors"], [0, 0.25, 0.5, 0.75, 0.95, 1]
        ),
    }
    return metrics, daily_staff


def audit_equipment(raw_dir: Path, mapping: pd.DataFrame) -> dict[str, Any]:
    equipment = pd.read_parquet(raw_dir / "equipment_capability.parquet")
    equipment["machine_id"] = clean_id(equipment["检查超声的机器ID"])
    equipment["room"] = clean_text(equipment["彩超诊室名称"])
    equipment["model"] = clean_text(equipment["机器型号"])
    purchase_raw = clean_text(equipment["设备购置时间"])
    numeric = pd.to_numeric(purchase_raw, errors="coerce")
    parsed = pd.to_datetime(purchase_raw, errors="coerce", format="mixed")
    serial_dates = pd.Timestamp("1899-12-30") + pd.to_timedelta(numeric, unit="D")
    equipment["purchase_date"] = parsed.fillna(serial_dates)
    return {
        "equipment_rows": int(len(equipment)),
        "unique_machine_ids": int(equipment["machine_id"].nunique(dropna=True)),
        "unique_current_rooms": int(equipment["room"].nunique(dropna=True)),
        "missing_machine_models": int(equipment["model"].isna().sum()),
        "invalid_purchase_dates": int(equipment["purchase_date"].isna().sum()),
        "machine_map_rows_after_numeric_id_filter": int(len(mapping)),
        "machine_map_current_room_valid": int(
            (~mapping["current_room"].str.contains("不能对应", na=False)).sum()
        ),
    }


def correlation(left: pd.Series, right: pd.Series) -> float | None:
    valid = left.notna() & right.notna()
    if valid.sum() < 3:
        return None
    return finite_float(left.loc[valid].corr(right.loc[valid]))


def reconcile_daily(
    daily_counts: pd.DataFrame,
    inpatient_order: pd.DataFrame,
    inpatient_report: pd.DataFrame,
    outpatient_order: pd.DataFrame,
    outpatient_report: pd.DataFrame,
    output: Path,
) -> dict[str, Any]:
    base = daily_counts[["date", "住院超声检查人次", "住院超声检查项目数", "门诊超声检查人次", "门诊超声检查项目数"]].copy()
    for prefix, frame, date_column in [
        ("in_order", inpatient_order, "order_date"),
        ("in_report", inpatient_report, "date"),
        ("out_order", outpatient_order, "order_date"),
        ("out_report", outpatient_report, "date"),
    ]:
        renamed = frame.rename(columns={date_column: "date"}).copy()
        renamed = renamed.rename(
            columns={column: f"{prefix}_{column}" for column in renamed.columns if column != "date"}
        )
        base = base.merge(renamed, on="date", how="left")
    base.to_csv(output, index=False, encoding="utf-8-sig")
    return {
        "inpatient_project_count_vs_order_detail_rows_correlation": correlation(
            base["住院超声检查项目数"], base["in_order_detail_rows"]
        ),
        "inpatient_project_count_vs_report_detail_rows_correlation": correlation(
            base["住院超声检查项目数"], base["in_report_detail_rows"]
        ),
        "inpatient_visits_vs_order_unique_patients_correlation": correlation(
            base["住院超声检查人次"], base["in_order_unique_patients"]
        ),
        "inpatient_visits_vs_report_unique_patients_correlation": correlation(
            base["住院超声检查人次"], base["in_report_unique_patients"]
        ),
        "outpatient_project_count_vs_order_detail_rows_correlation": correlation(
            base["门诊超声检查项目数"], base["out_order_detail_rows"]
        ),
        "outpatient_project_count_vs_report_detail_rows_correlation": correlation(
            base["门诊超声检查项目数"], base["out_report_detail_rows"]
        ),
        "outpatient_visits_vs_order_unique_patients_correlation": correlation(
            base["门诊超声检查人次"], base["out_order_unique_patients"]
        ),
        "outpatient_visits_vs_report_unique_patients_correlation": correlation(
            base["门诊超声检查人次"], base["out_report_unique_patients"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_AUDIT_DIR / "data_audit_metrics.json",
    )
    parser.add_argument("--tables-dir", type=Path, default=DEFAULT_AUDIT_DIR)
    args = parser.parse_args()
    args.tables_dir.mkdir(parents=True, exist_ok=True)

    mapping, room_map = load_machine_map(args.raw_dir)
    results: dict[str, Any] = {"period": {"start": str(START_DATE.date()), "end": str(END_DATE.date())}}
    detail_daily: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for label, filename in [
        ("inpatient", "inpatient.parquet"),
        ("physical_exam", "physical_exam.parquet"),
        ("outpatient", "outpatient.parquet"),
    ]:
        print(f"Auditing {label}", flush=True)
        metrics, daily_order, daily_report = audit_detail(
            label, args.raw_dir / filename, room_map, args.tables_dir
        )
        results[label] = metrics
        detail_daily[label] = (daily_order, daily_report)
        gc.collect()

    daily_metrics, daily_counts = audit_daily_counts(args.raw_dir / "daily_counts.parquet")
    results["daily_counts"] = daily_metrics
    doctor_metrics, daily_staff = audit_doctor_day(args.raw_dir / "doctor_day.parquet")
    results["doctor_day"] = doctor_metrics
    daily_staff.to_csv(
        args.tables_dir / "audit_daily_working_doctors.csv", index=False, encoding="utf-8-sig"
    )
    results["equipment_and_mapping"] = audit_equipment(args.raw_dir, mapping)
    results["daily_reconciliation"] = reconcile_daily(
        daily_counts,
        detail_daily["inpatient"][0],
        detail_daily["inpatient"][1],
        detail_daily["outpatient"][0],
        detail_daily["outpatient"][1],
        args.tables_dir / "audit_daily_reconciliation.csv",
    )

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {args.output_json}")


if __name__ == "__main__":
    main()
