"""Merge independently generated sensitivity shards into the final result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


SCENARIOS = [
    "nominal_no_special",
    "low_doctor_q25",
    "strict_capability",
    "bladder_45min",
    "bladder_90min",
    "transfer_5min",
    "transfer_15min",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--shard-root", type=Path, required=True)
    args = parser.parse_args()

    metrics_path = args.base_dir / "policy_scenario_metrics.csv"
    daily_path = args.base_dir / "daily_service_metrics.csv"
    summary_path = args.base_dir / "summary.json"

    base_metrics = pd.read_csv(metrics_path)
    metric_parts = [base_metrics[base_metrics["scenario"].eq("main_5pct_upper")]]
    base_daily = pd.read_csv(daily_path, low_memory=False)
    daily_parts = [base_daily[base_daily["scenario"].eq("main_5pct_upper")]]

    for scenario in SCENARIOS:
        shard = args.shard_root / scenario
        shard_metrics = pd.read_csv(shard / "policy_scenario_metrics.csv")
        selected_metrics = shard_metrics[shard_metrics["scenario"].eq(scenario)]
        if len(selected_metrics) != 1:
            raise ValueError(f"{scenario}: expected one metric row, found {len(selected_metrics)}")
        metric_parts.append(selected_metrics)

        shard_daily = pd.read_csv(shard / "daily_service_metrics.csv", low_memory=False)
        selected_daily = shard_daily[shard_daily["scenario"].eq(scenario)]
        if selected_daily.empty:
            raise ValueError(f"{scenario}: daily metrics are missing")
        daily_parts.append(selected_daily)

    metrics = pd.concat(metric_parts, ignore_index=True)
    daily = pd.concat(daily_parts, ignore_index=True)
    metrics.to_csv(metrics_path, index=False, encoding="utf-8-sig")
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["metrics"] = metrics.to_dict(orient="records")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
