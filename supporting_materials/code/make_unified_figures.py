"""Create vector figures from the frozen result chain."""
from __future__ import annotations
from pathlib import Path
import json
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
P1 = ROOT / "supporting_materials/results/p1"
INPUT = ROOT / "supporting_materials/processed_data/unified_holdout"
FROZEN = ROOT / "supporting_materials/results/final_frozen"
CAL = ROOT / "supporting_materials/results/calibration"
OUT = ROOT / "supporting_materials/figures/paper_final"
BLUE, ORANGE, GREEN, RED, PURPLE, GRAY = "#276FBF", "#F28E2B", "#3A9D5D", "#C93C3C", "#7A5195", "#6B7280"
LIGHT, GRID = "#E8EEF5", "#D7DEE8"
POLICY_LABELS = {
    "FCFS_SHARED": "FCFS\n最低编号",
    "SLACK_GUARD_SHARED": "松弛度\n最低编号",
    "FCFS_LOAD_BALANCED": "FCFS\n负荷均衡",
    "SLACK_LOAD_BALANCED": "松弛度\n负荷均衡",
    "FCFS_SCARCITY_PRESERVING": "FCFS\n稀缺保护",
    "SLACK_SCARCITY_PRESERVING": "松弛度\n稀缺保护",
}


def alpha_label(value: float) -> str:
    text = f"{float(value):.3f}"
    return text[:-1] if text.endswith("0") else text

