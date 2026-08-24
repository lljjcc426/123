"""Create final paper figures from the authoritative unified result chain."""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
P1 = ROOT / "supporting_materials" / "results" / "p1"
UNIFIED = ROOT / "supporting_materials" / "results" / "unified_schedule"
INPUT = ROOT / "supporting_materials" / "processed_data" / "unified_holdout"
CAPABILITY = ROOT / "supporting_materials" / "results" / "capability"
OUT = ROOT / "supporting_materials" / "figures" / "paper_final"

BLUE = "#276FBF"
ORANGE = "#F28E2B"
GREEN = "#3A9D5D"
RED = "#C93C3C"
PURPLE = "#7A5195"
GRAY = "#6B7280"
LIGHT = "#E8EEF5"


def configure() -> None:
    candidates = ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"]
    available = {font.name for font in font_manager.fontManager.ttflist}
    family = next((name for name in candidates if name in available), "DejaVu Sans")
    plt.rcParams.update(
        {
            "font.family": family,
            "axes.unicode_minus": False,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "axes.labelcolor": "#263238",
            "text.color": "#263238",
            "xtick.color": "#455A64",
            "ytick.color": "#455A64",
            "figure.dpi": 150,
            "savefig.dpi": 300,
        }
    )
    OUT.mkdir(parents=True, exist_ok=True)


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)


def monthly_demand() -> None:
    frame = pd.read_csv(P1 / "monthly_trends.csv", parse_dates=["period"])
    frame = frame[frame["basis"].eq("开单日")]
    colors = {"住院": BLUE, "门诊": ORANGE, "体检": GREEN}
    fig, ax = plt.subplots(figsize=(10.2, 4.4))
    for source, group in frame.groupby("source", sort=False):
        group = group.sort_values("period")
        ax.plot(
            group["period"],
            group["mean_daily_episodes"],
            lw=1.8,
            label=source,
            color=colors[source],
        )
    split = pd.Timestamp("2024-04-01")
    ax.axvspan(split, pd.Timestamp("2025-04-01"), color=LIGHT, alpha=0.9, zorder=0)
    ax.axvline(split, color=GRAY, lw=1.1, ls="--")
    ax.text(split + pd.Timedelta(days=10), ax.get_ylim()[1] * 0.93, "时间顺序留出期", color=GRAY)
    ax.set_title("三类患者月度日均开单量及时间顺序留出边界")
    ax.set_ylabel("日均事件数")
    ax.set_xlabel("月份")
    ax.legend(ncol=3, frameon=False, loc="upper left")
    ax.grid(axis="y", color="#D7DEE8", lw=0.7, alpha=0.8)
    fig.tight_layout()
    save(fig, "fig01_monthly_demand")


