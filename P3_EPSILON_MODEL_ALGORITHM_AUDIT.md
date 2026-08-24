# P3 ε约束模型与算法审计

审计状态：**全年17点扫描、局部细化、推荐点明细物化、alpha=0等价核验、P3独立排程验证、8个代表窗口精确对照和真实峰值日修复路径审计均已完成。** 当前权威推荐点为 $\alpha=0.45$。本文所称前沿是启发式实际达到的可行非支配解集，不宣称全年精确Pareto前沿；精确对照与修复路径审计的证据范围分别限定在对应子问题和修复排程可行性。

## 1. 正式模型口径

设评价期门诊、体检背景事件集合为 $I_B$，$N_B=|I_B|$；事件 $i$ 在计划日截止前完整完成时 $y_i=1$。正式全年服务下限为

\[
K_B(\alpha)=\left\lceil \alpha N_B\right\rceil,
\qquad
\sum_{i\in I_B}y_i\ge K_B(\alpha).
\]

生产入口只在评价期背景事件上计算 $N_B$，再执行 `ceil(alpha * total_background)`；代码见 `supporting_materials/code/run_pre_freeze_scenarios.py:306-322`。点结果写出总量、整数目标、实际完成数和可行标记，见同文件 `364-421`；合并阶段重新按整数完成数判断可行性并构造实际非支配集，见 `552-600`。最终审计还会独立重算每行目标、可行性、扫描网格和选中点一致性，见 `supporting_materials/code/finalize_model_audits.py:584-655`。

本次评价期背景总事件数为 $N_B=96\,046$。在推荐点 $\alpha=0.45$，整数下限为

\[
K_B(0.45)=\lceil0.45\times96\,046\rceil=43\,221.
\]

实际完整完成 $54\,137$ 个背景事件，完成率为 $56.3657\%$，满足全年整数下限，缺口为0。

## 2. 全年缺口修复与逐日quota边界

主算法不计算或执行逐日配额。全年预留函数只接收一个 `required_background` 整数并在达到该总数时停止，见 `supporting_materials/code/run_pre_freeze_scenarios.py:171-214`。`inpatient_first` 和 `global_deficit_repair` 均使用同一全年约束口径，见 `217-303`；基线、两类修复候选和可行候选选择见 `306-360`。点诊断与最终选择均显式记录 `daily_quota_used=False`，见 `397-455`、`628-666`；冻结检查同时拒绝旧quota字段，见 `supporting_materials/code/finalize_model_audits.py:657-687`。

推荐点的实际候选对照为：

| 候选 | 背景排序 | 背景完成 | 住院48小时完成 | P50/P90等待（h） | 是否满足ε | 是否选中 |
|---|---|---:|---:|---:|---|---|
| `inpatient_first` | scarcity | 38,872 | 60,368 | 3.58/22.08 | 否，缺4,349 | 否 |
| `global_deficit_repair` | scarcity | 56,155 | 45,819 | 7.00/29.50 | 是 | 否 |
| `global_deficit_repair` | FCFS | 54,137 | 45,861 | 3.92/21.83 | 是 | 是 |

基线不足时，两种修复日历相互独立并行构造；代码见 `supporting_materials/code/run_pre_freeze_scenarios.py:328-346`。在满足ε的候选中，FCFS修复按P2固定词典序保留了更多住院完成事件，因此成为推荐点的生产方案。逐日完成率只可作为描述性统计，不是数学约束。

## 3. 与P2共享现实调度内核

P3没有另写患者、项目、房间或医生调度器。候选通过 `create_calendar` 创建日历，并调用 `run_group_with_policy`/`schedule_group`，见 `supporting_materials/code/run_pre_freeze_scenarios.py:217-303`；共享入口位于 `supporting_materials/code/run_unified_scheduler.py:600-644`，完整事件规划位于同文件 `484-559`。

现实患者约束按真实 `patient_id` 跨全部event生效：`Task` 携带患者键，日历使用稀疏患者区间表，预留和回滚同步更新，候选同时检查全局不重叠及异室前后双向转运间隔；代码见 `supporting_materials/code/run_unified_scheduler.py:121-132`、`184-209`、`246-289`、`311-379`。

## 4. alpha=0边界已逐行验收

当 $\alpha=0$ 时，$K_B(0)=0$，`inpatient_first` 基线无需触发修复。当前alpha=0明细使用P2选中策略 `FCFS_LOAD_BALANCED`，住院48小时完成数为60,368，背景在住院排程后使用残余容量并完成38,872个事件；`detail_saved=True`、`repair_triggered=False`。

独立比较器不仅比较完成数，还逐行比较任务、时间、房间、转运和事件结果，并重新检查患者时间线；实现见 `supporting_materials/code/verify_p2_p3_kernel_equivalence.py:61-148`。当前结果为：

| 核验项 | P2 | P3 alpha=0住院子集 | 不一致/违规 |
|---|---:|---:|---:|
| 任务行 | 117,843 | 117,843 | 0 |
| 事件结果行 | 71,029 | 71,029 | 0 |
| 跨event患者重叠 | 0 | 0 | 0 |
| 相邻异室转运不足 | 0 | 0 | 0 |

策略、10分钟转运设置、患者约束声明和48小时完成数也全部一致，比较报告 `passed=true`。冻结程序对此执行独立门槛检查，见 `supporting_materials/code/finalize_model_audits.py:785-808`。

## 5. 17点扫描、局部细化与推荐点

默认粗网格为0.00至0.70、步长0.05，共15点；十进制网格构造见 `supporting_materials/code/run_pre_freeze_scenarios.py:22-51`。本次又完成两个局部点0.525和0.575，最终17点为：

