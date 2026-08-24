# 支撑材料与复现说明

本目录只保留最终论文的权威数据链。根目录题面 DOCX、压缩包和 `C题数据/` 下 7 份原始工作簿均保持原样；正式成品只有 LaTeX 源与 PDF，不生成 Word。

## 权威目录

- `processed_data/raw_parquet/`：原始工作簿的字段保真转存。
- `processed_data/unified_holdout/`：三类患者统一事件、项目、训练期医生容量、项目能力证据及训练期设备稀缺权重。
- `results/p1/`：问题一需求、峰平、项目时长和医生相对吞吐分析。
- `results/capability/`：22 台设备的项目能力证据审计。
- `results/doctor_project_time/`：训练期医生--项目时长代理；不作为主排程绝对时长。
- `results/unified_schedule/`：三策略、七项补充敏感性、权威患者级排程和独立核验；联合稀缺度作为帕累托备选，不替代住院主 KPI 的策略选择。
- `figures/paper_final/`：论文使用的 9 幅矢量 PDF 图。
- `tables/audit/`：原始字段、日汇总和申请事件键审计结果。

## 从原始数据复现

以下命令均从工作区根目录运行：

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
python supporting_materials/code/run_unified_scheduler.py
python supporting_materials/code/verify_unified_schedule.py
python supporting_materials/code/build_unified_paper_tables.py
python supporting_materials/code/make_unified_figures.py
python paper/build_latex.py
```

正式患者级结果是 `results/unified_schedule/final_patient_task_schedule.csv`；住院推荐表是 `inpatient_recommended_schedule.csv`；机器可读总表和独立核验分别为 `summary.json` 与 `independent_verification.json`。

七个敏感性情景彼此独立。需要利用多核电脑时，可先用 `--main-only` 冻结三种主策略，
再把 `--sensitivity-only --sensitivity-scenario <情景名>` 指向七个独立输出目录并行运行，
最后用 `merge_sensitivity_shards.py` 合并。默认无参数命令仍按单进程顺序复现，二者数值口径相同。

## 现实与证据边界

- 训练期固定为 2019-03-01 至 2024-03-31，留出期固定为 2024-04-01 至 2025-03-31；训练期稀缺权重和医生容量均不读取留出期项目构成或报告活动。
- `病人ID + 精确开单时间` 是申请事件代理，不是附件中的原始申请单 ID。
- 题给区间中点/上界是主排程时长；相邻报告间隔只作问题一相对证据，不能解释为实测扫查时长。
- 门诊/体检的报告日只构造回顾性计划日压力，不代表掌握历史预约时刻。
- 50 个没有项目级严格匹配的项目使用类别级能力回退并逐项留痕；严格证据敏感性禁用该回退。
- 医生容量是训练期活动区间重构出的总并发代理，不是未来实名班表或专项资质矩阵。
- 主情景的 60 分钟憋尿准备和 10 分钟跨室转运均不是附件事实，分别用 45/90 和 5/15 分钟检验边界；憋尿准备按“开单时刻+提前量”计算，计划日开班前已满足提前量的门诊/体检患者不被重复延迟。
- 最后一个排程任务结束只代理报告提交，因此 48 小时完成率是排程层估计，不是临床上线后的因果证明。

运行环境与依赖见 `ENVIRONMENT.md` 和 `requirements.txt`。只需复核受影响模块，不要求为形式反复运行无关的基础检查。
