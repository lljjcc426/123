# P2/P3核心调度内核一致性审计

审计状态：**P2六策略全年结果、P3全年17点结果及两者明细均已在共享内核上重算；P2/P3独立验证、alpha=0逐行等价核验、P3八窗精确对照与真实峰值日修复路径审计均已完成。** 精确对照和修复审计分别只支持对应有限子问题的最优性结论与修复排程的可行性结论。

## 1. 共享调用链

| 核验维度 | P2 | P3 | 代码证据 |
|---|---|---|---|
| 输入事件、项目和能力 | `load_inputs`后只保留住院 | 同一`load_inputs`保留三类来源 | P2 `supporting_materials/code/run_pre_freeze_scenarios.py:74-83`；P3 `364-384` |
| 患者排序 | `run_group_with_policy` | 同一函数 | `supporting_materials/code/run_unified_scheduler.py:629-644` |
| 项目顺序候选 | `task_order_candidates` | 同一函数 | `supporting_materials/code/run_unified_scheduler.py:484-500` |
| 完整事件规划 | `plan_event` | 同一函数 | `supporting_materials/code/run_unified_scheduler.py:534-559` |
| 房间选择 | 策略的`room_mode` | 同一策略、同一`room_mode` | `supporting_materials/code/run_unified_scheduler.py:35-66`、`600-626` |
| 设备、医生、工作块 | `WorkCalendar` | 同一类 | `supporting_materials/code/run_unified_scheduler.py:145-379` |
| 患者互斥和转运 | 稀疏患者区间表 | 同一日历状态 | `supporting_materials/code/run_unified_scheduler.py:184-209`、`246-289` |
| 结果统计 | 共享schedule/outcomes/metrics | 同一组统计函数 | P3候选 `supporting_materials/code/run_pre_freeze_scenarios.py:271-293` |

P2六个分片只改变声明的患者排序与房间tie-break；最终选择不改变调度内核。分片与汇总入口见 `supporting_materials/code/run_pre_freeze_scenarios.py:74-168`。P3候选只组合共享入口，不复制患者、项目或房间规划器，见同文件 `217-303`。

## 2. P2固定策略空间和当前选择

候选空间固定为

\[
\{\mathrm{FCFS},\ \mathrm{arrival\text{-}window\ slack}\}
\times
\{\mathrm{lowest\ ID},\ \mathrm{current\ load},\ \mathrm{scarcity\ preserving}\},
\]

共6个策略，代码常量见 `supporting_materials/code/run_unified_scheduler.py:59-66`。词典序依次为：最大化住院48小时完整完成数，最小化P90、P50等待、多项目跨室率和排入分钟数，最后按稳定策略ID升序；声明及真实比较键见同文件 `70-77`、`647-656`。`finalize-p2`和最终审计均重新调用同一比较键，见 `supporting_materials/code/run_pre_freeze_scenarios.py:109-160`、`supporting_materials/code/finalize_model_audits.py:485-515`。

当前唯一选中策略为 `FCFS_LOAD_BALANCED`，房间规则为`current_load`。评价期70,771个住院事件中，60,368个在48小时内完整完成，完成率85.3005%；P50/P90/P95等待为3.58/22.08/23.67小时，多项目跨室率58.1649%。

住院slack的代码定义仍是静态“到院窗口余量”

\[
S_i=(d_i-p_i)-5\sum_{j\in J_i}q_{ij},
\]

而不是从当前排程时刻计算的动态余量。常量及排序实现见 `supporting_materials/code/run_unified_scheduler.py:78-80`、`562-597`。

## 3. 跨event患者现实约束

同一`patient_id`可能因不同开单时刻形成多个event，因此仅检查event内部项目顺序不够。当前共享内核执行以下约束：

- `Task`显式携带`patient_id`，见 `supporting_materials/code/run_unified_scheduler.py:121-132`；
- `WorkCalendar`以稀疏`patient_intervals`维护患者占用，克隆时深拷贝，见 `184-209`；
- `reserve`/`release`同步提交和回滚患者区间，见 `246-269`；
- `patient_available`对既有任务前、后两个方向检查不重叠，异室时额外保留转运时间，见 `271-289`；
- `find_task`把患者可用性与房间、医生容量和工作块共同纳入候选，见 `311-379`。

独立验证器按导出任务的真实`patient_id`重建时间线；实现见 `supporting_materials/code/verify_unified_schedule.py:51-75`，正式检查键见 `324-332`。

## 4. P2/P3最终任务表独立验证

| 核验范围 | P2 | P3推荐点 |
|---|---:|---:|
| 状态事件 | 71,029 | 167,361 |
| 评价事件 | 70,771 | 166,817 |
| 预热状态事件 | 258 | 544 |
| 已排任务行 | 117,843 | 159,580 |
| 已排完整事件 | 60,592 | 100,296 |
| 跨event患者重叠违规 | 0 | 0 |
| 相邻异室转运不足 | 0 | 0 |
| 房间重叠违规 | 0 | 0 |
| 最大医生并发/容量 | 20/20 | 20/20 |