def doctor_capacity() -> None:
    frame = pd.read_csv(INPUT / "doctor_slot_capacity.csv")
    labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    fig, axes = plt.subplots(2, 1, figsize=(10.2, 5.8), sharex=True)
    for ax, column, title in zip(
        axes,
        ["capacity_main", "capacity_low"],
        ["训练日中位数容量（主情景）", "训练日下四分位容量（偏紧情景）"],
    ):
        for weekday, group in frame.groupby("weekday"):
            x = np.arange(len(group))
            ax.plot(x, group[column], lw=1.25, label=labels[int(weekday)])
        ax.set_ylabel("可并发医生数")
        ax.set_title(title, loc="left", fontsize=11)
        ax.grid(axis="y", color="#D7DEE8", lw=0.6)
    tick_index = [0, 12, 24, 36, 47, 48, 60, 72, 84, 95]
    tick_label = ["08:00", "09:00", "10:00", "11:00", "11:55", "13:00", "14:00", "15:00", "16:00", "16:55"]
    axes[-1].set_xticks(tick_index, tick_label)
    axes[-1].set_xlabel("5 分钟时隙")
    axes[0].legend(ncol=7, frameon=False, loc="upper center", bbox_to_anchor=(0.5, 1.32))
    fig.suptitle("由训练期医生工作日记录重构的共享时隙容量", y=1.02, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig02_doctor_capacity")


def capability_coverage() -> None:
    items = pd.read_csv(INPUT / "items.csv", low_memory=False)
    events = pd.read_csv(INPUT / "events.csv", usecols=["event_id", "source"])
    frame = items.merge(events, on="event_id", how="left", validate="many_to_one")
    level = np.where(
        frame["capability_level"].eq("category_fallback"),
        "类别回退",
        np.where(frame["capability_level"].eq("explicit_bedside"), "床旁明确", "严格项目证据"),
    )
    frame["evidence_group"] = level
    table = frame.groupby(["source", "evidence_group"]).size().unstack(fill_value=0)
    table = table.div(table.sum(axis=1), axis=0).reindex(["住院", "门诊", "体检"])
    order = ["严格项目证据", "床旁明确", "类别回退"]
    colors = [BLUE, GREEN, ORANGE]
    fig, ax = plt.subplots(figsize=(8.8, 3.6))
    left = np.zeros(len(table))
    for column, color in zip(order, colors):
        values = table.get(column, pd.Series(0, index=table.index)).to_numpy()
        bars = ax.barh(table.index, values, left=left, color=color, height=0.55, label=column)
        for bar, value, start in zip(bars, values, left):
            if value >= 0.045:
                ax.text(start + value / 2, bar.get_y() + bar.get_height() / 2, f"{value:.1%}", ha="center", va="center", color="white", fontsize=9)
        left += values
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    ax.set_xlabel("项目任务占比")
    ax.set_title("三类患者项目—设备兼容证据覆盖")
    ax.legend(ncol=3, frameon=False, loc="lower center", bbox_to_anchor=(0.5, -0.38))
    fig.tight_layout()
    save(fig, "fig03_capability_coverage")


def policy_tradeoff() -> None:
    metrics = pd.read_csv(UNIFIED / "policy_scenario_metrics.csv")
    frame = metrics[metrics["scenario"].eq("main_5pct_upper")].copy()
    labels = {
        "FCFS_SHARED": "共享 FCFS",
        "SLACK_GUARD_SHARED": "松弛度保护",
        "JOINT_SCARCITY": "联合稀缺度",
    }
    colors = {"FCFS_SHARED": BLUE, "SLACK_GUARD_SHARED": ORANGE, "JOINT_SCARCITY": GREEN}
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    for row in frame.itertuples(index=False):
        ax.scatter(
            row.background_on_time_rate,
            row.inpatient_48h_rate,
            s=170,
            color=colors[row.policy],
            edgecolor="white",
            linewidth=1.2,
            zorder=3,
        )
        ax.annotate(
            labels[row.policy],
            (row.background_on_time_rate, row.inpatient_48h_rate),
            xytext=(7, 7),
            textcoords="offset points",
            fontsize=10,
        )
    ax.set_xlabel("门诊/体检预约日内完成率")
    ax.set_ylabel("住院 48 小时内完成率")
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.1%}")
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.1%}")
    ax.grid(color="#D7DEE8", lw=0.7)
    ax.set_title("共享资源下三种患者级排程策略比较")
    ax.set_xlim(frame["background_on_time_rate"].min() - 0.008, frame["background_on_time_rate"].max() + 0.013)
    ax.set_ylim(frame["inpatient_48h_rate"].min() - 0.006, frame["inpatient_48h_rate"].max() + 0.006)
    fig.tight_layout()
    save(fig, "fig04_policy_tradeoff")


def sensitivity() -> None:
    metrics = pd.read_csv(UNIFIED / "policy_scenario_metrics.csv")
    main = metrics[
        metrics["scenario"].eq("main_5pct_upper") & metrics["policy"].eq("FCFS_SHARED")
    ].iloc[0]
    frame = metrics[~metrics["scenario"].eq("main_5pct_upper")].copy()
    name_map = {
        "nominal_no_special": "无 5% 时长上浮",
        "low_doctor_q25": "医生容量下四分位",
        "strict_capability": "仅严格设备兼容",
        "bladder_45min": "憋尿准备 45 分钟",
        "bladder_90min": "憋尿准备 90 分钟",
        "transfer_5min": "跨室转运 5 分钟",
        "transfer_15min": "跨室转运 15 分钟",
    }
    frame["label"] = frame["scenario"].map(name_map)
    frame["inpatient_delta_pp"] = (frame["inpatient_48h_rate"] - main["inpatient_48h_rate"]) * 100
    frame["background_delta_pp"] = (frame["background_on_time_rate"] - main["background_on_time_rate"]) * 100
    y = np.arange(len(frame))
    fig, ax = plt.subplots(figsize=(8.8, 5.5))
    ax.axvline(0, color="#263238", lw=1)
    ax.hlines(y, frame["background_delta_pp"], frame["inpatient_delta_pp"], color="#B7C2CF", lw=2)
    ax.scatter(frame["inpatient_delta_pp"], y, color=BLUE, s=70, label="住院 48 小时率")
    ax.scatter(frame["background_delta_pp"], y, color=ORANGE, s=70, label="背景预约日率")
    ax.set_yticks(y, frame["label"])
    ax.invert_yaxis()
    ax.set_xlabel("相对主推荐策略的变化（百分点）")
    ax.set_title("关键证据与参数边界的敏感性")
    ax.grid(axis="x", color="#D7DEE8", lw=0.7)
    ax.legend(frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.5, -0.32))
    fig.tight_layout()
    save(fig, "fig05_sensitivity")