def configure() -> None:
    available = {font.name for font in font_manager.fontManager.ttflist}
    family = next((name for name in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC"] if name in available), "DejaVu Sans")
    plt.rcParams.update({"font.family": family, "axes.unicode_minus": False, "axes.spines.top": False, "axes.spines.right": False, "figure.dpi": 150, "savefig.dpi": 300})
    OUT.mkdir(parents=True, exist_ok=True)

def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)

def monthly_demand() -> None:
    frame = pd.read_csv(P1 / "monthly_trends.csv", parse_dates=["period"])
    frame = frame[frame["basis"].eq("开单日")]
    colors = {"住院": BLUE, "门诊": ORANGE, "体检": GREEN}
    fig, ax = plt.subplots(figsize=(10.2, 4.3))
    for source, group in frame.groupby("source", sort=False):
        ax.plot(group["period"], group["mean_daily_episodes"], lw=1.7, color=colors[source], label=source)
    split = pd.Timestamp("2024-04-01")
    ax.axvspan(split, pd.Timestamp("2025-04-01"), color=LIGHT, alpha=.9)
    ax.axvline(split, color=GRAY, ls="--", lw=1)
    ax.text(split + pd.Timedelta(days=10), ax.get_ylim()[1]*.92, "时间顺序留出期", color=GRAY)
    ax.set(title="三类患者月度日均开单事件与留出边界", xlabel="月份", ylabel="日均事件数")
    ax.grid(axis="y", color=GRID); ax.legend(frameon=False, ncol=3)
    fig.tight_layout(); save(fig, "fig01_monthly_demand")

def doctor_capacity() -> None:
    frame = pd.read_csv(INPUT / "doctor_slot_capacity.csv")
    fig, axes = plt.subplots(2, 1, figsize=(10.2, 5.6), sharex=True)
    labels = ["周一","周二","周三","周四","周五","周六","周日"]
    for ax, column, title in zip(axes, ["capacity_main","capacity_low"], ["训练期中位并发（主情景）","训练期下四分位并发（偏紧情景）"]):
        for weekday, group in frame.groupby("weekday"):
            ax.plot(np.arange(len(group)), group[column], lw=1.2, label=labels[int(weekday)])
        ax.set_ylabel("并发医生数"); ax.set_title(title, loc="left", fontsize=11); ax.grid(axis="y", color=GRID)
    axes[-1].set_xticks([0,12,24,36,47,48,60,72,84,95], ["08:00","09:00","10:00","11:00","11:55","13:00","14:00","15:00","16:00","16:55"])
    axes[0].legend(ncol=7, frameon=False, loc="upper center", bbox_to_anchor=(.5,1.32))
    fig.suptitle("训练期星期—5分钟共享医生容量", y=1.02, fontweight="bold")
    fig.tight_layout(); save(fig, "fig02_doctor_capacity")

def capability_coverage() -> None:
    summary = pd.read_csv(INPUT / "project_machine_summary.csv", encoding="utf-8-sig")
    items = pd.read_csv(INPUT / "items.csv", encoding="utf-8-sig", low_memory=False)
    events = pd.read_csv(INPUT / "events.csv", encoding="utf-8-sig", usecols=["event_id","source"])
    frame = items[["event_id","project_norm"]].merge(events,on="event_id").merge(summary[["project_norm","evidence_level"]],on="project_norm")
    table = frame.groupby(["source","evidence_level"]).size().unstack(fill_value=0).reindex(["住院","门诊","体检"])
    table = table.div(table.sum(axis=1), axis=0)
    fig, ax = plt.subplots(figsize=(8.8, 3.7)); left=np.zeros(len(table))
    display = {"A":"直接匹配", "B":"语义匹配", "C":"明确广义", "D":"未确认"}
    for level,color in zip("ABCD",[BLUE,GREEN,ORANGE,RED]):
        values=table.get(level,pd.Series(0,index=table.index)).to_numpy()
        bars=ax.barh(table.index,values,left=left,color=color,height=.56,label=display[level])
        for bar,val,start in zip(bars,values,left):
            if val>.035: ax.text(start+val/2,bar.get_y()+bar.get_height()/2,f"{val:.1%}",ha="center",va="center",color="white",fontsize=9)
        left += values
    ax.set_xlim(0,1); ax.xaxis.set_major_formatter(lambda x,_:f"{x:.0%}"); ax.set_xlabel("项目任务占比"); ax.set_title("项目—设备匹配方式覆盖")
    ax.legend(ncol=4,frameon=False,loc="lower center",bbox_to_anchor=(.5,-.38))
    fig.tight_layout(); save(fig, "fig03_capability_coverage")

def p2_policy() -> None:
    frame = pd.read_csv(FROZEN / "p2_inpatient_only/policy_metrics.csv")
    labels=[POLICY_LABELS[policy] for policy in frame["policy"]]
    x=np.arange(len(frame)); colors=[BLUE,ORANGE,GREEN,PURPLE,GRAY,RED][:len(frame)]
    fig, axes=plt.subplots(1,2,figsize=(11.4,4.2))
    axes[0].plot(x,frame["inpatient_48h_rate"],color=GRID,lw=1.4,zorder=1)
    axes[0].scatter(x,frame["inpatient_48h_rate"],color=colors,s=70,zorder=2)
    rate_min, rate_max = frame["inpatient_48h_rate"].min(), frame["inpatient_48h_rate"].max()
    rate_pad = max((rate_max-rate_min)*.2, .003)
    axes[0].set_xticks(x,labels,fontsize=8); axes[0].set_ylim(max(0,rate_min-rate_pad),min(1,rate_max+rate_pad)); axes[0].yaxis.set_major_formatter(lambda v,_:f"{v:.1%}"); axes[0].set_title("住院48小时完整完成率")
    axes[1].bar(x,frame["inpatient_wait_p50_hours_conditional"],color=colors,width=.62,label="P50")
    axes[1].bar(x,frame["inpatient_wait_p90_hours_conditional"]-frame["inpatient_wait_p50_hours_conditional"],bottom=frame["inpatient_wait_p50_hours_conditional"],color=LIGHT,width=.62,label="P50至P90")
    axes[1].set_xticks(x,labels,fontsize=8); axes[1].set_ylabel("小时"); axes[1].set_title("条件等待时间"); axes[1].legend(frameon=False)
    for ax in axes: ax.grid(axis="y",color=GRID,zorder=0)
    fig.tight_layout(); save(fig, "fig04_p2_policy")

def pareto() -> None:
    frame=pd.read_csv(FROZEN/"p3_joint/pareto_metrics.csv")
    frame=frame[
        frame["epsilon_feasible"].eq(True) & frame["pareto_nondominated"].eq(True)
    ].sort_values(["background_on_time_rate", "inpatient_48h_rate"]).copy()
    selected=float(json.loads((FROZEN/"p3_joint/selection.json").read_text(encoding="utf-8"))["selected_alpha"])
    fig,ax=plt.subplots(figsize=(7.4,5.0))
    ax.plot(frame["background_on_time_rate"],frame["inpatient_48h_rate"],"-o",color=BLUE,lw=1.8,ms=6)
    for index, row in enumerate(frame.itertuples(index=False)):
        offset_y = 7 if index % 2 == 0 else -13
        ax.annotate(f"$\\alpha$={alpha_label(row.background_target_alpha)}",(row.background_on_time_rate,row.inpatient_48h_rate),xytext=(5,offset_y),textcoords="offset points",fontsize=8)
    mark=frame[np.isclose(frame["background_target_alpha"],selected)].iloc[0]
    ax.scatter(mark["background_on_time_rate"],mark["inpatient_48h_rate"],s=180,color=RED,edgecolor="white",zorder=5,label="推荐折中点")
    ax.xaxis.set_major_formatter(lambda v,_:f"{v:.0%}"); ax.yaxis.set_major_formatter(lambda v,_:f"{v:.0%}")
    ax.set(xlabel="门诊/体检计划日代理完成率",ylabel="住院48小时完整完成率",title="共享资源下的住院—背景服务Pareto前沿")
    ax.grid(color=GRID); ax.legend(frameon=False)
    fig.tight_layout(); save(fig, "fig05_pareto")

def calibration() -> None:
    frame=pd.read_csv(CAL/"calibration_metrics.csv")
    scenario_order=[
        "C0_historical_report", "C1_duration_only", "C2_standard_hours",
        "C3_doctor_capacity", "C4_project_capability", "C5_item_preparation",
        "C6_joint_background", "C7_formal_heuristic",
    ]
    frame=frame.set_index("scenario").loc[scenario_order].reset_index()
    labels=["历史报告","仅时长","标准班次","医生并发","设备能力","项目准备","背景竞争","正式策略"]
    colors=[GRAY,GREEN,GREEN,GREEN,ORANGE,ORANGE,RED,BLUE]
    fig,ax=plt.subplots(figsize=(10.0,4.2))
    bars=ax.bar(np.arange(len(frame)),frame["rate"],color=colors,width=.68)
    ax.set_xticks(np.arange(len(frame)),labels,rotation=18,ha="right"); ax.set_ylim(0,1.05); ax.yaxis.set_major_formatter(lambda v,_:f"{v:.0%}")
    for bar,val in zip(bars,frame["rate"]): ax.text(bar.get_x()+bar.get_width()/2,val+.015,f"{val:.1%}",ha="center",fontsize=8)
    ax.set_ylabel("完成率"); ax.set_title("从历史口径到正式联合排程的逐层现实校准"); ax.grid(axis="y",color=GRID)
    fig.tight_layout(); save(fig,"fig06_calibration")

def sensitivity() -> None:
    frame=pd.read_csv(FROZEN/"sensitivity_metrics.csv").set_index("audit_scenario")
    base=frame.loc["preparation_item"]
    order=["preparation_event","doctor_low","capability_AB","bladder45","bladder90","transfer5","transfer15"]
    names=["事件级准备","医生容量下四分位","仅直接/语义匹配","憋尿45分钟","憋尿90分钟","转运5分钟","转运15分钟"]
    ip=(frame.loc[order,"inpatient_48h_rate"]-base["inpatient_48h_rate"])*100
    bg=(frame.loc[order,"background_on_time_rate"]-base["background_on_time_rate"])*100
    y=np.arange(len(order)); fig,ax=plt.subplots(figsize=(8.8,5.1))
    ax.axvline(0,color="#263238",lw=1); ax.hlines(y,bg,ip,color="#B7C2CF",lw=2)
    ax.scatter(ip,y,color=BLUE,s=65,label="住院率"); ax.scatter(bg,y,color=ORANGE,s=65,label="背景率")
    ax.set_yticks(y,names); ax.invert_yaxis(); ax.set_xlabel("相对主情景变化（百分点）"); ax.set_title("关键边界敏感性")
    ax.grid(axis="x",color=GRID); ax.legend(frameon=False,ncol=2)
    fig.tight_layout(); save(fig,"fig07_sensitivity")

def daily_performance() -> None:
    daily=pd.read_csv(FROZEN/"p3_joint/daily_service_metrics.csv")
    daily["metric_date"]=pd.to_datetime(daily["metric_date"],format="mixed").dt.normalize()
    ip=daily[daily["source"].eq("住院")].sort_values("metric_date")
    bg=daily[~daily["source"].eq("住院")].groupby("metric_date",as_index=False).agg(events=("events","sum"),deadline_met=("deadline_met","sum"))
    bg["deadline_rate"]=bg["deadline_met"]/bg["events"]
    fig,ax=plt.subplots(figsize=(10.2,4.3))
    ax.plot(ip["metric_date"],ip["deadline_rate"].rolling(14,min_periods=1).mean(),color=BLUE,label="住院48小时率")
    ax.plot(bg["metric_date"],bg["deadline_rate"].rolling(14,min_periods=1).mean(),color=ORANGE,label="背景计划日率")
    ax.yaxis.set_major_formatter(lambda v,_:f"{v:.0%}"); ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2)); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.set(xlabel="留出期日期",ylabel="14日滚动完成率",title="推荐联合策略的日级稳定性"); ax.grid(axis="y",color=GRID); ax.legend(frameon=False,ncol=2)
    fig.tight_layout(); save(fig,"fig08_daily_performance")

