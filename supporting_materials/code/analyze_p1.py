"""P1 demand, project-family, and workload-proxy analysis.

The source workbooks and frozen Parquet files are read-only inputs. Results and
figures are written below supporting_materials by default.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SUPPORTING_DIR = ROOT / "supporting_materials"
SEED = 20260823
START_DATE = pd.Timestamp("2019-03-01")
END_DATE = pd.Timestamp("2025-03-31")
VALIDATION_START = pd.Timestamp("2024-04-01")
VALIDATION_END = pd.Timestamp("2025-03-31")

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

SOURCE_FILES = {
    "住院": "inpatient.parquet",
    "门诊": "outpatient.parquet",
    "体检": "physical_exam.parquet",
}

NON_SERVICE_PATTERN = (
    r"^(?:床旁(?:B超检查|彩色多普勒超声检查)加收|"
    r"彩色胶片打印|超声计算机图文报告)$"
)

# The first matching rule wins. Obstetric rules precede cardiac because
# "胎儿心脏" is an obstetric level-IV item rather than a routine cardiac item.
CATEGORY_RULES = [
    {
        "category": "非服务计费/报告项",
        "pattern": NON_SERVICE_PATTERN,
        "basis": "整条内容仅为床旁加收、胶片打印或图文报告，不单独占用扫查时间；床旁标记仍保留",
        "lower": 0.0,
        "nominal": 0.0,
        "upper": 0.0,
    },
    {
        "category": "产科III/IV级",
        "pattern": r"(?:III|IV|\u2162|\u2163|三|四)级产科|胎儿心脏|系统产前超声",
        "basis": "题面明确III/IV级产科为30--40分钟；胎儿心脏归入IV级资源族",
        "lower": 30.0,
        "nominal": 35.0,
        "upper": 40.0,
    },
    {
        "category": "产科I/II级",
        "pattern": r"(?:I|II|\u2160|\u2161|一|二)级产科|早孕|胎儿生物物理|母胎医学|宫颈管长度|产科超声",
        "basis": "题面明确I/II级产科为15--20分钟；其余产科筛查按同资源族管理",
        "lower": 15.0,
        "nominal": 17.5,
        "upper": 20.0,
    },
    {
        "category": "心脏",
        "pattern": r"心脏|心包|心动图|冠脉|室壁|瓣膜|经食道|经食管",
        "basis": "题面明确心脏超声为10--15分钟；心脏声学造影仍属于心脏项目，故优先于一般“造影”规则",
        "lower": 10.0,
        "nominal": 12.5,
        "upper": 15.0,
    },
    {
        "category": "介入/定位",
        "pattern": r"穿刺|活检|置管|造影|定位|介入|引导",
        "basis": "在排除心脏项目后，操作性项目按介入/定位资源管理；题面未另给时长，采用其他项目区间",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
    {
        "category": "血管",
        "pattern": r"血管|动脉|静脉|大隐|小隐|血流图|加血流",
        "basis": "由项目名称识别血管专用资源族；题面未另给时长，采用其他项目区间",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
    {
        "category": "经阴道/腔内",
        "pattern": r"经阴道|腔内彩超|妇科B超（经阴道）|妇科B超\(经阴道\)",
        "basis": "由检查路径识别腔内资源族；题面未另给时长，采用其他项目区间",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
    {
        "category": "泌尿/经腹妇科",
        "pattern": r"泌尿|输尿管|膀胱|前列腺|双肾|肾彩超|尿量|经腹妇科|妇科B超（经腹）|妇科B超\(经腹\)|盆底",
        "basis": "题面要求泌尿系和经腹妇科考虑充盈膀胱约束；时长采用其他项目区间",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
    {
        "category": "腹部/胃肠",
        "pattern": r"腹部|腹水|腹盆|肝|胆|胰|脾|胃|肠道|阑尾|肠系膜|腹腔|腹膜后|膜腹后|肾上腺",
        "basis": "题面要求腹部及肠系膜项目空腹并优先上午；时长采用其他项目区间",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
    {
        "category": "浅表器官",
        "pattern": r"甲状腺|甲状旁腺|乳腺|淋巴结|体表|包块|阴囊|睾丸|附睾|涎腺|浅表|腹股沟|双眼",
        "basis": "由项目部位识别通用浅表资源族；时长采用其他项目区间",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
    {
        "category": "儿科专项",
        "pattern": r"婴儿头颅|新生儿|髋关节",
        "basis": "设备清单显示儿科专项能力差异；题面未另给时长，采用其他项目区间",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
    {
        "category": "一般其他",
        "pattern": r".*",
        "basis": "未命中前述资源族，按题面其他项目5--10分钟",
        "lower": 5.0,
        "nominal": 7.5,
        "upper": 10.0,
    },
]

CATEGORY_ORDER = [rule["category"] for rule in CATEGORY_RULES]
CATEGORY_RANK = {category: index for index, category in enumerate(reversed(CATEGORY_ORDER))}
DURATION = {
    rule["category"]: (rule["lower"], rule["nominal"], rule["upper"])
    for rule in CATEGORY_RULES
}

FLAG_PATTERNS = {
    "床旁标记": r"床旁",
    "空腹上午标记": r"腹部|肝胆|胃肠|肠道|阑尾|肠系膜|胰|脾",
    "充盈膀胱标记": r"泌尿|输尿管|膀胱|前列腺|经腹妇科|妇科B超（经腹）|妇科B超\(经腹\)|盆底",
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
    seconds = (
        pd.to_numeric(parts["hour"], errors="coerce") * 3600
        + pd.to_numeric(parts["minute"], errors="coerce") * 60
        + pd.to_numeric(parts["second"], errors="coerce").fillna(0)
    )
    return dates + pd.to_timedelta(seconds, unit="s")


def normalize_project(series: pd.Series) -> pd.Series:
    result = clean_text(series).fillna("")
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
        result = result.str.replace(old, new, regex=False)
    result = result.str.replace(r"^\[|\]$", "", regex=True)
    result = result.str.replace(r",(?:憋尿彩超|心脏彩超|彩超|B超)$", "", regex=True)
    return result.replace("", pd.NA)


def expand_embedded_project_lists(frame: pd.DataFrame) -> pd.DataFrame:
    """Split the source system's explicit ``][`` multi-item encoding.

    A single order field can contain several separately billed examinations,
    encoded as ``[item,modality][item,modality]``.  Only the bracket boundary
    is used as a separator; commas and Chinese enumeration marks inside an
    examination name are retained.  This preserves compound anatomy names
    while making the scheduling task count agree with the source semantics.
    """
    expanded = frame.copy()
    expanded["ordered_project_original"] = expanded["ordered_project"]
    expanded["ordered_project"] = clean_text(expanded["ordered_project"]).str.split(
        r"\]\s*\[", regex=True
    )
    expanded = expanded.explode("ordered_project", ignore_index=True)
    expanded["ordered_project"] = (
        clean_text(expanded["ordered_project"])
        .str.replace(r"^[\[\],]+|[\[\],]+$", "", regex=True)
    )
    expanded["source_component_index"] = expanded.groupby("source_row").cumcount() + 1
    return expanded


def classify_projects(series: pd.Series) -> pd.DataFrame:
    normalized = normalize_project(series)
    category = pd.Series("一般其他", index=series.index, dtype="string")
    unmatched = pd.Series(True, index=series.index)
    for rule in CATEGORY_RULES[:-1]:
        hit = normalized.str.contains(rule["pattern"], case=False, regex=True, na=False) & unmatched
        category.loc[hit] = rule["category"]
        unmatched.loc[hit] = False
    result = pd.DataFrame({"project_norm": normalized, "category": category})
    result["non_service_item"] = normalized.str.fullmatch(NON_SERVICE_PATTERN, na=False)
    for flag, pattern in FLAG_PATTERNS.items():
        result[flag] = normalized.str.contains(pattern, regex=True, na=False)
    result["duration_lower_min"] = result["category"].map(lambda x: DURATION[x][0])
    result["duration_nominal_min"] = result["category"].map(lambda x: DURATION[x][1])
    result["duration_upper_min"] = result["category"].map(lambda x: DURATION[x][2])
    return result


def load_detail(path: Path, source: str) -> pd.DataFrame:
    frame = pd.read_parquet(path).rename(columns=DETAIL_RENAME)
    frame = expand_embedded_project_lists(frame)
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
    frame["source"] = source
    classes = classify_projects(frame["ordered_project"])
    frame = pd.concat([frame, classes], axis=1)
    frame["category_rank"] = frame["category"].map(CATEGORY_RANK).fillna(0).astype(int)
    frame["category_score"] = frame["duration_nominal_min"] * 100 + frame["category_rank"]
    return frame


def make_project_catalog(
    frame: pd.DataFrame,
    start_date: pd.Timestamp = START_DATE,
    end_date: pd.Timestamp = END_DATE,
) -> pd.DataFrame:
    frame = frame[
        frame["order_dt"].notna()
        & frame["order_dt"].dt.normalize().between(start_date, end_date)
    ].copy()
    columns = [
        "source",
        "ordered_project",
        "project_norm",
        "category",
        "床旁标记",
        "空腹上午标记",
        "充盈膀胱标记",
        "non_service_item",
        "duration_lower_min",
        "duration_nominal_min",
        "duration_upper_min",
    ]
    return (
        frame.groupby(columns, dropna=False)
        .size()
        .rename("record_count")
        .reset_index()
        .sort_values(["source", "record_count"], ascending=[True, False])
    )


def make_order_episodes(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame[
        frame["order_dt"].notna()
        & frame["order_dt"].dt.normalize().between(START_DATE, END_DATE)
    ].copy()
    valid["patient_key"] = valid["patient_id"].fillna("缺失_")
    missing = valid["patient_id"].isna()
    valid.loc[missing, "patient_key"] = "缺失_" + valid.loc[missing, "source_row"].astype(str)
    keys = ["source", "patient_key", "order_dt"]
    summary = (
        valid.groupby(keys, dropna=False)
        .agg(
            project_row_count=("source_row", "size"),
            category_count=("category", "nunique"),
            nonservice_record_count=("non_service_item", "sum"),
            bedside=("床旁标记", "max"),
            fasting_before_10=("空腹上午标记", "max"),
            requires_bladder=("充盈膀胱标记", "max"),
        )
        .reset_index()
    )
    unique_projects = valid.drop_duplicates(keys + ["project_norm"]).copy()
    service_counts = (
        unique_projects[~unique_projects["non_service_item"]]
        .groupby(keys, dropna=False)
        .size()
        .rename("unique_project_count")
        .reset_index()
    )
    nonservice_counts = (
        unique_projects[unique_projects["non_service_item"]]
        .groupby(keys, dropna=False)
        .size()
        .rename("unique_nonservice_item_count")
        .reset_index()
    )
    workload = (
        unique_projects.groupby(keys, dropna=False)
        .agg(
            workload_lower_min=("duration_lower_min", "sum"),
            nominal_workload_min=("duration_nominal_min", "sum"),
            workload_upper_min=("duration_upper_min", "sum"),
        )
        .reset_index()
    )
    primary = (
        valid.sort_values("category_score")
        .drop_duplicates(keys, keep="last")[keys + ["category"]]
        .rename(columns={"category": "primary_category"})
    )
    result = (
        summary.merge(service_counts, on=keys, how="left")
        .merge(nonservice_counts, on=keys, how="left")
        .merge(workload, on=keys, how="left")
        .merge(primary, on=keys, how="left")
    )
    result[["unique_project_count", "unique_nonservice_item_count"]] = result[
        ["unique_project_count", "unique_nonservice_item_count"]
    ].fillna(0).astype(int)
    return result


def make_report_episodes(frame: pd.DataFrame) -> pd.DataFrame:
    valid = frame[
        frame["order_dt"].notna()
        & frame["report_dt"].notna()
        & frame["exam_doctor_id"].notna()
        & frame["machine_id"].notna()
    ].copy()
    valid["patient_key"] = valid["patient_id"].fillna("缺失_")
    missing = valid["patient_id"].isna()
    valid.loc[missing, "patient_key"] = "缺失_" + valid.loc[missing, "source_row"].astype(str)
    keys = ["source", "patient_key", "order_dt", "exam_doctor_id", "machine_id"]
    summary = (
        valid.groupby(keys, dropna=False)
        .agg(
            report_dt=("report_dt", "max"),
            project_row_count=("source_row", "size"),
            category_count=("category", "nunique"),
            nonservice_record_count=("non_service_item", "sum"),
            bedside=("床旁标记", "max"),
            fasting_before_10=("空腹上午标记", "max"),
            requires_bladder=("充盈膀胱标记", "max"),
        )
        .reset_index()
    )
    unique_projects = valid.drop_duplicates(keys + ["project_norm"]).copy()
    service_counts = (
        unique_projects[~unique_projects["non_service_item"]]
        .groupby(keys, dropna=False)
        .size()
        .rename("unique_project_count")
        .reset_index()
    )
    nonservice_counts = (
        unique_projects[unique_projects["non_service_item"]]
        .groupby(keys, dropna=False)
        .size()
        .rename("unique_nonservice_item_count")
        .reset_index()
    )
    workload = (
        unique_projects.groupby(keys, dropna=False)
        .agg(
            workload_lower_min=("duration_lower_min", "sum"),
            nominal_workload_min=("duration_nominal_min", "sum"),
            workload_upper_min=("duration_upper_min", "sum"),
        )
        .reset_index()
    )
    primary = (
        valid.sort_values("category_score")
        .drop_duplicates(keys, keep="last")[keys + ["category"]]
        .rename(columns={"category": "primary_category"})
    )
    result = (
        summary.merge(service_counts, on=keys, how="left")
        .merge(nonservice_counts, on=keys, how="left")
        .merge(workload, on=keys, how="left")
        .merge(primary, on=keys, how="left")
    )
    result[["unique_project_count", "unique_nonservice_item_count"]] = result[
        ["unique_project_count", "unique_nonservice_item_count"]
    ].fillna(0).astype(int)
    return result


def multiproject_sensitivity(episodes: pd.DataFrame, basis: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (source,), group in episodes.groupby(["source"]):
        multiple = group["unique_project_count"].gt(1)
        for coefficient in [1.0, 0.9, 0.8]:
            adjusted = group["nominal_workload_min"].where(
                ~multiple,
                group["nominal_workload_min"] * coefficient,
            )
            rows.append(
                {
                    "source": source,
                    "basis": basis,
                    "multiproject_coefficient": coefficient,
                    "episode_count": int(len(group)),
                    "multiproject_episode_count": int(multiple.sum()),
                    "multiproject_episode_share": float(multiple.mean()),
                    "total_nominal_workload_min": float(adjusted.sum()),
                    "mean_nominal_workload_per_episode_min": float(adjusted.mean()),
                }
            )
    return pd.DataFrame(rows)


def complete_daily(
    daily: pd.DataFrame,
    source: str,
    basis: str,
) -> pd.DataFrame:
    calendar = pd.DataFrame({"date": pd.date_range(START_DATE, END_DATE, freq="D")})
    out = calendar.merge(daily, on="date", how="left")
    out["episode_count"] = out["episode_count"].fillna(0).astype(int)
    out["project_row_count"] = out["project_row_count"].fillna(0).astype(int)
    out.insert(0, "basis", basis)
    out.insert(0, "source", source)
    return out


def aggregate_trends(daily: pd.DataFrame, frequency: str) -> pd.DataFrame:
    frame = daily.copy()
    if frequency == "weekly":
        frame["period"] = frame["date"].dt.to_period("W-SUN").dt.start_time
    elif frequency == "monthly":
        frame["period"] = frame["date"].dt.to_period("M").dt.start_time
    elif frequency == "annual":
        frame["period"] = frame["date"].dt.to_period("Y").dt.start_time
    else:
        raise ValueError(frequency)
    result = (
        frame.groupby(["source", "basis", "period"], as_index=False)
        .agg(
            episode_count=("episode_count", "sum"),
            project_row_count=("project_row_count", "sum"),
            calendar_days=("date", "size"),
            mean_daily_episodes=("episode_count", "mean"),
            median_daily_episodes=("episode_count", "median"),
            p90_daily_episodes=("episode_count", lambda x: x.quantile(0.9)),
        )
    )
    if frequency == "annual":
        result["full_calendar_year"] = result["period"].dt.year.between(2020, 2024)
    return result


def calendar_design(dates: pd.Series, origin: pd.Timestamp) -> np.ndarray:
    dates = pd.Series(pd.to_datetime(dates)).reset_index(drop=True)
    n = len(dates)
    trend = (dates - origin).dt.days.to_numpy(dtype=float) / 365.25
    day_of_year = dates.dt.dayofyear.to_numpy(dtype=float)
    columns: list[np.ndarray] = [
        np.ones(n),
        trend,
        np.sin(2 * np.pi * day_of_year / 365.25),
        np.cos(2 * np.pi * day_of_year / 365.25),
    ]
    weekday = dates.dt.dayofweek.to_numpy()
    month = dates.dt.month.to_numpy()
    columns.extend((weekday == value).astype(float) for value in range(1, 7))
    columns.extend((month == value).astype(float) for value in range(2, 13))
    return np.column_stack(columns)


def metric_row(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    residual = predicted - actual
    abs_error = np.abs(residual)
    denominator = np.maximum(np.abs(actual) + np.abs(predicted), 1e-9)
    return {
        "MAE": float(np.mean(abs_error)),
        "RMSE": float(np.sqrt(np.mean(residual**2))),
        "WAPE": float(abs_error.sum() / max(np.abs(actual).sum(), 1e-9)),
        "sMAPE": float(np.mean(2 * abs_error / denominator)),
        "mean_bias": float(np.mean(residual)),
    }


def chronological_validation(daily: pd.DataFrame) -> pd.DataFrame:
    results: list[dict[str, Any]] = []
    series_frames: list[tuple[str, str, pd.DataFrame]] = []
    for (source, basis), group in daily.groupby(["source", "basis"]):
        series_frames.append((source, basis, group.sort_values("date").copy()))
    for basis, group in daily.groupby("basis"):
        combined = (
            group.groupby("date", as_index=False)["episode_count"].sum().sort_values("date")
        )
        series_frames.append(("三类合计", basis, combined))

    for source, basis, frame in series_frames:
        frame = frame.sort_values("date").reset_index(drop=True)
        y = frame["episode_count"].to_numpy(dtype=float)
        dates = frame["date"]
        train_mask = dates.lt(VALIDATION_START).to_numpy()
        test_mask = dates.between(VALIDATION_START, VALIDATION_END).to_numpy()
        actual = y[test_mask]

        predictions: dict[str, np.ndarray] = {}
        predictions["7日季节朴素"] = pd.Series(y).shift(7).to_numpy()[test_mask]

        same_weekday_median = np.full(len(frame), np.nan)
        for index in np.flatnonzero(test_mask):
            history_index = [index - 7 * lag for lag in range(1, 9) if index - 7 * lag >= 0]
            same_weekday_median[index] = np.median(y[history_index])
        predictions["过去8周同星期中位数"] = same_weekday_median[test_mask]

        design_train = calendar_design(dates[train_mask], START_DATE)
        response_train = np.log1p(y[train_mask])
        ridge = 1e-4 * np.eye(design_train.shape[1])
        ridge[0, 0] = 0
        coefficient = np.linalg.solve(
            design_train.T @ design_train + ridge,
            design_train.T @ response_train,
        )
        design_test = calendar_design(dates[test_mask], START_DATE)
        predictions["日历趋势对数岭回归"] = np.maximum(np.expm1(design_test @ coefficient), 0)

        for model, predicted in predictions.items():
            finite = np.isfinite(predicted) & np.isfinite(actual)
            metrics = metric_row(actual[finite], predicted[finite])
            results.append(
                {
                    "source": source,
                    "basis": basis,
                    "model": model,
                    "train_start": str(dates[train_mask].min().date()),
                    "train_end": str(dates[train_mask].max().date()),
                    "validation_start": str(dates[test_mask].min().date()),
                    "validation_end": str(dates[test_mask].max().date()),
                    "validation_days": int(finite.sum()),
                    **metrics,
                }
            )
    result = pd.DataFrame(results)
    result["best_WAPE_within_series"] = result.groupby(["source", "basis"])["WAPE"].transform("min").eq(result["WAPE"])
    return result


def peak_flat_summary(daily: pd.DataFrame) -> pd.DataFrame:
    frames: list[tuple[str, str, pd.DataFrame]] = []
    for (source, basis), group in daily.groupby(["source", "basis"]):
        frames.append((source, basis, group.copy()))
    for basis, group in daily.groupby("basis"):
        frames.append(
            (
                "三类合计",
                basis,
                group.groupby("date", as_index=False)["episode_count"].sum(),
            )
        )
    rows: list[dict[str, Any]] = []
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for source, basis, frame in frames:
        training = frame[
            frame["date"].between(START_DATE, VALIDATION_START - pd.Timedelta(days=1))
        ].copy()
        holdout = frame[frame["date"].between(VALIDATION_START, VALIDATION_END)].copy()
        training["weekday"] = training["date"].dt.dayofweek
        training["month"] = training["date"].dt.month
        values = training["episode_count"]
        q45, q50, q55, q90, q95 = values.quantile([0.45, 0.5, 0.55, 0.9, 0.95])
        peak_candidates = training[training["episode_count"].ge(q90)].copy()
        peak_candidates["distance"] = (peak_candidates["episode_count"] - q90).abs()
        flat_candidates = training[
            training["episode_count"].between(q45, q55, inclusive="both")
        ].copy()
        flat_candidates["distance"] = (flat_candidates["episode_count"] - q50).abs()
        peak_row = peak_candidates.sort_values(["distance", "date"]).iloc[0]
        flat_row = flat_candidates.sort_values(["distance", "date"]).iloc[0]
        weekday_median = training.groupby("weekday")["episode_count"].median()
        month_median = training.groupby("month")["episode_count"].median()
        rows.append(
            {
                "source": source,
                "basis": basis,
                "period": f"{START_DATE.date()}至{(VALIDATION_START - pd.Timedelta(days=1)).date()}",
                "threshold_data_role": "training_only",
                "q45": float(q45),
                "median_flat_level": float(q50),
                "q55": float(q55),
                "q90_peak_threshold": float(q90),
                "q95_stress_threshold": float(q95),
                "representative_peak_date": str(peak_row["date"].date()),
                "representative_peak_count": int(peak_row["episode_count"]),
                "representative_flat_date": str(flat_row["date"].date()),
                "representative_flat_count": int(flat_row["episode_count"]),
                "peak_weekday": weekdays[int(weekday_median.idxmax())],
                "peak_weekday_median": float(weekday_median.max()),
                "peak_calendar_month": int(month_median.idxmax()),
                "peak_month_daily_median": float(month_median.max()),
                "holdout_peak_day_share": float(holdout["episode_count"].ge(q90).mean()),
                "holdout_stress_day_share": float(holdout["episode_count"].ge(q95).mean()),
                "holdout_flat_day_share": float(
                    holdout["episode_count"].between(q45, q55, inclusive="both").mean()
                ),
            }
        )
    return pd.DataFrame(rows)


def median_absolute_deviation(series: pd.Series) -> float:
    values = series.dropna().to_numpy(dtype=float)
    if len(values) == 0:
        return math.nan
    median = np.median(values)
    return float(np.median(np.abs(values - median)))


def report_gap_proxy(episodes: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    frame = episodes[
        episodes["report_dt"].dt.normalize().between(START_DATE, END_DATE)
        & episodes["exam_doctor_id"].notna()
        & episodes["nominal_workload_min"].gt(0)
    ].copy()
    frame["report_date"] = frame["report_dt"].dt.normalize()
    frame = frame.sort_values(["exam_doctor_id", "report_date", "report_dt"])
    frame["previous_report_dt"] = frame.groupby(["exam_doctor_id", "report_date"])["report_dt"].shift(1)
    frame["report_gap_min"] = (frame["report_dt"] - frame["previous_report_dt"]).dt.total_seconds() / 60
    hour = frame["report_dt"].dt.hour + frame["report_dt"].dt.minute / 60
    valid = frame["report_gap_min"].gt(0) & frame["report_gap_min"].le(60) & hour.between(6, 22)
    frame["valid_gap_proxy"] = valid
    valid_frame = frame[valid].copy()
    category_proxy_frame = valid_frame[valid_frame["unique_project_count"].eq(1)].copy()
    grouped = (
        category_proxy_frame.groupby("primary_category")["report_gap_min"]
        .agg(
            proxy_n="size",
            proxy_median_min="median",
            proxy_q25_min=lambda x: x.quantile(0.25),
            proxy_q75_min=lambda x: x.quantile(0.75),
            proxy_mad_min=median_absolute_deviation,
        )
        .reset_index()
    )
    overall_median = float(category_proxy_frame["report_gap_min"].median())
    grouped["relative_burden_index"] = grouped["proxy_median_min"] / overall_median
    diagnostics = {
        "all_report_episodes": int(len(frame)),
        "episodes_with_previous_same_doctor_day": int(frame["report_gap_min"].notna().sum()),
        "zero_or_negative_gap_count": int(frame["report_gap_min"].le(0).sum()),
        "gap_over_60_min_count": int(frame["report_gap_min"].gt(60).sum()),
        "valid_gap_proxy_count": int(valid.sum()),
        "valid_gap_proxy_share_of_all_episodes": float(valid.mean()),
        "single_project_valid_gap_proxy_count": int(len(category_proxy_frame)),
        "single_project_valid_gap_proxy_share": float(len(category_proxy_frame) / max(valid.sum(), 1)),
        "overall_single_project_valid_gap_median_min": overall_median,
        "interpretation": "类别代理仅使用单项目事件；相邻报告间隔仍含扫查、书写、等待和批量出报告效应，只能作为相对负荷代理，不能解释为服务时长。",
    }
    return grouped, diagnostics, frame


def doctor_efficiency(
    episodes_with_gaps: pd.DataFrame,
    doctor_day_path: Path,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    frame = episodes_with_gaps.copy()
    frame["report_date"] = frame["report_dt"].dt.normalize()
    frame = frame.sort_values(["exam_doctor_id", "report_date", "report_dt"])
    day = (
        frame.groupby(["exam_doctor_id", "report_date"], as_index=False)
        .agg(
            episode_count=("patient_key", "size"),
            project_row_count=("project_row_count", "sum"),
            nominal_workload_min=("nominal_workload_min", "sum"),
            first_report=("report_dt", "min"),
            last_report=("report_dt", "max"),
            first_episode_nominal=("nominal_workload_min", "first"),
        )
    )
    day["report_span_min"] = (day["last_report"] - day["first_report"]).dt.total_seconds() / 60
    day["effective_window_min"] = day["report_span_min"] + day["first_episode_nominal"]
    day["proxy_productivity"] = day["nominal_workload_min"] / day["effective_window_min"]
    valid = (
        day["episode_count"].ge(3)
        & day["report_span_min"].gt(0)
        & day["report_span_min"].le(16 * 60)
        & np.isfinite(day["proxy_productivity"])
        & day["proxy_productivity"].gt(0)
    )
    valid_day = day[valid].copy()
    raw_log = np.log(valid_day["proxy_productivity"])
    low, high = raw_log.quantile([0.01, 0.99])
    valid_day["log_productivity_winsor"] = raw_log.clip(low, high)

    pooled_within_variance = float(
        valid_day.groupby("exam_doctor_id")["log_productivity_winsor"].var().median()
    )
    if not math.isfinite(pooled_within_variance) or pooled_within_variance <= 0:
        pooled_within_variance = float(valid_day["log_productivity_winsor"].var())
    doctors = (
        valid_day.groupby("exam_doctor_id")
        .agg(
            valid_days=("report_date", "size"),
            total_episodes=("episode_count", "sum"),
            mean_log_productivity=("log_productivity_winsor", "mean"),
            variance_log_productivity=("log_productivity_winsor", "var"),
            raw_proxy_productivity=("proxy_productivity", "median"),
        )
        .reset_index()
    )
    doctors["variance_log_productivity"] = doctors["variance_log_productivity"].fillna(pooled_within_variance)
    doctors["sampling_variance"] = doctors["variance_log_productivity"] / doctors["valid_days"]
    mu0 = float(np.average(doctors["mean_log_productivity"], weights=doctors["valid_days"]))
    between_observed = float(doctors["mean_log_productivity"].var(ddof=1))
    mean_sampling = float(doctors["sampling_variance"].mean())
    tau2 = max(between_observed - mean_sampling, 1e-6)
    doctors["shrinkage_weight"] = tau2 / (tau2 + doctors["sampling_variance"])
    doctors["posterior_log_productivity"] = (
        doctors["shrinkage_weight"] * doctors["mean_log_productivity"]
        + (1 - doctors["shrinkage_weight"]) * mu0
    )
    doctors["posterior_variance"] = 1 / (1 / tau2 + 1 / doctors["sampling_variance"])
    doctors["raw_relative_throughput_factor"] = np.exp(doctors["mean_log_productivity"] - mu0)
    doctors["shrunk_relative_throughput_factor"] = np.exp(doctors["posterior_log_productivity"] - mu0)
    posterior_sd = np.sqrt(doctors["posterior_variance"])
    doctors["factor_ci95_lower"] = np.exp(doctors["posterior_log_productivity"] - mu0 - 1.96 * posterior_sd)
    doctors["factor_ci95_upper"] = np.exp(doctors["posterior_log_productivity"] - mu0 + 1.96 * posterior_sd)
    doctors = doctors.sort_values("shrunk_relative_throughput_factor", ascending=False)

    raw_doctor_day = pd.read_parquet(doctor_day_path).rename(
        columns={
            "检查人ID": "exam_doctor_id",
            "检查日期": "report_date",
            "部位数": "listed_project_count",
            "最早检查时间": "listed_first_report",
            "最晚检查时间": "listed_last_report",
        }
    )
    raw_doctor_day["exam_doctor_id"] = clean_id(raw_doctor_day["exam_doctor_id"])
    raw_doctor_day["report_date"] = pd.to_datetime(raw_doctor_day["report_date"], errors="coerce", format="mixed").dt.normalize()
    raw_doctor_day["listed_project_count"] = pd.to_numeric(raw_doctor_day["listed_project_count"], errors="coerce")
    raw_doctor_day["listed_first_report"] = pd.to_datetime(raw_doctor_day["listed_first_report"], errors="coerce", format="mixed")
    raw_doctor_day["listed_last_report"] = pd.to_datetime(raw_doctor_day["listed_last_report"], errors="coerce", format="mixed")
    reconciliation = raw_doctor_day.merge(
        day[
            [
                "exam_doctor_id",
                "report_date",
                "project_row_count",
                "episode_count",
                "first_report",
                "last_report",
            ]
        ],
        on=["exam_doctor_id", "report_date"],
        how="left",
    )
    matched = reconciliation[
        reconciliation["listed_project_count"].notna()
        & reconciliation["project_row_count"].notna()
    ].copy()
    first_abs_minutes = (matched["listed_first_report"] - matched["first_report"]).dt.total_seconds().abs() / 60
    last_abs_minutes = (matched["listed_last_report"] - matched["last_report"]).dt.total_seconds().abs() / 60
    diagnostics = {
        "doctor_day_rows": int(len(day)),
        "valid_doctor_days_for_efficiency": int(len(valid_day)),
        "doctor_count_estimated": int(len(doctors)),
        "daily_validity_rule": "至少3个报告事件，报告跨度大于0且不超过16小时；日对数生产率在1%与99%分位温莎化。",
        "empirical_bayes_prior_log_mean": mu0,
        "empirical_bayes_between_doctor_variance": tau2,
        "table6_matched_doctor_days": int(len(matched)),
        "table6_project_count_correlation": float(matched["listed_project_count"].corr(matched["project_row_count"])),
        "table6_project_count_MAE": float((matched["listed_project_count"] - matched["project_row_count"]).abs().mean()),
        "table6_first_time_median_abs_difference_min": float(first_abs_minutes.median()),
        "table6_last_time_median_abs_difference_min": float(last_abs_minutes.median()),
        "interpretation": "因报告时刻包含非扫查时间，因子仅表示历史报告吞吐代理；当前医生名单未给出时不能直接映射为未来个人速度。",
    }
    return doctors, diagnostics, reconciliation


def duration_table(gap_proxy: pd.DataFrame, category_volume: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for priority, rule in enumerate(CATEGORY_RULES, start=1):
        rows.append(
            {
                "priority": priority,
                "category": rule["category"],
                "keyword_regex": rule["pattern"],
                "classification_basis": rule["basis"],
                "duration_lower_min": rule["lower"],
                "duration_nominal_min": rule["nominal"],
                "duration_upper_min": rule["upper"],
                "robust_schedule_parameter_min": rule["upper"],
                "special_case_frequency_from_problem": 0.05,
                "special_case_extra_duration_known": False,
                "multiproject_default_coefficient": 1.0,
                "multiproject_sensitivity_lower": 0.8,
                "multiproject_sensitivity_upper": 1.0,
            }
        )
    result = pd.DataFrame(rows)
    total_volume = category_volume.groupby("category")["record_count"].sum().rename("all_source_record_count")
    result = result.merge(total_volume, on="category", how="left")
    result = result.merge(gap_proxy, left_on="category", right_on="primary_category", how="left").drop(columns="primary_category")
    return result


def finite_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [finite_json(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def set_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.sans-serif": ["SimHei", "Microsoft YaHei", "Arial Unicode MS", "DejaVu Sans"],
            "axes.unicode_minus": False,
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.dpi": 150,
            "savefig.dpi": 220,
        }
    )


def make_figures(
    daily: pd.DataFrame,
    monthly: pd.DataFrame,
    peak_flat: pd.DataFrame,
    durations: pd.DataFrame,
    doctors: pd.DataFrame,
    figures_dir: Path,
) -> None:
    set_plot_style()
    colors = {"住院": "#1f77b4", "门诊": "#d95f02", "体检": "#2a9d8f"}

    fig, ax = plt.subplots(figsize=(11, 5.2))
    order = daily[daily["basis"].eq("开单日")].copy()
    for source, group in order.groupby("source"):
        group = group.sort_values("date")
        rolling = group["episode_count"].rolling(28, center=True, min_periods=14).mean()
        ax.plot(group["date"], rolling, label=f"{source}（28日中心均值）", color=colors[source], linewidth=1.4)
    ax.axvline(VALIDATION_START, color="#555555", linestyle="--", linewidth=1, label="时间顺序验证起点")
    ax.set_ylabel("每日开单事件数")
    ax.set_title("三类患者开单需求长期趋势")
    ax.legend(ncol=2, frameon=False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(figures_dir / "daily_order_trend.png", bbox_inches="tight")
    plt.close(fig)

    fig, axes = plt.subplots(2, 1, figsize=(11, 7.2), sharex=True)
    for axis, basis in zip(axes, ["开单日", "报告日"]):
        selected = monthly[monthly["basis"].eq(basis)]
        for source, group in selected.groupby("source"):
            axis.plot(group["period"], group["mean_daily_episodes"], label=source, color=colors[source], linewidth=1.3)
        axis.set_ylabel("月内日均事件数")
        axis.set_title(f"{basis}口径")
        axis.grid(axis="y", alpha=0.2)
    axes[0].legend(ncol=3, frameon=False)
    axes[-1].set_xlabel("月份")
    fig.suptitle("开单需求与报告吞吐的月度趋势（口径分离）", y=0.995)
    fig.tight_layout()
    fig.savefig(figures_dir / "monthly_order_report_trend.png", bbox_inches="tight")
    plt.close(fig)

    recent_order = daily[
        daily["basis"].eq("开单日") & daily["date"].between(VALIDATION_START, VALIDATION_END)
    ].copy()
    recent_order["weekday"] = recent_order["date"].dt.dayofweek
    profile = recent_order.groupby(["source", "weekday"])["episode_count"].median().reset_index()
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for source, group in profile.groupby("source"):
        ax.plot(group["weekday"], group["episode_count"], marker="o", label=source, color=colors[source])
    ax.set_xticks(range(7), labels)
    ax.set_ylabel("日开单事件中位数")
    ax.set_title("验证期星期负荷剖面")
    ax.legend(frameon=False)
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(figures_dir / "weekday_order_profile.png", bbox_inches="tight")
    plt.close(fig)

    plot_duration = durations.sort_values("duration_nominal_min")
    fig, ax = plt.subplots(figsize=(10, 6))
    y = np.arange(len(plot_duration))
    error = np.vstack(
        [
            plot_duration["duration_nominal_min"] - plot_duration["duration_lower_min"],
            plot_duration["duration_upper_min"] - plot_duration["duration_nominal_min"],
        ]
    )
    ax.errorbar(
        plot_duration["duration_nominal_min"],
        y,
        xerr=error,
        fmt="o",
        color="#1f77b4",
        ecolor="#7f8c8d",
        capsize=3,
        label="题面下界/中点/上界",
    )
    proxy_scaled = plot_duration["relative_burden_index"] * 7.5
    ax.scatter(proxy_scaled, y, marker="x", color="#d95f02", label="报告间隔相对指数×7.5（非时长）")
    ax.set_yticks(y, plot_duration["category"])
    ax.set_xlabel("分钟或相对指数缩放值")
    ax.set_title("调度时长参数与报告间隔代理的边界")
    ax.legend(frameon=False)
    ax.grid(axis="x", alpha=0.2)
    fig.tight_layout()
    fig.savefig(figures_dir / "duration_and_gap_proxy.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    factors = doctors["shrunk_relative_throughput_factor"].sort_values().reset_index(drop=True)
    ax.plot(np.arange(1, len(factors) + 1), factors, marker="o", markersize=3, linewidth=1, color="#2a9d8f")
    ax.axhline(1, color="#555555", linestyle="--", linewidth=1)
    ax.set_xlabel("历史医生（按收缩因子排序）")
    ax.set_ylabel("相对报告吞吐因子")
    ax.set_title("经验贝叶斯收缩后的医生历史吞吐代理")
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(figures_dir / "doctor_throughput_factors.png", bbox_inches="tight")
    plt.close(fig)


def markdown_table(frame: pd.DataFrame, columns: list[str], limit: int | None = None) -> str:
    selected = frame[columns].copy()
    if limit is not None:
        selected = selected.head(limit)
    header = "|" + "|".join(columns) + "|"
    divider = "|" + "|".join(["---"] * len(columns)) + "|"
    rows = []
    for _, row in selected.iterrows():
        values = []
        for value in row:
            if pd.isna(value):
                values.append("不适用")
            elif isinstance(value, float):
                values.append(f"{value:.3f}")
            else:
                values.append(str(value))
        rows.append("|" + "|".join(values) + "|")
    return "\n".join([header, divider, *rows])


def write_report(
    output_path: Path,
    summary: dict[str, Any],
    peak_flat: pd.DataFrame,
    validation: pd.DataFrame,
    durations: pd.DataFrame,
    doctors: pd.DataFrame,
    weekly: pd.DataFrame,
    annual: pd.DataFrame,
    multiproject: pd.DataFrame,
    nonservice: pd.DataFrame,
) -> None:
    combined_order = peak_flat[
        peak_flat["source"].eq("三类合计") & peak_flat["basis"].eq("开单日")
    ].iloc[0]
    best = validation[validation["best_WAPE_within_series"]].sort_values(["source", "basis"])
    duration_view = durations[
        [
            "category",
            "duration_lower_min",
            "duration_nominal_min",
            "duration_upper_min",
            "proxy_n",
            "proxy_median_min",
            "relative_burden_index",
        ]
    ]
    factor_quantiles = doctors["shrunk_relative_throughput_factor"].quantile([0.05, 0.5, 0.95])
    full_years = annual[annual["full_calendar_year"]].copy()
    full_years["year"] = full_years["period"].dt.year
    annual_view = full_years[
        ["source", "basis", "year", "episode_count", "mean_daily_episodes"]
    ]
    weekly_peak = (
        weekly.sort_values("mean_daily_episodes", ascending=False)
        .groupby(["source", "basis"], as_index=False)
        .first()[["source", "basis", "period", "episode_count", "mean_daily_episodes"]]
    )
    weekly_peak["period"] = weekly_peak["period"].dt.date.astype(str)
    multi_view = multiproject[
        [
            "source",
            "basis",
            "multiproject_coefficient",
            "multiproject_episode_share",
            "total_nominal_workload_min",
            "mean_nominal_workload_per_episode_min",
        ]
    ]
    nonservice_view = nonservice[
        ["source", "ordered_project", "record_count", "bedside_record_count"]
    ]
    text = f"""# P1 数据分析技术报告