def daily_performance() -> None:
    daily = pd.read_csv(UNIFIED / "daily_service_metrics.csv")
    # The result file contains both date-only and timestamp-formatted rows from
    # different scenarios.  Parse the mixed ISO representations explicitly;
    # otherwise pandas leaves an object series and matplotlib interprets the
    # row positions as days since 1970.
    daily["metric_date"] = pd.to_datetime(daily["metric_date"], format="mixed").dt.normalize()
    frame = daily[
        daily["scenario"].eq("main_5pct_upper") & daily["policy"].eq("FCFS_SHARED")
    ].copy()
    inpatient = frame[frame["source"].eq("住院")].sort_values("metric_date")
    background = (
        frame[~frame["source"].eq("住院")]
        .groupby("metric_date", as_index=False)
        .agg(events=("events", "sum"), deadline_met=("deadline_met", "sum"))
        .sort_values("metric_date")
    )
    background["deadline_rate"] = background["deadline_met"] / background["events"]
    fig, ax = plt.subplots(figsize=(10.2, 4.5))
    ax.plot(
        inpatient["metric_date"],
        inpatient["deadline_rate"].rolling(14, min_periods=1).mean(),
        color=BLUE,
        lw=1.7,
        label="住院 48 小时率（14 日滚动）",
    )
    ax.plot(
        background["metric_date"],
        background["deadline_rate"].rolling(14, min_periods=1).mean(),
        color=ORANGE,
        lw=1.7,
        label="门诊/体检预约日率（14 日滚动）",
    )
    ax.axhline(inpatient["deadline_met"].sum() / inpatient["events"].sum(), color=BLUE, ls="--", lw=0.9)
    ax.axhline(background["deadline_met"].sum() / background["events"].sum(), color=ORANGE, ls="--", lw=0.9)
    ax.set_ylim(0.25, 0.95)
    ax.yaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    ax.set_xlabel("留出期日期")
    ax.set_ylabel("完成率")
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.tick_params(axis="x", rotation=0)
    ax.set_title("主推荐策略的日级服务稳定性")
    ax.grid(axis="y", color="#D7DEE8", lw=0.7)
    ax.legend(frameon=False, ncol=2, loc="lower center", bbox_to_anchor=(0.5, -0.30))
    fig.tight_layout()
    save(fig, "fig06_daily_performance")


def representative_gantt() -> None:
    schedule = pd.read_csv(
        UNIFIED / "final_patient_task_schedule.csv",
        parse_dates=["start_dt", "end_dt"],
        dtype={"room_id": "string"},
        low_memory=False,
    )
    schedule["evaluation_cohort"] = schedule["evaluation_cohort"].astype(str).str.lower().eq("true")
    frame = schedule[schedule["evaluation_cohort"]].copy()
    frame["date"] = frame["start_dt"].dt.normalize()
    daily_minutes = frame.groupby("date")["duration_minutes"].sum()
    target = daily_minutes.idxmax()
    day = frame[frame["date"].eq(target)].copy()
    room_order = (
        day.groupby(["room_id", "room_name"])["duration_minutes"]
        .sum()
        .sort_values(ascending=True)
        .index.tolist()
    )
    y_lookup = {room_id: pos for pos, (room_id, _) in enumerate(room_order)}
    colors = {"住院": BLUE, "门诊": ORANGE, "体检": GREEN}
    fig, ax = plt.subplots(figsize=(10.8, 7.2))
    origin = target + pd.Timedelta(hours=8)
    for row in day.itertuples(index=False):
        start = (row.start_dt - origin).total_seconds() / 3600
        width = (row.end_dt - row.start_dt).total_seconds() / 3600
        ax.barh(
            y_lookup[str(row.room_id)],
            width,
            left=start,
            height=0.72,
            color=colors[row.source],
            edgecolor="white",
            linewidth=0.25,
        )
    ax.axvspan(4, 5, color="#F0F2F5", zorder=0)
    ax.set_yticks(
        range(len(room_order)),
        [f"{room_name}（{room_id}）" for room_id, room_name in room_order],
        fontsize=8,
    )
    ax.set_xticks(range(10), [f"{8 + hour:02d}:00" for hour in range(10)])
    ax.set_xlim(0, 9)
    ax.set_xlabel("时刻")
    ax.set_title(f"高负荷代表日 {target.date()} 的 22 台设备患者级排程")
    ax.grid(axis="x", color="#D7DEE8", lw=0.6)
    ax.legend(
        handles=[Patch(color=colors[key], label=key) for key in ["住院", "门诊", "体检"]],
        frameon=False,
        ncol=3,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.13),
    )
    fig.tight_layout()
    save(fig, "fig07_representative_gantt")