`0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.525, 0.55, 0.575, 0.60, 0.65, 0.70`。

局部点建议和完成判定见 `supporting_materials/code/run_pre_freeze_scenarios.py:472-535`，合并、归一化理想点距离和明细物化见 `552-666`。当前 `local_refinement_completed=true`、`requires_new_point_runs_before_final_selection=false`。

其中0.00至0.65的16个点满足各自整数下限；0.70要求67,233个背景完成事件，当前启发式实际完成63,278个，未达到下限，故不进入已达到下限的可行前沿。该结果只能说明本次有限候选搜索未找到达标方案，不能据此判定原数学模型在 $\alpha=0.70$ 时不可行。当前已达到下限的非支配集含16个alpha值。按该经验前沿的归一化理想点距离最小规则，选中 $\alpha=0.45$，距离为0.811011。

推荐点主要结果如下：

| 指标 | 结果 |
|---|---:|
| 住院评价事件 | 70,771 |
| 住院48小时完整完成 | 45,861（64.8020%） |
| 背景评价事件 | 96,046 |
| 背景整数下限/实际完成 | 43,221/54,137 |
| 背景完成率 | 56.3657% |
| 住院P50/P90/P95等待 | 3.92/21.83/25.58 h |
| 多项目住院跨室率 | 30.6329% |
| 构造方法/背景排序 | `global_deficit_repair` / FCFS |

选中分片的六类明细已复制到 `p3_joint`，`detail_materialized=true`、`missing_detail_files=[]`、`selection_ready_for_freeze=true`；物化检查见 `supporting_materials/code/run_pre_freeze_scenarios.py:538-549`、`608-666`。

## 6. 独立验证、代表窗口精确对照与修复路径审计

P3独立验证重新读取导出任务表，而不复用调度器内部状态。当前验证覆盖167,361个状态事件、166,817个评价事件和159,580行已排任务；544个预热事件只进入状态、不进入评价统计。全部检查通过，尤其跨event患者重叠为0、相邻异室10分钟转运不足为0、房间重叠为0，观察到的医生最大并发20未超过容量20。患者时间线检查实现见 `supporting_materials/code/verify_unified_schedule.py:51-75`、`324-332`。

P3八类三来源代表窗口规模为20/40/60/40/20/40/60/100，均读取当前 $\alpha=0.45$ 和 `FCFS_LOAD_BALANCED`。生产侧直接调用全年同一 `solve_p3_epsilon`，精确侧求解同一事件子集，调用与下限一致性检查见 `supporting_materials/code/benchmark_exact_p3_scheduler.py:267-327`；incumbent、best bound、求解器gap、启发式至界gap及两侧违规数的写出见同文件 `328-370`。当前8例均未触发repair，均采用 `inpatient_first`；8例均为 `OPTIMAL`，求解器gap和启发式至已证最优值的gap均为0，精确排程与生产排程的独立违规数也均为0。该结论只证明这8个未触发repair的代表子问题中，生产基线分支达到对应子问题的已证最优值；它不证明修复分支最优，也不证明全年联合问题全局最优。精确对照的冻结核验见 `supporting_materials/code/finalize_model_audits.py:743-818`。

为覆盖repair分支，另按评价期 `case_date` 的项目时长上界总和最大、并列取最早日期的固定规则，选中真实峰值日2025-02-17。该日共有805个事件，其中住院305个、门诊407个、体检93个；背景事件共500个，在 $\alpha=0.45$ 下整数下限为225。住院优先基线只完成213个背景事件，低于下限12个，因而自然触发repair。两个重构候选及最终选择如下：

| 候选 | 背景排序 | 背景完成 | 住院完成 | 是否达到225个背景下限 | 是否选中 |
|---|---|---:|---:|---|---|
| `inpatient_first` | scarcity | 213 | 259 | 否 | 否 |
| `global_deficit_repair` | scarcity | 258 | 259 | 是 | 是 |
| `global_deficit_repair` | FCFS | 260 | 259 | 是 | 否 |

生产词典序最终选择scarcity修复候选，完成背景258个、住院259个。独立检查覆盖事件完整性、房间兼容、释放/准备、截止、空腹、工作块、房间互斥、患者互斥/转运、医生容量、背景下限、任务键唯一性、任务身份、患者身份和时长，共14项，违规数均为0。峰值日选取、生产repair调用、候选记录和14项检查见 `supporting_materials/code/benchmark_exact_p3_scheduler.py:383-498`，结果物化见同文件 `647-661`；冻结阶段重新核对峰值日输入、候选结构、下限、最终选择和14项零违规，见 `supporting_materials/code/finalize_model_audits.py:820-960`。该审计只证明修复分支在真实数据中会被自然触发，且所选排程满足正式约束；它没有建立对应修复子问题的精确模型，因而不构成修复分支最优性证据。

## 7. 专项审计结论

当前P3权威结果同时满足：全年整数ε语义正确、无逐日quota、15点粗网格完整、两个局部点完成、推荐点可行且非支配、明细已物化、alpha=0与P2逐行一致、最终任务表独立验证通过、八类基线代表窗口精确对照通过、真实峰值日repair自然触发且14项独立检查均为0违规。证据边界为：`OPTIMAL`和gap 0只适用于8个未触发repair的有限子问题；峰值日审计只证明repair触发与排程可行，不证明repair最优；全年方案仍按确定性启发式可行解表述，不声称全年全局最优。$\alpha=0.70$的未达标也仅是当前启发式搜索结果，不是数学不可行证明。
