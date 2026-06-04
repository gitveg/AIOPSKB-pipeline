# kimi2.6-v2

---

# 企业级智能运维（AIOps）知识库目录大纲

## 一、可观测性数据字典与指标规范

### 1.1 指标元数据规范（Metric Metadata Schema）
- **指标命名规范**：`{domain}_{subsystem}_{metric_name}_{aggregation}_{time_window}` 标准范式
- **标签（Label）设计原则**：高基数管控、维度爆炸预防、**基数阈值告警规则**
- **单位与量纲标准**：标准化单位映射表（字节/秒 → B/s，比率 → 0-1 或百分比）
- **指标生命周期状态**：`experimental` → `stable` → `deprecated` → `retired` 状态机定义

### 1.2 数据类型字典
- **时序指标（Metrics）**
  - **Gauge**：瞬时值、可增可减（内存使用率、队列深度）
  - **Counter**：单调递增、仅支持 `rate()` 或 `increase()` 查询（请求总量、错误数）
  - **Histogram/Summary**：分桶统计、**分位数计算误差规范**（如 P99 允许 ±0.5% 误差）
  - **Exemplar 关联规范**：高基数 trace_id 与低基数 metric 的关联标准
- **日志（Logs）**
  - **结构化日志 Schema**：`timestamp`, `severity`, `service`, `trace_id`, `span_id`, `message`, `attributes` 必填字段
  - **日志级别映射**：`DEBUG/INFO/WARN/ERROR/FATAL` 与业务影响等级关联矩阵
  - **日志采样策略**：**头部采样（Head-based）** vs. **尾部采样（Tail-based）** 决策树
- **链路追踪（Traces）**
  - **Span 语义规范**：`kind` 枚举（`client`/`server`/`producer`/`consumer`/`internal`）
  - **Baggage 传播限制**：大小上限、敏感信息过滤规则
  - **W3C Trace Context** 与 **B3 Propagation** 兼容映射表
- **性能剖析（Profiles）**
  - **pprof/gperftools 格式规范**：采样频率、符号表解析标准
  - **持续剖析（Continuous Profiling）** 数据保留周期与压缩策略

### 1.3 采集与传输规范
- **采集 Agent 配置字典**：采集间隔、超时、重试、批处理大小参数矩阵
- **OTLP（OpenTelemetry Protocol）** 协议版本兼容矩阵
- **数据质量校验规则**：空值率阈值、延迟上界（**新鲜度 SLA**：Metrics < 15s, Logs < 60s, Traces < 30s）
- ** cardinality 管控 SOP**：动态丢弃、标签重写、聚合降维操作手册

### 1.4 数据存储与治理
- **分层存储策略**：热存储（< 7 天）、温存储（7-30 天）、冷存储（> 30 天）技术选型矩阵
- **降采样（Downsampling）** 算法配置：均匀降采样 vs. **时序数据库原生降采样**（如 Prometheus `recording rule`）
- **数据保留与合规**：GDPR/等保删除策略、审计日志关联规范

---

## 二、核心算法库与模型资产

### 2.1 时序算法库（Time Series Algorithms）
- **异常检测算法卡片**
  - **统计基线类**：3-Sigma、**Grubbs 检验**、Seasonal Hybrid ESD（S-H-ESD）
  - **机器学习类**：Isolation Forest、One-Class SVM、**LSTM Autoencoder**（重构误差阈值设定规范）
  - **深度学习类**：**Transformer-based Anomaly Detection**（如 AnomalyTransformer）、**TimesNet**（2D 时序变分编码）
  - **无监督聚类类**：DBSCAN 时序适配、**Matrix Profile**（ motifs/discords 发现）
  - **算法选型决策树**：数据量、季节性、标注率、延迟要求四维评估矩阵
- **预测与容量规划算法卡片**
  - **Prophet**：节假日效应、变点检测、置信区间解释规范
  - **ARIMA/SARIMA**：平稳性检验（ADF）、差分阶数自动选择（AIC/BIC 准则）
  - **DeepAR**：概率预测、分位数损失函数、**似然比检验**模型更新触发条件
  - **N-BEATS/N-HiTS**：多尺度预测、**层次时间序列协调（Reconciliation）** 规范
- **时序特征工程库**
  - **统计特征**：滑动窗口统计量（均值/方差/偏度/峰度）、** tsfresh 自动特征提取** 配置
  - **频域特征**：FFT 主频率、**小波变换** 多尺度分解参数
  - **时序距离度量**：DTW（动态时间规整）、**SBD（形状基于距离）**、EDR（编辑距离 on Real sequence）

