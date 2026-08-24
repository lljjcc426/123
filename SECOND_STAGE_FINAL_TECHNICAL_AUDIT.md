# 第二阶段最终技术审计报告

## 1. 冻结结论

`MODEL_AND_RESULTS_FROZEN = TRUE`。

本结论由当前代码和当前结果逐项重算，不沿用旧 QA 报告中的 PASS。未通过项：无。

## 2. 当前权威方案

- P2 候选策略数：6；固定词典序选中：`FCFS_LOAD_BALANCED`。
- P2 住院 48 小时完整完成：60368/70771。
- P3 扫描点数：17；选中 alpha：0.45。
- P3 住院 48 小时完整完成：45861/70771。
- P3 全年背景 ε 目标/完成：43221/54137。

## 3. 模型与算法核验边界

P2 策略选择按代码中的固定词典序重算；slack 仅指“到院窗口余量”，不是动态排程时刻剩余量。P2 与 P3 共用患者、项目、房间、医生容量和跨室转运内核。P3 正式约束只使用全年整数下限 `background_completed >= ceil(alpha * total_background)`，逐日 quota 不进入约束。启发式 Pareto 前沿仅称为“已达到的非支配解集”，不宣称全年全局最优。

## 4. 冻结检查

| 检查 | 结果 | 当前证据 |
|---|---|---|
| `train_holdout_no_leakage` | PASS | P1 thresholds, forecast split, project catalog and duration/doctor estimates must all respect 2024-03-31 |
| `all_50_fallback_reviewed` | PASS | legacy_review_rows=50; expected=50 |
| `no_blanket_category_fallback` | PASS | rooms must trace to A/B/C evidence; level D and family-wide fallback are excluded |
| `bedside_semantics_passed` | PASS | machine 7 requires project capability intersect bedside-location capability |
| `input_semantics_passed` | PASS | input_semantic_verification.passed=True |
| `p2_pure_inpatient_scenario` | PASS | P2 must contain no background events; warm-up may seed state but not evaluation statistics |
| `p2_policy_selection_matches_code` | PASS | summary='FCFS_LOAD_BALANCED'; fixed-key result='FCFS_LOAD_BALANCED'; policies=['FCFS_LOAD_BALANCED', 'FCFS_SCARCITY_PRESERVING', 'FCFS_SHARED', 'SLACK_GUARD_SHARED', 'SLACK_LOAD_BALANCED', 'SLACK_SCARCITY_PRESERVING'] |
| `p2_slack_definition_matches_code` | PASS | summary='arrival_window_slack_minutes=(deadline_dt-order_dt)-work_slots*5'; code='arrival_window_slack_minutes=(deadline_dt-order_dt)-work_slots*5' |
| `p2_exact_implementation_equivalent` | PASS | cases=['bedside_peak', 'multi_project_peak', 'normal_weekday', 'obstetric_peak', 'peak_weekday', 'weekend']; equivalence_columns={'equiv_event_deadline', 'equiv_workblock', 'equiv_room_compatibility_and_choice', 'equiv_task_object_identity', 'equiv_patient_event_identity', 'equiv_complete_event_task_expansion', 'equiv_preparation_release', 'equiv_transfer', 'equiv_patient_nonoverlap', 'equiv_doctor_capacity', 'equiv_deterministic_tie_break', 'equiv_task_patient_identity'} |
| `p2_exact_status_metadata_valid` | PASS | status/bound/gap/time semantics valid |
| `p2_high_load_benchmark_passed` | PASS | six fixed windows need incumbents; peak_weekday must contain at least 100 events |
| `p2_capability_failure_decomposed` | PASS | categories=['A', 'B', 'C', 'D', 'E', 'F']; decomposition=10258; P2 failures=10258 |
| `p2_schedule_verification_passed` | PASS | missing=[]; failed=[] |
| `p3_global_epsilon_semantics_passed` | PASS | required=ceil(alpha*total), feasibility and selected counts are recomputed |
| `p3_no_daily_quota` | PASS | selection, scan and every candidate must use daily_quota_used=false; deprecated_columns=[]; deprecated_keys=[] |
| `p3_alpha_grid_dense` | PASS | required=[0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]; actual=[0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.525, 0.55, 0.575, 0.6, 0.65, 0.7] |
| `p3_local_refinement_completed` | PASS | noncoarse_point=True; completed=True |
| `p3_exact_benchmark_exists` | PASS | cases=['background_peak_n40', 'bedside_pressure_n20', 'equipment_competition_n60', 'inpatient_peak_n60', 'multi_project_peak_n40', 'obstetric_pressure_n40', 'ordinary_joint_n20', 'recommended_alpha_typical_n100']; alpha=0.45; deprecated_quota_columns=[]; source must be selection.json |
| `p3_exact_status_metadata_valid` | PASS | status/bound/gap/time semantics valid |
| `p3_repair_path_audit_passed` | PASS | input_recomputed=True; date=2025-02-17; baseline=[{'construction_method': 'inpatient_first', 'background_order_strategy': 'scarcity', 'background_completed_events': 213, 'background_deficit_events': 12, 'inpatient_completed_events': 259, 'epsilon_constraint_satisfied': False}]; selected=global_deficit_repair/scarcity; validation_keys=['background_minimum', 'deadline', 'doctor_capacity', 'duration', 'event_completeness', 'fasting_window', 'patient_identity', 'patient_overlap_or_transfer', 'release_or_preparation', 'room_compatibility', 'room_overlap', 'task_identity', 'task_key_unique', 'workblock']; violations=0 |
| `p2_p3_kernel_equivalent` | PASS | P3 alpha=0 inpatient tasks and outcomes must match selected P2 row for row |
| `p3_schedule_verification_passed` | PASS | missing=[]; failed=[] |
| `historical_calibration_exists` | PASS | scenarios=['C0_historical_report', 'C1_duration_only', 'C2_standard_hours', 'C3_doctor_capacity', 'C4_project_capability', 'C5_item_preparation', 'C6_joint_background', 'C7_formal_heuristic']; all rates exclude warm-up; C5=P2 and C6/C7=selected P3 |
| `preparation_sensitivity_exists` | PASS | preparation_scenarios=['preparation_event', 'preparation_item']; issues=[] |
| `sensitivity_scenarios_complete` | PASS | required=['bladder45', 'bladder90', 'capability_AB', 'doctor_low', 'preparation_event', 'preparation_item', 'seed_11', 'seed_131', 'seed_29', 'seed_47', 'seed_83', 'transfer15', 'transfer5']; actual=['bladder45', 'bladder90', 'capability_AB', 'doctor_low', 'preparation_event', 'preparation_item', 'seed_11', 'seed_131', 'seed_29', 'seed_47', 'seed_83', 'transfer15', 'transfer5']; issues=[] |
| `multi_seed_exists` | PASS | required=['seed_11', 'seed_131', 'seed_29', 'seed_47', 'seed_83']; count=5; issues=[] |
| `paper_numbers_match_final_results` | PASS | consistency passed=True |
| `authoritative_result_unique` | PASS | legacy supporting_materials/results/unified_schedule must be absent |
| `all_authoritative_files_present` | PASS | all manifest inputs must exist and be non-empty |

## 5. 产物读取异常

无。

## 6. 结论

只有全部检查为 PASS，且论文—结果一致性审计重新读取最终结果后也通过，manifest 才会写入 `MODEL_AND_RESULTS_FROZEN = true`。代表窗口的精确求解只验证相应子问题；全年 P2/P3 仍按确定性启发式可行解表述。
