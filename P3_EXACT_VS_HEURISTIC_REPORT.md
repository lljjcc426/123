# P3 精确求解与生产启发式对照报告

基准服务下限为 alpha=0.4500，来源为 `supporting_materials/results/final_frozen/p3_joint/selection.json`；生产策略为 `FCFS_LOAD_BALANCED`。每个子问题同时包含住院、门诊和体检事件，正式约束为 `background_completed >= ceil(alpha * background_events)`；逐日配额不在精确模型中。

## 模型与实现

- P2生产策略解析：`supporting_materials/code/run_unified_scheduler.py:93`，P3不另设房间或住院排序策略。
- 项目展开、能力、床旁与项目级准备：`supporting_materials/code/run_unified_scheduler.py:382`，两侧共用同一 `Task` 集合。
- 生产 P3 入口：`supporting_materials/code/run_pre_freeze_scenarios.py:306`，与全年 P3 共用。
- 生产调度内核：`supporting_materials/code/run_unified_scheduler.py:629` 与 `supporting_materials/code/run_unified_scheduler.py:534`。
- 精确子问题：`supporting_materials/code/benchmark_exact_scheduler.py:395`。
- 精确模型包含完整事件选择、项目设备兼容、床旁设备交集、项目级准备、空腹与憋尿、患者互斥、跨室转运、设备互斥、星期×5分钟医生容量、上午/下午工作块、住院48小时截止、背景计划日截止及背景最低完成数。

## 八类代表窗口

|case|event_count|inpatient_events|outpatient_events|physical_exam_events|required_background|heuristic_background_complete|heuristic_inpatient_complete|repair_triggered|exact_inpatient_incumbent|best_bound|solver_status|solver_relative_gap|heuristic_gap_to_bound|solve_seconds|time_limit_seconds|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|ordinary_joint_n20|20|8|6|6|6|12|4|False|4|4.0|OPTIMAL|0.0|0.0|0.49490890000015497|180.0|
|background_peak_n40|40|10|16|14|14|30|6|False|6|6.0|OPTIMAL|0.0|0.0|1.4710135999921476|180.0|
|inpatient_peak_n60|60|36|12|12|11|24|32|False|32|32.0|OPTIMAL|0.0|0.0|3.029621199995745|180.0|
|multi_project_peak_n40|40|16|13|11|11|19|14|False|14|14.0|OPTIMAL|0.0|0.0|11.732113699996262|180.0|
|bedside_pressure_n20|20|8|6|6|6|8|0|False|0|-0.0|OPTIMAL|-0.0|-0.0|2.96385640000517|180.0|
|obstetric_pressure_n40|40|16|13|11|11|23|15|False|15|15.0|OPTIMAL|0.0|0.0|6.326814799991553|180.0|
|equipment_competition_n60|60|24|19|17|17|34|23|False|23|23.0|OPTIMAL|0.0|0.0|6.84370170001057|180.0|
|recommended_alpha_typical_n100|100|40|32|28|27|60|33|False|33|33.0|OPTIMAL|0.0|0.0|4.1727380999946035|180.0|

求解器相对间隙定义为 `(best_bound-incumbent)/max(|best_bound|,1)`；生产启发式相对最好界的差距按同一分母计算。
规模覆盖：[20, 40, 60, 100]；三类患者同时存在：True。
OPTIMAL 场景数：8/8；FEASIBLE 场景数：0/8。
所有场景相对最好界的最大启发式差距上界：0.0000%。
仅在已证 OPTIMAL 场景中的最大启发式差距：0.0000%。
CP-SAT 与生产启发式排程的独立约束检查违规数分别为 0 和 0。

## 真实峰值日修复路径审计

按评估期 `case_date` 的 `upper_minutes` 总和最大且并列时日期最早的固定规则，选中 2025-02-17；共 805 个事件（住院 305、门诊 407、体检 93），项目时长区间上界汇总指标为 20375 分钟。
基线完成背景事件 213 个，低于整数下限 225，因此修复触发状态为 `True`。最终采用 `global_deficit_repair/scarcity`，完成背景事件 258 个、住院事件 259 个；ε约束满足状态为 `True`，独立约束检查违规数为 0。
该审计只证明真实数据中修复分支会被自然触发，且输出排程满足正式约束；它不是修复分支的精确最优性证明。八个 CP-SAT 窗口中有 0 个触发修复、8 个采用基线构造，精确最优性结论只适用于各自被实际对照的子问题。

## 结论边界

`OPTIMAL` 只表示对应代表子问题在给定模型下已证最优；`FEASIBLE` 只报告 incumbent、best bound、gap 和时限。该基准用于量化生产启发式在代表窗口中的求解质量，不证明全年问题达到全局最优。