# 正式来源登记表

> 核验日期：2026-08-24。中文来源由国家部门、政府门户或期刊官网核验；英文论文由 DOI、Crossref 和出版方元数据核验。仅保留正文实际使用的 17 条来源。

| Key | 完整来源 | 权威核验入口 | 本题用途 | 使用边界 |
|---|---|---|---|---|
| `gupta2008` | GUPTA D, DENTON B. Appointment scheduling in health care: Challenges and opportunities[J]. IIE Transactions, 2008, 40(9): 800-819. | [DOI](https://doi.org/10.1080/07408170802165880) | 医疗预约问题框架 | 通用综述，不给业务参数 |
| `ahmadi2017` | AHMADI-JAVID A, JALALI Z, KLASSEN K J. Outpatient appointment systems in healthcare: A review of optimization studies[J]. European Journal of Operational Research, 2017, 258(1): 3-34. | [DOI](https://doi.org/10.1016/j.ejor.2016.06.064) | 预约优化分类 | 主要覆盖门诊 |
| `nhc2020` | 国家卫生健康委员会办公厅. 关于进一步完善预约诊疗制度加强智慧医院建设的通知：国卫办医函〔2020〕405号[EB/OL]. 2020-05-21. | [国家卫健委](https://www.nhc.gov.cn/yzygj/c100068/202005/43b2d23ff48448ffae96700bc6eaccd7.shtml) | 分时段和集中预约政策背景 | 不照搬30分钟粒度 |
| `chenjuan2023` | 陈娟, 李志会, 赵浩, 等. 分时段分项目组多途径预约模式在妇幼专科医院超声检查中的应用[J]. 中国妇幼卫生杂志, 2023, 14(6): 77-80. | [期刊官网](https://yzws.cbpt.cnki.net/portal/journal/portal/client/paper/bdf8158ebaa8ce68bdc52ed3ece9a2ed), [DOI](https://doi.org/10.19757/j.cnki.issn1674-7763.2023.06.014) | 超声分时段、分项目组预约 | 单院效果不外推 |
| `marynissen2019` | MARYNISSEN J, DEMEULEMEESTER E. Literature review on multi-appointment scheduling problems in hospitals[J]. European Journal of Operational Research, 2019, 272(2): 407-419. | [DOI](https://doi.org/10.1016/j.ejor.2018.03.001) | 多项目组合预约 | 资源拓扑需重建 |
| `apergi2020` | APERGI L A, BARAS J S, GOLDEN B L, et al. An optimization model for multi-appointment scheduling in an outpatient cardiology setting[J]. Operations Research for Health Care, 2020, 26: 100267. | [DOI](https://doi.org/10.1016/j.orhc.2020.100267) | 患者级多步骤联合模型 | 非超声场景 |
| `wang2019` | 王珊珊, 李金林, 彭春, 等. 不确定服务时间下分布式鲁棒门诊预约调度和排程[J]. 系统工程学报, 2019, 34(4): 566-576. | [期刊官网](https://jse.tju.edu.cn/ch/reader/view_abstract.aspx?file_no=20190411&flag=1&journal_id=jse) | 不确定服务时长下的预约与排序 | 单服务台，不提供本题策略 |
| `zhu2015` | 朱顺痣, 王大寒, 何亚男, 等. 基于时间序列模型的医院门诊量分析与预测[J]. 中国科学技术大学学报, 2015, 45(10): 795-803. | [期刊官网](https://just.ustc.edu.cn/cn/article/id/1162), [DOI](https://doi.org/10.3969/j.issn.0253-2778.2015.10.001) | 趋势、周内效应、序列相关 | 单院结果不作本院参数 |
| `xiang2009` | 向前, 陈平雁. 预测医院门诊量的ARIMA模型构建及应用[J]. 南方医科大学学报, 2009, 29(5): 1076-1078. | [PubMed](https://pubmed.ncbi.nlm.nih.gov/19460744/) | 趋势和季节预测结构 | 不照搬ARIMA阶数和误差 |
| `luo2017` | LUO L, LUO L, ZHANG X, et al. Hospital daily outpatient visits forecasting using a combinatorial model based on ARIMA and SES models[J]. BMC Health Services Research, 2017, 17: 469. | [DOI](https://doi.org/10.1186/s12913-017-2407-9) | 医院日需求预测 | 单院门诊，不外推数值 |
| `lai2025` | LAI C H, LU Y J, CHEN P S. Using data-driven techniques to predict outpatient ultrasound examination time for the multi-clinic outpatient appointment scheduling problem[J]. Communications in Statistics - Simulation and Computation, 2025, 54(9): 3358-3376. | [DOI](https://doi.org/10.1080/03610918.2024.2349168) | 超声类别与时长预测 | online first 为2024；本题只估代理时长 |
| `hrhospital2025` | 华容区人民医院. 超声科流程及注意事项[EB/OL]. 2025-08-20. | [政府门户](https://www.hbhr.gov.cn/hrqxxgk/xxgkml/ggqsydwxxgk/wsjk/hrqrmyy/202508/t20250821_720866.html), [机构目录](https://www.hbhr.gov.cn/hrqxxgk/xxgkml/ggqsydwxxgk/wsjk/hrqrmyy/list.html) | 空腹、饮水憋尿的现实流程 | 外院流程只说明可行性，60分钟仍为本文假设 |
| `patrick2008` | PATRICK J, PUTERMAN M L, QUEYRANNE M. Dynamic multipriority patient scheduling for a diagnostic resource[J]. Operations Research, 2008, 56(6): 1507-1525. | [DOI](https://doi.org/10.1287/opre.1080.0590) | 截止时限驱动的动态容量分配 | 原文成本和优先级不迁移 |
| `patrick2007` | PATRICK J, PUTERMAN M L. Improving resource utilization for diagnostic services through flexible inpatient scheduling: A method for improving resource utilization[J]. Journal of the Operational Research Society, 2007, 58(2): 235-245. | [DOI](https://doi.org/10.1057/palgrave.jors.2602242) | 住院柔性容量 | CT案例，不照搬比例 |
| `chen2022` | CHEN P S, CHEN G Y H, LIU L W, et al. Using simulation optimization to solve patient appointment scheduling and examination room assignment problems for patients undergoing ultrasound examination[J]. Healthcare, 2022, 10(1): 164. | [DOI](https://doi.org/10.3390/healthcare10010164) | 超声预约与检查室指派 | 原案例房间同质，参数不可迁移 |
| `qiao2024` | 乔岩, 冉伦, 李金林, 等. 基于两阶段随机规划的远程会诊预约调度问题研究[J]. 中国管理科学, 2024, 32(1): 86-93. | [期刊官网](https://www.zgglkx.com/CN/10.16381/j.cnki.issn1003-207x.2020.1989), [DOI](https://doi.org/10.16381/j.cnki.issn1003-207x.2020.1989) | 随机服务时间下的两阶段预约与排序 | 不支持超声检查室能力主张 |
| `nhc2022` | 国家卫生健康委员会办公厅. 关于印发超声诊断等5个专业医疗质量控制指标（2022年版）的通知：国卫办医函〔2022〕161号[EB/OL]. 2022-05-27. | [国家卫健委](https://www.nhc.gov.cn/yzygj/c100068/202205/164e6556f6d34c33a3344fec9a2c5074.shtml) | 医师工作量、设备质控 | 不给本院容量与项目时长 |

## 核验结论

- 8 条中文来源与 9 条英文来源均有官方网页、期刊页、PubMed 或 DOI 元数据入口。
- 所有外部数值均被限制在原研究场景；本题的时长、能力矩阵、容量和完成率只来自赛题附件、明确假设或本项目计算。
- `CITATION_LEDGER.md` 记录正文主张与引用位置，硬验收负责检查引用 key 与参考文献条目的双向闭环。
