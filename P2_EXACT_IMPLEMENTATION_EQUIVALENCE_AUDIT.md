# P2 精确基准与生产启发式实现等价性审计

P2_EXACT_IMPLEMENTATION_EQUIVALENCE = TRUE

## 实现调用链

- P2生产策略解析：`supporting_materials/code/run_unified_scheduler.py:93`。
- 项目展开、能力、床旁与项目级准备：`supporting_materials/code/run_unified_scheduler.py:382`，基准直接复用其 `Task` 对象。
- 患者优先级：`supporting_materials/code/run_unified_scheduler.py:562`。
- 共享调度入口：`supporting_materials/code/run_unified_scheduler.py:629`。
- 完整事件构造：`supporting_materials/code/run_unified_scheduler.py:659` 调用 `supporting_materials/code/run_unified_scheduler.py:534`。
- 项目排列候选：`supporting_materials/code/run_unified_scheduler.py:484`。
- 日历创建：`supporting_materials/code/run_unified_scheduler.py:600`；房间选择、医生容量与工作块：`supporting_materials/code/run_unified_scheduler.py:145`。
- 基准启发式入口：`supporting_materials/code/benchmark_exact_scheduler.py:655`，直接调用上述生产函数。

## 逐项等价关系

|项目|实现关系|运行期证据列|
|---|---|---|
|patient/event|基准不重建事件，直接使用 `events.event_id` 及原 `patient_id`|`equiv_patient_event_identity`|
|task|启发式计划中的 `PlanStep.task` 必须是生产 `tasks[event_id]` 中同一对象|`equiv_task_object_identity`|
|patient key|`Task.patient_id` 与事件 `patient_id` 一致，生产与精确模型均按该全局键互斥|`equiv_task_patient_identity`, `equiv_patient_nonoverlap`|
|complete event|每个排入事件的项目索引集合与生产 `tasks[event_id]` 完全一致|`equiv_complete_event_task_expansion`|
|room|直接使用完整生产房间集、兼容集合与 `WorkCalendar.room_choice`|`equiv_room_compatibility_and_choice`|
|preparation|直接使用项目级 release、空腹和憋尿准备语义|`equiv_preparation_release`|
|release/deadline|逐项目复核释放时刻及事件截止时刻|`equiv_preparation_release`, `equiv_event_deadline`|
|transfer|生产 `patient_available` 与精确成对约束均在既有任务前、后双向检查；同室为0、跨室为10分钟|`equiv_transfer`, `equiv_patient_nonoverlap`|
|doctor|直接使用 `capacity_main` 的星期×5分钟容量与生产占用数组|`equiv_doctor_capacity`|
|workblock|直接使用 `WorkCalendar.fits_block` 的上午/下午块|`equiv_workblock`|
|tie-break|同一空日历重复执行，比较事件顺序及完整计划签名|`equiv_deterministic_tie_break`|
|patient non-overlap|按真实 `patient_id` 复核跨事件不重叠及跨室转运|`equiv_patient_nonoverlap`|

## 运行期结果

|case|event_count|equiv_patient_event_identity|equiv_task_object_identity|equiv_task_patient_identity|equiv_complete_event_task_expansion|equiv_room_compatibility_and_choice|equiv_preparation_release|equiv_event_deadline|equiv_transfer|equiv_doctor_capacity|equiv_workblock|equiv_patient_nonoverlap|equiv_deterministic_tie_break|
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
|normal_weekday|20|True|True|True|True|True|True|True|True|True|True|True|True|
|peak_weekday|100|True|True|True|True|True|True|True|True|True|True|True|True|
|weekend|40|True|True|True|True|True|True|True|True|True|True|True|True|
|multi_project_peak|40|True|True|True|True|True|True|True|True|True|True|True|True|
|bedside_peak|20|True|True|True|True|True|True|True|True|True|True|True|True|
|obstetric_peak|40|True|True|True|True|True|True|True|True|True|True|True|True|

该审计只证明基准启发式与当前生产实现共享同一语义和调用链；求解质量由各场景的 `solver_status`、incumbent、best bound 和 gap 单独说明。