## 1. 结论摘要

本分析覆盖 2019-03-01 至 2025-03-31。三类患者按开单日合计的训练期平峰中位数为 {combined_order['median_flat_level']:.0f} 个开单事件/日，90% 高峰阈值为 {combined_order['q90_peak_threshold']:.0f} 个/日，95% 压力阈值为 {combined_order['q95_stress_threshold']:.0f} 个/日；代表性平峰日为 {combined_order['representative_flat_date']}（{combined_order['representative_flat_count']} 个），代表性高峰日为 {combined_order['representative_peak_date']}（{combined_order['representative_peak_count']} 个）。阈值和代表日只由 2019-03-01 至 2024-03-31 的训练期确定，最后12个月仅检验这些阈值在未来时段的表现。

项目分类采用“互斥项目族 + 非互斥资源标记”：项目族决定基础时长与设备能力，床旁、空腹上午、充盈膀胱三个标记决定地点或时段约束。规则逐条按优先级匹配，项目字典保留原名、规范名、命中类别和记录量，能够逐项追溯。

独立计费/报告条目不作为检查项目排程。只有规范化文本完整匹配“床旁B超检查加收”“床旁彩色多普勒超声检查加收”“彩色胶片打印”或“超声计算机图文报告”时才置0分钟；组合文本只要还含真实扫查项目，就按真实项目分类和计时。床旁加收虽然为0分钟，仍保留床旁资源标记并与同开单事件中的真实项目绑定。正式期命中数量如下：

