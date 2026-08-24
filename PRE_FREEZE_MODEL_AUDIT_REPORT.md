# 模型与结果冻结前技术审计报告

## 1. 最终结论

技术审计后的冻结判断为：`MODEL_AND_RESULTS_FROZEN = TRUE`。冻结检查逐项结果见本报告第14节和 `FINAL_RESULT_MANIFEST.json`。

## 2. 原始模型存在的问题

原模型存在四项会改变结果的硬问题：50个项目采用整族能力回退；床旁标记直接覆盖项目专项能力；问题三把模型自身约59.70%的背景完成率写成“满足需求”；问题一峰平阈值使用留出期分位数。另发现项目单元格中的显式 `][` 拼接没有拆成独立任务。上述问题均已在上游代码修复并重跑。

## 3. 设备能力整改

50个原回退项目已逐项列入 `LEGACY_50_FALLBACK_PROJECT_AUDIT.csv`，A/B/C级映射进入硬能力集合，D级项目排除；4个旧复合单元已按源字段边界拆分。整族回退已删除。当前目录D级项目 15 个。床旁审计共 55 个项目—来源组合；7号机只有在项目证据和床旁地点证据同时成立时才进入可行集。

## 4. P1整改

平峰、高峰、压力阈值和代表日全部改由训练期确定；留出期只统计阈值外推表现。日历岭回归保持 `log(1+N)` 拟合并经 `expm1` 返回原尺度；滚动基准只使用预测时点之前的已观测数据。参数来源逐项见 `TRAIN_HOLDOUT_PROVENANCE_AUDIT.md`。

## 5. P2结果

纯住院场景共 70,771 个评价事件，48小时完整完成 60,359 个，完成率 85.2878%；选用策略为 FCFS_SHARED。P50/P90/P95等待分别为 3.58/22.08/23.67 小时。

## 6. P3结果

联合场景按全留出期背景计划日代理完成率构造ε约束，日级配额短缺另作异质性诊断；自动选择的运行点为 alpha=0.30。该点住院48小时完整完成 42,730 个，完成率 60.3778%；门诊与体检计划日代理完成率 59.5308%。相对原63.95%/59.70%，分别变化 -3.59 和 -0.17 个百分点。该背景率只表示回顾性计划日压力场景，不称为全部需求已满足。

## 7. Pareto分析

`p3_joint/pareto_metrics.csv` 给出背景服务水平与住院48小时率的可行前沿。主点按“到可达理想点的归一化欧氏距离最小”确定，不用当前结果反向设阈值。

## 8. 历史现实校准

`calibration/CALIBRATION_REPORT.md` 从历史真实报告完成率开始，逐层加入题给时长、标准班次、医生并发、项目能力、准备条件和背景负荷。历史率与模型率口径不同；分解结果用于识别下降来源，而不把差值解释为模型直接造成的临床损失。

## 9. 精确求解验证

CP-SAT代表性小窗口共 6 个，启发式相对精确解的最大差距为 0.0000%，相对最好界最大差距为 0.0000%。全年结果因此仍称为可行近似解，不宣称全局最优。

## 10. 敏感性

已完成医生容量、A/B能力边界、跨室5/15分钟、憋尿45/90分钟、项目级/事件级准备及5个特殊病例seed。多seed住院率均值/标准差为 60.3626%/0.0195%。

## 11. 模型假设合理性

A类为题面直接给定（22台设备、33名医生、时长区间、5%特殊病例、48小时口径）；B类为训练期标定（需求、医生时隙容量、项目目录）；C类为数据不能唯一确定但已做敏感性（憋尿60分钟、跨室10分钟、报告完成代理、计划日代理）；原整族回退和床旁绕过专项能力属于D类，已删除或修正。

## 12. 最终冻结参数

时隙5分钟；工作时段08:00-12:00、13:00-17:00；跨室10分钟；憋尿60分钟；准备约束按项目粒度；设备能力为表1 A/B/C级逐项目映射，D级不进入主情景；医生为训练期星期×5分钟总并发代理；特殊病例比例5%，固定主seed 20260824；事件键为来源+患者ID+精确开单时刻；住院分母保留全部评价事件，最后任务结束作为报告完成代理。

## 13. 最终 authoritative 文件

唯一权威根目录：`supporting_materials/results/final_frozen/`。P2、P3、敏感性和 manifest 均在该目录；精确对照和校准分别位于 `supporting_materials/results/exact_benchmark/` 与 `supporting_materials/results/calibration/`。

## 14. 最终冻结判断

- [x] train_holdout_no_leakage
- [x] all_50_fallback_reviewed
- [x] no_blanket_category_fallback
- [x] bedside_semantics_passed
- [x] p2_exists
- [x] p3_pareto_exists
- [x] historical_calibration_exists
- [x] exact_benchmark_exists
- [x] preparation_sensitivity_exists
- [x] multi_seed_exists
- [x] input_semantics_passed
- [x] p2_schedule_verification_passed
- [x] p3_schedule_verification_passed
- [x] authoritative_result_unique

`MODEL_AND_RESULTS_FROZEN = TRUE`
