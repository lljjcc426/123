"""Build a reproducible department-level demand summary for Problem 1.

The source workbooks are not modified.  Department names are unavailable, so
all outputs retain the anonymous department identifiers supplied in the data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from analyze_p1 import END_DATE, SOURCE_FILES, START_DATE, VALIDATION_START, load_detail


def choose_event_department(service_rows: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Assign each application proxy to one department without double counting."""
    event_keys = ["source", "patient_key", "order_dt"]
    candidate_counts = service_rows.groupby(event_keys, dropna=False)["department_id"].nunique()
    mixed_department_events = int((candidate_counts > 1).sum())

    # Preserve the source ordering and use the first actual service project's
    # department.  This avoids letting exact duplicate rows vote multiple times.
    chosen = (
        service_rows.sort_values(event_keys + ["source_row"])
        .drop_duplicates(event_keys, keep="first")
        [event_keys + ["department_id"]]
    )
    return chosen, mixed_department_events


def build_summary(
    raw_dir: Path, end_date: pd.Timestamp
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    all_departments: list[pd.DataFrame] = []
    overview_rows: list[dict] = []
    metadata: dict = {
        "date_range": [START_DATE.date().isoformat(), end_date.date().isoformat()],
        "event_proxy": "source + patient_id + exact order datetime",
        "department_attribution": "department on the first source-ordered service project row",
        "sources": {},
    }

    for source, filename in SOURCE_FILES.items():
        frame = load_detail(raw_dir / filename, source)
        frame = frame[
            frame["order_dt"].notna()
            & frame["order_dt"].dt.normalize().between(START_DATE, end_date)
        ].copy()
        frame["patient_key"] = frame["patient_id"]
        missing_patient = frame["patient_key"].isna()
        frame.loc[missing_patient, "patient_key"] = (
            "missing_row_" + frame.index[missing_patient].astype(str)
        )
        frame["department_id"] = frame["department_id"].fillna("缺失")

        event_keys = ["source", "patient_key", "order_dt"]
        service_rows = frame[~frame["non_service_item"]].copy()
        chosen, mixed_count = choose_event_department(service_rows)

        unique_projects = service_rows.drop_duplicates(event_keys + ["project_norm"])
        event_workload = (
            unique_projects.groupby(event_keys, dropna=False)
            .agg(
                unique_service_projects=("project_norm", "size"),
                nominal_workload_min=("duration_nominal_min", "sum"),
                upper_workload_min=("duration_upper_min", "sum"),
            )
            .reset_index()
        )
        events = chosen.merge(event_workload, on=event_keys, how="inner", validate="one_to_one")

        summary = (
            events.groupby(["source", "department_id"], dropna=False)
            .agg(
                service_event_count=("order_dt", "size"),
                unique_service_projects=("unique_service_projects", "sum"),
                nominal_workload_min=("nominal_workload_min", "sum"),
                upper_workload_min=("upper_workload_min", "sum"),
            )
            .reset_index()
        )
        total_events = int(summary["service_event_count"].sum())
        summary["event_share"] = summary["service_event_count"] / total_events
        summary["mean_nominal_min_per_event"] = (
            summary["nominal_workload_min"] / summary["service_event_count"]
        )
        summary = summary.sort_values(
            ["service_event_count", "department_id"], ascending=[False, True]
        ).reset_index(drop=True)
        summary["rank"] = summary.index + 1
        summary["cumulative_event_share"] = summary["event_share"].cumsum()
        summary = summary[
            [
                "source",
                "rank",
                "department_id",
                "service_event_count",
                "event_share",
                "cumulative_event_share",
                "unique_service_projects",
                "nominal_workload_min",
                "upper_workload_min",
                "mean_nominal_min_per_event",
            ]
        ]
        all_departments.append(summary)

        top = summary.head(12)
        known_departments = summary[summary["department_id"] != "缺失"]
        missing_department_events = int(
            summary.loc[summary["department_id"] == "缺失", "service_event_count"].sum()
        )
        overview_rows.append(
            {
                "source": source,
                "service_event_count": total_events,
                "known_department_count": int(known_departments["department_id"].nunique()),
                "missing_department_event_count": missing_department_events,
                "top_6_event_share": float(summary.head(6)["event_share"].sum()),
                "top_12_event_share": float(top["event_share"].sum()),
                "top_6_department_ids": ",".join(summary.head(6)["department_id"].astype(str)),
                "top_6_event_counts": ",".join(
                    summary.head(6)["service_event_count"].astype(str)
                ),
                "mixed_department_event_count": mixed_count,
            }
        )
        metadata["sources"][source] = {
            "official_rows": int(len(frame)),
            "service_rows": int(len(service_rows)),
            "service_events": total_events,
            "known_department_count": int(known_departments["department_id"].nunique()),
            "missing_department_events": missing_department_events,
            "mixed_department_events": mixed_count,
        }

    return pd.concat(all_departments, ignore_index=True), pd.DataFrame(overview_rows), metadata


def main() -> None:
    parser = argparse.ArgumentParser()
    root_default = Path(__file__).resolve().parents[2]
    parser.add_argument("--raw-dir", type=Path, default=root_default / "supporting_materials/processed_data/raw_parquet")
    parser.add_argument("--output-dir", type=Path, default=root_default / "supporting_materials/results/p1")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    training_end = VALIDATION_START - pd.Timedelta(days=1)
    summary, overview, metadata = build_summary(args.raw_dir, training_end)
    full_summary, full_overview, full_metadata = build_summary(args.raw_dir, END_DATE)
    summary.to_csv(args.output_dir / "department_demand_summary.csv", index=False, encoding="utf-8-sig")
    overview.to_csv(args.output_dir / "department_demand_overview.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(
        args.output_dir / "department_demand_summary_train.csv", index=False, encoding="utf-8-sig"
    )
    overview.to_csv(
        args.output_dir / "department_demand_overview_train.csv", index=False, encoding="utf-8-sig"
    )
    full_summary.to_csv(
        args.output_dir / "department_demand_summary_full_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    full_overview.to_csv(
        args.output_dir / "department_demand_overview_full_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    metadata["boundary"] = {
        "authoritative_training_end": training_end.date().isoformat(),
        "full_audit_end": END_DATE.date().isoformat(),
        "holdout_used_for_configuration": False,
    }
    metadata["full_period_audit"] = full_metadata
    with (args.output_dir / "department_demand_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)

    print(overview.to_string(index=False))


if __name__ == "__main__":
    main()
