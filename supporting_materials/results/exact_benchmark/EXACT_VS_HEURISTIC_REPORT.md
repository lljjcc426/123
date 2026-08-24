# P2 Exact vs Heuristic Benchmark

启发式结果由生产调度器直接生成；CP-SAT 在相同患者、项目、房间、准备、转运、医生容量和工作块下最大化48小时完整完成事件数。`FEASIBLE` 仅表示时限内可行 incumbent，未写作最优解。
生产策略：`FCFS_LOAD_BALANCED`。

|case|date|event_count|heuristic_complete|exact_incumbent|best_bound|solver_status|solver_relative_gap|heuristic_gap_to_bound|solve_seconds|time_limit_seconds|exact_schedule_violations|
|---|---|---|---|---|---|---|---|---|---|---|---|
|normal_weekday|2024-07-17|20|17|17|17.0|OPTIMAL|0.0|0.0|1.4735679999866989|120.0|0|
|peak_weekday|2024-04-15|100|90|90|90.0|OPTIMAL|0.0|0.0|8.165592800010927|120.0|0|
|weekend|2024-04-07|40|37|37|37.0|OPTIMAL|0.0|0.0|3.509325999999419|120.0|0|
|multi_project_peak|2024-04-15|40|36|36|36.0|OPTIMAL|0.0|0.0|11.216828500007978|120.0|0|
|bedside_peak|2024-10-24|20|2|2|2.0|OPTIMAL|0.0|0.0|0.028714499989291653|120.0|0|
|obstetric_peak|2024-07-28|40|36|36|36.0|OPTIMAL|0.0|0.0|6.765271699987352|120.0|0|

OPTIMAL 场景数：6/6。
全部场景相对最好界的最大启发式差距上界：0.0000%。
精确解提取后独立检查的违规总数：0。