### 2.2 图算法库（Graph Algorithms）
- **拓扑分析算法卡片**
  - **PageRank/LeaderRank**：服务重要性排序、**个性化重启向量** 设置（Personalized PageRank）
  - **社区发现**：Louvain、**Leiden**、Infomap 在调用链图上的分辨率参数调优
  - **中心性分析**：Betweenness Centrality（瓶颈识别）、**Closeness Centrality**（故障传播速度评估）
- **图神经网络（GNN）算法卡片**
  - **GCN/GAT**：节点分类（服务健康状态预测）、**边级注意力权重** 解释规范
  - **GraphSAGE**：归纳式学习、邻居采样策略（K-hop, 每层采样数）
  - **Temporal GNN**：**TGAT**、**DySAT**（动态图注意力）在时变调用链上的应用
  - **根因定位专用**：**CausalGNN**、**RCD（Root Cause Diagnosis）** 因果图结构学习
- **因果推断算法卡片**
  - **PC 算法**：条件独立性检验（Fisher Z / G²）、**稳定性选择** 鲁棒性增强
  - **GES（Greed Equivalence Search）**：BIC 评分、**先验知识融合**（黑名单/白名单）
  - **DoWhy + EconML**：反事实估计、**ATE（平均处理效应）** 计算与置信区间
  - **因果时序模型**：**VAR（向量自回归）** Granger 因果检验、**SVAR** 结构冲击识别

### 2.3 日志与文本算法库
- **日志解析（Log Parsing）算法卡片**
  - **Drain**：固定深度树、相似度阈值、**前缀树压缩率** 评估指标
  - **Spell**：最长公共子序列（LCS）、**参数化 token 识别** 正则模板
  - **IPLoM**：迭代分区、**消息长度/令牌位置** 分层聚类参数
  - **UniParser/LogPrompt**：基于 **LLM 的 few-shot 解析** Prompt 模板与成本评估
- **日志异常检测算法卡片**
  - **语义向量类**：LogBERT、**SwissLog**（对比学习日志嵌入）
  - **序列模型类**：DeepLog（LSTM 下一日志预测）、**LogAnomaly**（TF-IDF + 注意力）
  - **模板级检测**：模板出现频率突变、**模板序列转移概率** 马尔可夫链模型

### 2.4 模型卡片（Model Cards）规范
- **模型身份标识**：`model_id`, `version`, `algorithm_family`, `task_type`, `owner_team`
- **训练数据谱系**：数据来源、时间范围、**样本不平衡处理策略**（过采样/欠采样/代价敏感）
- **特征依赖清单**：输入特征列表、**特征重要性排序**（SHAP/LIME 解释报告链接）
- **性能基准**：测试集指标（Precision/Recall/F1/AUC/MAPE）、**跨域泛化测试**（不同业务线 hold-out 验证）
- **推理服务规格**：延迟 P99、吞吐量 QPS、资源占用（GPU/CPU/内存）、**批处理动态扩容** 策略
- **模型衰退监控**：**PSI（Population Stability Index）**、**CSI（Characteristic Stability Index）** 阈值、触发重训练条件
- **伦理与安全**：隐私数据脱敏证明、**对抗样本鲁棒性** 测试结果、可解释性等级

---

## 三、故障排查 SOP 与 RCA 案例库

### 3.1 高阶故障排查 SOP（Standard Operating Procedures）
- **分层诊断协议**
  - **基础设施层**：节点级（CPU  steal time、内存 OOM killer、磁盘 IO wait）、网络级（TCP 重传率、**ECN 拥塞标记**、DNS 解析失败）
  - **容器与编排层**：Pod 驱逐原因矩阵（`Evicted`/`OOMKilled`/`ImagePullBackOff`）、**Cgroup 资源限制** 与宿主机超卖冲突排查
  - **中间件层**：连接池耗尽、**慢查询** 执行计划分析（`EXPLAIN ANALYZE`）、消息队列堆积与消费延迟因果链
  - **应用层**：线程死锁（`jstack` 线程 dump 分析）、**GC 压力**（G1/CMS/ZGC 日志解读 SOP）、依赖服务熔断雪崩
  - **业务逻辑层**：分布式事务一致性（**TCC/Saga** 状态机异常）、幂等性失效、缓存穿透/击穿/雪崩
