"""Build leakage-audited patient-level inputs for the unified scheduler.

The output has three deliberate boundaries:

1. Inpatient jobs are released at their order timestamp and have a 48-hour
   deadline.
2. Outpatient and physical-exam jobs use the observed report *date* as a
   retrospective plan-day scenario and cannot be released before their order
   time. Historical report time, room and doctor never enter dispatch fields.
3. Machine feasibility is recorded per normalized project with an explicit
   evidence level. A family match is never labelled as an exact project match.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import analyze_p1 as p1
import audit_capability as capability


ROOT = Path(__file__).resolve().parents[2]
SUPPORTING = ROOT / "supporting_materials"
RAW = SUPPORTING / "processed_data" / "raw_parquet"
P1_RESULTS = SUPPORTING / "results" / "p1"
CAPABILITY_RESULTS = SUPPORTING / "results" / "capability"
OUT = SUPPORTING / "processed_data" / "unified_holdout"

TRAIN_START = pd.Timestamp("2019-03-01")
HOLDOUT_START = pd.Timestamp("2024-04-01")
HOLDOUT_END_EXCLUSIVE = pd.Timestamp("2025-04-01")
# A job can occupy resources for at most 48 hours after release.  Therefore
# only the two calendar days immediately before the holdout can affect the
# state at 2024-04-01; a longer warm-up would add computation without adding a
# physically possible carry-over.
SIMULATION_START = HOLDOUT_START - pd.Timedelta(hours=48)
DAY_START_HOUR = 8
DAY_END_HOUR = 17
SLOT_MINUTES = 5
BLADDER_PREPARATION_MINUTES = 60
SEED = 20260824

SOURCE_CODES = {"住院": "IP", "门诊": "OP", "体检": "PE"}

EQUIPMENT_RENAME = {
    "检查超声的机器ID": "machine_id",
    "彩超诊室名称": "current_room",
    "机器型号": "machine_model",
    "设备购置时间": "purchase_date",
    "检查项目": "capability_text",
}

DOCTOR_DAY_RENAME = {
    "检查人ID": "doctor_id",
    "检查日期": "date",
    "部位数": "project_count",
    "最早检查时间": "first_report",
    "最晚检查时间": "last_report",
}

# These descriptors explicitly denote a whole clinically named class in table 1.
# They are broader than exact strings, but narrower and better evidenced than a
# blanket family matrix.
GENERIC_EVIDENCE = {
    "心脏": ("心脏彩超",),
    "产科III/IV级": ("III级产科", "IV级产科", "III级产科超声检查", "IV级产科超声检查"),
    "产科I/II级": ("I级产科", "II级产科", "I级产科超声检查", "II级产科超声检查"),
    "腹部/胃肠": ("腹部彩超",),
    "血管": ("血管彩超",),
}


def as_bool(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype("string").str.lower().isin(["true", "1", "yes"])


def clean_id(series: pd.Series) -> pd.Series:
    return p1.clean_id(series).replace("", pd.NA)


def round_up_slot(timestamp: pd.Timestamp) -> pd.Timestamp:
    if pd.isna(timestamp):
        return timestamp
    return timestamp.ceil(f"{SLOT_MINUTES}min")


def release_times(events: pd.DataFrame, bladder_minutes: int) -> pd.Series:
    """Return the earliest physically available time for each event.

    A background patient whose order already exists can complete preparation
    before the 08:00 planning window opens. Therefore readiness is
    max(planning-window start, order time + preparation), not a blanket delay
    applied after 08:00.
    """
    inpatient = events["source"].eq("住院")
    release = pd.to_datetime(events["order_dt"]).map(round_up_slot)
    background_start = pd.to_datetime(events["planned_date"]) + pd.Timedelta(hours=DAY_START_HOUR)
    release.loc[~inpatient] = np.maximum(
        release.loc[~inpatient].values.astype("datetime64[ns]"),
        background_start.loc[~inpatient].values.astype("datetime64[ns]"),
    )
    prepared = (pd.to_datetime(events["order_dt"]) + pd.Timedelta(minutes=bladder_minutes)).map(
        round_up_slot
    )
    bladder = events["bladder"].astype(bool)
    release.loc[bladder] = np.maximum(
        release.loc[bladder].values.astype("datetime64[ns]"),
        prepared.loc[bladder].values.astype("datetime64[ns]"),
    )
    return pd.to_datetime(release)


def mode_date(values: pd.Series) -> pd.Timestamp:
    dates = pd.to_datetime(values, errors="coerce").dropna().dt.normalize()
    if dates.empty:
        return pd.NaT
    counts = dates.value_counts()
    return pd.Timestamp(counts[counts.eq(counts.max())].index.min())


def unique_join(values: Iterable[Any]) -> str:
    return "|".join(sorted({str(value) for value in values if pd.notna(value) and str(value)}))


def load_source(source: str, filename: str) -> pd.DataFrame:
    frame = p1.load_detail(RAW / filename, source)
    frame["patient_id"] = clean_id(frame["patient_id"])
    missing = frame["patient_id"].isna()
    frame.loc[missing, "patient_id"] = "MISSING_" + frame.loc[missing, "source_row"].astype(str)
    frame["report_date"] = frame["report_dt"].dt.normalize()

    frame = frame.sort_values("source_row", kind="stable")

    duplicate_columns = [
        "patient_id",
        "order_dt",
        "ordered_project",
        "report_dt",
        "exam_doctor_id",
        "machine_id",
    ]
    frame["is_exact_duplicate_extra"] = frame.duplicated(duplicate_columns, keep="first")
    frame = frame[~frame["is_exact_duplicate_extra"]].copy()

    event_keys = ["source", "patient_id", "order_dt"]
    event_flags = (
        frame.groupby(event_keys, dropna=False)
        .agg(
            bedside=("床旁标记", "max"),
            fasting=("空腹上午标记", "max"),
            bladder=("充盈膀胱标记", "max"),
            planned_date=("report_date", mode_date),
        )
        .reset_index()
    )
    frame = frame.merge(event_flags, on=event_keys, how="left", validate="many_to_one")
    frame = frame[~frame["non_service_item"] & frame["project_norm"].notna()].copy()
    frame = frame.drop_duplicates(event_keys + ["project_norm"], keep="first")

    # Construct the complete application event before applying the simulation
    # boundary. Filtering detail rows first can truncate a multi-project event
    # whose reports fall on different dates and can change its modal plan date.
    if source == "住院":
        keep = frame["order_dt"].between(
            SIMULATION_START, HOLDOUT_END_EXCLUSIVE, inclusive="left"
        )
    else:
        keep = frame["planned_date"].between(
            SIMULATION_START, HOLDOUT_END_EXCLUSIVE, inclusive="left"
        )
    frame = frame[keep].copy()

    keys = (
        frame[event_keys]
        .drop_duplicates()
        .sort_values(["order_dt", "patient_id"], kind="stable")
        .reset_index(drop=True)
    )
    code = SOURCE_CODES[source]
    keys["event_id"] = [f"{code}2024-{index:06d}" for index in range(1, len(keys) + 1)]
    frame = frame.merge(keys, on=event_keys, how="left", validate="many_to_one")
    return frame


def build_patient_tables() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    source_frames = [
        load_source(source, filename) for source, filename in p1.SOURCE_FILES.items()
    ]
    items = pd.concat(source_frames, ignore_index=True)
    items["bedside"] = as_bool(items["bedside"])
    items["fasting"] = as_bool(items["fasting"])
    items["bladder"] = as_bool(items["bladder"])
    items["item_index"] = items.groupby("event_id").cumcount() + 1

    events = (
        items.groupby(["event_id", "source", "patient_id", "order_dt"], as_index=False)
        .agg(
            planned_date=("planned_date", "first"),
            bedside=("bedside", "max"),
            fasting=("fasting", "max"),
            bladder=("bladder", "max"),
            service_project_count=("project_norm", "size"),
            nominal_minutes=("duration_nominal_min", "sum"),
            upper_minutes=("duration_upper_min", "sum"),
            project_names=("project_norm", unique_join),
            categories=("category", unique_join),
        )
    )

    inpatient = events["source"].eq("住院")
    events["mandatory_background"] = ~inpatient
    events["deadline_dt"] = events["order_dt"] + pd.Timedelta(hours=48)
    events.loc[~inpatient, "deadline_dt"] = (
        events.loc[~inpatient, "planned_date"] + pd.Timedelta(hours=DAY_END_HOUR)
    )
    events["release_dt"] = release_times(events, BLADDER_PREPARATION_MINUTES)
    events["deadline_dt"] = pd.to_datetime(events["deadline_dt"])

    events["evaluation_cohort"] = np.where(
        inpatient,
        events["order_dt"].between(HOLDOUT_START, HOLDOUT_END_EXCLUSIVE, inclusive="left"),
        events["planned_date"].between(HOLDOUT_START, HOLDOUT_END_EXCLUSIVE, inclusive="left"),
    )
    rng = np.random.default_rng(SEED)
    events["special_case"] = False
    # Keep the required 5% share independent of the technical warm-up window.
    # The attachment identifies no individual complex cases, so the selected
    # event IDs are a fixed scenario sample rather than inferred diagnoses.
    for cohort_value in [False, True]:
        eligible = events.index[events["evaluation_cohort"].eq(cohort_value)].to_numpy()
        special_count = int(round(0.05 * len(eligible)))
        if special_count:
            chosen = rng.choice(eligible, size=special_count, replace=False)
            events.loc[chosen, "special_case"] = True
    events["duration_scenario"] = np.where(events["special_case"], "upper", "nominal")
    event_columns = [
        "event_id",
        "source",
        "patient_id",
        "order_dt",
        "planned_date",
        "release_dt",
        "deadline_dt",
        "mandatory_background",
        "special_case",
        "duration_scenario",
        "evaluation_cohort",
        "bedside",
        "fasting",
        "bladder",
        "service_project_count",
        "nominal_minutes",
        "upper_minutes",
        "project_names",
        "categories",
    ]
    events = events[event_columns].sort_values(["release_dt", "event_id"], kind="stable")

    items = items[
        [
            "event_id",
            "item_index",
            "source_row",
            "project_norm",
            "category",
            "duration_lower_min",
            "duration_nominal_min",
            "duration_upper_min",
            "bedside",
            "fasting",
            "bladder",
        ]
    ].copy()
    diagnostics = {
        "events": {source: int(count) for source, count in events["source"].value_counts().items()},
        "items": {source: int(count) for source, count in items.merge(events[["event_id", "source"]], on="event_id")["source"].value_counts().items()},
        "special_case_count": int(events["special_case"].sum()),
        "special_case_share": float(events["special_case"].mean()),
        "background_scenario_basis": "report date defines the retrospective plan day; release is no earlier than observed order time; report time, room and doctor are excluded",
        "bladder_preparation_minutes": BLADDER_PREPARATION_MINUTES,
        "bladder_readiness_rule": "max(plan-day start, order time plus preparation) for background; order time plus preparation for inpatient",
    }
    return events, items, diagnostics


def load_equipment() -> pd.DataFrame:
    frame = pd.read_parquet(RAW / "equipment_capability.parquet").rename(columns=EQUIPMENT_RENAME)
    frame["machine_id"] = clean_id(frame["machine_id"])
    frame["current_room"] = p1.clean_text(frame["current_room"])
    frame = frame[frame["machine_id"].str.fullmatch(r"\d+", na=False)].copy()
    if frame["machine_id"].nunique() != 22:
        raise ValueError("表1现行机器数量不是22台")
    return frame


def evidence_table(equipment: pd.DataFrame) -> pd.DataFrame:
    rules = capability.load_rules(P1_RESULTS / "category_rules.csv")
    rows: list[dict[str, Any]] = []
    for machine in equipment.itertuples(index=False):
        for raw_token in capability.split_capabilities(machine.capability_text):
            token = capability.normalize_project_text(raw_token)
            category_name, _, _ = capability.classify_token(token, rules)
            rows.append(
                {
                    "machine_id": str(machine.machine_id),
                    "current_room": machine.current_room,
                    "evidence_project": raw_token,
                    "evidence_norm": token,
                    "evidence_category": category_name,
                }
            )
    return pd.DataFrame(rows)


def explicit_generic_match(project: str, category_name: str, evidence: str) -> bool:
    candidates = GENERIC_EVIDENCE.get(category_name, ())
    return any(candidate in evidence for candidate in candidates)


def semantic_core(value: str) -> str:
    """Remove presentation words while retaining anatomy/procedure semantics."""
    text = capability.normalize_project_text(value)
    text = re.sub(
        r"彩色多普勒|浅表器官|超声常规检查|常规检查|超声检查|彩超|B超|"
        r"临床操作的|主任检查|主任|加收|减免",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"[\[\]()（）,:：，、+\-_/\\\s]", "", text)


def project_machine_matches(items: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    equipment = load_equipment()
    evidence = evidence_table(equipment)
    projects = items[["project_norm", "category"]].drop_duplicates().sort_values("project_norm")
    matches: list[dict[str, Any]] = []

    for project_row in projects.itertuples(index=False):
        project = capability.normalize_project_text(project_row.project_norm)
        category_name = str(project_row.category)
        category_evidence = evidence[evidence["evidence_category"].eq(category_name)]
        for row in category_evidence.itertuples(index=False):
            token = str(row.evidence_norm)
            rule: str | None = None
            if project == token:
                rule = "exact_project"
            elif min(len(project), len(token)) >= 6 and (project in token or token in project):
                rule = "specific_text_containment"
            elif min(len(semantic_core(project)), len(semantic_core(token))) >= 4 and (
                semantic_core(project) in semantic_core(token)
                or semantic_core(token) in semantic_core(project)
            ):
                rule = "semantic_core_match"
            elif explicit_generic_match(project, category_name, token):
                rule = "explicit_generic_descriptor"
            if rule:
                matches.append(
                    {
                        "project_norm": project_row.project_norm,
                        "category": category_name,
                        "machine_id": str(row.machine_id),
                        "current_room": row.current_room,
                        "match_level": "strict",
                        "match_rule": rule,
                        "evidence_project": row.evidence_project,
                    }
                )

        # Machine 7 explicitly says it performs bedside ultrasound projects.
        matches.append(
            {
                "project_norm": project_row.project_norm,
                "category": category_name,
                "machine_id": "7",
                "current_room": equipment.loc[equipment["machine_id"].eq("7"), "current_room"].iloc[0],
                "match_level": "bedside_only",
                "match_rule": "explicit_bedside_descriptor",
                "evidence_project": "带有床旁的超声项目",
            }
        )

    match_frame = pd.DataFrame(matches).drop_duplicates(
        ["project_norm", "machine_id", "match_level"], keep="first"
    )

    # A fallback is retained only for projects for which table 1 has no strict
    # text match. It remains labelled and is tested separately; it is never
    # described as project-level evidence.
    strict_counts = (
        match_frame[match_frame["match_level"].eq("strict")]
        .groupby("project_norm")["machine_id"]
        .nunique()
    )
    unmatched = projects[~projects["project_norm"].isin(strict_counts.index)]
    fallback_rows: list[dict[str, Any]] = []
    for project_row in unmatched.itertuples(index=False):
        subset = evidence[evidence["evidence_category"].eq(project_row.category)]
        for row in subset.drop_duplicates("machine_id").itertuples(index=False):
            fallback_rows.append(
                {
                    "project_norm": project_row.project_norm,
                    "category": project_row.category,
                    "machine_id": str(row.machine_id),
                    "current_room": row.current_room,
                    "match_level": "category_fallback",
                    "match_rule": "same_category_without_project_text_match",
                    "evidence_project": row.evidence_project,
                }
            )
    if fallback_rows:
        match_frame = pd.concat([match_frame, pd.DataFrame(fallback_rows)], ignore_index=True)

    rows: list[dict[str, Any]] = []
    grouped = match_frame.groupby(["project_norm", "category"], sort=False)
    for (project, category_name), group in grouped:
        strict_rooms = sorted(
            group.loc[group["match_level"].eq("strict"), "machine_id"].unique(), key=int
        )
        fallback_rooms = sorted(
            group.loc[group["match_level"].eq("category_fallback"), "machine_id"].unique(), key=int
        )
        rows.append(
            {
                "project_norm": project,
                "category": category_name,
                "strict_rooms": "|".join(strict_rooms),
                "fallback_rooms": "|".join(fallback_rooms),
                "strict_room_count": len(strict_rooms),
                "fallback_room_count": len(fallback_rooms),
                "uses_fallback_if_nonbedside": len(strict_rooms) == 0,
            }
        )
    summary = pd.DataFrame(rows)
    return match_frame.sort_values(["project_norm", "match_level", "machine_id"]), summary


def build_training_room_scarcity() -> pd.DataFrame:
    """Estimate room demand pressure from the frozen training catalog only."""
    catalog = pd.read_csv(
        P1_RESULTS / "project_category_catalog.csv", encoding="utf-8-sig", low_memory=False
    )
    non_service = catalog["non_service_item"].astype(str).str.lower().eq("true")
    catalog = catalog[~non_service].copy()
    _, project_summary = project_machine_matches(catalog[["project_norm", "category"]])
    demand = (
        catalog.groupby(
            ["project_norm", "category", "duration_nominal_min"], as_index=False
        )["record_count"]
        .sum()
        .merge(
            project_summary,
            on=["project_norm", "category"],
            how="left",
            validate="many_to_one",
        )
    )
    room_weight: dict[str, float] = defaultdict(float)
    for row in demand.itertuples(index=False):
        if "床旁" in str(row.project_norm):
            rooms = ["7"]
        else:
            room_text = row.strict_rooms if int(row.strict_room_count) > 0 else row.fallback_rooms
            rooms = [part for part in str(room_text).split("|") if part and part != "nan"]
        if not rooms:
            continue
        contribution = float(row.record_count) * float(row.duration_nominal_min) / len(rooms)
        for room in rooms:
            room_weight[room] += contribution
    return pd.DataFrame(
        [
            {
                "room_id": room,
                "training_weighted_demand_minutes": weight,
                "evidence_period_end": str((HOLDOUT_START - pd.Timedelta(days=1)).date()),
            }
            for room, weight in sorted(room_weight.items(), key=lambda pair: int(pair[0]))
        ]
    )


def slot_clock(slot_index: int) -> tuple[int, int]:
    if slot_index < 48:
        minute = 8 * 60 + slot_index * SLOT_MINUTES
    else:
        minute = 13 * 60 + (slot_index - 48) * SLOT_MINUTES
    return minute // 60, minute % 60


def clock_to_slot(timestamp: pd.Timestamp, side: str) -> int:
    minute = timestamp.hour * 60 + timestamp.minute + timestamp.second / 60
    if minute < 12 * 60:
        raw = (minute - 8 * 60) / SLOT_MINUTES
        base = 0
    else:
        raw = (minute - 13 * 60) / SLOT_MINUTES
        base = 48
    value = math.floor(raw) if side == "end" else math.ceil(raw)
    return int(np.clip(base + value, base, base + 48))


def build_doctor_slot_capacity() -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_parquet(RAW / "doctor_day.parquet").rename(columns=DOCTOR_DAY_RENAME)
    frame["doctor_id"] = clean_id(frame["doctor_id"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", format="mixed").dt.normalize()
    frame["first_report"] = pd.to_datetime(frame["first_report"], errors="coerce", format="mixed")
    frame["last_report"] = pd.to_datetime(frame["last_report"], errors="coerce", format="mixed")
    frame = frame[
        frame["date"].between(TRAIN_START, HOLDOUT_START, inclusive="left")
        & frame["doctor_id"].notna()
        & frame["first_report"].notna()
        & frame["last_report"].notna()
    ].copy()
    frame = (
        frame.groupby(["date", "doctor_id"], as_index=False)
        .agg(first_report=("first_report", "min"), last_report=("last_report", "max"))
    )

    calendar = pd.date_range(TRAIN_START, HOLDOUT_START - pd.Timedelta(days=1), freq="D")
    daily_arrays = {date: np.zeros(96, dtype=np.int16) for date in calendar}
    for row in frame.itertuples(index=False):
        date = pd.Timestamp(row.date)
        first_observed = pd.Timestamp(row.first_report)
        last_observed = pd.Timestamp(row.last_report)
        first_minute = first_observed.hour * 60 + first_observed.minute
        last_minute = last_observed.hour * 60 + last_observed.minute
        if 7 * 60 <= first_minute <= 9 * 60:
            start = date + pd.Timedelta(hours=8)
        elif 12 * 60 + 30 <= first_minute <= 14 * 60:
            start = date + pd.Timedelta(hours=13)
        else:
            start = first_observed - pd.Timedelta(minutes=10)
        if 11 * 60 <= last_minute <= 12 * 60 + 30 and first_minute < 12 * 60:
            end = date + pd.Timedelta(hours=12)
        elif 16 * 60 <= last_minute <= 19 * 60:
            end = date + pd.Timedelta(hours=17)
        else:
            end = last_observed
        for block_start, block_end, offset in [(8, 12, 0), (13, 17, 48)]:
            block_start_dt = date + pd.Timedelta(hours=block_start)
            block_end_dt = date + pd.Timedelta(hours=block_end)
            overlap_start = max(start, block_start_dt)
            overlap_end = min(end, block_end_dt)
            if overlap_end <= overlap_start:
                continue
            first_slot = clock_to_slot(overlap_start, "start")
            last_slot = clock_to_slot(overlap_end, "end")
            first_slot = max(first_slot, offset)
            last_slot = min(last_slot, offset + 48)
            if last_slot > first_slot:
                daily_arrays[date][first_slot:last_slot] += 1

    daily_rows: list[dict[str, Any]] = []
    for date, counts in daily_arrays.items():
        for slot_index, count in enumerate(counts):
            hour, minute = slot_clock(slot_index)
            daily_rows.append(
                {
                    "date": date,
                    "weekday": date.dayofweek,
                    "slot_index": slot_index,
                    "slot_time": f"{hour:02d}:{minute:02d}",
                    "active_doctor_proxy": int(count),
                }
            )
    daily = pd.DataFrame(daily_rows)
    slot = (
        daily.groupby(["weekday", "slot_index", "slot_time"], as_index=False)
        .agg(
            training_days=("date", "nunique"),
            median_active_doctors=("active_doctor_proxy", "median"),
            q25_active_doctors=("active_doctor_proxy", lambda values: values.quantile(0.25)),
            q75_active_doctors=("active_doctor_proxy", lambda values: values.quantile(0.75)),
            mean_active_doctors=("active_doctor_proxy", "mean"),
        )
    )
    slot["capacity_main"] = np.minimum(
        np.rint(slot["median_active_doctors"]).astype(int), 22
    )
    slot["capacity_low"] = np.minimum(
        np.floor(slot["q25_active_doctors"]).astype(int), 22
    )
    return slot, daily


def attach_room_sets(items: pd.DataFrame, project_summary: pd.DataFrame) -> pd.DataFrame:
    merged = items.merge(
        project_summary,
        on=["project_norm", "category"],
        how="left",
        validate="many_to_one",
    )
    if merged["strict_room_count"].isna().any():
        raise ValueError("存在未进入能力匹配的项目")
    merged["compatible_rooms"] = np.where(
        merged["bedside"],
        "7",
        np.where(
            merged["strict_room_count"].gt(0),
            merged["strict_rooms"],
            merged["fallback_rooms"],
        ),
    )
    merged["capability_level"] = np.where(
        merged["bedside"],
        "bedside_explicit",
        np.where(merged["strict_room_count"].gt(0), "strict_project", "category_fallback"),
    )
    if merged["compatible_rooms"].fillna("").eq("").any():
        examples = merged.loc[merged["compatible_rooms"].fillna("").eq(""), "project_norm"].head().tolist()
        raise ValueError(f"存在无任何兼容机器的项目: {examples}")
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUT)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    events, items, diagnostics = build_patient_tables()
    match_rows, project_summary = project_machine_matches(items)
    items = attach_room_sets(items, project_summary)
    slot_capacity, daily_capacity = build_doctor_slot_capacity()
    room_scarcity = build_training_room_scarcity()

    events.to_csv(args.output_dir / "events.csv", index=False, encoding="utf-8-sig")
    items.to_csv(args.output_dir / "items.csv", index=False, encoding="utf-8-sig")
    match_rows.to_csv(
        args.output_dir / "project_machine_evidence.csv", index=False, encoding="utf-8-sig"
    )
    project_summary.to_csv(
        args.output_dir / "project_machine_summary.csv", index=False, encoding="utf-8-sig"
    )
    slot_capacity.to_csv(
        args.output_dir / "doctor_slot_capacity.csv", index=False, encoding="utf-8-sig"
    )
    daily_capacity.to_csv(
        args.output_dir / "doctor_slot_capacity_training_days.csv",
        index=False,
        encoding="utf-8-sig",
    )
    room_scarcity.to_csv(
        args.output_dir / "room_scarcity_training.csv", index=False, encoding="utf-8-sig"
    )

    event_source = events[["event_id", "source"]]
    item_levels = items.merge(event_source, on="event_id", how="left")
    diagnostics["capability"] = {
        "unique_projects": int(project_summary["project_norm"].nunique()),
        "projects_with_strict_match": int(project_summary["strict_room_count"].gt(0).sum()),
        "projects_using_category_fallback": int(project_summary["strict_room_count"].eq(0).sum()),
        "item_share_strict_or_bedside": float(
            item_levels["capability_level"].ne("category_fallback").mean()
        ),
        "fallback_item_share_by_source": {
            source: float(group["capability_level"].eq("category_fallback").mean())
            for source, group in item_levels.groupby("source")
        },
    }
    diagnostics["doctor_capacity"] = {
        "method": "weekday-by-5-minute median of training-day active session proxy",
        "session_reconstruction": "first activity at 07:00-09:00 snaps to 08:00; 12:30-14:00 snaps to 13:00; last activity at 11:00-12:30 snaps to 12:00 and 16:00-19:00 snaps to 17:00; otherwise retain observed interval with a 10-minute start expansion",
        "room_cap": 22,
        "current_doctor_count_from_problem": 33,
        "main_capacity_min": int(slot_capacity["capacity_main"].min()),
        "main_capacity_max": int(slot_capacity["capacity_main"].max()),
    }
    diagnostics["time_scope"] = {
        "training_start": str(TRAIN_START.date()),
        "training_end_exclusive": str(HOLDOUT_START.date()),
        "holdout_start": str(HOLDOUT_START.date()),
        "holdout_end_exclusive": str(HOLDOUT_END_EXCLUSIVE.date()),
        "simulation_start": str(SIMULATION_START.date()),
        "warmup_days": int((HOLDOUT_START - SIMULATION_START).days),
    }
    diagnostics["room_scarcity_boundary"] = {
        "source": "2019-03-01 to 2024-03-31 frozen training project catalog",
        "holdout_project_mix_used": False,
        "measure": "record_count times nominal_minutes divided equally across compatible rooms",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(diagnostics, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