def room_utilization() -> None:
    schedule = pd.read_csv(
        UNIFIED / "final_patient_task_schedule.csv",
        parse_dates=["start_dt"],
        dtype={"room_id": "string"},
        low_memory=False,
    )
    evaluation = schedule["evaluation_cohort"].astype(str).str.lower().eq("true")
    frame = schedule[evaluation].copy()
    frame["date"] = frame["start_dt"].dt.normalize()
    dates = pd.date_range("2024-04-01", "2025-03-31", freq="D")
    rooms = frame[["room_id", "room_name"]].drop_duplicates()
    complete = pd.MultiIndex.from_product(
        [dates, rooms["room_id"]], names=["date", "room_id"]
    ).to_frame(index=False)
    used = frame.groupby(["date", "room_id"], as_index=False)["duration_minutes"].sum()
    complete = complete.merge(used, on=["date", "room_id"], how="left").fillna({"duration_minutes": 0})
    mean = complete.groupby("room_id")["duration_minutes"].mean().div(480).sort_values()
    name_map = rooms.set_index("room_id")["room_name"].to_dict()
    fig, ax = plt.subplots(figsize=(8.8, 6.2))
    colors = [RED if room == "7" else BLUE for room in mean.index]
    bars = ax.barh(range(len(mean)), mean.values, color=colors, height=0.68)
    ax.set_yticks(range(len(mean)), [f"{name_map[room]}（{room}）" for room in mean.index], fontsize=8)
    ax.xaxis.set_major_formatter(lambda value, _: f"{value:.0%}")
    ax.set_xlabel("留出期日均占用率（以每日 480 分钟计）")
    ax.set_title("主推荐策略下各设备日均占用")
    ax.grid(axis="x", color="#D7DEE8", lw=0.7)
    ax.legend(handles=[Patch(color=RED, label="床旁唯一设备"), Patch(color=BLUE, label="普通设备")], frameon=False)
    fig.tight_layout()
    save(fig, "fig08_room_utilization")


def modeling_flow() -> None:
    fig, ax = plt.subplots(figsize=(10.4, 3.7))
    ax.axis("off")
    boxes = [
        (0.02, "数据审计\n时间边界与事件口径"),
        (0.22, "P1 参数层\n需求·时长·设备·医生"),
        (0.42, "统一任务层\n患者—项目—可用机房"),
        (0.62, "连续日历排程\n房间与医生共享容量"),
        (0.82, "留出期评价\n约束核验与敏感性"),
    ]
    for index, (x, label) in enumerate(boxes):
        color = [LIGHT, "#DDE9F7", "#DFF1E5", "#FCE8D2", "#E9E0F0"][index]
        ax.text(
            x + 0.08,
            0.52,
            label,
            ha="center",
            va="center",
            fontsize=10,
            bbox=dict(boxstyle="round,pad=0.6", facecolor=color, edgecolor="#607D8B", linewidth=1.1),
            transform=ax.transAxes,
        )
        if index < len(boxes) - 1:
            ax.annotate(
                "",
                xy=(x + 0.19, 0.52),
                xytext=(x + 0.17, 0.52),
                arrowprops=dict(arrowstyle="->", color="#607D8B", lw=1.4),
                xycoords=ax.transAxes,
            )
    ax.text(0.50, 0.12, "训练期冻结参数（至 2024-03-31）  →  留出期只用于评价（2024-04-01 至 2025-03-31）", ha="center", fontsize=10, color=GRAY, transform=ax.transAxes)
    ax.set_title("从原始记录到可执行预约方案的建模链", pad=18)
    fig.tight_layout()
    save(fig, "fig09_modeling_flow")


def main() -> None:
    configure()
    monthly_demand()
    doctor_capacity()
    capability_coverage()
    policy_tradeoff()
    sensitivity()
    daily_performance()
    representative_gantt()
    room_utilization()
    modeling_flow()
    print(f"created 9 vector PDF figures in {OUT}")


if __name__ == "__main__":
    main()
