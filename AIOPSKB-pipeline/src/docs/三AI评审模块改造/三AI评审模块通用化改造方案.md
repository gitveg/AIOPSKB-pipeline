# 三AI评审模块通用化改造方案

> 目标：把现有「设备层」专用的三AI评审模块，改造成**层无关、可针对 设备 / 子设备 / 子系统 / 部件 / 零件 五个结构层**逐层评审的通用评审框架。
> 交付对象：执行此方案的 AI 工程师（GLM）。
> 模块位置：`src/ai_expert_review/`

---

## 0. 背景与现状

### 0.1 当前模块能力

`AI_Expert.py` 已是一套**层无关的多专家会话管理工具**：init / broadcast / chat / responses / stats / 仲裁，它本身不关心评审对象是什么——给什么 prompt 就广播什么。真正"绑死在设备层"的只有两处：

1. **专家角色** `EXPERT_PROFILES[*].default_role` 写死成了"设备分类专家"。
2. **只有一份 prompt 模板** `prompts/equipment_review_template.md`，绑定了"四维判定原则 + equipment_registry.md"。

当前流程是**半手动**：人把设备清单粘进模板 → `broadcast` → 收集回复 → Claude 主智能体仲裁。设备层一个子行业一份清单尚可手动；但结构层（子系统/部件/零件）是几百上千节点，手动不可行。

### 0.2 改造已锁定的四个决策

| # | 决策项 | 选定方案 |
|---|--------|---------|
| 1 | 自动化程度 | **全自动**：脚本从数据文件加载该层内容、自动拼 prompt、自动 broadcast |
| 2 | 评审范围/批次 | **先只评审主设备**，按"单个设备的整棵结构树"为一个评审单元 |
| 3 | 触发方式 | **保持独立 CLI 工具**，人工决定何时评审哪层，不嵌入 pipeline 自动跑 |
| 4 | 输出形态 | **结构化 JSON（标出问题节点+建议）+ markdown 报告**，人工据此执行修改，不自动改数据 |

### 0.3 边界

- 本次只覆盖 **5 个结构层**（设备/子设备/子系统/部件/零件），**不含故障层**——故障质量由 Judge + Kimi 标准核查那条线负责。
- 评审只产出意见，**不自动回写数据文件**；修改由人工/GLM 据报告执行。

---

## 1. 数据契约（自动加载的依据）

改造的核心是让脚本能按"层 + 目标"自动定位并读取数据。各层数据格式（已核实真实文件）：

| 层级 key | 数据文件路径（相对 `src/data/`） | 列结构 | 评审单元 |
|----------|-----------------------------|--------|---------|
| `equipment` | `{行业}/{子行业}/equipment_registry.md` | 设备名称 \| 设备类型 \| 描述 | 一个子行业的全部设备 |
| `sub_equipment` | `{行业}/{子行业}/{设备}/sub_equipment.md` | 子设备名称 \| 描述 | 一个设备的全部子设备 |
| `structure` | `{设备}/sub_system.md` + 各 `{子系统}/components.md` | 见下 | 一个设备的整棵结构树 |

> `structure` 是组合视图：
> - `sub_system.md`：子系统名称 \| 描述
> - 每个子系统目录下 `components.md`：部件 \| 零件 \| 描述 \| 易损标识 \| 维护方法 \| 报废方法

**关于"五层"与"三个评审命令"的关系**：部件、零件物理上同处 `components.md`，且粒度合理性必须放在整棵树里才能判断。因此：

- `equipment` / `sub_equipment` 各为独立评审单元。
- `subsystem` / `component` / `part` 三层合并为一次 **`structure`（结构树）评审**，喂入整棵树，但 prompt 内部由**三段针对性评审维度块**分别检视子系统、部件、零件。
- 同时保留 `--focus` 参数，允许只针对结构树里的某一层做聚焦评审（如 `--focus part`），此时只激活对应维度块、降低 token。

---

## 2. 代码改造

### 2.1 专家角色分层化

把 `default_role` 从"写死设备分类"改为**按层动态注入**。新增 `LAYER_EXPERT_ROLES`，结构为 `{layer: {expert_id: role}}`，在 `init` 时根据 `--layer` 选择对应角色；缺省回退到通用角色。

角色定位建议：

| 层 | DeepSeek 视角 | Kimi 视角 |
|----|--------------|-----------|
| equipment | 行业资深工程师（设备边界、主/辅/公用、现场配置） | 知识架构师（分类一致性、跨行业可复用、编码锚点） |
| sub_equipment | 行业工程师（市场主流机型/技术路线、存量占比） | 架构师（划分维度单一性、MECE） |
| structure（子系统/部件/零件） | **检修/可靠性工程师**（真实工程结构、可维护项粒度、备件） | 架构师（功能完备性、层级语义、失效独立性、粒度一致） |

### 2.2 新增 Loader（数据加载器）

新增 `loader.py`，职责：

