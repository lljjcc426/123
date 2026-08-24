# 复现环境

## 已使用环境

- 操作系统：Windows，PowerShell。
- Python：3.11.5。
- 数据处理：pandas 2.3.3、NumPy 2.4.6、PyArrow 25.0.0。
- Excel 读取：openpyxl 3.0.10、xlrd 2.0.2。
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
6. `run_pre_freeze_scenarios.py`：运行 P2、P3 Pareto 网格、准备粒度和多随机种子情景；独立场景可并行。
7. `benchmark_exact_scheduler.py`、`run_calibration_scenarios.py`：精确小窗口对照与现实校准。
8. `verify_model_semantics.py`、`verify_unified_schedule.py`：检查输入语义并独立重构全部排程约束。
9. `finalize_model_audits.py`：生成唯一冻结清单。
10. `build_unified_paper_tables.py`、`make_unified_figures.py`、`paper/build_latex.py`：生成论文图表和 PDF。

所有命令均从工作区根目录运行。原始 DOCX/XLS/XLSX 不写回。