{markdown_table(nonservice_view, ['source', 'ordered_project', 'record_count', 'bedside_record_count'])}

题目数据没有检查开始时刻。开单到报告时长包含排队、预约、检查、书写和报告发布，不能当作服务时长。本分析只把单项目事件中、同一医生同日报告事件的相邻间隔作为类别相对工作量代理，并将其限制在大于0且不超过60分钟；最终调度分钟参数仍直接取题面时长区间的中点，稳健情景取上界。5%特殊病例频率来自题面，但题面未给额外时长倍率，因此不人为设置倍率。

历史医生的收缩后相对报告吞吐因子 5%、50%、95% 分位分别为 {factor_quantiles.loc[0.05]:.3f}、{factor_quantiles.loc[0.5]:.3f}、{factor_quantiles.loc[0.95]:.3f}。该因子已按有效医生日做经验贝叶斯收缩，但仍是报告吞吐代理，不是临床扫查速度，也不能在缺少当前医生ID映射时直接用于点名排班。

## 2. 数据口径

- 开单事件：同一患者、同一精确开单时刻合并为一个事件；同一事件的服务项目按规范名称去重，纯计费/报告条目不计服务项目数。
- 报告事件：同一患者、同一开单时刻、同一检查医生和同一机器构成一个连续检查事件，完成时刻取该组最后报告时刻；事件内按规范项目名去重后逐项累加时长。
- 开单日序列描述到达需求；报告日序列描述历史完成吞吐。两者分别输出，未把报告日吞吐误称为到达需求。
- 日序列补齐完整自然日，未出现记录的日期按0处理；周、月、年均由完整日序列汇总。
- 2019年仅从3月开始，2025年仅到3月结束，年度总量横向比较应限于2020--2024完整年份。

