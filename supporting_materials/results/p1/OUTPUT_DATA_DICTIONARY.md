# P1 输出数据字典

## 冻结口径

- 数据期：2019-03-01 至 2025-03-31。
- 时间顺序验证期：2024-04-01 至 2025-03-31。
- 默认多项目系数：1.0。同一事件内的规范项目去重后逐项求和，并在同一兼容检查室连续安排。
- 敏感性多项目系数：0.8、0.9、1.0；0.8和0.9不是默认参数。
- 纯计费/报告条目：`non_service_item=True`，时长为0；床旁加收仍保留 `床旁标记=True`，与同一开单事件中的真实项目绑定。
- 题面服务时长：一般项目5--10分钟、心脏10--15分钟、产科I/II级15--20分钟、产科III/IV级30--40分钟。名义值取区间中点，稳健容量情景取上界。
- 报告间隔仅为相对负荷代理，不是检查服务时长。

## 下游主要入口

### `project_category_catalog.csv`

正式期开单项目字典，每行是一个患者来源下的原始项目名称。

- `source`：住院、门诊、体检。
- `ordered_project`：原始医嘱项目名称。
- `project_norm`：规范化项目名称，用于事件内项目去重。
- `category`：互斥项目族。
- `non_service_item`：是否为独立计费/报告条目。
- `床旁标记`：是否需要床旁资源。
- `空腹上午标记`：是否命中腹部/胃肠空腹上午约束。
- `充盈膀胱标记`：是否命中泌尿/经腹妇科充盈膀胱约束。
- `duration_lower_min`、`duration_nominal_min`、`duration_upper_min`：题面分钟参数。
- `record_count`：该来源正式期内的明细行数。

### `service_duration_parameters.csv`

按项目族汇总的调度时长入口。

- `category`：项目族。
- `duration_lower_min`、`duration_nominal_min`、`duration_upper_min`：下界、中点、上界。
- `robust_schedule_parameter_min`：稳健容量情景参数，等于题面上界。
- `special_case_frequency_from_problem`：题面给出的特殊病例比例0.05。
- `special_case_extra_duration_known`：额外倍率是否已知；当前为False。
- `multiproject_default_coefficient`：默认1.0。
- `multiproject_sensitivity_lower`、`multiproject_sensitivity_upper`：敏感性区间0.8--1.0。
- `proxy_*`、`relative_burden_index`：单项目报告间隔代理统计，只用于相对负荷校核。

### `resource_flag_rules.csv`

床旁、空腹上午、充盈膀胱三类非互斥约束的正则表达式。分类族规则见同目录 `category_rules.csv`。

### `peak_flat_summary.csv`

最后12个月的高峰/平峰口径。

- `basis`：开单日表示需求，报告日表示历史吞吐。
- `median_flat_level`：日事件数中位数，作为平峰水平。
- `q90_peak_threshold`：日事件数90%分位，作为高峰阈值。
- `q95_stress_threshold`：日事件数95%分位，作为压力情景阈值。
- `representative_*`：最接近相应水平的真实日期和事件数。
- `peak_weekday`、`peak_calendar_month`：按日中位数识别的峰值星期和月份。

三类开单事件合计的冻结值为：平峰439个/日，Q90高峰723个/日，Q95压力阈值892.6个/日；代表性平峰日2024-04-28，代表性高峰日2024-07-29。

### `multiproject_coefficient_sensitivity.csv`

默认逐项求和与0.8/0.9敏感性情景的总工作量。`basis` 区分开单事件与报告事件；`multiproject_episode_share` 只把至少两个真实服务项目的事件计为多项目事件。

### `doctor_efficiency_shrunk.csv`

历史医生报告吞吐代理，不是临床扫查速度。

- `valid_days`、`total_episodes`：进入估计的历史信息量。
- `raw_relative_throughput_factor`：未收缩相对因子。
- `shrunk_relative_throughput_factor`：经验贝叶斯后验相对因子。
- `factor_ci95_lower`、`factor_ci95_upper`：后验95%区间。

当前医生名单和历史ID没有映射时，下游默认总体因子1.0，只能把历史因子分布用于敏感性分析。

## 完整趋势与验证

- `daily_trends.csv`：完整自然日日序列，缺少记录的自然日补0。
- `weekly_trends.csv`：周汇总。
- `monthly_trends.csv`：月汇总。
- `annual_trends.csv`：年汇总；只把2020--2024标记为完整年份。
- `chronological_validation.csv`：固定最后12个月留出的时间顺序验证结果。
- `category_volume_summary.csv`：正式期项目族记录量与来源内占比。
- `report_gap_proxy_by_category.csv`：单项目报告间隔代理。
- `non_service_item_summary.csv`：正式期纯计费/报告条目数量。
- `doctor_day_reconciliation.csv`：重建医生日与表6的逐日对照。
- `analysis_summary.json`：关键诊断和建模边界的机器可读摘要。

## 复现入口

```powershell
python supporting_materials/code/analyze_p1.py
```

脚本固定随机种子 `20260823`，只读取 `supporting_materials/processed_data/raw_parquet/`，结果写入 `supporting_materials/results/p1/`，图件写入 `supporting_materials/figures/p1/`。