- `resolve_paths(layer, target, subsystem=None)`：把 `--layer` + `--target`（如 `power/wind`、`power/thermal/condenser`）解析成具体数据文件路径。
- `load_layer_data(layer, target)`：读取并返回**结构化对象**（不是裸 markdown）：
  - `equipment` → `[{name, type, desc}]`
  - `sub_equipment` → `[{name, desc}]`
  - `structure` → `{subsystems: [{name, desc, components: [{part, piece, desc, wear, maintain, scrap}]}]}`
- 解析 markdown 表格为对象，便于 prompt 渲染、节点定位、JSON 比对。
- 校验：文件缺失/空表/列数不符时给出明确报错。

### 2.3 新增 Prompt Builder

新增 `prompt_builder.py`，职责：

- 维护 5 套**评审维度块**（见第 3 章），按 `layer`/`focus` 组装。
- `build_review_prompt(layer, target, data, anchors)`：拼装成完整 prompt，包含：
  1. 角色与任务声明
  2. 评审对象上下文（行业/设备名 + 编码锚点）
  3. **完整数据清单**（由 Loader 渲染，必须全量，缺此评审无意义）
  4. 该层针对性评审维度
  5. **结构化输出要求（JSON schema，见 4.1）**
- 编码锚点从 `config.py` 的 `SUB_INDUSTRY_CODING_ANCHORS` 取（已存在）。

### 2.4 新增 `review` 子命令（核心编排）

在 `AI_Expert.py` 新增 `review` 子命令，串起全自动流程：

```
python AI_Expert.py review --layer equipment      --target power/wind
python AI_Expert.py review --layer sub_equipment  --target power/wind/风电机组
python AI_Expert.py review --layer structure      --target power/thermal/condenser
python AI_Expert.py review --layer structure      --target power/thermal/condenser --focus part
```

流程：
1. Loader 加载数据 → 2. PromptBuilder 拼 prompt → 3. `init` 对应层角色会话（或复用）→ 4. `broadcast` 给 deepseek+kimi → 5. 解析两方 JSON → 6. 生成仲裁草稿 + 报告 → 7. 归档。

参数：`--experts`（默认 deepseek,kimi）、`--focus`（结构层聚焦 subsystem/component/part）、`--output`（报告路径，默认按归档规则）、`--round`（轮次，支持多轮追问）。

### 2.5 结构化输出解析

新增 JSON 解析与容错（参考 `standard_checker.py` 的 JSON 抽取做法）：从专家回复里提取 ```json 块；失败时降级保存原始 markdown 并告警。解析后做 schema 校验（4.1）。

### 2.6 仲裁与报告

主智能体（Claude）读取两方结构化 JSON：
- **共识项**（两方都标的问题）→ 高优先级，直接列入"需修改"。
- **分歧项**（仅一方标）→ 主智能体依判定原则裁决，给出采纳/驳回 + 理由。
- 输出 `评审报告.md`：总评分、需修改节点清单（按 severity 排序）、遗漏项、冗余项、分歧裁决。

> 仲裁保持人在环：主智能体生成裁决草稿，人工确认后据此改数据。不自动改库、不自动触发重生成。

---

## 3. 各层针对性评审 Prompt 设计

每套 prompt = 角色 + 上下文 + 数据清单 + **下列维度块** + 输出要求。以下是各层的维度块核心内容。

### 3.1 设备层（equipment）

沿用现有四维判定原则，维度块：

- **分类合理性**：主设备/辅助设备/公用系统三分类是否符合四维判定（服务对象 / 与能量转换核心的距离 / 故障的设备级影响 / 配置粒度）；有无"同构异类"。
- **覆盖完整性**：是否覆盖该子行业全部主要设备；对照编码锚点（KKS/RDS-PP/IEC 62548 等）与现场实际有无遗漏。
- **边界清晰性**：设备间边界是否清晰、有无重叠/重复、有无应合并或应拆分项。
- **编码锚点对照**：逐设备能否在对应标准编码体系中找到归属。

### 3.2 子设备层（sub_equipment）

子设备 = 同一设备的**技术路线/型式变体**（如风电机组：双馈/直驱/半直驱）。维度块：

- **划分维度单一性**：是否按同一个维度切分（如技术路线），严禁混维度（如把"技术路线"和"容量等级"混在一张表）。
- **MECE（互斥且穷尽）**：各子设备互不重叠、合并起来能覆盖该设备的主流型式。
- **存量与可维护性裁剪**：是否过度细分小众/试验性路线（市场份额极低的应合并或标注）；是否冗余；是否遗漏主流型式。**既不冗余、又覆盖全**是核心判据。
- **命名一致性**：命名规范、口径统一（含括号缩写如 DFIG/PMSG 的一致性）。

### 3.3 结构层（structure：子系统 / 部件 / 零件）

整棵树一次评审，内部分三段维度块。

#### 3.3.1 子系统维度块（subsystem）

- **功能完备性**：是否覆盖该设备所有主要功能链/能量流环节，无关键功能缺失。
- **划分逻辑一致**：是否统一按"功能/能量流"划分（不要一部分按功能、一部分按物理位置）。
- **粒度一致性**：各子系统粒度相当，不要一个特别庞大、一个特别琐碎。
- **边界清晰**：子系统间无功能重叠、无重复。
- **符合真实工程结构**：与该设备真实的系统划分一致（对照行业认知）。

#### 3.3.2 部件维度块（component）

- **拆解充分性**：是否拆到了合理的**可维护单元**粒度，不过粗（如不能把整台齿轮箱当一个部件不再拆）。
- **功能完备性**：覆盖所属子系统的全部关键部件，无遗漏。
- **失效独立性**：每个部件应是**独立的失效/维护单元**（独立失效模式、可独立检修/更换）。
- **粒度一致性**：同级部件粒度相当。
- **维护/报废挂载合理性**：维护方法、报废方法**应挂在部件层**且内容合理、可操作（这是部件层独有职责，子系统层和零件层不挂）。

#### 3.3.3 零件维度块（part）

- **聚焦易损/可更换件**：应聚焦易损件、可更换件、关键失效件；不罗列无运维意义的紧固件等（除非是关键易损）。
- **关键失效覆盖**：覆盖该部件下会导致部件功能丧失的关键零件。
- **不过度细分**：避免把不可独立更换、无独立失效意义的最小结构都列出。
- **归属正确**：每个零件挂在正确的父部件下。
- **易损标识合理性**：`易损标识` 列与零件实际属性一致。

---

## 4. 输出与落地

### 4.1 专家输出 JSON Schema

每位专家在回复末尾输出一个 ```json 块：