## 3. 项目分类与调度时长

{markdown_table(duration_view, list(duration_view.columns))}

说明：`proxy_median_min` 是单项目报告事件间隔的稳健中位数，含等待和书写；`relative_burden_index` 仅用于检验类别相对负荷，不替代题面时长。多项目事件默认按规范项目去重后逐项累加题面参数，并在同一兼容检查室连续安排。题面没有给出同次检查的固定节约比例，因此默认合并系数为1.0；0.8和0.9只作为敏感性情景：

{markdown_table(multi_view, ['source', 'basis', 'multiproject_coefficient', 'multiproject_episode_share', 'total_nominal_workload_min', 'mean_nominal_workload_per_episode_min'])}

## 4. 高峰和平峰识别

{markdown_table(peak_flat, ['source', 'basis', 'median_flat_level', 'q90_peak_threshold', 'q95_stress_threshold', 'representative_flat_date', 'representative_peak_date', 'peak_weekday', 'peak_calendar_month'])}

高峰阈值取训练期日事件数90%分位，压力阈值取95%分位；平峰水平取训练期中位数，代表日也只从训练期选择。留出期仅统计落入训练期平峰、高峰和压力阈值的日期比例。月份用月内“每日事件数中位数”排序，避免月份天数不同造成总量偏差。

