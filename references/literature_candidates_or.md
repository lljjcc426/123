# 超声预约与多资源调度英文文献候选及核验记录

> 阶段：外部资料与相关研究检索（仅 Phase 2）  
> 检索与核验日期：2026-08-23  
> 语言与文献类型：英文、同行评议期刊论文  
> 当前用途：为后续模型选择、方法论说明和参考文献定稿提供候选；本文件不是论文正文，也不代表所有条目最终都会进入正文。

## 1. 题目结构与检索边界

本题需要同时处理门诊、体检和住院患者，设备与医生两类资源，检查项目与设备能力匹配，项目时长和医生效率异质，空腹等时间窗，同一患者多项目尽量同室同段，以及急查等随机扰动。核心服务指标是住院患者从开单到全部报告完成不超过 48 小时。

据此，检索不局限于关键词“ultrasound”。高度特定的英文超声预约优化论文在本轮检索结果中较少，故纳入与其数学结构一致的 radiology、diagnostic facility、nuclear medicine 和 multi-appointment scheduling 研究。只有同时满足“方法结构可迁移”与“来源可核验”的条目才进入核心候选集。

## 2. 检索策略

### 2.1 数据库与核验入口

- Crossref Works API：核验 DOI、题名、作者顺序、期刊、年份、卷期和页码/文章号。
- DOI resolver 与出版社落地页：INFORMS、Elsevier/ScienceDirect、Springer Nature、Taylor & Francis 等，用于核对摘要和出版状态。
- PubMed：补充核验 Health Care Management Science 中的医疗预约论文及摘要。
- 出版社作者页、大学机构库和 IDEAS/RePEc：仅作摘要或元数据补充，不替代 DOI/Crossref 核验。

### 2.2 核心检索式

以下检索式按数据库语法作了必要调整，逻辑结构保持一致：

1. `"outpatient appointment scheduling" AND (healthcare OR hospital) AND (review OR optimization)`
2. `(diagnostic OR radiology OR imaging OR ultrasound) AND resource AND scheduling AND (inpatient OR outpatient OR emergency)`
3. `"multi-priority patient scheduling" AND (diagnostic OR imaging)`
4. `"rolling horizon" AND appointment AND scheduling AND healthcare`
5. `("multi-appointment" OR "multi-step") AND hospital AND (resource OR "integer programming")`
6. `(queueing OR stochastic OR robust) AND appointment scheduling AND healthcare`
7. `("service level" OR "wait-time target" OR "waiting time guarantee" OR deadline) AND appointment scheduling`
8. `"same day" AND multiple appointments AND hospital resources`

### 2.3 纳入与排除标准

纳入标准：

- 直接讨论医疗预约、诊断/影像资源调度、多优先级患者、多项目/多步骤预约、滚动时域或服务水平约束；
- 英文同行评议期刊论文；
- DOI 能由 Crossref 精确返回，且题名、作者、出版物和年份一致；
- 摘要至少能支持本文件所记录的方法描述；
- 经典论文不受年份限制，近年论文用于补足 robust/service-level 和 multi-resource 方法。

排除标准：

- 博客、自媒体、商业宣传页；
- 只有二手引文且无法核验原始出版信息；
- 仅讨论挂号系统界面、提醒短信或纯预测 no-show，而没有资源调度决策；
- 与本题结构弱相关的一般人员排班、手术室排班或生产排程；
- 已有正式期刊版本时，不使用预印本代替期刊版本。

### 2.4 筛选与核验说明

- 本轮属于目标式 evidence mapping，不声称是 PRISMA 系统综述。跨平台搜索结果动态排序且大量重复，接口未提供可稳定复核的统一总命中量，因此不填造一个“总检索数”。
- 对最终 12 篇核心候选逐篇进行了 Crossref 元数据精确匹配，并以 DOI/出版社页面核对摘要级方法。
- 12 个 DOI 均唯一，未发现题名与 DOI 错配。
- `VERIFIED` 仅表示书目信息和摘要级方法得到核验；受限全文未取得的条目不标记为“全文已读”。

## 3. 证据分级口径

本任务评价的是运筹优化方法，不是临床疗效。为避免把模拟/优化论文误当作临床高等级证据，采用两轴记录：