- **诊断工具链操作手册**
  - **动态追踪**：eBPF 程序编写规范（`bpftrace`/`bcc`）、**uprobe/kprobe** 探针 attach 安全准则
  - **性能剖析**：`async-profiler` 火焰图解读、**Off-CPU 分析** 阻塞点定位
  - **网络抓包**：`tcpdump` 过滤表达式模板、**Wireshark 专家信息** 快速解码
  - **JVM 诊断**：`arthas` 命令矩阵（`trace`/`watch`/`tt`/`heapdump`）、**安全点（Safepoint）** 暂停分析
- **应急响应分级 SOP**
  - **P0（业务瘫痪）**：立即止损（回滚/降级/扩容）→ 战时指挥官任命 → **作战室（War Room）** 召集协议
  - **P1（核心功能受损）**：影响面评估（**错误预算** 消耗速率计算）→ 定向修复 → 灰度验证
  - **P2（非核心功能异常）**：排期修复 → 监控补强 → 事后复盘
  - **通信模板库**：内部技术通报模板、外部客服话术模板、**Status Page** 更新规范

### 3.2 经典 RCA（Root Cause Analysis）案例库
- **案例元数据结构**
  - **故障指纹**：`fault_signature`（时间/空间/模式三维哈希）、**相似故障检索** 标签
  - **时间线（Timeline）**：发现时间、MTTR、**故障注入到告警触达** 延迟分解
  - **影响域拓扑**：受损服务列表、**爆炸半径** 量化（请求失败数 × 持续时间）
  - **根因链（Causal Chain）**：表面现象 → 直接原因 → **根因（Root Cause）** → 缺失的防御机制
  - **复盘方法论**：**5 Whys** 记录、**鱼骨图** 扫描文件、**FMEA（失效模式与影响分析）** 更新条目
- **案例分类字典**
  - **级联故障类**：服务 A 超时 → 服务 B 线程池耗尽 → 服务 C 熔断 → 全链路雪崩（附 **Hystrix/Resilience4j** 参数调优教训）
  - **变更引发类**：配置推送异常、**数据库 Schema 变更** 锁表、发布系统灰度比例计算错误
  - **资源竞争类**：** noisy neighbor**（ noisy 邻居效应）、CPU 调度器 **CFS quota** 与实时性冲突
  - **数据异常类**：缓存与数据库不一致、**消息队列重复消费**、分布式时钟偏移（**时钟同步** NTP 跳变）
  - **第三方依赖类**：云厂商 API 限流、CDN 节点异常、**DNS 服务商** 解析劫持
  - **安全攻击类**：DDoS 流量特征、**CC 攻击**（Challenge Collapsar）与正常促销流量区分 SOP
- **模式提取与复用**
  - **故障模式库（Failure Mode Library）**：已验证的故障模式模板、**防御模式（Defense Pattern）** 映射
  - **检测规则沉淀**：基于历史 RCA 的 **PromQL/LogQL** 告警规则、**多信号关联** 条件（Metric + Log + Trace 同时异常）
  - **演练案例库**：**混沌工程（Chaos Engineering）** 实验设计（故障注入点、预期稳态假设、**终止条件（Abort Condition）**）

---

## 四、LLM/RAG 运维工程实践与 Prompt 库

### 4.1 运维大模型工程架构规范
- **模型选型决策矩阵**
  - **基座模型**：通用 LLM（GPT-4/Claude/通义千问） vs. **代码专用**（CodeLlama/StarCoder） vs. **垂直微调**（基于运维语料预训练）
  - **规模选择**：7B/13B/70B 在 **推理成本** 与 **上下文长度** 上的权衡、**量化策略**（INT8/INT4/AWQ/GPTQ）性能损失评估
  - **部署模式**：API 调用、**私有化 vLLM/TGI 部署**、**边缘侧推理**（Jetson/昇腾）场景适配
- **RAG（检索增强生成）架构规范**
  - **文档分块策略**：固定长度 vs. **语义分块**（基于句子嵌入相似度）、**层次化分块**（章节 → 段落 → 代码片段）
  - **嵌入模型选型**：`text-embedding-ada-002`、**BGE**、**M3E**、运维领域微调嵌入模型效果对比
  - **向量数据库选型**：Milvus/Pinecone/Weaviate/ **Pgvector** 性能基准（召回率@K、延迟 P99）
  - **检索策略**：**混合检索**（向量相似度 + BM25 关键词）、**重排序（Rerank）** 模型（Cross-Encoder）、**查询重写（Query Rewriting）** 技术
  - **上下文组装协议**：**最大边际相关性（MMR）** 去重、**引用溯源（Citation）** 格式规范

