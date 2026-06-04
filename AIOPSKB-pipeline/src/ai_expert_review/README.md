# 三AI专家评审模块

> 知识库设备层分类与覆盖度的多AI独立评审系统
> 详见：`construct_guide.md` 0.2.1 节（判定原则）和 2.1-2.7 节（智能体角色）

---

## 架构

```
                    ┌──────────────────────────────┐
                    │       Claude 主智能体          │
                    │   综合裁决 / 最终裁定 / 报告    │
                    └──────────┬───────────────────┘
                               │ 整合两方意见
              ┌────────────────┼────────────────┐
              ▼                │                ▼
  ┌───────────────────┐        │    ┌──────────────────────┐
  │  DeepSeek 专家     │        │    │    Kimi 专家          │
  │  deepseek-v4-pro  │        │    │    kimi-k2.6          │
  │                   │        │    │                       │
  │  电力行业资深工程师  │        │    │  工业知识体系架构师     │
  │  30年运维经验       │        │    │  ISO 14224 / KKS      │
  │  工程实务导向      │        │    │  分类逻辑一致导向      │
  └───────────────────┘        │    └──────────────────────┘
                               │
                    四维判定原则 + 编码锚点
                    (construct_guide.md 0.2.1)
```

## 专家角色

| 专家 | 模型 | 视角 | 评审侧重点 |
|------|------|------|-----------|
| DeepSeek | deepseek-v4-pro | 行业工程师 | 工程实务合理性、设备边界、现场可操作分类 |
| Kimi | kimi-k2.6 | 知识架构师 | 分类逻辑一致性、跨行业可复用性、知识检索效率 |
| Claude（主智能体） | — | 仲裁者 | 综合两方意见，基于判定原则做出最终裁决 |

## 使用流程

### 1. 初始化会话

```bash
cd src
python ai_expert_review/AI_Expert.py init --topic "光伏设备清单三AI专家评审"
```

### 2. 广播评审内容

```bash
# 从文件发送
python ai_expert_review/AI_Expert.py broadcast --file reviews/pv_main_equipment/评审prompt.md --output responses.md

# 直接消息
python ai_expert_review/AI_Expert.py broadcast --message "请审查..." --experts deepseek,kimi
```

### 3. 追问与交互

```bash
# 向指定专家追问
python ai_expert_review/AI_Expert.py chat --expert deepseek --message "你提到的第3点，能否展开？"

# 查看最新回复
python ai_expert_review/AI_Expert.py responses
```

### 4. 主智能体仲裁

Claude 主智能体读取两方回复，逐条裁决分歧，输出最终裁定。

### 5. 归档

- 专家会话记录 → `sessions/`（或对应的 `reviews/{sub_industry}_main_equipment/`）
- 评审报告 → `reviews/{sub_industry}_main_equipment/评审报告.md`

## 评审依据

1. **四维判定原则**（construct_guide.md 0.2.1）：服务对象、与能量转换核心的距离、故障的设备级影响、配置粒度
2. **编码锚点**（config.py SUB_INDUSTRY_CODING_ANCHORS）：各子行业对应的行业标准编码体系（KKS / RDS-PP / IEC 62548 / IEC 61850 等）
3. **三分类标准**：主设备 / 辅助设备 / 公用系统

## 评审历史

| 子行业 | 评审日期 | 评审对象 | 评分 | 关键产出 |
|--------|---------|---------|------|---------|
| 火电 | 2026-05 | 6项主设备 + 全清单 | — | 子设备拆分修正、主设备确认 |
| 水电 | 2026-05 | 7项主设备 + 全清单 | — | 主设备确认、边界划定 |
| 风电 | 2026-05 | 2项主设备 + 全清单 | — | 主设备确认 |
| 光伏 | 2026-05-14 / 05-29 | 全清单（两轮） | 7.0/10 | MLPE拆分、主变压器降级、边界修正 |
| 核电 | 2026-05 | 主设备清单 | — | — |
| 输电 | 2026-05 | 主设备清单 | — | — |
| 变电 | 2026-05 | 主设备清单 | — | — |
| 配电 | 2026-05 | 主设备清单 | — | — |
| 储能 | 2026-05 | 主设备清单 | — | 6项分歧（BMS/EMS、容器类等），全部裁定 |

> 详见 `reviews/设备分类工作进度汇报.md`

## 目录结构

```
ai_expert_review/
├── README.md                              # 本文件
├── AI_Expert.py                           # 多专家会话管理脚本
├── sessions/                              # 运行时会话状态（JSON）
│   ├── deepseek_session.json
│   └── kimi_session.json
├── reviews/                               # 已完成评审记录
│   ├── thermal_main_equipment/
│   ├── hydro_main_equipment/
│   ├── wind_main_equipment/
│   ├── pv_main_equipment/
│   ├── nuclear_main_equipment/
│   ├── distribution_main_equipment/
│   ├── energy_storage_main_equipment/
│   ├── substation_main_equipment/
│   ├── transmission_main_equipment/
│   └── 设备分类工作进度汇报.md
└── prompts/                               # 通用评审 prompt 模板
    └── equipment_review_template.md
```

## CLI 命令速查

| 命令 | 说明 |
|------|------|
| `list` | 列出可用专家及 API 配置状态 |
| `init --topic "..."` | 初始化会话，设定评审主题 |
| `broadcast -m "..."` | 向所有专家广播消息 |
| `broadcast -f file.md -o out.md` | 从文件广播并保存回复 |
| `chat -e deepseek -m "..."` | 与指定专家单独对话 |
| `history -e deepseek` | 查看专家完整对话历史 |
| `responses` | 查看所有专家最新一轮回复 |
| `reset -e deepseek` | 重置某位专家的会话 |
| `stats` | 查看 token 用量统计 |

## 典型评审 prompt 结构

评审 prompt 必须包含以下部分：

1. **背景**：子行业上下文、已有主设备列表
2. **四维判定原则**：完整的判定标准
3. **编码锚点**：该子行业对应的标准编码体系（KKS / RDS-PP / IEC 62548 等）
4. **⚠️ 待审查设备清单**：**从 `equipment_registry.md` 完整复制全部设备条目**（设备名称 + 设备类型 + 描述），这是评审的核心对象，缺此则评审无意义
5. **评审维度**：分类合理性 / 覆盖完整性 / 边界清晰性
6. **输出要求**：逐条意见 + 评分 + 修改建议

通用模板见 `prompts/equipment_review_template.md`。
