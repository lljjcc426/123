# 历史现实校准报告

历史报告完成率与标准化排程率口径不同。下表在同一留出期事件定义上逐层加入题给时长、标准班次、医生并发、设备能力、准备条件和背景负荷。

|scenario|completed|total|rate|added_constraint|change_from_previous_pp|
|---|---|---|---|---|---|
|C0_historical_report|59266|70864|0.836334386994807|observed order-to-report result|nan|
|C1_duration_only|70771|70771|1.0|problem upper durations only|16.3665613005193|
|C2_standard_hours|70771|70771|1.0|8-12 and 13-17 work blocks; all rooms interchangeable; 22-doctor cap|0.0|
|C3_doctor_capacity|70771|70771|1.0|training-derived weekday-slot doctor capacity|0.0|
|C4_project_capability|60526|70771|0.855237314719306|reviewed project-machine compatibility without preparation|-14.476268528069403|
|C5_item_preparation|60359|70771|0.8528775911037006|item-level fasting, bladder readiness and bedside semantics|-0.23597236156053247|
|C6_joint_background|42730|70771|0.6037783838012746|outpatient/physical-exam epsilon target alpha=0.3|-24.909920730242607|
|C7_formal_heuristic|42730|70771|0.6037783838012746|selected deterministic large-scale construction policy|0.0|

C0使用真实报告提交时刻；C1-C7使用排程中最后任务结束作为报告完成代理。两者不能直接作因果比较，分层结果用于定位模型下降来自哪一类约束。