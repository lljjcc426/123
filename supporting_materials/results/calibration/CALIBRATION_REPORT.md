# 历史现实校准报告

历史报告完成率与标准化排程率口径不同。下表在同一留出期事件定义上逐层加入题给时长、标准班次、医生并发、设备能力、准备条件和背景负荷。

|scenario|completed|total|rate|policy|warmup_in_statistics|added_constraint|change_from_previous_pp|
|---|---|---|---|---|---|---|---|
|C0_historical_report|59283|70771|0.8376736233768068|OBSERVED|False|observed order-to-report result|nan|
|C1_duration_only|70771|70771|1.0|FCFS_LOAD_BALANCED|False|nominal durations with the fixed 5% upper-duration cases|16.232637662319316|
|C2_standard_hours|70771|70771|1.0|FCFS_LOAD_BALANCED|False|8-12 and 13-17 work blocks; all rooms interchangeable; 22-doctor cap|0.0|
|C3_doctor_capacity|70771|70771|1.0|FCFS_LOAD_BALANCED|False|training-derived weekday-slot doctor capacity|0.0|
|C4_project_capability|60513|70771|0.8550536236594085|FCFS_LOAD_BALANCED|False|reviewed project-machine compatibility without preparation|-14.49463763405915|
|C5_item_preparation|60368|70771|0.8530047618374758|FCFS_LOAD_BALANCED|False|item-level fasting, bladder readiness and bedside semantics|-0.2048861821932757|
|C6_joint_background|45861|70771|0.6480196690734905|FCFS_LOAD_BALANCED|False|outpatient/physical-exam epsilon target alpha=0.45|-20.498509276398526|
|C7_formal_heuristic|45861|70771|0.6480196690734905|FCFS_LOAD_BALANCED|False|solution-method record only; no additional feasible-set constraint beyond C6|0.0|

C0使用真实报告提交时刻；C1-C7使用排程中最后任务结束作为报告完成代理。两者不能直接作因果比较，分层结果用于定位模型下降来自哪一类约束。