def gantt() -> None:
    schedule=pd.read_csv(FROZEN/"p3_joint/final_patient_task_schedule.csv",parse_dates=["start_dt","end_dt"],dtype={"room_id":"string"},low_memory=False)
    schedule["date"]=schedule["start_dt"].dt.normalize()
    target=schedule.groupby("date")["duration_minutes"].sum().idxmax()
    day=schedule[schedule["date"].eq(target)].copy()
    room_order=day.groupby(["room_id","room_name"])["duration_minutes"].sum().sort_values().index.tolist()
    ymap={room:i for i,(room,_) in enumerate(room_order)}; colors={"住院":BLUE,"门诊":ORANGE,"体检":GREEN}
    fig,ax=plt.subplots(figsize=(10.5,6.8)); origin=target+pd.Timedelta(hours=8)
    for row in day.itertuples(index=False):
        left=(row.start_dt-origin).total_seconds()/3600; width=(row.end_dt-row.start_dt).total_seconds()/3600
        ax.barh(ymap[str(row.room_id)],width,left=left,height=.7,color=colors[row.source],edgecolor="white",linewidth=.2)
    ax.axvspan(4,5,color="#F0F2F5"); ax.set_yticks(range(len(room_order)),[f"{name}({room})" for room,name in room_order],fontsize=8)
    ax.set_xticks(range(10),[f"{8+h:02d}:00" for h in range(10)]); ax.set_xlim(0,9); ax.set_xlabel("时刻"); ax.set_title(f"高负荷代表日 {target.date()} 的设备排程")
    ax.grid(axis="x",color=GRID); ax.legend(handles=[Patch(color=colors[k],label=k) for k in colors],frameon=False,ncol=3)
    fig.tight_layout(); save(fig,"fig09_representative_gantt")

