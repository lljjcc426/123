# 支撑材料与复现说明

原始题面和 `C题数据/` 中的工作簿保持不变。正式论文只维护 LaTeX 与 PDF，不生成 Word。

## 权威数据链

- `processed_data/raw_parquet/`：原始工作簿的字段保真转存。
- `processed_data/unified_holdout/`：统一患者事件、项目任务、训练期医生容量和项目—设备兼容输入。
- `results/p1/`：问题一的需求、预测、峰平、科室、项目时长和医生相对吞吐结果。
- `results/capability/`：项目—设备关系、旧版50个回退项目和床旁能力的逐项检查。
- `results/exact_benchmark/`：代表性小窗口 CP-SAT 与构造算法对照。
- `results/calibration/`：历史口径到标准化排程的 C0--C7 校准链。
- `results/final_frozen/`：唯一权威 P2、P3、敏感性结果及 `FINAL_RESULT_MANIFEST.json`。
- `figures/paper_final/`：正文使用的10幅矢量图。

冻结前旧目录 `results/unified_schedule/` 已删除，避免与 `results/final_frozen/` 形成两套冲突结果。

## 复现顺序

```powershell
python supporting_materials/code/inspect_inputs.py
python supporting_materials/code/extract_to_parquet.py
python supporting_materials/code/audit_data.py
python supporting_materials/code/bundle_sensitivity.py
python supporting_materials/code/analyze_p1.py
python supporting_materials/code/analyze_department_demand.py
python supporting_materials/code/audit_capability.py
python supporting_materials/code/estimate_doctor_project_times.py
python supporting_materials/code/build_unified_inputs.py
python supporting_materials/code/build_legacy_fallback_audit.py
python supporting_materials/code/run_pre_freeze_scenarios.py
python supporting_materials/code/benchmark_exact_scheduler.py
python supporting_materials/code/run_calibration_scenarios.py
python supporting_materials/code/verify_model_semantics.py
python supporting_materials/code/verify_unified_schedule.py
python supporting_materials/code/finalize_model_audits.py
python supporting_materials/code/build_unified_paper_tables.py
python supporting_materials/code/make_unified_figures.py
python paper/build_latex.py
```

P3 的不同 $\alpha$、敏感性和随机种子场景可写入独立分片目录并行运行，随后由场景脚本合并。全部命令从工作区根目录执行。

## 解释边界

- 训练期为 2019-03-01 至 2024-03-31，留出期为 2024-04-01 至 2025-03-31。
- 题给区间中点/上界是排程时长；相邻报告间隔只用于比较相对负荷。
- 门诊、体检报告日只构造回顾性计划日压力，不是真实预约日。
- 项目—设备集合只来自题面表1；无法确认的项目保留在完成率分母但不赋予设备。
- 医生容量是训练期星期—5分钟槽总并发代理，不是未来实名资质矩阵。
- 60分钟憋尿和10分钟转运为情景参数，均已做边界敏感性。
- 最后一个任务结束代理报告提交，48小时率是预约排程层估计。
