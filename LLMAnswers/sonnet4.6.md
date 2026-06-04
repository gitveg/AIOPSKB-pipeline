# 智能运维知识库（AIOps Knowledge Base）

> 版本：v1.0 | 创建日期：2026-04-17 | 维护人：运维团队

---

## 目录

1. [基础设施与环境管理](#1-基础设施与环境管理)
2. [操作系统运维](#2-操作系统运维)
3. [网络运维](#3-网络运维)
4. [存储与数据库运维](#4-存储与数据库运维)
5. [容器与云原生运维](#5-容器与云原生运维)
6. [云平台运维](#6-云平台运维)
7. [监控、告警与可观测性](#7-监控告警与可观测性)
8. [日志管理与分析](#8-日志管理与分析)
9. [自动化运维与DevOps](#9-自动化运维与devops)
10. [安全运维（SecOps）](#10-安全运维secops)
11. [故障管理与应急响应](#11-故障管理与应急响应)
12. [性能调优与容量规划](#12-性能调优与容量规划)
13. [AIOps 智能化运维](#13-aiops-智能化运维)
14. [ITIL 与运维流程管理](#14-itil-与运维流程管理)
15. [运维工具链全景](#15-运维工具链全景)
16. [典型场景案例库](#16-典型场景案例库)

---

## 1. 基础设施与环境管理

### 1.1 物理基础设施
- 数据中心规划（机房选址、供电、制冷、布线标准）
- 服务器硬件架构（CPU、内存、硬盘、RAID、网卡）
- UPS、PDU 电源管理
- IPMI / iDRAC / iLO 带外管理
- 硬件资产管理与生命周期

### 1.2 虚拟化平台
- VMware vSphere / ESXi 架构与管理
- KVM / QEMU 虚拟化
- Hyper-V 管理
- oVirt / Proxmox 开源虚拟化
- 虚拟机模板、快照、迁移策略
- 资源池与 HA / DRS 配置

### 1.3 基础设施即代码（IaC）
- Terraform 核心概念与实践
- Pulumi 使用
- CloudFormation（AWS）
- ARM Template / Bicep（Azure）
- 状态管理与远端 Backend 配置
- 模块化与复用最佳实践

### 1.4 配置管理
- Ansible Playbook 编写规范
- SaltStack 架构与 State 管理
- Puppet / Chef 配置管理
- 幂等性设计原则
- 配置漂移检测与修复

---

## 2. 操作系统运维

### 2.1 Linux 系统运维
#### 2.1.1 系统基础
- 目录结构与文件系统（ext4、XFS、Btrfs、ZFS）
- 进程管理（ps、top、htop、systemd、cgroups）
- 用户与权限管理（sudo、ACL、PAM）
- 启动流程（BIOS/UEFI → GRUB → Kernel → systemd）

#### 2.1.2 常用发行版
- Red Hat / CentOS / Rocky Linux / AlmaLinux（rpm、yum/dnf）
- Ubuntu / Debian（dpkg、apt）
- SUSE / openSUSE（zypper）
- 发行版选型建议

#### 2.1.3 系统调优
- 内核参数调优（sysctl）
- 文件描述符与连接数优化
- NUMA 架构感知调优
- 内存大页（HugePages）配置
- CPU 亲和性与中断绑定（irqbalance）
- I/O 调度器选择（CFQ / deadline / noop / mq-deadline）

#### 2.1.4 常见故障排查
- 系统负载高排查思路
- OOM（内存溢出）分析
- 磁盘 I/O 瓶颈定位
- 网络连通性与丢包排查
- Kdump / crash 内核转储分析

### 2.2 Windows Server 运维
- Active Directory 域管理
- Group Policy 配置
- Windows Server 角色与功能（DNS、DHCP、IIS、RDS）
- PowerShell 自动化脚本
- 事件日志分析（Event Viewer）
- WMI / WinRM 远程管理

### 2.3 系统安全加固
- CIS Benchmark 基线加固
- SSH 安全配置（禁 root、密钥认证、端口变更）
- 最小化软件安装原则
- SELinux / AppArmor 策略
- auditd 审计日志配置

---

## 3. 网络运维

### 3.1 网络基础理论
- OSI 七层模型与 TCP/IP 四层模型
- IP 地址规划（CIDR、VLSM、子网划分）
- ARP、ICMP、DNS、DHCP 协议原理
- TCP 三次握手 / 四次挥手 / 拥塞控制

### 3.2 交换网络
- VLAN 配置与 Trunk 链路
- STP / RSTP / MSTP 生成树协议
- 链路聚合（LACP / 802.3ad）
- QoS 流量策略

### 3.3 路由与广域网
- 静态路由与动态路由（OSPF、BGP、IS-IS）
- MPLS / SD-WAN 架构
- NAT / PAT 配置
- VPN（IPsec、SSL VPN、GRE Tunnel）

### 3.4 网络安全设备
- 防火墙策略管理（iptables、nftables、Palo Alto、Fortinet）
- WAF（Web 应用防火墙）配置与调优
- IDS / IPS 规则管理
- DDoS 防护策略

### 3.5 负载均衡
- Nginx / HAProxy 配置与调优
- F5 BIG-IP 管理
- LVS（IPVS）架构
- 健康检查策略
- 会话保持（Session Persistence）

### 3.6 网络运维工具
- 抓包分析（tcpdump、Wireshark）
- 网络探测（nmap、ping、traceroute、mtr）
- 带宽测试（iperf3）
- SNMP 监控与 NetFlow 分析

---

## 4. 存储与数据库运维

### 4.1 存储架构
- DAS / NAS / SAN 架构对比
- 分布式存储（Ceph、GlusterFS、MinIO）
- 对象存储（S3 协议）
- 存储性能指标（IOPS、吞吐量、延迟）

### 4.2 MySQL / MariaDB 运维
- 安装部署与初始化配置
- 主从复制（GTID 模式）
- MGR（MySQL Group Replication）
- 慢查询分析与索引优化
- Binlog 管理与备份恢复
- 连接池（ProxySQL / MySQL Router）
- InnoDB 参数调优

### 4.3 PostgreSQL 运维
- 流复制与 Patroni 高可用
- VACUUM / ANALYZE 维护
- 慢查询（pg_stat_statements）分析
- 扩展插件管理（pgvector、PostGIS、TimescaleDB）
- 逻辑复制与 CDC

### 4.4 Redis 运维
- 数据结构与使用场景
- 持久化策略（RDB / AOF）
- 主从复制与 Sentinel 高可用
- Redis Cluster 分片架构
- 内存淘汰策略与大 Key 排查
- Redis 性能优化与慢日志分析

### 4.5 Elasticsearch 运维
- 集群架构（Master / Data / Ingest / Coordinating）
- 索引生命周期管理（ILM）
- 分片设计与 Mapping 优化
- 常见故障（脑裂、OOM、磁盘告警）处理
- 冷热数据分层存储

### 4.6 消息队列运维
- Kafka 集群部署与参数调优
- RabbitMQ 管理与高可用配置
- RocketMQ 运维要点
- 消费积压告警与处理
- 消息幂等与事务保障

### 4.7 备份与容灾
- 备份策略（全量 / 增量 / 差异）
- RPO / RTO 定义与设计
- 异地容灾架构（两地三中心）
- 备份有效性验证
- 常用备份工具（Percona XtraBackup、pg_basebackup、Velero）

---

## 5. 容器与云原生运维

### 5.1 Docker 容器管理
- 镜像构建（Dockerfile 最佳实践、多阶段构建）
- 容器生命周期管理
- 网络模式（bridge、host、overlay、macvlan）
- 数据卷与持久化存储
- Docker Compose 多服务编排
- 私有镜像仓库（Harbor）搭建与管理
- 容器安全扫描（Trivy、Clair）

### 5.2 Kubernetes 运维
#### 5.2.1 集群架构
- 控制平面组件（API Server、etcd、Scheduler、Controller Manager）
- 工作节点组件（kubelet、kube-proxy、Container Runtime）
- 网络插件（Calico、Flannel、Cilium）
- 存储插件（CSI 驱动）

#### 5.2.2 核心资源管理
- Pod、Deployment、StatefulSet、DaemonSet、Job/CronJob
- Service（ClusterIP / NodePort / LoadBalancer）
- Ingress / IngressClass / Gateway API
- ConfigMap / Secret 管理
- RBAC 权限体系
- Namespace 隔离策略

#### 5.2.3 集群运维
- 集群安装（kubeadm、Rancher RKE2、K3s）
- 节点扩缩容与版本升级
- etcd 备份与恢复
- 证书管理与轮换
- 污点（Taint）与容忍（Toleration）调度策略
- PodDisruptionBudget（PDB）保障

#### 5.2.4 可观测性
- kube-state-metrics / metrics-server
- Prometheus Operator 部署
- Grafana 监控大盘
- 日志收集（Loki、Fluentd/Fluentbit）
- 链路追踪（Jaeger、Tempo）

#### 5.2.5 高可用与弹性伸缩
- HPA（Horizontal Pod Autoscaler）
- VPA（Vertical Pod Autoscaler）
- KEDA 事件驱动伸缩
- Cluster Autoscaler 节点自动扩缩

### 5.3 服务网格（Service Mesh）
- Istio 架构与流量管理
- Envoy Proxy 配置
- 流量策略（金丝雀发布、流量镜像、熔断）
- mTLS 双向认证
- Linkerd 轻量级服务网格

### 5.4 GitOps 与持续交付
- ArgoCD 配置与应用管理
- Flux CD 自动同步
- Helm Chart 开发与版本管理
- Kustomize 多环境配置

---

## 6. 云平台运维

### 6.1 阿里云
- ECS / ACK / ASK 管理
- OSS / NAS / ESSD 存储
- RDS / PolarDB / Redis / MongoDB 托管数据库
- SLB / ALB / CLB 负载均衡
- VPC / 安全组 / ACL 网络管理
- 云监控（CloudMonitor）与告警配置
- RAM 权限管理与最小权限原则
- 费用优化（预留实例、节省计划）

### 6.2 腾讯云
- CVM / TKE / EKS 容器服务
- COS 对象存储
- 云数据库（MySQL / Redis / MongoDB）
- CLB / WAF / DDoS 防护
- 云日志服务（CLS）

### 6.3 AWS
- EC2 / EKS / ECS / Fargate
- S3 / EBS / EFS 存储
- RDS / ElastiCache / DynamoDB
- VPC / Security Group / Route53
- CloudWatch / CloudTrail / Config
- IAM 策略与角色
- Cost Explorer 费用分析

### 6.4 Azure
- Virtual Machines / AKS
- Azure Blob Storage / Azure Files
- Azure SQL / Cosmos DB / Cache for Redis
- Azure Monitor / Log Analytics
- Azure Active Directory（Entra ID）

### 6.5 混合云与多云管理
- 统一身份认证（SSO / LDAP 集成）
- 跨云网络互联（专线、VPN、云联网）
- 多云成本可见性（FinOps）
- Terraform 多 Provider 管理
- 多云 CMDB 资产管理

---

## 7. 监控、告警与可观测性

### 7.1 可观测性三支柱
- 指标（Metrics）：Prometheus 数据模型、PromQL 查询语言
- 日志（Logs）：结构化日志、日志级别规范
- 链路追踪（Traces）：OpenTelemetry 标准、Span 概念

### 7.2 监控体系建设
- 监控分层（基础设施层 → 平台层 → 应用层 → 业务层）
- 黄金指标：延迟、流量、错误率、饱和度（RED / USE 方法）
- SLI / SLO / SLA 定义与计算
- 监控即代码（Monitoring as Code）

### 7.3 Prometheus 生态
- Prometheus 架构与数据采集（Pull 模型）
- Exporter 全景（Node Exporter、Blackbox Exporter、Custom Exporter）
- 标签（Label）设计与高基数问题
- Recording Rules 与 Alerting Rules 编写
- Thanos / Cortex / VictoriaMetrics 长期存储方案
- Alertmanager 告警路由与静默策略

### 7.4 Grafana 可视化
- Dashboard 设计规范
- 变量（Variable）与模板化 Dashboard
- 告警（Grafana Alerting）配置
- Grafana Loki 日志面板集成
- Grafana Tempo 链路追踪集成

### 7.5 APM（应用性能监控）
- SkyWalking 探针接入与拓扑分析
- Pinpoint 追踪
- Elastic APM
- Datadog APM（商业方案）
- 慢接口、异常调用链分析方法

### 7.6 告警策略设计
- 告警分级（P0/P1/P2/P3）
- 告警收敛与聚合（避免告警风暴）
- On-call 轮班机制（PagerDuty / 自建）
- 告警升级策略
- 静默与抑制规则

---

## 8. 日志管理与分析

### 8.1 日志采集架构
- Agent 采集（Filebeat、Fluentd、Fluentbit、Vector）
- 直推模式 vs 中转模式
- 日志采集的可靠性保障（背压、重试、幂等写入）

### 8.2 ELK / EFK 技术栈
- Elasticsearch 集群部署与调优
- Logstash Pipeline 配置（Input / Filter / Output）
- Kibana 数据探索与 Discover 使用
- Grok 正则解析与 Dissect 解析器
- 索引模板（Index Template）设计

### 8.3 Grafana Loki
- Loki 架构（Distributor / Ingester / Querier）
- LogQL 查询语法
- 标签策略与低基数设计
- 与 Promtail / Fluentbit 集成

### 8.4 日志规范
- 结构化日志（JSON 格式）规范
- TraceID / SpanID 串联
- 敏感信息脱敏（密码、手机号、身份证）
- 日志保留与归档策略（冷热分层）

### 8.5 日志安全审计
- 操作审计日志（堡垒机日志、sudo 日志）
- 数据库审计日志
- 登录失败与异常访问检测
- SIEM 集成（安全信息与事件管理）

---

## 9. 自动化运维与DevOps

### 9.1 CI/CD 流水线
- Jenkins Pipeline（Declarative / Scripted）
- GitLab CI/CD 配置（.gitlab-ci.yml）
- GitHub Actions Workflow
- Tekton 云原生流水线
- 制品管理（Nexus、JFrog Artifactory）
- 流水线安全（SAST、DAST、依赖扫描、镜像扫描）

### 9.2 发布策略
- 蓝绿部署（Blue-Green Deployment）
- 金丝雀发布（Canary Release）
- 滚动更新（Rolling Update）
- A/B 测试发布
- 功能开关（Feature Flag）
- 回滚策略与回滚触发条件

### 9.3 运维自动化脚本
- Shell 脚本规范（错误处理、日志输出、参数校验）
- Python 运维脚本最佳实践
- PowerShell 自动化（Windows 环境）
- 定时任务管理（crontab、systemd timer）
- 任务调度平台（XXL-Job、Airflow、Azkaban）

### 9.4 自助运维平台
- CMDB（配置管理数据库）设计与选型
- 运维工单系统（ServiceNow、JIRA Service Management）
- 自助发布平台
- 堡垒机（jumpserver、Teleport）
- 运维审批流程自动化

### 9.5 混沌工程
- 混沌工程原则（Principles of Chaos Engineering）
- Chaos Monkey / ChaosBlade / Chaos Mesh
- 故障注入场景（CPU 满载、磁盘填满、网络延迟/丢包）
- 稳态假设验证
- 游戏日（Game Day）演练规范

---

## 10. 安全运维（SecOps）

### 10.1 身份与访问管理（IAM）
- 最小权限原则
- 多因素认证（MFA）
- 统一身份认证（LDAP / AD / OAuth2 / SAML）
- PAM（特权账号管理）
- 服务账号与 API Key 生命周期管理

### 10.2 网络安全
- 零信任网络架构（ZTNA）
- 微隔离（Micro-segmentation）
- VPN / SASE 方案
- 防火墙策略审计与清理
- 端口暴露面扫描（Shodan、Censys）

### 10.3 漏洞管理
- CVE 漏洞扫描（Nessus、OpenVAS、Qualys）
- 容器镜像漏洞扫描（Trivy、Snyk）
- 依赖库 SCA 扫描
- 漏洞修复优先级评估（CVSS 评分）
- 补丁管理流程

### 10.4 安全监控与响应
- SIEM 平台（Splunk、IBM QRadar、Wazuh）
- EDR（终端检测响应）
- 入侵检测（AIDE、Falco、Sysdig）
- 安全事件响应流程（SOAR）
- 取证与溯源分析

### 10.5 合规与数据安全
- 等级保护（等保 2.0）合规要求
- GDPR / 数据安全法 / 个人信息保护法
- 数据分类分级与脱敏
- 密钥管理（HashiCorp Vault、KMS）
- 传输加密（TLS 1.2+ 配置）与存储加密

---

## 11. 故障管理与应急响应

### 11.1 故障分级与定义
- P0（全站不可用）/ P1（核心功能受损）/ P2（部分功能异常）/ P3（轻微影响）
- 故障影响范围评估
- SLA 违约判定标准

### 11.2 故障应急响应流程
- 故障发现与上报（监控告警 / 用户反馈 / 主动巡检）
- 应急响应启动（战时指挥官制度）
- 故障隔离（快速止血 vs 根因定位）
- 恢复操作与验证
- 信息通报（内部通知、客户公告模板）

### 11.3 故障排查方法论
- 分层排查法（从用户侧 → 网络 → 应用 → 中间件 → 数据库 → OS → 硬件）
- 二分法快速定位
- 时间轴分析（变更关联分析）
- 对比分析法（正常 vs 异常实例）
- 5 Why 根因分析

### 11.4 故障复盘（Post-mortem）
- 复盘文化（无指责原则，Blameless Postmortem）
- 复盘报告模板（事件时间线 / 根因分析 / 影响评估 / 改进措施）
- 改进项跟踪闭环（Action Item Owner + Deadline）
- 故障知识库沉淀
- 复盘会议组织规范

### 11.5 变更管理
- 变更分级（紧急变更 / 标准变更 / 计划变更）
- 变更窗口管理（禁止大促期间变更）
- 变更评审检查清单
- 变更回滚预案
- 灰度变更策略

---

## 12. 性能调优与容量规划

### 12.1 性能分析方法论
- USE 方法（Utilization / Saturation / Errors）
- RED 方法（Rate / Errors / Duration）
- 基准测试（Benchmark）与性能基线
- 火焰图（Flame Graph）分析
- 性能剖析工具（perf、eBPF、bpftrace）

### 12.2 操作系统性能调优
- CPU 调度优化（taskset、NUMA 绑定）
- 内存优化（swap 策略、THP 禁用、内存碎片整理）
- 磁盘 I/O 优化（fio 测试、I/O 调度器、文件系统挂载参数）
- 网络协议栈调优（TCP 缓冲区、连接追踪表、TIME_WAIT）

### 12.3 应用层性能调优
- JVM 调优（堆内存设置、GC 算法选择、GC 日志分析）
- Go Runtime 调优（GOMAXPROCS、内存模型）
- Python 性能优化（GIL、异步 IO、Cython）
- 连接池调优（数据库连接池、HTTP 连接池）
- 缓存策略（本地缓存、分布式缓存、缓存穿透/击穿/雪崩防护）

### 12.4 数据库性能调优
- 慢查询识别与索引优化
- 执行计划分析（EXPLAIN）
- 锁等待与死锁分析
- 读写分离与分库分表
- 查询缓存与预编译语句

### 12.5 容量规划
- 容量模型建立（流量预测模型）
- 压测（JMeter、Gatling、k6、Locust）
- 水位线管理（CPU/内存/磁盘告警阈值）
- 弹性伸缩策略（定时伸缩 / 指标触发伸缩）
- 大促压测与容量评估流程

---

## 13. AIOps 智能化运维

### 13.1 AIOps 概述
- AIOps 定义与发展历程（Gartner 定义）
- AIOps 与传统运维的区别
- AIOps 能力全景图
- 落地路径与成熟度模型

### 13.2 智能告警
- 告警降噪（基于聚类的告警分组）
- 告警关联分析（时序相关性、拓扑关联）
- 异常检测算法（3-Sigma、DBSCAN、Isolation Forest、LSTM）
- 动态阈值 vs 静态阈值
- 告警根因推荐

### 13.3 智能故障诊断
- 故障图谱（知识图谱 + 拓扑关系）
- 根因定位（RCA）算法
- 指标异常传播路径分析
- 日志异常检测（日志模板挖掘、LogBERT）
- 基于大模型（LLM）的故障诊断辅助

### 13.4 智能运维决策
- 变更风险评估模型
- 预测性维护（预测磁盘故障、节点异常）
- 容量智能预测（Prophet、ARIMA 时序预测）
- 自动化响应剧本（Runbook Automation）
- ChatOps 与运维机器人（Slack Bot / 企业微信机器人）

### 13.5 大模型在运维中的应用
- LLM 辅助故障诊断（RAG + 知识库）
- 自然语言转 PromQL / SQL 查询
- 日志智能摘要与根因解释
- 运维知识问答系统
- Copilot 辅助运维脚本生成

### 13.6 数据平台与运维数据治理
- 运维数据湖建设
- 时序数据库选型（InfluxDB、TDengine、VictoriaMetrics）
- 特征工程与数据标注
- 模型训练、评估与上线（MLOps）
- 运维数据安全与隐私

---

## 14. ITIL 与运维流程管理

### 14.1 ITIL 4 核心概念
- 服务价值系统（SVS）
- 四个维度（组织与人员、信息与技术、伙伴与供应商、价值流与流程）
- 指导原则（专注价值、从现在开始、迭代反馈、协同合作）
- 持续改进（Continual Improvement）

### 14.2 核心管理实践
- 变更赋能（Change Enablement）
- 事件管理（Incident Management）
- 问题管理（Problem Management）
- 服务台（Service Desk）
- 服务请求管理（Service Request Management）
- 配置管理（CMDB）

### 14.3 SRE（网站可靠性工程）
- SRE 与运维的关系
- Error Budget（错误预算）机制
- Toil（重复劳动）识别与消除
- SRE 值班（On-call）文化
- SRE 团队建设与职责

### 14.4 运维团队管理
- 运维 KPI / OKR 制定
- 知识管理（Knowledge Management）
- 运维文档规范（Runbook、SOP、架构图）
- 技术债务管理
- 运维团队能力建设路径

---

## 15. 运维工具链全景

### 15.1 工具分类全景

| 类别 | 主流工具 |
|------|----------|
| 版本控制 | Git、GitLab、GitHub、Gitea |
| CI/CD | Jenkins、GitLab CI、GitHub Actions、Argo CD、Tekton |
| 容器运行时 | Docker、containerd、CRI-O |
| 容器编排 | Kubernetes、Nomad、Docker Swarm |
| IaC | Terraform、Pulumi、Ansible、SaltStack |
| 监控 | Prometheus、VictoriaMetrics、Zabbix、Datadog |
| 可视化 | Grafana、Kibana、Datadog |
| 日志 | ELK Stack、Loki、Graylog |
| APM | SkyWalking、Pinpoint、Elastic APM |
| 链路追踪 | Jaeger、Zipkin、Tempo |
| 告警 | Alertmanager、PagerDuty、OpsGenie |
| 制品库 | Harbor、Nexus、JFrog Artifactory |
| 密钥管理 | HashiCorp Vault、AWS KMS、阿里云 KMS |
| 堡垒机 | JumpServer、Teleport、CyberArk |
| CMDB | iTop、ServiceNow、自研 |
| 混沌工程 | Chaos Mesh、ChaosBlade、Gremlin |
| 压测 | JMeter、k6、Gatling、Locust |
| 安全扫描 | Trivy、Snyk、SonarQube、Nessus |

### 15.2 工具选型原则
- 开源 vs 商业的权衡
- 社区活跃度与生态成熟度
- 与现有技术栈的集成性
- TCO（总拥有成本）评估
- 团队学习曲线

---

## 16. 典型场景案例库

### 16.1 故障处理案例
- 数据库主从切换导致业务中断的处理过程
- Kubernetes 节点 NotReady 排查全流程
- Redis 内存打满导致服务不可用案例
- 磁盘 I/O 100% 导致系统卡顿排查
- DNS 解析异常引发的级联故障分析

### 16.2 架构优化案例
- 单体应用拆分微服务的运维演进
- 从 ELK 迁移到 Loki 降本增效实践
- 基于 KEDA 实现消息队列驱动的弹性伸缩
- 混合云网络打通与统一监控建设

### 16.3 自动化建设案例
- 基于 Ansible 实现百台服务器配置统一管理
- GitOps 实践：从手动部署到全自动化发布
- 运维机器人接入企业微信实现告警自愈
- 基于 Python + 大模型构建运维知识问答系统

### 16.4 大促保障案例
- 大促前全链路压测实施方案
- 弹性伸缩预案与容量预热策略
- 限流降级熔断配置（Sentinel / Resilience4j）
- 大促期间监控大盘搭建与值班规范

---

## 附录

### A. 常用命令速查
- Linux 系统排查常用命令
- Docker / Kubernetes 常用命令
- 数据库运维常用 SQL
- 网络排查命令速查

### B. 文档模板
- 故障复盘报告模板
- 变更申请单模板
- 容量评估报告模板
- SLA 协议模板
- Runbook 编写模板

### C. 学习资源推荐
- 书籍：《SRE：Google 运维解密》、《凤凰项目》、《DevOps 实践指南》
- 社区：CNCF、OpenTelemetry、Kubernetes 官方文档
- 认证：CKA/CKS（Kubernetes）、AWS/Azure/阿里云认证、ITIL 4 Foundation

### D. 术语表
- 常用运维术语中英文对照
- 缩写解释（MTTR、MTBF、RTO、RPO、SLI、SLO、SLA）

---

> **维护说明**：本知识库为持续演进文档，建议每季度进行一次内容审查与更新。
> 欢迎团队成员通过 PR 方式贡献内容，共同完善知识体系。