def modeling_flow() -> None:
    fig,ax=plt.subplots(figsize=(10.4,3.6)); ax.axis("off")
    boxes=[("数据整理\n事件与边界",LIGHT),("P1参数层\n需求·时长·能力", "#DDE9F7"),("P2纯住院\n患者级排程","#DFF1E5"),("P3联合\nε约束与Pareto","#FCE8D2"),("模型检验\n结果解释","#E9E0F0")]
    xs=np.linspace(.1,.9,len(boxes))
    for i,((label,color),x) in enumerate(zip(boxes,xs)):
        ax.text(x,.58,label,ha="center",va="center",fontsize=10,bbox=dict(boxstyle="round,pad=.6",facecolor=color,edgecolor="#607D8B"),transform=ax.transAxes)
        if i<len(boxes)-1: ax.annotate("",xy=(xs[i+1]-.09,.58),xytext=(x+.09,.58),arrowprops=dict(arrowstyle="->",color="#607D8B",lw=1.4),xycoords=ax.transAxes)
    ax.text(.5,.16,"训练期估计参数（至2024-03-31）  →  留出期仅评价（2024-04-01至2025-03-31）",ha="center",color=GRAY,transform=ax.transAxes)
    ax.set_title("统一患者—项目—设备—医生排程建模链",pad=18)
    fig.tight_layout(); save(fig,"fig10_modeling_flow")

def main() -> None:
    configure(); monthly_demand(); doctor_capacity(); capability_coverage(); p2_policy(); pareto(); calibration(); sensitivity(); daily_performance(); gantt(); modeling_flow()
    print("created 10 vector PDF figures")

if __name__ == "__main__": main()
