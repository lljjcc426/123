# FINAL_MODEL_VALIDATION_REPORT

## Level 1 Raw-data semantic audit

原始时间范围、字段、事件键、重复记录和报告延迟由 `tables/audit/data_audit_metrics.json` 与 `bundle_key_sensitivity.json` 核查。

## Level 2 Model-input semantic audit

输入语义验证结果：通过。设备能力、50项复核、床旁交集、训练/留出边界、医生资质边界和报告代理见 `input_semantic_verification.json`。

## Level 3 Schedule feasibility audit

P2独立检查：通过；P3独立检查：通过。检查覆盖任务唯一性、时长、项目房间兼容、床旁、释放/截止、工作时段、空腹、憋尿准备、设备互斥、患者互斥、跨室转运、医生并发和结果聚合。

最终结论：三层均通过。