### 4.2 Prompt 工程库（Prompt Library）
- **Prompt 设计原则**
  - **角色设定模板**：`你是一位资深 SRE，擅长 Kubernetes 排错...` 角色卡片标准范式
  - **输出格式约束**：JSON Schema 强制输出、**思维链（Chain-of-Thought）** 触发词（`请逐步分析...`）
  - **少样本示例（Few-shot）** 构造：正例/反例比例、**边界案例** 覆盖要求
- **运维场景 Prompt 模板**
  - **日志解析与摘要**：`给定以下 {service} 的异常日志片段，提取错误模式、定位可能组件、给出排查优先级...`
  - **告警降噪与关联**：`以下是一组同时触发的告警列表，请基于服务拓扑和告警文本相似度，判断是否为同一根因导致，并给出合并建议...`
  - **故障排查引导**：`现象：{symptom}，已采集数据：{metrics/logs/traces}，请按可能性从高到低列出根因假设，并给出验证命令...`
  - **Runbook 生成**：`基于以下 RCA 案例，生成可执行的逐步排查 Runbook，要求每个步骤包含验证命令和预期输出...`
  - **SQL/ PromQL 生成**：`自然语言查询：{question}，数据 Schema：{schema}，请生成符合以下规范的查询：{dialect}...`
  - **事后复盘报告**：`基于以下故障时间线和处理记录，生成技术复盘报告，包含：现象摘要、根因分析、改进措施（按优先级排序）、待办事项（Owner + Deadline）...`
  - **知识库问答**：`基于以下检索到的相关文档片段，回答用户问题。如果文档不足以回答，明确说明'根据现有知识库无法确定'...`
- **Prompt 版本管理与评估**
  - **A/B 测试框架**：相同输入下不同 Prompt 的 **答案一致性（Consistency）**、**事实准确性（Factuality）**、**操作可行性（Actionability）** 评分
  - **对抗测试用例**：**提示注入（Prompt Injection）** 防御、**越狱（Jailbreak）** 尝试记录、敏感信息泄露测试
  - **效果衰退监控**：用户满意度评分、**人工修正率**、**二次查询率**（首次回答未解决问题比例）

### 4.3 运维 Agent 与自动化
- **Agent 架构模式**
  - **ReAct（Reasoning + Acting）**：思考 → 行动（调用工具）→ 观察 → 循环终止条件
  - **Plan-and-Solve**：任务分解 → 子任务调度 → 结果聚合 → **自我验证（Self-verification）**
  - **Multi-Agent 协作**：诊断 Agent、修复 Agent、验证 Agent、**人类在环（Human-in-the-loop）** 决策点
- **工具调用（Function Calling）规范**
  - **工具注册 Schema**：`name`, `description`, `parameters`（JSON Schema 严格定义）
  - **运维工具集**：查询时序数据库、检索日志、执行 **kubectl** 命令、调用 **Jenkins/Argo** 流水线、创建 **Jira/飞书** 工单
  - **安全沙箱**：命令白名单、**资源配额限制**、操作审计日志、**危险操作二次确认** 机制
- **效果评估指标**
  - **任务完成率（Task Success Rate）**：端到端自动化闭环比例
  - **平均诊断步数**：到达正确根因所需的交互轮次
  - **人工接管率**：Agent 无法处理转人工的比例及原因分类

---

## 五、知识库质量保证与运维规范

### 5.1 数据保鲜机制（Data Freshness Governance）
- **知识时效性分级**
  - **实时级（Real-time）**：告警规则、**当前系统拓扑**（自动同步 CMDB）
  - **日更级（Daily）**：指标字典变更、模型推理服务状态、**昨日故障统计**
  - **周更级（Weekly）**：算法实验报告、**SLO 达成率** 趋势、RCA 案例入库
  - **月更级（Monthly）**：架构评审结论、**技术债清单** 更新、工具链版本升级记录
  - **季度评审（Quarterly）**：知识库整体架构健康度评估、**僵尸条目** 清理
- **自动化保鲜流水线**
  - **数据血缘追踪**：知识条目 → 源数据/文档/代码仓库 → 变更监听 → **自动失效标记**
  - **过期检测规则**：最后更新时间 > TTL 阈值、上游 Schema 变更、**关联系统已下线**
  - **保鲜任务队列**：低优先级后台扫描、**增量校验**（仅检查变更部分）、人工复核工单生成

