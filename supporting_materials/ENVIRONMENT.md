# 复现环境

## 已使用环境

- 操作系统：Windows，PowerShell。
- Python：3.11.5。
- 数据处理：pandas 2.3.3、NumPy 2.4.6、PyArrow 25.0.0。
- Excel 读取：openpyxl 3.0.10、xlrd 2.0.2。
- 图表：Matplotlib 3.10.7。
- LaTeX：MiKTeX 25.12、XeLaTeX 4.16。

最终患者级排程使用确定性连续日历构造算法，不依赖商业求解器。论文只维护 LaTeX 与 PDF，不生成 Word。

## 运行顺序

1. `inspect_inputs.py`、`extract_to_parquet.py`：核对附件并转存原始字段。
2. `audit_data.py`、`bundle_sensitivity.py`：数据质量与申请事件键审计。
3. `analyze_p1.py`、`analyze_department_demand.py`：需求、预测、峰平、时长和科室分析。
4. `audit_capability.py`、`estimate_doctor_project_times.py`：设备能力证据与医生--项目相对时长证据。
5. `build_unified_inputs.py`：形成三类患者统一事件、项目、医生容量和训练期稀缺权重。
6. `run_unified_scheduler.py`：生成三策略、主方案和七项补充敏感性。
7. `verify_unified_schedule.py`：独立重构并检查全部硬约束。
8. `build_unified_paper_tables.py`、`make_unified_figures.py`、`paper/build_latex.py`：生成论文图表和 PDF。

所有命令均从工作区根目录运行。原始 DOCX/XLS/XLSX 不写回。