完整日序列同时按周、月、年汇总。各序列在全观察期内的日均负荷最高周如下；周首日期为周一：

{markdown_table(weekly_peak, ['source', 'basis', 'period', 'episode_count', 'mean_daily_episodes'])}

完整年份的年度结果如下。2019年从3月开始、2025年到3月结束，因此未混入完整年份比较：

{markdown_table(annual_view, ['source', 'basis', 'year', 'episode_count', 'mean_daily_episodes'])}

## 5. 时间顺序验证

训练集固定为 2019-03-01 至 2024-03-31，验证集固定为 2024-04-01 至 2025-03-31，未随机打乱。比较7日季节朴素、滚动一步的过去8周同星期中位数、只使用日历和长期趋势的对数岭回归。滚动一步模型在每个验证日只使用该日以前的真实观测。下表列出每条序列按WAPE最优的基线：

{markdown_table(best, ['source', 'basis', 'model', 'MAE', 'RMSE', 'WAPE', 'sMAPE', 'mean_bias'])}

此验证用于判断季节/星期结构能否在未来时间段复现，不把其中任何一个基线当成最终排程需求预测器。最终模型应至少以最优基线为对照，并在滚动窗口中重估。

## 6. 工作量代理与医生收缩估计

报告间隔代理先按“同一医生、同一报告日”排序，仅保留 `(0, 60]` 分钟间隔，并只用单项目事件形成类别统计。医生日生产率定义为去重项目题面名义时长之和除以有效报告窗口；多项目默认系数为1.0。有效窗口为最晚减最早报告时刻，再补首个事件名义时长。至少3个事件、跨度不超过16小时的医生日进入估计，日对数生产率在1%和99%分位温莎化。