- 设计层级 V：对建模研究进行有明确检索或分类框架的结构化综述；
- 设计层级 VI：单个分析模型、仿真或真实科室案例研究；
- 设计层级 VII：同行评议的叙述性综述或方法路线图；
- 方法适配 A：可作为本题核心建模依据；B：可作为重要补充或基线；C：只能在明确局限下使用。

该分级不表示临床因果证据强度。所有核心候选均来自已建立的同行评议期刊和正规出版社，本轮未发现掠夺性期刊警报。可访问的摘要/落地页不足以完成逐篇完整 COI 审计，因此“未见商业冲突”不得写成“已证明无冲突”。

## 4. 核心候选总览（N = 12）

| 编号 | 主题 | 主要方法 | 对本题最直接的作用 | 设计层级 | 方法适配 |
|---|---|---|---|---|---|
| OR-01 | 医疗预约综述 | 决策与环境因素路线图 | 建立需求、容量、变异与实时调整的分析框架 | VII | B |
| OR-02 | 门诊预约优化综述 | 优化研究分类与比较 | 候选模型谱系与建模要素检查 | V | A |
| OR-03 | 多预约综述 | 多资源患者路径分类 | 同一患者多项目组合预约的概念框架 | V | A |
| OR-04 | 滚动时域 | 仿真、超载规则、延迟触发 | 高峰/平峰与滚动重排策略 | VI | B |
| OR-05 | 诊断资源三类患者 | 有限时域动态规划 | 门诊、住院、急诊的联合容量与实时优先级 | VI | A |
| OR-06 | 等候与容量 | 排队模型与仿真 | 需求-容量基线和服务延迟解释 | VI | B |
| OR-07 | 住院弹性预约 | 容量预留优化与仿真 | 48 小时窗内住院需求延期/容量预留思想 | VI | A |
| OR-08 | 多优先级服务目标 | MDP、近似动态规划、线性规划 | 把等待时限直接嵌入动态分配策略 | VI | A |
| OR-09 | 两资源混合患者 | 广义 Bailey-Welch 规则、邻域搜索 | 两诊室下门诊/住院/急诊日内排序基线 | VI | A |
| OR-10 | 多步骤在线预约 | 随机在线调度、真实科室计算实验 | 同一患者多项目、时间窗、资源组合 | VI | A |
| OR-11 | 多预约整数规划 | IP、有效不等式、共享资源 | 患者级项目绑定、时限和资源容量约束 | VI | A |
| OR-12 | 服务水平保证 | 鲁棒优化、MILP、影像科案例 | 将等待保证作为硬约束而非仅作加权目标 | VI | A |

## 5. 逐篇核验记录

### OR-01 Gupta & Denton (2008)

**核验书目信息**  
Gupta, D., & Denton, B. (2008). Appointment scheduling in health care: Challenges and opportunities. *IIE Transactions, 40*(9), 800-819. https://doi.org/10.1080/07408170802165880

