"""Materialize the formal sensitivity and multi-seed shard outputs."""

from __future__ import annotations

import finalize_model_audits as audits


EXPECTED_SCENARIOS = audits.ALL_SENSITIVITY_SCENARIOS


def main() -> None:
    shard_root = audits.FROZEN / "sensitivity_shards"
    actual = {
        path.name
        for path in shard_root.iterdir()
        if path.is_dir() and (path / "metrics.csv").is_file()
    } if shard_root.exists() else set()
    if actual != EXPECTED_SCENARIOS:
        raise RuntimeError(
            "sensitivity shards do not match the formal scenario set: "
            f"missing={sorted(EXPECTED_SCENARIOS - actual)}, "
            f"unexpected={sorted(actual - EXPECTED_SCENARIOS)}"
        )

    errors: dict[str, str] = {}
    p2 = audits.load_json(audits.P2 / "summary.json", errors)
    p3 = audits.load_json(audits.P3 / "selection.json", errors)
    metrics, seed_summary, preparation = audits.sensitivity_outputs(errors, p2, p3)
    if errors:
        raise RuntimeError(f"cannot materialize sensitivity shards: {errors}")
    if set(metrics["audit_scenario"].astype(str)) != EXPECTED_SCENARIOS:
        raise RuntimeError("merged sensitivity rows do not match the formal scenario set")
    if int(seed_summary.get("seed_count", 0)) != len(audits.SEED_SCENARIOS):
        raise RuntimeError("multi-seed summary does not contain all five formal seeds")
    if set(preparation["audit_scenario"].astype(str)) != {
        "preparation_item", "preparation_event",
    }:
        raise RuntimeError("preparation sensitivity pair is incomplete")
    print(f"SENSITIVITY_SCENARIOS_MATERIALIZED={len(metrics)}")


if __name__ == "__main__":
    main()