对每名医生的平均对数生产率采用正态层次模型的经验贝叶斯收缩：先由医生间方差扣除平均抽样方差估计先验方差，再按各医生的日内波动和有效天数形成数据权重。输出包括原始相对因子、收缩因子和95%区间。该处理降低少量医生日导致的极端值，但不消除报告流程和病例组合造成的混杂。

表6复核结果：匹配医生日 {summary['doctor_efficiency']['table6_matched_doctor_days']} 条，明细项目记录数与表6部位数相关系数为 {summary['doctor_efficiency']['table6_project_count_correlation']:.4f}，两端报告时刻中位绝对差分别为 {summary['doctor_efficiency']['table6_first_time_median_abs_difference_min']:.2f} 和 {summary['doctor_efficiency']['table6_last_time_median_abs_difference_min']:.2f} 分钟。该一致性支持“报告事件重建”用于吞吐分析，但不改变其非服务时长属性。

## 7. 可用于后续模型的参数与边界

1. 基础时长使用 `service_duration_parameters.csv` 的中点；同一事件各去重服务项目默认逐项求和并连续同室安排，容量压力测试使用逐项上界之和；`non_service_item=True` 的独立条目为0分钟。
2. 多项目合并系数默认1.0，0.8--1.0只用于敏感性分析，不将“同室连续”解释为零增量同时扫描。
3. 5%特殊病例单独占用上界槽位或设情景变量；在没有额外时长证据时不外推倍率。
4. 医生收缩因子只适合历史敏感性分析。若后续获得当前33名医生ID对应和班表，才可逐人应用；否则使用总体因子1并以因子分布做情景。
5. 体检历史机器ID几乎不能对应现行诊室时，项目族分析仍可用于总工作量，但不能据此恢复旧房间的精确能力。
6. 报告事件分组依赖“患者+精确开单时刻+医生+机器”。同分钟多张申请单可能被合并，故排程应对事件粒度另做口径敏感性分析。