两份`independent_verification.json`均为`passed=true`。预热事件只用于日历状态初始化，`warmup_in_statistics=false`；P2评价背景数为0，P3评价住院/背景事件分别为70,771/96,046。项目存在性、5%时长、设备兼容、床旁7号机、释放与截止、准备条件、5分钟网格、工作块、空腹、医生容量和结果标记等检查也全部为0违规。

## 5. alpha=0等价边界的实际结果

P3在 $\alpha=0$ 时先运行`inpatient_first`；由于 $K_B(0)=0$，不会触发`global_deficit_repair`。代码见 `supporting_materials/code/run_pre_freeze_scenarios.py:306-360`。alpha=0分片已保存明细，并使用与P2相同的 `FCFS_LOAD_BALANCED`、`current_load`房间规则和10分钟跨室转运。

逐行比较字段包括任务的event、patient、项目序号、顺序、起止时刻、房间、时长和转运，以及事件的完成标记、截止标记、首项开始、末项结束和失败原因。比较器实现见 `supporting_materials/code/verify_p2_p3_kernel_equivalence.py:22-58`、`61-148`。

| 等价项 | P2 | P3 alpha=0住院子集 | 结果 |
|---|---:|---:|---|
| 48小时完整完成 | 60,368 | 60,368 | 一致 |
| 任务行 | 117,843 | 117,843 | 0行不一致 |
| 事件结果行 | 71,029 | 71,029 | 0行不一致 |
| 患者重叠违规 | 0 | 0 | 一致 |
| 异室转运不足 | 0 | 0 | 一致 |
| 转运参数 | 10 min | 10 min | 一致 |

比较报告同时确认策略、患者约束声明、转运设置和完成数一致，最终`passed=true`。冻结程序不只读取总布尔值，而是逐项要求上述匹配与四类患者违规均为0，见 `supporting_materials/code/finalize_model_audits.py:785-808`。

## 6. P3推荐点仍调用同一内核

当前P3在17点扫描中选中 $\alpha=0.45$，策略仍为 `FCFS_LOAD_BALANCED`，房间模式仍为`current_load`。该点采用`global_deficit_repair`加FCFS背景顺序，完成45,861个住院事件和54,137个背景事件；全年背景整数下限为43,221，因此约束满足。P3只改变背景服务下限和两类事件进入共享内核的构造次序，没有改变患者、项目、房间、医生容量或转运可行域。候选构造与选择见 `supporting_materials/code/run_pre_freeze_scenarios.py:217-360`。

## 7. 代表窗口精确对照与P3修复路径边界

P2精确基准的启发式侧直接调用生产`run_group_with_policy`，见 `supporting_materials/code/benchmark_exact_scheduler.py:655-689`；六类窗口规模为20/100/40/40/20/40，均使用当前选中策略，求解状态均为`OPTIMAL`，精确排程违规数均为0。

P3精确基准的启发式侧直接调用生产`solve_p3_epsilon`，精确侧随后求解同一子集；调用与正式背景整数下限一致性检查见 `supporting_materials/code/benchmark_exact_p3_scheduler.py:267-327`。八类三来源窗口规模为20/40/60/40/20/40/60/100，均使用 $\alpha=0.45$ 和当前P2策略。8个窗口的 `repair_triggered` 均为false，即生产侧全部采用住院优先基线；8例均为`OPTIMAL`，求解器gap、启发式至精确最优值的gap均为0，精确与启发式排程违规数均为0。精确模型的患者成对转运约束见 `supporting_materials/code/benchmark_exact_scheduler.py:244-260`、`492-495`。因此，这组`OPTIMAL`和gap 0证据只说明共享内核的基线分支在8个有限子问题上达到已证最优值，不覆盖repair分支，也不外推为全年全局最优。

repair分支另由真实峰值日审计覆盖。固定规则选中2025-02-17，共805个事件、500个背景事件，$\alpha=0.45$对应背景下限225。基线背景完成213、住院完成259，因 $213<225$ 自然触发repair；scarcity修复完成背景258、住院259，FCFS修复完成背景260、住院259，生产词典序最终选择scarcity。所选排程的事件完整性、资源能力、时间窗、患者互斥/转运、医生容量、身份与时长等14项独立检查均为0违规。审计构造与检查见 `supporting_materials/code/benchmark_exact_p3_scheduler.py:383-498`，结果写出见同文件 `647-661`，冻结复核见 `supporting_materials/code/finalize_model_audits.py:820-960`。这项结果只证明共享生产内核中的repair分支可被真实数据自然触发并产生正式约束可行排程；没有对该805事件修复问题做精确求解，不能据此声称repair分支最优。

## 8. 专项审计结论

共享调用链、P2固定词典序、slack口径、跨event患者互斥、双向异室转运、alpha=0逐行结果、P2/P3独立验证、八个基线窗口精确对照及真实峰值日repair路径均已用当前结果验收。P2与P3的差异来自问题三的全年背景服务下限及构造次序，不来自两套不一致的患者调度内核。结论范围严格限定为：alpha=0证明两者住院调度逐行等价；8窗精确结果证明对应基线子问题最优；峰值日审计证明repair触发与排程可行；以上均不证明全年P3或repair分支达到全局最优。
