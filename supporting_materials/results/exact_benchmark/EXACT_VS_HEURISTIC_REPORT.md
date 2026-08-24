# Exact vs Heuristic Benchmark

代表性小规模住院窗口使用与主模型相同的项目时长、设备集合、医生总并发、准备条件、患者互斥和跨室转运约束。CP-SAT 在每个窗口内最大化48小时完整完成患者数；全年模型仍采用构造算法。

|case|date|event_count|heuristic_complete|exact_complete|best_bound|heuristic_gap_to_exact|heuristic_gap_to_bound|solver_status|solve_seconds|
|---|---|---|---|---|---|---|---|---|---|
|normal_weekday|2024-07-17|18|15|15|15.0|0.0|0.0|OPTIMAL|47.093723700003466|
|peak_weekday|2024-04-15|18|16|16|16.0|0.0|0.0|OPTIMAL|36.8300678999949|
|weekend|2024-04-07|18|16|16|16.0|0.0|0.0|OPTIMAL|32.74517600001127|
|multi_project_peak|2024-05-20|10|10|10|10.0|0.0|0.0|OPTIMAL|47.64225810000789|
|bedside_peak|2024-10-24|18|2|2|2.0|0.0|0.0|OPTIMAL|0.7156233999994583|
|obstetric_peak|2024-07-28|18|16|16|16.0|0.0|0.0|OPTIMAL|42.65232760000799|

最大启发式相对精确解差距：0.0000%。
最大启发式相对最好界差距：0.0000%。