## 8. 复现

在工作区根目录执行：

```powershell
python supporting_materials/code/analyze_p1.py
```

随机种子固定为 {SEED}。脚本只读取 `supporting_materials/processed_data/raw_parquet/`，结果写入 `supporting_materials/results/p1/`，图件写入 `supporting_materials/figures/p1/`。
"""
    output_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=SUPPORTING_DIR / "processed_data" / "raw_parquet",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SUPPORTING_DIR / "results" / "p1",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=SUPPORTING_DIR / "figures" / "p1",
    )
    args = parser.parse_args()
    np.random.seed(SEED)
    results_dir = args.output_dir
    figures_dir = args.figures_dir
    results_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    all_catalogs_train: list[pd.DataFrame] = []
    all_catalogs_full: list[pd.DataFrame] = []
    all_daily: list[pd.DataFrame] = []
    all_report_episodes: list[pd.DataFrame] = []
    all_multiproject_sensitivity: list[pd.DataFrame] = []
    source_diagnostics: dict[str, Any] = {}

    for source, filename in SOURCE_FILES.items():
        frame = load_detail(args.raw_dir / filename, source)
        official_frame = frame[
            frame["order_dt"].notna()
            & frame["order_dt"].dt.normalize().between(START_DATE, END_DATE)
        ].copy()
        all_catalogs_train.append(
            make_project_catalog(frame, START_DATE, VALIDATION_START - pd.Timedelta(days=1))
        )
        all_catalogs_full.append(make_project_catalog(frame, START_DATE, END_DATE))
        order_episodes = make_order_episodes(frame)
        report_episodes = make_report_episodes(frame)
        order_episodes = order_episodes[order_episodes["nominal_workload_min"].gt(0)].copy()
        report_episodes = report_episodes[report_episodes["nominal_workload_min"].gt(0)].copy()
        all_report_episodes.append(report_episodes)
        all_multiproject_sensitivity.append(multiproject_sensitivity(order_episodes, "开单事件"))
        official_report_episodes = report_episodes[
            report_episodes["report_dt"].dt.normalize().between(START_DATE, END_DATE)
        ].copy()
        all_multiproject_sensitivity.append(multiproject_sensitivity(official_report_episodes, "报告事件"))

        order_daily = (
            order_episodes.assign(date=order_episodes["order_dt"].dt.normalize())
            .groupby("date", as_index=False)
            .agg(episode_count=("patient_key", "size"), project_row_count=("project_row_count", "sum"))
        )
        report_daily = (
            report_episodes.assign(date=report_episodes["report_dt"].dt.normalize())
            .loc[lambda x: x["date"].between(START_DATE, END_DATE)]
            .groupby("date", as_index=False)
            .agg(episode_count=("patient_key", "size"), project_row_count=("project_row_count", "sum"))
        )
        all_daily.append(complete_daily(order_daily, source, "开单日"))
        all_daily.append(complete_daily(report_daily, source, "报告日"))
        source_diagnostics[source] = {
            "detail_rows": int(len(frame)),
            "official_detail_rows": int(len(official_frame)),
            "official_order_events": int(len(order_episodes)),
            "official_report_events": int(len(official_report_episodes)),
            "unique_ordered_project_names": int(official_frame["ordered_project"].nunique(dropna=True)),
            "unclassified_general_other_share": float(official_frame["category"].eq("一般其他").mean()),
            "non_service_item_rows": int(official_frame["non_service_item"].sum()),
            "non_service_item_share": float(official_frame["non_service_item"].mean()),
            "bedside_row_share": float(official_frame["床旁标记"].mean()),
            "fasting_constraint_row_share": float(official_frame["空腹上午标记"].mean()),
            "bladder_constraint_row_share": float(official_frame["充盈膀胱标记"].mean()),
        }
        del frame, official_frame, order_episodes, official_report_episodes

    catalog = pd.concat(all_catalogs_train, ignore_index=True)
    catalog_full = pd.concat(all_catalogs_full, ignore_index=True)
    daily = pd.concat(all_daily, ignore_index=True)
    report_episodes_all = pd.concat(all_report_episodes, ignore_index=True)
    report_episodes_training = report_episodes_all[
        report_episodes_all["report_dt"].dt.normalize().lt(VALIDATION_START)
    ].copy()
    multiproject = pd.concat(all_multiproject_sensitivity, ignore_index=True)

    category_volume = (
        catalog_full.groupby(["source", "category"], as_index=False)["record_count"].sum()
    )
    category_volume["share_within_source"] = category_volume["record_count"] / category_volume.groupby("source")["record_count"].transform("sum")
    nonservice = (
        catalog_full[catalog_full["non_service_item"]]
        .groupby(["source", "ordered_project"], as_index=False)
        .agg(
            record_count=("record_count", "sum"),
            bedside_record_count=("record_count", lambda x: x.sum()),
        )
    )
    nonservice["bedside_record_count"] = np.where(
        nonservice["ordered_project"].str.contains("床旁", na=False),
        nonservice["record_count"],
        0,
    )

    weekly = aggregate_trends(daily, "weekly")
    monthly = aggregate_trends(daily, "monthly")
    annual = aggregate_trends(daily, "annual")
    validation = chronological_validation(daily)
    peak_flat = peak_flat_summary(daily)
    # Scheduling-time and doctor-efficiency estimates are model inputs, so they
    # must be frozen before the chronological holdout begins.  Full-period
    # report episodes remain available only for descriptive trend outputs.
    gap_proxy, gap_diagnostics, episode_gap_frame = report_gap_proxy(report_episodes_training)
    doctors, doctor_diagnostics, reconciliation = doctor_efficiency(
        episode_gap_frame,
        args.raw_dir / "doctor_day.parquet",
    )
    durations = duration_table(gap_proxy, category_volume)

    rules = pd.DataFrame(
        [
            {
                "priority": index,
                "category": rule["category"],
                "keyword_regex": rule["pattern"],
                "classification_basis": rule["basis"],
                "duration_lower_min": rule["lower"],
                "duration_nominal_min": rule["nominal"],
                "duration_upper_min": rule["upper"],
            }
            for index, rule in enumerate(CATEGORY_RULES, start=1)
        ]
    )
    flags = pd.DataFrame(
        [
            {"flag": flag, "keyword_regex": pattern}
            for flag, pattern in FLAG_PATTERNS.items()
        ]
    )

    # The authoritative catalog stops before the chronological holdout.  The
    # full-period catalog is descriptive only and must not be joined into
    # holdout dispatch inputs.
    catalog.to_csv(results_dir / "project_category_catalog.csv", index=False, encoding="utf-8-sig")
    catalog.to_csv(results_dir / "project_category_catalog_train.csv", index=False, encoding="utf-8-sig")
    catalog_full.to_csv(
        results_dir / "project_category_catalog_full_audit.csv",
        index=False,
        encoding="utf-8-sig",
    )
    rules.to_csv(results_dir / "category_rules.csv", index=False, encoding="utf-8-sig")
    flags.to_csv(results_dir / "resource_flag_rules.csv", index=False, encoding="utf-8-sig")
    category_volume.to_csv(results_dir / "category_volume_summary.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(results_dir / "daily_trends.csv", index=False, encoding="utf-8-sig")
    weekly.to_csv(results_dir / "weekly_trends.csv", index=False, encoding="utf-8-sig")
    monthly.to_csv(results_dir / "monthly_trends.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(results_dir / "annual_trends.csv", index=False, encoding="utf-8-sig")
    validation.to_csv(results_dir / "chronological_validation.csv", index=False, encoding="utf-8-sig")
    peak_flat.to_csv(results_dir / "peak_flat_summary.csv", index=False, encoding="utf-8-sig")
    gap_proxy.to_csv(results_dir / "report_gap_proxy_by_category.csv", index=False, encoding="utf-8-sig")
    durations.to_csv(results_dir / "service_duration_parameters.csv", index=False, encoding="utf-8-sig")
    doctors.to_csv(results_dir / "doctor_efficiency_shrunk.csv", index=False, encoding="utf-8-sig")
    reconciliation.to_csv(results_dir / "doctor_day_reconciliation.csv", index=False, encoding="utf-8-sig")
    multiproject.to_csv(results_dir / "multiproject_coefficient_sensitivity.csv", index=False, encoding="utf-8-sig")
    nonservice.to_csv(results_dir / "non_service_item_summary.csv", index=False, encoding="utf-8-sig")

    summary = {
        "seed": SEED,
        "period": {"start": str(START_DATE.date()), "end": str(END_DATE.date())},
        "validation_period": {
            "start": str(VALIDATION_START.date()),
            "end": str(VALIDATION_END.date()),
            "split_type": "strict chronological holdout",
        },
        "catalog_boundary": {
            "authoritative_project_catalog_end": str((VALIDATION_START - pd.Timedelta(days=1)).date()),
            "full_period_catalog_output": "project_category_catalog_full_audit.csv",
            "holdout_names_used_for_dispatch_join": False,
        },
        "doctor_time_boundary": {
            "authoritative_report_gap_end": str((VALIDATION_START - pd.Timedelta(days=1)).date()),
            "holdout_report_times_used_for_doctor_or_duration_estimation": False,
        },
        "source_diagnostics": source_diagnostics,
        "report_gap_proxy": gap_diagnostics,
        "doctor_efficiency": doctor_diagnostics,
        "multiproject_sensitivity": multiproject.to_dict(orient="records"),
        "non_service_items": nonservice.to_dict(orient="records"),
        "modeling_boundary": {
            "has_exam_start_timestamp": False,
            "turnaround_used_as_service_time": False,
            "duration_parameter_basis": "problem-statement intervals; midpoint for nominal, upper bound for robust scenario",
            "special_case_frequency": 0.05,
            "special_case_extra_duration_multiplier": None,
        },
    }
    (results_dir / "analysis_summary.json").write_text(
        json.dumps(finite_json(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    make_figures(daily, monthly, peak_flat, durations, doctors, figures_dir)
    write_report(
        results_dir / "P1_DATA_ANALYSIS_REPORT.md",
        summary,
        peak_flat,
        validation,
        durations,
        doctors,
        weekly,
        annual,
        multiproject,
        nonservice,
    )

    print(json.dumps(finite_json(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
