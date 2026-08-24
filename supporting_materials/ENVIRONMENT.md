# 复现环境

## 已使用环境

- 操作系统：Windows，PowerShell。
- Python：3.11.5。
- 数据处理：pandas 2.3.3、NumPy 2.4.6、PyArrow 25.0.0。
- Excel 读取：openpyxl 3.1.5、xlrd 2.0.2。
- 图表：Matplotlib 3.10.7。
- 精确子问题求解：OR-Tools 9.14.6206。
- LaTeX：MiKTeX 25.12、XeLaTeX 4.16。

全年患者级排程使用确定性连续日历构造算法；OR-Tools 只用于代表性小窗口的 CP-SAT 精确对照，不依赖商业求解器。论文只维护 LaTeX 与 PDF，不生成 Word。

## 运行顺序

1. `inspect_inputs.py`、`extract_to_parquet.py`：核对附件并转存原始字段。
2. `audit_data.py`、`bundle_sensitivity.py`：数据质量与申请事件键审计。
3. `analyze_p1.py`、`analyze_department_demand.py`：需求、预测、峰平、时长和科室分析。
4. `audit_capability.py`、`estimate_doctor_project_times.py`：设备能力与医生--项目相对时长分析。
5. `build_unified_inputs.py`、`build_legacy_fallback_audit.py`：形成统一输入并逐项处理旧类别回退项目。
6. `run_pre_freeze_scenarios.py --stage p2-point`：六策略用独立进程并行，`--stage finalize-p2` 按固定词典序选择并物化明细。
7. `run_pre_freeze_scenarios.py --stage p3-point`：0.00--0.70 粗网格、局部细化点、选中点明细、敏感性和多种子均按分片并行；`--stage finalize-p3` 合并 P3，`finalize_sensitivity_outputs.py` 在制表前合并敏感性与种子分片。
8. `benchmark_exact_scheduler.py`、`benchmark_exact_p3_scheduler.py`、`run_calibration_scenarios.py`：P2/P3 精确小窗口对照与现实校准。
9. `verify_model_semantics.py`、`verify_unified_schedule.py`、`verify_p2_p3_kernel_equivalence.py`：检查输入语义、完整排程约束和 alpha=0 内核等价性。
10. `build_unified_paper_tables.py`、`make_unified_figures.py`、`paper/build_latex.py`：从最终结果重建论文图表和 PDF。
11. `paper_hard_acceptance.py`、`finalize_model_audits.py`：先生成论文—结果一致性证据，再冻结 manifest，最后重新生成最终 QA。

所有命令均从工作区根目录运行。原始 DOCX/XLS/XLSX 不写回。