```json
{
  "layer": "structure",
  "target": "power/thermal/condenser",
  "focus": "all",
  "overall_score": 7.5,
  "verdict": "需修订",
  "issues": [
    {
      "level": "subsystem | component | part",
      "node": "节点名（如 冷却水流通与密封系统 / 水室 / 隔板）",
      "dimension": "粒度一致性 | 失效独立性 | ...",
      "severity": "致命 | 严重 | 一般",
      "problem": "问题描述",
      "suggestion": "具体修改建议"
    }
  ],
  "missing": [{"level": "...", "parent": "...", "name": "...", "reason": "..."}],
  "redundant": [{"level": "...", "node": "...", "reason": "..."}]
}
```

`verdict` 取值：`通过` / `需修订` / `需重做`。

### 4.2 报告与归档

- 归档目录沿用现有约定：`reviews/{target_slug}_{layer}/`
  - 例：`reviews/condenser_structure/`、`reviews/wind_equipment/`
- 目录内：`评审prompt.md`（实际下发的 prompt）、`responses_r{n}.json`（两方原始结构化回复）、`评审报告.md`（主智能体仲裁结论）。
- README 的"评审历史"表扩展一列"层级"，记录每次评审的层与评分。

---

## 5. 改造清单与优先级

| # | 任务 | 文件 | 优先级 |
|---|------|------|--------|
| 1 | `LAYER_EXPERT_ROLES` 分层角色 + `init` 按层注入 | `AI_Expert.py` | P0 |
| 2 | `loader.py`：路径解析 + markdown 表格→结构化对象 | 新增 | P0 |
| 3 | `prompt_builder.py`：5 套维度块 + 组装 | 新增 | P0 |
| 4 | `review` 子命令：全自动编排 | `AI_Expert.py` | P0 |
| 5 | 专家 JSON 输出解析 + schema 校验 + 容错 | `AI_Expert.py` / 新增 | P0 |
| 6 | 主智能体仲裁与 `评审报告.md` 生成 | 由 Claude 执行（提供报告模板） | P1 |
| 7 | 5 套 prompt 维度块落地为模板文件 | `prompts/{layer}_review.md` | P0 |
| 8 | 归档目录规则 + README 更新 | `reviews/` + `README.md` | P1 |
| 9 | `--focus` 聚焦单层评审 | `AI_Expert.py` / `prompt_builder.py` | P2 |

**建议执行顺序**：先做 P0（1→2→3→7→4→5）打通"全自动评审一个设备结构树"的主链路，用凝汽器（已是改造后结构）做端到端验证；再补 P1 仲裁/归档；最后 P2 聚焦评审。

---

## 6. 验证用例

打通后用以下用例做端到端验证：

1. `review --layer equipment --target power/wind` → 复现现有设备层评审能力（回归）。
2. `review --layer sub_equipment --target power/wind/风电机组` → 验证子设备瘦身评审（双馈/直驱主流 + 小众路线裁剪建议）。
3. `review --layer structure --target power/thermal/condenser` → 验证整棵结构树评审（5 子系统 + 各部件/零件），重点看是否能指出粒度不一致、维护方法挂载、零件过度细分等问题。
4. `review --layer structure --target power/thermal/condenser --focus part` → 验证聚焦单层。
