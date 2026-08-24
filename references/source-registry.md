# 正式来源登记表

> 核验日期：2026-08-23。官方文件按发布机构页面和原始附件核验；论文按 DOI、出版社页面或 PubMed/PMC 核验题名、作者、期刊、年份与摘要级方法。仅正文实际使用的来源进入最终参考文献。

| ID | 完整来源 | 核验入口 | 本题用途 | 边界 |
|---|---|---|---|---|
| S01 | 国家卫生健康委员会办公厅. 国家卫生健康委办公厅关于印发超声诊断等5个专业医疗质量控制指标（2022年版）的通知: 国卫办医函〔2022〕161号[EB/OL]. 2022-05-27. | [通知](https://www.nhc.gov.cn/yzygj/c100068/202205/164e6556f6d34c33a3344fec9a2c5074.shtml)；[附件1](https://www.nhc.gov.cn/yzygj/c100068/202205/164e6556f6d34c33a3344fec9a2c5074/files/1733999799946_77274.pdf) | 48小时完成率定义、申请单分母、及时性含义 | 本题无申请单ID，需报告代理口径 |
| S02 | American College of Radiology, Society for Pediatric Radiology, Society of Radiologists in Ultrasound. ACR-SPR-SRU Practice Parameter for the Performance and Interpretation of Diagnostic Ultrasound Examinations[R]. 2023. | [ACR](https://gravitas.acr.org/PPTS/GetDocumentView?docId=24) | 人员、设备、记录与质控应分层约束 | 不是中国强制标准，不提供本院参数 |
| S03 | GUPTA D, DENTON B. Appointment scheduling in health care: challenges and opportunities[J]. IIE Transactions, 2008, 40(9): 800-819. | [DOI](https://doi.org/10.1080/07408170802165880) | 预约环境、变异与实时调整框架 | 通用综述，不能直接给本题解 |
| S04 | AHMADI-JAVID A, JALALI Z, KLASSEN K J. Outpatient appointment systems in healthcare: a review of optimization studies[J]. European Journal of Operational Research, 2017, 258(1): 3-34. | [DOI](https://doi.org/10.1016/j.ejor.2016.06.064) | 优化模型分类与方法选择 | 主要覆盖门诊单次预约 |
| S05 | MARYNISSEN J, DEMEULEMEESTER E. Literature review on multi-appointment scheduling problems in hospitals[J]. European Journal of Operational Research, 2019, 272(2): 407-419. | [DOI](https://doi.org/10.1016/j.ejor.2018.03.001) | 将多项目患者建成组合预约 | 资源路径与本题不完全同构 |
| S06 | CHEN P S, CHEN G Y H, LIU L W, et al. Using simulation optimization to solve patient appointment scheduling and examination room assignment problems for patients undergoing ultrasound examination[J]. Healthcare, 2022, 10(1): 164. | [DOI](https://doi.org/10.3390/healthcare10010164) | 超声多房间预约与仿真检验 | 原案例房间较同质，参数不可迁移 |
| S07 | LAI C H, LU Y J, CHEN P S. Using data-driven techniques to predict outpatient ultrasound examination time for the multi-clinic outpatient appointment scheduling problem[J]. Communications in Statistics - Simulation and Computation, 2025, 54(9): 3358-3376. | [DOI](https://doi.org/10.1080/03610918.2024.2349168) | 检查类别时长估计与可解释基线 | 本题缺扫描起止时刻，只能估代理 |
| S08 | GREEN L V, SAVIN S, WANG B. Managing patient service in a diagnostic medical facility[J]. Operations Research, 2006, 54(1): 11-25. | [DOI](https://doi.org/10.1287/opre.1060.0242) | 事前容量和当日动态排序分层 | 聚合单资源模型，需扩展兼容矩阵 |
| S09 | PATRICK J, PUTERMAN M L. Improving resource utilization for diagnostic services through flexible inpatient scheduling[J]. Journal of the Operational Research Society, 2007, 58(2): 235-245. | [DOI](https://doi.org/10.1057/palgrave.jors.2602242) | 住院容量保护与空闲回填 | CT案例，不能照搬容量比例 |
| S10 | PATRICK J, PUTERMAN M L, QUEYRANNE M. Dynamic multipriority patient scheduling for a diagnostic resource[J]. Operations Research, 2008, 56(6): 1507-1525. | [DOI](https://doi.org/10.1287/opre.1080.0590) | 时限驱动的动态容量分配 | 数学内核为时段索引MILP，真实切片用SLACK-GUARD启发式，不照搬ADP |
| S11 | LIN C K Y. Dynamic appointment scheduling with forecasting and priority-specific access time service level standards[J]. Computers & Industrial Engineering, 2019, 135: 970-986. | [DOI](https://doi.org/10.1016/j.cie.2019.06.049) | 预测与优先级服务水平联动 | 服务终点需改为全部报告完成 |
| S12 | LUO L, LUO L, ZHANG X, et al. Hospital daily outpatient visits forecasting using a combinatorial model based on ARIMA and SES models[J]. BMC Health Services Research, 2017, 17: 469. | [DOI](https://doi.org/10.1186/s12913-017-2407-9) | 周内效应与滚动预测验证 | 单院门诊结果不可外推 |
| S13 | VAN DER AALST W M P, SCHONENBERG M H, SONG M. Time prediction based on process mining[J]. Information Systems, 2011, 36(2): 450-475. | [DOI](https://doi.org/10.1016/j.is.2010.09.001) | 区分病例、事件、资源和时间戳语义 | 两事件间隔不等于扫描时长 |
| S14 | SEXAUER R, BESTLER C. Time is money: considerations for measuring the radiological reading time[J]. Journal of Imaging, 2022, 8(8): 208. | [DOI](https://doi.org/10.3390/jimaging8080208) | 系统时间戳偏差与稳健估计 | 放射阅片场景，仅作方法警示 |
| S15 | APERGI L A, BARAS J S, GOLDEN B L, et al. An optimization model for multi-appointment scheduling in an outpatient cardiology setting[J]. Operations Research for Health Care, 2020, 26: 100267. | [DOI](https://doi.org/10.1016/j.orhc.2020.100267) | 多项目、期限、共享资源MILP骨架 | 确定性且非超声场景 |
| S16 | BAUERHENNE C, KOLISCH R, SCHULZ A S. Robust appointment scheduling with waiting time guarantees[J]. Manufacturing & Service Operations Management, 2026, 28(3): 995-1009. | [DOI](https://doi.org/10.1287/msom.2024.0852) | 先满足患者级时限，再优化次级成本 | 等待保证不等于本题开单至报告时限 |

## 核验状态说明

- `S01` 的官方附件明确给出“住院超声检查48小时内完成率（US-TL-01）”及计算公式；早期候选笔记中“未规定48小时”的判断已被本登记表纠正。
- `S03`--`S16` 均已核对 DOI 与出版元数据；方法用途主要在摘要级核验。除开放全文条目外，不声称全部受限全文已逐页阅读。
- 最终论文不采用任何外部医院的检查时长、容量比例、预约间隔或效果值作为本题参数。
