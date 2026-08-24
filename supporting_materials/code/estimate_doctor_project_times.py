"""Estimate doctor-project scheduling times from report gaps with shrinkage.

The source data do not contain scan start/end timestamps. The exported values are
therefore scheduling estimates, not measured scan durations.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import analyze_p1 as p1


ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "supporting_materials" / "processed_data" / "raw_parquet"
P1_RESULTS = ROOT / "supporting_materials" / "results" / "p1"
CAPABILITY = ROOT / "supporting_materials" / "results" / "capability"
OUT = ROOT / "supporting_materials" / "results" / "doctor_project_time"


def single_project_episodes() -> pd.DataFrame:
    all_rows: list[pd.DataFrame] = []
    for source, filename in p1.SOURCE_FILES.items():
        frame = p1.load_detail(RAW / filename, source)
        valid = frame[
            frame["order_dt"].notna()
            & frame["report_dt"].notna()
            & frame["exam_doctor_id"].notna()
            & frame["machine_id"].notna()
            & frame["report_dt"].dt.normalize().between(
                p1.START_DATE, p1.VALIDATION_START - pd.Timedelta(days=1)
            )
        ].copy()
        valid["patient_key"] = valid["patient_id"].fillna("缺失_")
        missing = valid["patient_id"].isna()
        valid.loc[missing, "patient_key"] = "缺失_" + valid.loc[missing, "source_row"].astype(str)
        keys = ["source", "patient_key", "order_dt", "exam_doctor_id", "machine_id"]
        service = valid[~valid["non_service_item"]].drop_duplicates(keys + ["project_norm"])
        counts = service.groupby(keys).size().rename("unique_service_projects").reset_index()
        single = service.merge(counts, on=keys, how="left")
        single = single[single["unique_service_projects"].eq(1)].copy()
        reports = (
            valid.groupby(keys, as_index=False)["report_dt"].max()
            .merge(
                single[
                    keys
                    + [
                        "project_norm",
                        "category",
                        "duration_lower_min",
                        "duration_nominal_min",
                        "duration_upper_min",
                    ]
                ].drop_duplicates(keys),
                on=keys,
                how="inner",
                validate="one_to_one",
            )
        )
        all_rows.append(reports)
    episodes = pd.concat(all_rows, ignore_index=True)
    episodes["report_date"] = episodes["report_dt"].dt.normalize()
    episodes = episodes.sort_values(["exam_doctor_id", "report_date", "report_dt"])
    episodes["previous_report_dt"] = episodes.groupby(
        ["exam_doctor_id", "report_date"]
    )["report_dt"].shift(1)
    episodes["report_gap_min"] = (
        episodes["report_dt"] - episodes["previous_report_dt"]
    ).dt.total_seconds() / 60
    hour = episodes["report_dt"].dt.hour + episodes["report_dt"].dt.minute / 60
    return episodes[
        episodes["report_gap_min"].gt(0)
        & episodes["report_gap_min"].le(60)
        & hour.between(6, 22)
    ].copy()


def complete_doctor_project_grid(direct: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    doctors = pd.read_csv(P1_RESULTS / "doctor_efficiency_shrunk.csv", encoding="utf-8-sig")
    observed_doctors = direct[["exam_doctor_id"]].drop_duplicates()
    doctors = observed_doctors.merge(doctors, on="exam_doctor_id", how="outer", validate="one_to_one")
    doctors["has_doctor_factor_evidence"] = doctors["shrunk_relative_throughput_factor"].notna()
    doctors["valid_days"] = doctors["valid_days"].fillna(0).astype(int)
    doctors["shrunk_relative_throughput_factor"] = doctors[
        "shrunk_relative_throughput_factor"
    ].fillna(1.0)
    catalog = pd.read_csv(P1_RESULTS / "project_category_catalog.csv", encoding="utf-8-sig")
    projects = (
        catalog[~catalog["non_service_item"].astype(str).str.lower().eq("true")]
        .groupby(
            [
                "project_norm",
                "category",
                "duration_lower_min",
                "duration_nominal_min",
                "duration_upper_min",
            ],
            as_index=False,
        )["record_count"]
        .sum()
        .rename(columns={"record_count": "project_record_count"})
    )
    project_keys = [
        "project_norm",
        "category",
        "duration_lower_min",
        "duration_nominal_min",
        "duration_upper_min",
    ]
    direct_projects = direct[project_keys].drop_duplicates().assign(project_record_count=0)
    projects = (
        pd.concat([projects, direct_projects], ignore_index=True)
        .groupby(project_keys, as_index=False)["project_record_count"]
        .sum()
    )
    doctor_columns = [
        "exam_doctor_id",
        "valid_days",
        "shrunk_relative_throughput_factor",
        "factor_ci95_lower",
        "factor_ci95_upper",
        "has_doctor_factor_evidence",
    ]
    grid = doctors[doctor_columns].merge(projects, how="cross")
    return grid, doctors


def estimate_times(episodes: pd.DataFrame) -> pd.DataFrame:
    direct = (
        episodes.groupby(
            [
                "exam_doctor_id",
                "project_norm",
                "category",
                "duration_lower_min",
                "duration_nominal_min",
                "duration_upper_min",
            ],
            as_index=False,
        )["report_gap_min"]
        .agg(
            proxy_n="size",
            report_gap_mean_min="mean",
            report_gap_median_min="median",
            report_gap_q25_min=lambda values: values.quantile(0.25),
            report_gap_q75_min=lambda values: values.quantile(0.75),
        )
    )
    grid, _ = complete_doctor_project_grid(direct)
    grouped = grid.merge(
        direct,
        on=[
            "exam_doctor_id",
            "project_norm",
            "category",
            "duration_lower_min",
            "duration_nominal_min",
            "duration_upper_min",
        ],
        how="left",
        validate="one_to_one",
    )
    grouped["proxy_n"] = grouped["proxy_n"].fillna(0).astype(int)
    grouped["doctor_adjusted_nominal_min"] = (
        grouped["duration_nominal_min"]
        / grouped["shrunk_relative_throughput_factor"].fillna(1.0)
    ).clip(grouped["duration_lower_min"], grouped["duration_upper_min"])
    grouped["gap_proxy_clipped_min"] = grouped["report_gap_median_min"].clip(
        grouped["duration_lower_min"], grouped["duration_upper_min"]
    )
    grouped["gap_weight"] = grouped["proxy_n"] / (grouped["proxy_n"] + 20.0)
    gap_component = grouped["gap_proxy_clipped_min"].fillna(
        grouped["doctor_adjusted_nominal_min"]
    )
    grouped["estimated_mean_service_min"] = (
        grouped["gap_weight"] * gap_component
        + (1 - grouped["gap_weight"]) * grouped["doctor_adjusted_nominal_min"]
    ).clip(grouped["duration_lower_min"], grouped["duration_upper_min"])
    grouped["has_direct_pair_evidence"] = grouped["proxy_n"].gt(0)
    grouped["estimate_basis"] = np.select(
        [
            grouped["proxy_n"].ge(20) & grouped["has_doctor_factor_evidence"],
            grouped["proxy_n"].gt(0) & grouped["has_doctor_factor_evidence"],
            grouped["proxy_n"].gt(0),
        ],
        [
            "单项目相邻报告间隔与医生吞吐收缩加权",
            "小样本向医生调整后的题面名义时长收缩",
            "有直接组合记录但医生因子不足；向题面名义时长收缩",
        ],
        default="无直接组合记录；使用可用医生因子调整后的题面名义时长",
    )
    grouped["is_measured_scan_duration"] = False
    return grouped.sort_values(["exam_doctor_id", "category", "proxy_n"], ascending=[True, True, False])


def category_summary(estimates: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for category, frame in estimates.groupby("category"):
        direct = frame[frame["has_direct_pair_evidence"]]
        weights = direct["proxy_n"].to_numpy(dtype=float)
        direct_values = direct["estimated_mean_service_min"].to_numpy(dtype=float)
        all_values = frame["estimated_mean_service_min"].to_numpy(dtype=float)
        rows.append(
            {
                "category": category,
                "doctor_project_pairs": int(len(frame)),
                "direct_evidence_pairs": int(len(direct)),
                "valid_gap_episodes": int(weights.sum()),
                "weighted_estimated_mean_min": float(np.average(direct_values, weights=weights)),
                "estimate_p10_min": float(np.quantile(direct_values, 0.10)),
                "estimate_median_min": float(np.median(direct_values)),
                "estimate_p90_min": float(np.quantile(direct_values, 0.90)),
                "complete_estimate_p10_min": float(np.quantile(all_values, 0.10)),
                "complete_estimate_median_min": float(np.median(all_values)),
                "complete_estimate_p90_min": float(np.quantile(all_values, 0.90)),
                "minimum_estimate_min": float(all_values.min()),
                "maximum_estimate_min": float(all_values.max()),
            }
        )
    return pd.DataFrame(rows).sort_values("weighted_estimated_mean_min", ascending=False)


def machine_profile() -> pd.DataFrame:
    frame = pd.read_csv(CAPABILITY / "equipment_source_rows.csv", encoding="utf-8-sig")

    def parse_purchase(value: object) -> pd.Timestamp:
        text = str(value).strip()
        numeric = pd.to_numeric(text, errors="coerce")
        if pd.notna(numeric) and 30000 <= float(numeric) <= 60000:
            return pd.Timestamp("1899-12-30") + pd.to_timedelta(float(numeric), unit="D")
        return pd.to_datetime(text, errors="coerce")

    frame["purchase_date_parsed"] = frame["purchase_date"].map(parse_purchase)
    frame["equipment_age_years_2025_03_31"] = (
        (pd.Timestamp("2025-03-31") - frame["purchase_date_parsed"]).dt.days / 365.25
    )
    matrix = pd.read_csv(CAPABILITY / "capability_matrix.csv", encoding="utf-8-sig")
    family_columns = [column for column in matrix.columns if column not in ["machine_id", "current_room"]]
    matrix["compatible_family_count"] = matrix[family_columns].sum(axis=1)
    return frame.merge(
        matrix[["machine_id", "compatible_family_count"]],
        on="machine_id",
        how="left",
        validate="one_to_one",
    )[
        [
            "machine_id",
            "current_room",
            "machine_model",
            "purchase_date_parsed",
            "equipment_age_years_2025_03_31",
            "compatible_family_count",
        ]
    ].sort_values("machine_id")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    episodes = single_project_episodes()
    estimates = estimate_times(episodes)
    summary = category_summary(estimates)
    machines = machine_profile()
    estimates.to_csv(OUT / "doctor_project_time_estimates.csv", index=False, encoding="utf-8-sig")
    estimates[estimates["has_direct_pair_evidence"]].to_csv(
        OUT / "doctor_project_direct_evidence.csv", index=False, encoding="utf-8-sig"
    )
    summary.to_csv(OUT / "category_time_summary.csv", index=False, encoding="utf-8-sig")
    machines.to_csv(OUT / "machine_profile.csv", index=False, encoding="utf-8-sig")
    (OUT / "summary.json").write_text(
        json.dumps(
            {
                "training_start": str(p1.START_DATE.date()),
                "training_end": str((p1.VALIDATION_START - pd.Timedelta(days=1)).date()),
                "holdout_report_times_used": False,
                "is_measured_scan_duration": False,
                "valid_single_project_gaps": int(len(episodes)),
                "complete_doctor_project_estimates": int(len(estimates)),
                "direct_evidence_pairs": int(estimates["has_direct_pair_evidence"].sum()),
                "machine_count": int(len(machines)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"{len(estimates):,} complete doctor-project estimates, "
        f"{int(estimates['has_direct_pair_evidence'].sum()):,} with direct pair evidence, "
        f"from {len(episodes):,} valid single-project gaps; {len(machines)} machines",
        flush=True,
    )


if __name__ == "__main__":
    main()
