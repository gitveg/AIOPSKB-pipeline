# 三AI专家评审模块

> 工业设备智能运维知识库的**层无关多AI评审系统**
> 支持设备 / 子设备 / 子系统-部件-零件（结构树）三个评审层级
> 详见：`construct_guide.md` 0.2.1 节（判定原则）和 2.1-2.7 节（智能体角色）

---

## 架构

```
                    ┌──────────────────────────────────────┐
                    │       review 全自动评审命令             │
                    │   Loader → PromptBuilder → Debate     │
                    │         → ResponseParser → Report     │
                    └──────────┬───────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                │                ▼
  ┌───────────────────┐        │    ┌──────────────────────┐
  │  DeepSeek 专家     │        │    │    Kimi 专家          │
  │  deepseek-v4-pro  │        │    │    kimi-k2.6          │
  │                   │  多轮辩论  │    │                       │
  │  角色按层动态注入    │◄──────►│    │  角色按层动态注入       │
  └───────────────────┘        │    └──────────────────────┘
                               │
                    ┌──────────┴───────────┐
                    │  人工仲裁 / Claude     │
                    │  基于报告裁定分歧       │
                    └──────────────────────┘
```

## 评审层级与专家角色

| 评审层级 | layer 参数 | DeepSeek 角色 | Kimi 角色 | 评审单元 |
|----------|-----------|--------------|-----------|---------|
| 设备清单 | `equipment` | 行业资深工程师（设备边界、主/辅/公用） | 知识架构师（分类一致性、编码锚点） | 一个子行业的全部设备 |
| 子设备清单 | `sub_equipment` | 行业工程师（市场主流机型、技术路线） | 架构师（维度单一性、MECE） | 一个设备的全部子设备 |
| 结构树 | `structure` | 检修/可靠性工程师（可维护项粒度、备件） | 架构师（功能完备性、粒度一致） | 一个设备的整棵结构树 |

> 结构树评审合并了子系统/部件/零件三层，整棵树一次评审。可通过 `--focus` 聚焦单层。

## 快速开始

### 全自动评审（推荐）

```bash
# 设备层评审
python AI_Expert.py review --layer equipment --sub 火电

# 子设备层评审（锅炉有子设备）
python AI_Expert.py review --layer sub_equipment --sub 火电 --equip 锅炉

# 结构树评审（凝汽器，v3.0格式）
python AI_Expert.py review --layer structure --sub 火电 --equip 凝汽器

# 结构树聚焦零件层
python AI_Expert.py review --layer structure --sub 火电 --equip 凝汽器 --focus part --rounds 1
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--layer` | 评审层级（equipment/sub_equipment/structure） | 必填 |
| `--industry` | 行业名称 | 电力 |
| `--sub` | 子行业名称（如 火电） | 必填 |
| `--equip` | 设备名称（sub_equipment/structure 层必填） | — |
| `--focus` | structure 层聚焦模式（all/subsystem/component/part） | all |
| `--rounds` | 最大辩论轮次 | 3 |
| `--temperature` | LLM temperature | 0.3 |
| `--output-dir` | 报告输出目录 | 自动生成 |

### 输出文件

每次评审输出到 `reviews/{设备}_{layer}/`：

```
reviews/condenser_structure/
├── 评审报告.md              # 四段式报告（背景/专家意见/裁定/变更建议）
├── deepseek_response.json   # DeepSeek 最终结构化回复
├── kimi_response.json       # Kimi 最终结构化回复
└── debate_log.json          # 多轮辩论 token 记录
```

## 多轮辩论机制

1. **Round 1**：两位专家独立审查相同数据，各自输出结构化 JSON
2. **Round 2+**：每位专家看到**对方上一轮回复**（不看仲裁），可修正或坚持
3. **提前终止**：两方均判定"通过"，或评分趋同且判定一致时提前结束
4. **仲裁**：全部轮次结束后，人工/Claude 基于报告裁定分歧（不自动改数据）

## 专家 JSON 输出 Schema

每位专家输出：

```json
{
  "layer": "structure",
  "overall_score": 7.5,
  "verdict": "通过|需修订|需重做",
  "issues": [
    {"level": "component", "node": "...", "dimension": "...",
     "severity": "致命|严重|一般", "problem": "...", "suggestion": "..."}
  ],
  "missing": [{"level": "...", "parent": "...", "name": "...", "reason": "..."}],
  "redundant": [{"level": "...", "node": "...", "reason": "..."}]
}
```

## 各层评审维度

### 设备层（equipment）
- 分类合理性：主设备/辅助设备/公用系统三分类
- 覆盖完整性：对照编码锚点与现场实际
- 边界清晰性：设备间无重叠
- 编码锚点对照

