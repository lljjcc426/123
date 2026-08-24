"""Sensitivity analysis for the inferred inpatient application key.

The source data do not contain an application-form identifier. This script
compares observable grouping keys and duplicate policies without declaring any
one of them to be the unobserved ground truth.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SUPPORTING_DIR = ROOT / "supporting_materials"
START_DATE = pd.Timestamp("2019-03-01")
END_DATE = pd.Timestamp("2025-03-31")
RENAME = {
    "开单日期（年月日）": "order_date_raw",
    "开单时间（00:00）": "order_time_raw",
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
    return clean_text(series).str.replace(r"\.0$", "", regex=True)


def combine_datetime(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(date_series, errors="coerce", format="mixed").dt.normalize()
    parts = clean_text(time_series).str.extract(
        r"(?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}(?:\.\d+)?))?"
    )
    elapsed = pd.to_timedelta(
        pd.to_numeric(parts["hour"], errors="coerce") * 3600
        + pd.to_numeric(parts["minute"], errors="coerce") * 60
        + pd.to_numeric(parts["second"], errors="coerce").fillna(0),
        unit="s",
    )
    return dates + elapsed


def summarize(frame: pd.DataFrame, keys: list[str]) -> dict[str, float | int]:
    episodes = (
        frame.groupby(keys, dropna=False)
        .agg(
            project_rows=("source_row", "size"),
            report_rows=("report_dt", "count"),
            completion_dt=("report_dt", "max"),
        )
        .reset_index()
    )
    episodes["completion_hours"] = (
        episodes["completion_dt"] - episodes["order_dt"]
    ).dt.total_seconds() / 3600
    episodes["complete_48h"] = episodes["report_rows"].eq(
        episodes["project_rows"]
    ) & episodes["completion_hours"].between(0, 48, inclusive="both")
    multi = episodes["project_rows"].gt(1)
    return {
        "episode_count": int(len(episodes)),
        "complete_48h_count": int(episodes["complete_48h"].sum()),
        "completion_rate": float(episodes["complete_48h"].mean()),
        "multi_project_episode_count": int(multi.sum()),
        "multi_project_episode_rate": float(multi.mean()),
        "max_project_rows": int(episodes["project_rows"].max()),
        "episodes_over_five_rows": int(episodes["project_rows"].gt(5).sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=SUPPORTING_DIR / "processed_data" / "raw_parquet",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SUPPORTING_DIR / "tables" / "audit" / "bundle_key_sensitivity.json",
    )
    args = parser.parse_args()

    frame = pd.read_parquet(args.raw_dir / "inpatient.parquet").rename(columns=RENAME)
    raw_columns = [column for column in frame.columns if column != "source_row"]
    for column in ["patient_id", "order_doctor_id", "department_id", "exam_doctor_id", "machine_id"]:
        frame[column] = clean_id(frame[column])
    frame["order_dt"] = combine_datetime(frame["order_date_raw"], frame["order_time_raw"])
    frame["report_dt"] = combine_datetime(frame["report_date_raw"], frame["report_time_raw"])
    frame = frame[
        frame["patient_id"].notna()
        & frame["order_dt"].dt.normalize().between(START_DATE, END_DATE)
    ].copy()

    key_definitions = {
        "patient_time": ["patient_id", "order_dt"],
        "patient_time_department": ["patient_id", "order_dt", "department_id"],
        "patient_time_doctor_department": [
            "patient_id",
            "order_dt",
            "order_doctor_id",
            "department_id",
        ],
    }
    output: dict[str, object] = {
        "period": {"start": str(START_DATE.date()), "end": str(END_DATE.date())},
        "source_rows_after_period_and_key_filter": int(len(frame)),
        "observable_key_definitions": key_definitions,
        "policies": {},
    }
    for policy, working in {
        "keep_exact_duplicates": frame,
        "drop_exact_duplicates": frame.drop_duplicates(raw_columns, keep="first"),
    }.items():
        policy_result: dict[str, object] = {
            "rows": int(len(working)),
            "groupings": {},
        }
        for name, keys in key_definitions.items():
            policy_result["groupings"][name] = summarize(working, keys)
        output["policies"][policy] = policy_result

    coarse = frame.groupby(["patient_id", "order_dt"], dropna=False).agg(
        strict_group_count=("source_row", lambda _: 0)
    )
    strict = (
        frame.groupby(["patient_id", "order_dt", "order_doctor_id", "department_id"], dropna=False)
        .size()
        .rename("rows")
        .reset_index()
    )
    strict_counts = (
        strict.groupby(["patient_id", "order_dt"], dropna=False)
        .size()
        .rename("strict_group_count")
    )
    output["patient_time_groups_split_by_strict_key"] = int(strict_counts.gt(1).sum())
    output["patient_time_groups_total"] = int(len(coarse))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