- 官方落地页：[DOI / Taylor & Francis](https://doi.org/10.1080/07408170802165880)
- 核验结果：`VERIFIED`。Crossref 返回的题名、两位作者、期刊、2008 年、40(9)、800-819 与出版社页面一致。
- 摘要级关键方法：对医疗预约系统的环境因素和决策层次进行路线图式综述，重点包括到达/服务时间变异、患者与服务提供者偏好、信息技术以及从预约规则到实时扰动响应的决策。
- 与本题关联：适合支撑“预约不是单一静态排序”的问题界定；本题的项目时长、医生效率、患者类别和临时急查均属于该文强调的系统环境因素。
- 局限：为广义医疗预约综述，不专门讨论影像设备能力矩阵、医生-机器双资源或患者多项目同室约束；文献较早。
- 证据：设计层级 VII；方法适配 B。可作问题背景与方法分类依据，不宜单独决定本题模型。
- 期刊/COI 状态：正规同行评议期刊；可访问页面列出 NSF 资助与致谢，未见直接商业产品利益声明，未做全文级 COI 审计。

### OR-02 Ahmadi-Javid, Jalali, & Klassen (2017)

**核验书目信息**  
Ahmadi-Javid, A., Jalali, Z., & Klassen, K. J. (2017). Outpatient appointment systems in healthcare: A review of optimization studies. *European Journal of Operational Research, 258*(1), 3-34. https://doi.org/10.1016/j.ejor.2016.06.064

- 官方落地页：[DOI / Elsevier](https://doi.org/10.1016/j.ejor.2016.06.064)
- 核验结果：`VERIFIED`。Crossref 与 Elsevier 页面元数据一致。
- 摘要级关键方法：综合评述门诊预约系统中的解析与数值优化研究，围绕系统环境、决策变量、目标、约束和求解方法建立分类框架。
- 与本题关联：可用于系统比较确定性 IP/MILP、随机规划、动态规划、排队与仿真等候选路线，并检查是否遗漏患者行为、随机扰动和实时决策。
- 局限：综述主要覆盖 2016 年前研究；多数门诊预约模型以单次就诊或单主要资源为中心，不能直接解决本题多项目同室和 48 小时全部完成指标。
- 证据：设计层级 V；方法适配 A。是后续方法选择的核心综述来源。
- 期刊/COI 状态：Elsevier 旗下成熟 OR 期刊；摘要与元数据页未显示商业冲突，全文 COI 信息未逐项取得。

### OR-03 Marynissen & Demeulemeester (2019)

**核验书目信息**  
Marynissen, J., & Demeulemeester, E. (2019). Literature review on multi-appointment scheduling problems in hospitals. *European Journal of Operational Research, 272*(2), 407-419. https://doi.org/10.1016/j.ejor.2018.03.001

- 官方落地页：[DOI / Elsevier](https://doi.org/10.1016/j.ejor.2018.03.001)
- 核验结果：`VERIFIED`。Crossref 返回作者、卷期和页码与 Elsevier 页面一致。
- 摘要级关键方法：以 Web of Science/Scopus 检索为基础，分类讨论患者需依次访问多个资源类型的 multi-appointment scheduling；区分同日 combination appointments 与跨日 appointment series，并梳理范围、目标、约束、算法和验证方式。
- 与本题关联：本题“一张申请单包含多个部位，尽量同一时间段、同一检查室完成”可视为带设备能力兼容性的 combination appointment；该文提供患者路径与多资源集中协调的规范表述。
- 局限：综述覆盖到 2017 年底；许多纳入研究横跨多个科室，而本题多项目可能共享同一超声设备，资源拓扑不完全相同。
- 证据：设计层级 V；方法适配 A。是患者级项目捆绑约束的重要理论来源。
- 期刊/COI 状态：正规同行评议期刊；未在摘要级页面见商业利益冲突信息，未做全文级 COI 审计。

### OR-04 Rohleder & Klassen (2002)

**核验书目信息**  
Rohleder, T. R., & Klassen, K. J. (2002). Rolling horizon appointment scheduling: A simulation study. *Health Care Management Science, 5*(3), 201-209. https://doi.org/10.1023/A:1019748703353

- 官方落地页：[DOI / Springer](https://doi.org/10.1023/A:1019748703353)；[PubMed PMID 12363047](https://pubmed.ncbi.nlm.nih.gov/12363047/)
- 核验结果：`VERIFIED`。Crossref、PubMed 的作者、年份、卷期、页码和 DOI 一致。
- 摘要级关键方法：在需求负荷波动的 rolling-horizon 环境中，用仿真比较超载规则（如 overtime、double booking）及其延迟触发策略；在六类需求模式下同时评价患者端和服务端指标。
- 与本题关联：可支撑依据月份、星期和日内高峰滚动更新住院预约额度，而不是冻结整月静态表；也提示“何时触发超载措施”与“用哪种措施”应分开建模。
- 局限：是通用预约仿真，未建模检查项目-设备兼容性、医生轮转和患者多项目；double booking 不能在本题中未经数据依据直接采用。
- 证据：设计层级 VI；方法适配 B。适合滚动时域机制与仿真验证，不是完整主模型。
- 期刊/COI 状态：正规同行评议期刊并被 PubMed 收录；摘要页未提供完整 COI 声明。

### OR-05 Green, Savin, & Wang (2006)

**核验书目信息**  
Green, L. V., Savin, S., & Wang, B. (2006). Managing patient service in a diagnostic medical facility. *Operations Research, 54*(1), 11-25. https://doi.org/10.1287/opre.1060.0242

- 官方落地页：[DOI / INFORMS](https://doi.org/10.1287/opre.1060.0242)
- 核验结果：`VERIFIED`。Crossref 与 INFORMS 页面元数据、摘要一致。
- 摘要级关键方法：面向预约门诊、随机到达住院和需尽快服务的急诊三类患者，联合设计门诊预约表和实时服务优先级；建立有限时域动态规划，利用大型城市医院数据做数值与敏感性研究，并比较启发式规则。
- 与本题关联：患者类别与本题高度同构，可用于分离“事前容量/预约设计”和“当日动态排序”两层决策，并为特殊检查插入提供结构依据。
- 局限：以诊断设施的聚合容量为主，没有显式患者多项目、检查室能力集合和医生-机器双重匹配；目标为成本/运行表现而非 48 小时完成人数比例。
- 证据：设计层级 VI；方法适配 A。是诊断资源多类别动态调度的核心原始论文。
- 期刊/COI 状态：INFORMS 正规同行评议期刊；可访问页面未见商业利益冲突声明，未做全文级 COI 审计。

### OR-06 Green & Savin (2008)

**核验书目信息**  
Green, L. V., & Savin, S. (2008). Reducing delays for medical appointments: A queueing approach. *Operations Research, 56*(6), 1526-1538. https://doi.org/10.1287/opre.1080.0575

- 官方落地页：[DOI / INFORMS](https://doi.org/10.1287/opre.1080.0575)
- 核验结果：`VERIFIED`。Crossref 精确匹配题名、作者、卷期、页码和 DOI。
- 摘要级关键方法：把预约积压建模为单服务台排队系统，允许临近服务的患者以状态相关概率未被服务并重新入队；推导确定性与指数服务时间下的稳态队长分布，并用仿真比较排队指标。
- 与本题关联：可作为需求-有效容量关系、积压形成和等待服务水平的解析基线；有助于说明仅提高平均利用率可能放大延期风险。
- 局限：单服务台、稳态和 no-show 机制与本题多机器、多技能医生、时变高峰及多项目成组不同；不能直接输出检查室和时间排序。
- 证据：设计层级 VI；方法适配 B。适合基线与机制解释，不宜作为主排程模型。
- 期刊/COI 状态：INFORMS 正规同行评议期刊；摘要级页面未提供完整 COI 信息。

### OR-07 Patrick & Puterman (2007)

**核验书目信息**  
Patrick, J., & Puterman, M. L. (2007). Improving resource utilization for diagnostic services through flexible inpatient scheduling: A method for improving resource utilization. *Journal of the Operational Research Society, 58*(2), 235-245. https://doi.org/10.1057/palgrave.jors.2602242

- 官方落地页：[DOI / Journal of the Operational Research Society](https://doi.org/10.1057/palgrave.jors.2602242)
- 核验结果：`VERIFIED`。Crossref 与期刊落地页的作者、2007 年卷期和页码一致；网页的后期上线/迁移日期不作为论文出版年。
- 摘要级关键方法：针对容量不足、需求随机且有多优先级的 CT 服务，允许部分非急住院需求滚动到次日，并用可快速响应的门诊患者填补闲置；求解在 overtime 约束下最小化未利用容量的预留策略，再用仿真检验。
- 与本题关联：直接支持“为住院需求预留多少容量、剩余容量怎样由门诊/体检填充”的两阶段思路；48 小时指标可作为住院延后上限而非允许无界推迟。
- 局限：依赖可延期住院患者和 on-call outpatient pool 的业务假设；本题必须依据数据重新定义可延期类别，不能照搬比例或参数。
- 证据：设计层级 VI；方法适配 A。是住院弹性预约和容量预留的重要原始来源。
- 期刊/COI 状态：正规同行评议 OR 期刊；摘要级页面未见商业冲突说明，未做全文级 COI 审计。

### OR-08 Patrick, Puterman, & Queyranne (2008)

**核验书目信息**  
Patrick, J., Puterman, M. L., & Queyranne, M. (2008). Dynamic multipriority patient scheduling for a diagnostic resource. *Operations Research, 56*(6), 1507-1525. https://doi.org/10.1287/opre.1080.0590

- 官方落地页：[DOI / INFORMS](https://doi.org/10.1287/opre.1080.0590)
- 核验结果：`VERIFIED`。Crossref 与 INFORMS 页面元数据和摘要一致。
- 摘要级关键方法：将多优先级诊断患者的动态容量分配建成 MDP，以低成本达到各类 wait-time targets；因状态空间过大，利用等价线性规划和近似动态规划构造策略，并通过仿真评价。
- 与本题关联：与“住院患者 48 小时全部完成”最直接对应。可将距离 48 小时截止的剩余时间、患者优先级和可行检查室作为状态/紧迫度，并把超时作为硬约束或高罚损失。
- 局限：模型以聚合诊断容量为中心，摘要未显示患者多项目绑定、医生-设备技能和日内连续时间细节；近似策略需由本题数据单独验证。
- 证据：设计层级 VI；方法适配 A。是服务时限驱动动态调度的核心方法来源。
- 期刊/COI 状态：INFORMS 正规同行评议期刊；摘要级页面未见商业利益冲突声明。

### OR-09 Sickinger & Kolisch (2009)

**核验书目信息**  
Sickinger, S., & Kolisch, R. (2009). The performance of a generalized Bailey-Welch rule for outpatient appointment scheduling under inpatient and emergency demand. *Health Care Management Science, 12*(4), 408-419. https://doi.org/10.1007/s10729-009-9098-7

- 官方落地页：[DOI / Springer](https://doi.org/10.1007/s10729-009-9098-7)
- 核验结果：`VERIFIED`。Crossref、Springer/作者机构页元数据一致。
- 摘要级关键方法：研究两个资源共同服务门诊、住院和急诊三类患者的问题，提出广义 Bailey-Welch 预约规则与邻域搜索启发式，比较不同参数下的期望总收益和日内预约表结构。
- 与本题关联：提供一个计算简单、可解释的两诊室日内预约基线；可用于和后续 MILP/滚动优化结果比较，检验复杂算法是否真正带来增益。
- 局限：目标是收益、等待与拒绝服务成本的加权和，不是 48 小时完成率；没有同一患者多项目和医生轮转约束，服务时间建模也比本题简化。
- 证据：设计层级 VI；方法适配 A。适合作为多资源混合患者的强基线与启发式来源。
- 期刊/COI 状态：正规同行评议期刊；可访问摘要未提供完整 COI 声明。

### OR-10 Pérez et al. (2013)

**核验书目信息**  
Pérez, E., Ntaimo, L., Malavé, C. O., Bailey, C., & McCormack, P. (2013). Stochastic online appointment scheduling of multi-step sequential procedures in nuclear medicine. *Health Care Management Science, 16*(4), 281-299. https://doi.org/10.1007/s10729-013-9224-4

- 官方落地页：[DOI / Springer](https://doi.org/10.1007/s10729-013-9224-4)
- 核验结果：`VERIFIED`。Crossref、Springer/作者机构页的五位作者、卷期、页码和 DOI 一致。
- 摘要级关键方法：针对具有严格时间窗和随机性的多步骤核医学流程，构造患者与资源的随机在线调度算法，并在真实科室数据上以患者端和科室端指标评价；算法同时确定开始时间和所用资源。
- 摘要级结果：与实际策略相比，计算研究报告平均每年可多安排约 600 名患者，预约等待平均减少约 2 天。该数值仅是原研究场景结果，不可外推为本题效果。
- 与本题关联：为“同一患者多个检查项目作为一个组合任务”“在线到达后立即给出可行时间与资源”提供直接方法参照，也能容纳空腹等项目时间窗。
- 局限：核医学的步骤先后和放射性药物衰减约束具有场景特异性；超声多项目通常是设备兼容与连续占用问题，不能照搬其流程参数。
- 证据：设计层级 VI；方法适配 A。是随机、多步骤、多资源在线调度的核心相邻场景证据。
- 期刊/COI 状态：正规同行评议期刊；摘要提到真实诊所应用，未在可访问页面见商业产品利益声明，未做全文级 COI 审计。

### OR-11 Apergi, Baras, Golden, & Wood (2020)

**核验书目信息**  
Apergi, L. A., Baras, J. S., Golden, B. L., & Wood, K. E. (2020). An optimization model for multi-appointment scheduling in an outpatient cardiology setting. *Operations Research for Health Care, 26*, 100267. https://doi.org/10.1016/j.orhc.2020.100267

- 官方落地页：[DOI / Elsevier](https://doi.org/10.1016/j.orhc.2020.100267)
- 核验结果：`VERIFIED`。Crossref 与 Elsevier 页面返回四位作者、期刊、2020 年、卷 26 和文章号 100267。
- 摘要级关键方法：建立整数规划，使患者在规定期限内完成所需诊断/治疗步骤，同时满足准备/恢复时间、患者可用性和共享资源容量；目标减少到院次数和院内等待，并通过 formulation improvements 与 valid inequalities 加速求解。
- 与本题关联：可直接借鉴患者-项目-时段-检查室分配变量、全部项目完成时限、项目准备时间窗、资源容量和“减少往返/集中检查”目标，是本题确定性 MILP 骨架的高相关来源。
- 局限：采用确定性项目时长，主要研究心脏科跨资源流程；未处理本题医生效率随机性、急查插入和滚动重排，目标也不是最大化 48 小时完成率。
- 证据：设计层级 VI；方法适配 A。是多项目成组与整数规划约束设计的核心原始论文。
- 期刊/COI 状态：Elsevier 同行评议期刊；出版社页披露部分工作获 Lockheed Martin Chair funds 支持，这构成需透明记录的资助信息，但摘要未显示其与医疗排程结论存在直接商业利益关系。

### OR-12 Bauerhenne, Kolisch, & Schulz (2026)

**核验书目信息**  
Bauerhenne, C., Kolisch, R., & Schulz, A. S. (2026). Robust appointment scheduling with waiting time guarantees. *Manufacturing & Service Operations Management, 28*(3), 995-1009. https://doi.org/10.1287/msom.2024.0852

- 官方落地页：[DOI / INFORMS](https://doi.org/10.1287/msom.2024.0852)
- 核验结果：`VERIFIED`。INFORMS 显示 2026-01-05 online publication，卷期为 2026 年 28(3)，995-1009；Crossref 元数据一致。DOI 中的“2024”不是出版年份。
- 摘要级关键方法：在服务时间和 no-show 的 box uncertainty sets 下，最小化总成本并对每位患者提供等待时间保证；证明一般问题 NP-hard，给出 MILP，并证明若干特殊情形下 Smallest-Variance-First 与 Bailey-Welch 变体最优；以大学医院影像科数据做案例。
- 与本题关联：明确说明“限制每个患者等待时间”与“仅最小化平均等待”不同。对本题应优先把 48 小时完成设为患者级服务约束/违约变量，再在其后优化利用率、等待和加班，而不是只做加权平均。
- 局限：论文的 waiting-time guarantee 主要针对预约系统等待，不能未经定义就等同于本题从开单到全部报告的 48 小时；摘要未显示多项目绑定和医生-设备技能约束。Box uncertainty 也可能较保守，需要用本题历史分布校准。
- 证据：设计层级 VI；方法适配 A。是本轮最新且最直接的服务水平约束方法来源。
- 期刊/COI 状态：INFORMS 正规同行评议期刊；页面披露德国研究基金会资助，未见商业资助声明。

## 6. 来源质量矩阵

| 编号 | 元数据/DOI | 出版社与同行评议 | 方法透明度（摘要级） | 时效性 | COI 信息 | 总体建议 |
|---|---|---|---|---|---|---|
| OR-01 | 通过 | 通过 | 通过 | 经典但较早 | 有资助信息，完整 COI 未取得 | 支持性引用 |
| OR-02 | 通过 | 通过 | 通过 | 较早综述 | 完整 COI 未取得 | 核心综述 |
| OR-03 | 通过 | 通过 | 通过 | 中等 | 完整 COI 未取得 | 核心综述 |
| OR-04 | 通过 | 通过/PubMed | 通过 | 经典 | 完整 COI 未取得 | 滚动时域基线 |
| OR-05 | 通过 | 通过 | 通过 | 经典 | 完整 COI 未取得 | 核心方法 |
| OR-06 | 通过 | 通过 | 通过 | 经典 | 完整 COI 未取得 | 排队基线 |
| OR-07 | 通过 | 通过 | 通过 | 经典 | 完整 COI 未取得 | 核心方法 |
| OR-08 | 通过 | 通过 | 通过 | 经典 | 完整 COI 未取得 | 核心方法 |
| OR-09 | 通过 | 通过 | 通过 | 经典 | 完整 COI 未取得 | 启发式基线 |
| OR-10 | 通过 | 通过 | 通过 | 中等 | 完整 COI 未取得 | 核心相邻场景 |
| OR-11 | 通过 | 通过 | 通过 | 较新 | 已记录资助信息 | 核心 IP 来源 |
| OR-12 | 通过 | 通过 | 通过 | 最新 | 公共基金资助 | 核心服务水平来源 |

## 7. 近似但本轮未纳入核心 12 篇的文献

这些论文真实且相关，但因篇数上限、方法重叠或场景特异性未进入核心集，可在正文需要时替换：

1. Cayirli, T., & Veral, E. (2003). *Outpatient scheduling in health care: A review of literature*. DOI: [10.1111/j.1937-5956.2003.tb00218.x](https://doi.org/10.1111/j.1937-5956.2003.tb00218.x)。经典综述，但与 OR-01/OR-02 的方法背景重叠。
2. Kolisch, R., & Sickinger, S. (2008). *Providing radiology health care services to stochastic demand of different customer classes*. DOI: [10.1007/s00291-007-0116-1](https://doi.org/10.1007/s00291-007-0116-1)。两台 CT、三类患者、MDP，相关性高，但与 OR-05、OR-08、OR-09 重叠。
3. Pérez, E., Ntaimo, L., Wilhelm, W. E., Bailey, C., & McCormack, P. (2011). *Patient and resource scheduling of multi-step medical procedures in nuclear medicine*. DOI: [10.1080/19488300.2011.617718](https://doi.org/10.1080/19488300.2011.617718)。OR-10 是其更强调随机在线决策的后续研究。
4. Zhou, J., Li, J., Guo, H., & Lin, Y. (2017). *The booking problem of a diagnostic resource with multiple patient classes and emergency interruptions*. DOI: [10.1016/j.cie.2017.01.001](https://doi.org/10.1016/j.cie.2017.01.001)。中国大型医院 CT 案例，但其 emergency booking-limit MDP 与核心动态资源论文重叠。
5. Zattar da Silva, R. B., Fogliatto, F. S., Krindges, A., & Cecconello, M. S. (2021). *Dynamic capacity allocation in a radiology service considering different types of patients, individual no-show probabilities, and overbooking*. DOI: [10.1186/s12913-021-06918-y](https://doi.org/10.1186/s12913-021-06918-y)。多容量影像资源与真实数据很有价值，但本题当前未给出 no-show，故未优先纳入。
6. Namakshenas, M., Mahdavi Mazdeh, M., Braaksma, A., & Heydari, M. (2023). *Appointment scheduling for medical diagnostic centers considering time-sensitive pharmaceuticals: A dynamic robust optimization approach*. DOI: [10.1016/j.ejor.2022.06.037](https://doi.org/10.1016/j.ejor.2022.06.037)。动态鲁棒 MIP 很强，但放射性药物约束与超声场景差异较大。

## 8. 可供后续阶段使用的边界结论

以下仅是文献到建模变量/约束的映射，不是最终模型结论：

- 48 小时指标应优先表达为患者级“全部项目完成”服务约束或违约变量，而不应只最小化平均等待（OR-08、OR-12）。
- 同一患者多个项目需要作为组合预约或患者路径统一分配，不能把每条检查项目记录完全独立排序（OR-03、OR-10、OR-11）。
- 预约方案至少分为事前容量/模板配置与当日动态重排两层，并允许按滚动时域更新（OR-04、OR-05、OR-07）。
- 简单 Bailey-Welch/邻域规则和排队近似可作为基线，但不能代替设备能力、医生轮转和患者项目绑定约束（OR-06、OR-09）。
- 急查和特殊患者应通过容量预留、动态插入或场景扰动处理；文献中的 no-show、双重预约和收益参数不能在没有本题数据依据时照搬（OR-04、OR-05、OR-07、OR-12）。

## 9. 检索局限

- 本轮以英文同行评议论文为主，未覆盖中文数据库；后续若论文需要中国医院政策语境或超声行业流程，可另行检索中文来源与官方规范。
- 多数高质量方法论文研究 CT、MRI、核医学或跨科室诊断流程。它们支持数学结构，不等于超声业务参数证据。
- 若出版社只开放摘要，本文件只记录摘要可支持的内容；没有根据二手文章补写全文细节。
- 尚未把候选文献按正文首次引用顺序编号。最终编号必须等论文主方法和实际引用位置冻结后再生成。