### 子设备层（sub_equipment）
- 划分维度单一性：严禁混维度
- MECE：互斥且穷尽
- 存量与可维护性裁剪
- 命名一致性

### 结构树（structure）

**子系统维度**：功能完备性 / 划分逻辑一致 / 粒度一致性 / 边界清晰 / 符合真实工程结构

**部件维度**：拆解充分性 / 功能完备性 / 失效独立性 / 粒度一致性 / 维护报废挂载合理性

**零件维度**：聚焦易损可更换件 / 关键失效覆盖 / 不过度细分 / 归属正确 / 易损标识合理性

## 手动模式命令（保留）

旧的手动流程仍然可用：

```bash
# 初始化（支持 --layer 自动选择角色）
python AI_Expert.py init --topic "..." --layer equipment

# 广播消息
python AI_Expert.py broadcast -f prompt.md -o responses.md

# 追问
python AI_Expert.py chat -e deepseek -m "..."

# 其他命令
python AI_Expert.py list          # 专家状态
python AI_Expert.py responses     # 最新回复
python AI_Expert.py history -e deepseek  # 完整历史
python AI_Expert.py stats         # token 统计
python AI_Expert.py reset -e deepseek    # 重置会话
```

## 评审历史

| 子行业 | 评审日期 | 评审层级 | 评审对象 | 关键产出 |
|--------|---------|---------|---------|---------|
| 火电 | 2026-05 | equipment | 6项主设备 + 全清单 | 子设备拆分修正、主设备确认 |
| 水电 | 2026-05 | equipment | 7项主设备 + 全清单 | 主设备确认、边界划定 |
| 风电 | 2026-05 | equipment | 2项主设备 + 全清单 | 主设备确认 |
| 光伏 | 2026-05 | equipment | 全清单（两轮） | MLPE拆分、主变压器降级 |
| 核电 | 2026-05 | equipment | 主设备清单 | — |
| 输电 | 2026-05 | equipment | 主设备清单 | — |
| 变电 | 2026-05 | equipment | 主设备清单 | — |
| 配电 | 2026-05 | equipment | 主设备清单 | — |
| 储能 | 2026-05 | equipment | 主设备清单 | 6项分歧全部裁定 |

> 详见 `reviews/设备分类工作进度汇报.md`

## 目录结构

```
ai_expert_review/
├── README.md                              # 本文件
├── AI_Expert.py                           # 主脚本（含 review 命令 + run_debate）
├── loader.py                              # 数据加载器（路径解析 + markdown 解析）
├── prompt_builder.py                      # prompt 组装器（按层 + 按角色）
├── response_parser.py                     # JSON 提取 + schema 校验
├── report_generator.py                    # 评审报告生成器
├── sessions/                              # 运行时会话状态（JSON）
├── reviews/                               # 评审记录与报告
│   ├── thermal_main_equipment/
│   ├── ...（9个子行业）
│   └── 设备分类工作进度汇报.md
└── prompts/                               # 评审 prompt 模板
    ├── equipment_review_template.md       # 旧模板（参考）
    ├── equipment_review.md                # 设备层 prompt
    ├── sub_equipment_review.md            # 子设备层 prompt
    ├── structure_review.md                # 结构层 prompt
    └── debate_round.md                    # 辩论续轮模板
```

## CLI 命令速查

| 命令 | 说明 |
|------|------|
| `review --layer ... --sub ...` | **全自动评审**（数据加载→prompt→辩论→报告） |
| `init --topic "..." [--layer ...]` | 初始化会话（可选按层注入角色） |
| `broadcast -m "..."` | 向所有专家广播消息 |
| `chat -e deepseek -m "..."` | 与指定专家单独对话 |
| `history -e deepseek` | 查看专家完整对话历史 |
| `responses` | 查看所有专家最新一轮回复 |
| `list` | 列出可用专家及 API 配置状态 |
| `stats` | 查看 token 用量统计 |
| `reset -e deepseek` | 重置某位专家的会话 |

## 典型评审 prompt 结构

评审 prompt 由 `prompt_builder.py` 自动组装，包含：

1. **角色声明**：从 `LAYER_EXPERT_ROLES` 按层按专家动态注入
2. **评审依据**：四维判定原则 / MECE / 功能分解标准（按层选择）
3. **编码锚点**：该子行业对应的标准编码体系
4. **完整数据清单**：由 `loader.py` 自动加载并渲染为 markdown 表格
5. **评审维度**：按层选择对应维度块
6. **JSON 输出要求**：结构化 schema 定义
7. **辩论续轮**（Round 2+）：对方上轮回复 + 修正指令
