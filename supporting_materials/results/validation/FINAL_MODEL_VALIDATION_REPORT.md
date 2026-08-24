# FINAL_MODEL_VALIDATION_REPORT

## 输入语义

`input_semantics_passed = True`。

## P2 排程可行性

`p2_schedule_verification_passed = True`。独立验证器必须包含按 `patient_id` 跨全部 event 的互斥检查和相邻异室转运检查；旧版仅 event 内检查的 JSON 不满足冻结条件。

## P3 排程可行性

`p3_schedule_verification_passed = True`。P3 还必须同时通过全年 ε 语义、无逐日 quota、精确小窗口和 alpha=0 内核等价检查。

## 最终状态

`MODEL_AND_RESULTS_FROZEN = TRUE`。未通过项：无。