### 5.2 模型效果衰退评估规范（Model Degradation Protocol）
- **监控指标体系**
  - **数据漂移（Data Drift）**：输入特征分布变化、**协变量漂移（Covariate Shift）** 检测（KS 检验/卡方检验）
  - **概念漂移（Concept Drift）**：**先验概率漂移**（Prior Shift）、**后验漂移**（Posterior Shift）、**决策边界漂移**
  - **性能衰退**：业务指标（告警准确率、MTTR 辅助效果）趋势监控、**控制图（Control Chart）** 异常点标记
- **衰退响应流程**
  - **黄色预警**：PSI > 0.1 或性能下降 10% → 自动触发 **影子测试（Shadow Testing）** → 生成对比报告
  - **橙色预警**：PSI > 0.2 或性能下降 20% → **模型回滚** 至上一稳定版本 → 启动紧急重训练
  - **红色预警**：PSI > 0.3 或性能下降 30% → **立即下线** → 切换至规则引擎兜底 → 成立专项修复组
- **重训练触发条件与规范**
  - **主动触发**：季度计划重训练、**新标注数据积累** 达到阈值（如 10K 新样本）
  - **被动触发**：漂移检测超标、业务投诉集中、**混沌工程实验** 暴露模型盲区
  - **重训练 SOP**：数据快照冻结、**基线对比实验**（新旧模型同测）、灰度发布（5% → 50% → 100%）、**回滚预案** 就绪检查

### 5.3 知识库内容质量标准
- **准确性（Accuracy）**
  - **技术事实校验**：算法原理引用 **原始论文** 或权威文档、命令行参数经过 **多环境验证**
  - **案例真实性**：RCA 案例必须附 **真实时间线**（脱敏后）、禁止虚构或过度简化
  - **交叉引用完整性**：术语首次出现时标注 **内部定义链接**、避免歧义
- **完整性（Completeness）**
  - **MECE 自检清单**：每个分类下的条目是否 **相互独立**、合起来是否 **完全穷尽** 该领域
  - **缺失项标记**：`TODO` 标签规范（优先级、预计补齐时间、负责人）
  - **版本覆盖**：关键条目需覆盖 **多版本**（如 Kubernetes 1.24/1.28/1.30 差异说明）
- **可检索性（Discoverability）**
  - **标签体系**：技术域标签（`#observability` `#causal-inference`）、场景标签（`#oncall` `#capacity-planning`）、难度标签（`#beginner` `#expert`）
  - **同义词映射**：**"SLO" ↔ "服务等级目标"**、**"Cardinality" ↔ "基数"** ↔ "维度爆炸"
  - **搜索优化**：标题关键词密度、**FAQ 模式**（问题-答案对）独立条目化
- **可维护性（Maintainability）**
  - **编辑规范**：Markdown 格式标准、**代码块语言标注**、图表 **PlantUML/Mermaid** 源码附注
  - **变更日志（Changelog）**：每次修改记录 `date`, `author`, `change_type`（`add`/`modify`/`deprecate`），**破坏性变更** 高亮警示
  - **评审机制**：技术专家 **Peer Review** 清单、**领域 Owner** 终审制度、**季度内容审计** 报告

### 5.4 知识库运营指标（KPIs）
- **活跃度指标**：周活跃编辑人数、**新增条目速率**、**查询访问量** 趋势
- **质量指标**：过期条目占比、**用户满意度评分**（1-5 星）、**知识被引用次数**（在 Runbook/告警中的引用链路）
- **效能指标**：故障排查时 **知识库检索次数** vs. 直接求助专家次数比率、**MTTR 缩短贡献度**（基于知识库使用前后的对比分析）

---

## 附录：知识库索引与快速导航

- **术语总表（Glossary）**：按字母序排列的全部 **加粗专业术语** 释义与内部标准定义
- **标签云（Tag Cloud）**：高频技术标签与关联条目数
- **版本历史（Version History）**：知识库架构重大变更记录（v1.0 → v2.0 分类体系演进）
- **贡献者名录（Contributors）**：领域专家、**知识 Owner** 联系方式、**值班轮换** 表

---

**编制说明**：本大纲严格遵循 MECE 原则，五大板块（数据字典、算法模型、故障案例、LLM 实践、质量保证）覆盖 AIOps 知识资产的全生命周期。每个三级条目均为可直接实例化的知识单元，具备明确的输入（数据源/场景）、处理逻辑（算法/SOP/Prompt）、输出（模型/规则/报告）及质量验收标准。建议配套建设基于 **Markdown + Git + CI/CD** 的文档即代码（Docs-as-Code）流水线，确保知识库与技术栈同步演进。