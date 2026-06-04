# AIOpsKB 知识库质量防御体系改进方案

> **文档版本**: v1.0
> **创建日期**: 2026-05-09
> **适用范围**: 工业设备智能运维知识库构建管道（pipeline）
> **目标**: 通过多层防御机制，系统性避免知识库生成过程中的结构性错误、行业知识错误和数据重复问题

---

## 一、背景与目标

### 1.1 当前痛点

在火电行业知识库试点构建过程中，发现了以下典型缺陷：

| 缺陷类型 | 具体案例 | 影响 |
|---------|---------|------|
| **子设备拆分错误** | 锅炉子设备罗列了22种分类维度（自然循环/立式/蒸汽等），而非技术路线 | 知识库层级混乱，无法指导实际工程 |
| **行业知识错误** | 大型汽轮发电机轴承被描述为滚动轴承，故障全是滚动轴承模式 | 严重误导现场工程师，丧失知识库可信度 |
| **部件层级归属错误** | 引风机、除尘器、凝汽器等独立设备被当作其他设备的"部件" | 破坏层级一致性，导致故障知识割裂 |
| **数据重复** | 过热器管故障文件中5种故障完全重复出现两次 | 浪费存储和token，降低数据质量 |
| **审查漏检** | Judge评分≥7但仍存在重大错误 | 现有审查维度不足以拦截全部问题 |

### 1.2 改进目标

构建**四层防御体系**：
1. **Prompt约束前置预防** — 在生成源头注入否定性约束和领域规则
2. **代码自动化快速拦截** — 零token成本的结构校验和去重
3. **LLM深度审查兜底** — 针对高风险领域知识进行专项守卫
4. **流程改造固化质量门** — 在pipeline关键节点嵌入不可逆检查

---

## 二、问题根因分析

```
┌─────────────────────────────────────────────────────────────┐
│  根因1: Collector缺乏否定性约束                               │
│  → 只告诉LLM"要写什么"，没告诉它"禁止写什么"                   │
│  → 结果: 把锅炉分类维度当作子设备、把独立设备当作部件           │
├─────────────────────────────────────────────────────────────┤
│  根因2: Judge只审"有没有"，不审"对不对"                       │
│  → 审查维度: 覆盖度、粒度、边界                               │
│  → 缺失维度: 行业知识正确性、层级归属、数据重复               │
├─────────────────────────────────────────────────────────────┤
│  根因3: 无自动化结构校验层                                    │
│  → 所有检查都依赖LLM Judge                                    │
│  → 结果: 高成本、慢反馈、漏检重复行                           │
├─────────────────────────────────────────────────────────────┤
│  根因4: 无领域知识注入机制                                    │
│  → 全靠LLM自身知识，无工程规则约束                            │
│  → 结果: 发电机轴承类型、锅炉拆分方式等专业知识错误           │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、总体架构改进

### 3.1 改造后的构建流程

```
┌─────────────────────────────────────────────────────────────┐
│  Phase A: 生成 (Collector)                                    │
│  └── Prompt增强: 否定约束 + 领域规则 + 自检指令               │
│       ↓                                                       │
│  Gate 1: 自动化结构校验 (StructValidator)                     │
│  └── 去重检查 / 层级冲突检测 / 领域规则关键词扫描 / 格式校验   │
│  └── 输出: 通过 或 {结构问题列表, 可自动修复项}               │
│       ↓                                                       │
│  Gate 2: 领域守卫审查 (DomainGuard)                           │
│  └── 针对高风险场景: 锅炉子设备、发电机轴承等                 │
│  └── 轻量LLM (flash模型), 专项规则审查                        │
│  └── 输出: pass / reject + 领域错误列表                       │
│       ↓                                                       │
│  Phase B: 质量审查 (Judge增强)                                │
│  └── 覆盖度 + 分类 + 粒度 + 边界 + 正确性 + 重复性            │
│  └── 输出: score + missing_items + issues + suggestions       │
│       ↓                                                       │
│  Gate 3: 自动化去重与修复 (Deduplicator)                      │
│  └── 代码层消除重复条目 / 保留最完整版本                      │
│       ↓                                                       │
│  Phase C: 整合 (Consolidation)                                │
│       ↓                                                       │
│  Gate 4: 终检 (StructValidator)                               │
│  └── 最终格式校验 + 去重确认                                  │
│       ↓                                                       │
│  Write to Disk                                                │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 新增/修改文件清单

| 文件路径 | 类型 | 说明 |
|---------|------|------|
| `src/pipeline/agents/struct_validator.py` | **新增** | 自动化结构校验模块 |
| `src/pipeline/agents/domain_guard.py` | **新增** | 领域知识守卫智能体 |
| `src/pipeline/agents/deduplicator.py` | **新增** | 去重与修复模块 |
| `src/pipeline/agents/collector.py` | **修改** | Prompt增加否定性约束和自检指令 |
| `src/pipeline/agents/judge.py` | **修改** | 增加正确性和重复性审查维度 |
| `src/pipeline/orchestrator.py` | **修改** | 插入四层质量门 |

---

## 四、模块详细设计

### 4.1 模块一：StructValidator（自动化结构校验）

**定位**: 纯代码实现，零token成本，在LLM审查之前快速拦截结构性错误。

**核心能力**:
- **去重检查**: 基于故障名称/部件名称检测重复行
- **层级冲突检测**: 检查components.md中是否有条目同时存在于equipment_registry.md
- **领域规则关键词扫描**: 扫描禁用关键词（如"滚动轴承"出现在发电机部件中）
- **格式校验**: 检查Markdown表格列数一致性

**领域规则库设计**:

```python
DOMAIN_RULES = {
    "generator_bearing_type": {
        "layer": "component",
        "equipment": "发电机",
        "rule": "大型汽轮发电机轴承必须是滑动轴承（轴瓦），禁止描述为滚动轴承。",
        "forbidden_keywords": ["滚动轴承", "滚道", "滚动体", "保持架", "SKF", "NTN"],
        "required_concepts": ["轴瓦", "乌金", "巴氏合金", "油膜"],
    },
    "boiler_sub_equipment": {
        "layer": "sub_equipment",
        "equipment": "锅炉",
        "rule": "子设备必须是具体技术路线（煤粉炉、CFB、余热锅炉），禁止罗列分类维度。",
        "forbidden_keywords": [
            "自然循环锅炉", "强制循环锅炉", "立式锅炉", "卧式锅炉",
            "蒸汽锅炉", "热水锅炉", "电站锅炉", "工业锅炉", "水管锅炉", "火管锅炉"
        ],
    },
}
```

**关键函数签名**:

```python
def validate(layer: str, context: dict, content: str,
             equip_registry: List[str] = None) -> Tuple[bool, List[str]]:
    """
    返回: (是否通过, 问题列表)
    问题格式: "行号: 具体问题描述"
    """
```

**校验触发时机**:
1. Collector每轮输出后 → 快速拦截，反馈给Collector修正
2. Consolidation输出后、写入磁盘前 → 终检确认

---

### 4.2 模块二：DomainGuard（领域知识守卫智能体）

**定位**: 轻量级LLM智能体（使用flash模型），针对**高风险领域知识**做专项审查。

**设计原则**:
- 不替代Judge，而是**前置过滤**：在Judge之前拦截明显的行业知识错误
- 仅对**已知高风险场景**触发，避免不必要的LLM调用
- 返回结构化JSON，便于Orchestrator决策

**当前覆盖的高风险场景**:

| 场景 | 触发条件 | 审查重点 |
|------|---------|---------|
| 锅炉子设备拆分 | `layer=sub_equipment` 且 `equipment=锅炉` | 禁止分类维度混入 |
| 发电机轴承部件 | `layer=component` 且 `equipment=发电机` 且 `component=轴承` | 必须是滑动轴承 |
| 发电机轴承故障 | `layer=fault` 且 `equipment=发电机` 且 `component=轴承` | 禁止滚动轴承故障模式 |

**扩展机制**:
随着构建推进，向 `domain_guard.py` 中持续添加新的 `_guard_xxx` 函数，覆盖更多高风险场景（如：变压器绝缘材料类型、汽轮机叶片材料等级等）。

**Prompt设计要点**:
- 明确给出"领域规则"和"错误示例"
- 要求LLM做"是/否"判断，而非模糊评价
- 输出严格JSON：`{"verdict": "pass/reject", "score": 1-10, "issues": [], "suggestions": []}`

---

### 4.3 模块三：Deduplicator（去重与修复模块）

**定位**: 纯代码实现，在Consolidation之前消除Collector多轮扩充产生的重复条目。

**策略**:
- **故障文件**: 基于"故障名称"去重，当名称相同时保留**内容更完整**的版本（非空单元格更多）
- **部件文件**: 基于"部件名称"去重，保留第一次出现的版本
- **设备/子行业文件**: 同理

**关键函数**:

```python
def deduplicate_faults(content: str) -> str:
    """基于故障名称去重，保留最完整版本"""

def deduplicate_components(content: str) -> str:
    """基于部件名称去重"""

def deduplicate_generic(content: str, key_col: int = 0,
                        header_names: tuple = ()) -> str:
    """通用去重函数"""
```

**触发时机**:
1. Collector每轮输出后（配合StructValidator的重复检测）
2. Consolidation输出后、写入磁盘前（终检去重）

---

### 4.4 模块四：Collector Prompt增强

**核心思路**: 增加**否定性约束**和**自检指令**，在生成源头预防错误。

#### 4.4.1 子设备层增强

在现有prompt末尾追加:

```
要求补充（必须遵守）:
11. 【关键约束】子设备必须是具体的技术路线或结构型式，禁止罗列设备的分类维度。
    以下禁止作为子设备:
    - 按循环方式: 自然循环锅炉、强制循环锅炉、直流锅炉
    - 按结构形式: 立式锅炉、卧式锅炉、水管锅炉、火管锅炉
    - 按输出介质: 蒸汽锅炉、热水锅炉、汽水两用锅炉
    - 按用途: 电站锅炉、工业锅炉
    - 其他维度: 超临界压力锅炉、导热油锅炉
    正确示例: 煤粉炉、循环流化床锅炉(CFB)、燃气锅炉、余热锅炉
12. 生成完成后请自检: 列表中是否混入了分类维度? 如果有, 请删除。
```

#### 4.4.2 部件层增强

```
要求补充（必须遵守）:
13. 【关键约束】部件必须是该设备的内部组成单元。禁止将独立设备列为该设备的部件。
    常见易混淆的独立设备包括: 引风机、送风机、除尘器、烟囱、除渣设备、凝汽器、给水泵。
    如果某装置在该子行业的设备清单(equipment_registry.md)中已是独立设备,
    则绝不应出现在本部件列表中。
14. 生成完成后请自检: 列表中的部件是否都是内部组成单元? 是否有独立设备混入? 如果有, 请删除。
```

#### 4.4.3 故障层增强

```
要求补充（必须遵守）:
11. 【关键约束】每个故障的机理描述必须符合该部件实际的工程原理, 禁止张冠李戴。
    高风险场景示例:
    - 大型汽轮发电机轴承是滑动轴承(轴瓦), 禁止出现滚动轴承故障模式
    - 大型泵组轴承通常是滑动轴承, 小型泵才可能是滚动轴承
12. 生成完成后请自检:
    a) 故障列表中是否有重复名称? 如果有, 请删除重复项。
    b) 机理描述是否张冠李戴? 如果有, 请修正。
```

---

### 4.5 模块五：Judge增强

在现有审查维度基础上，增加两个维度:

#### 故障层 (fault) 增加:

```
6. 行业知识正确性: 故障机理是否符合该部件实际的物理/化学/力学原理?
   是否存在张冠李戴(如将滚动轴承故障套用到滑动轴承)?
7. 数据重复性: 同一故障名称是否出现了多次?
```

#### 部件层 (component) 增加:

```
5. 层级归属正确性: 列表中的部件是否都是该设备的内部组成单元?
   是否存在将独立设备(如引风机、除尘器、凝汽器)错误归入的情况?
```

#### 子设备层 (sub_equipment) 增加:

```
6. 拆分合理性: 子设备是否为具体技术路线? 是否混入了分类维度?
   子设备之间是否为并列关系而非交叉包含关系?
```

---

## 五、Orchestrator 流程改造

### 5.1 改造点

在 `orchestrator.py` 的 `_run_layer` 方法中，按以下顺序插入质量门:

```
Collector输出
    ↓
[Gate 1] StructValidator 自动化校验
    ├── 通过 → 继续
    └── 未通过
        ├── 可自动修复(如重复) → Deduplicator自动修复 → 继续
        └── 不可自动修复 → 记录问题, 反馈给Collector
    ↓
[Gate 2] DomainGuard 领域守卫
    ├── pass (score≥8) → 继续
    └── reject → 将领域错误反馈给Collector, 本轮重做
    ↓
[Phase B] Judge 质量审查 (增强版)
    ├── 高分通过 → 跳过Consolidation
    └── 有缺失/问题 → 反馈Collector补充 或 进入Consolidation
    ↓
[Gate 3] Deduplicator 终检去重
    ↓
Consolidation
    ↓
[Gate 4] StructValidator 终检
    ↓
Write to Disk
```

### 5.2 关键代码逻辑

```python
# 1. 引入新模块
from agents.struct_validator import validate as struct_validate
from agents.domain_guard import guard_check
from agents.deduplicator import deduplicate_faults, deduplicate_components

# 2. Collector输出后: Gate 1 + Gate 2
result, _ = collect_layer(layer, context | {"existing": accumulated})

# Gate 1: 结构校验
equip_registry = self._read_equipment_list(sub_dir) if layer == "component" else []
passed, issues = struct_validate(layer, context, result, equip_registry)
if not passed:
    # 自动修复重复
    if layer == "fault":
        result = deduplicate_faults(result)
    # 将剩余问题反馈给Collector
    context["struct_issues"] = issues

# Gate 2: 领域守卫
guard_result = guard_check(layer, context, result)
if guard_result.get("verdict") == "reject":
    context["domain_errors"] = guard_result.get("issues", [])
    # 跳过Judge, 直接让Collector下一轮重做
    continue

# 3. Judge审查 (使用增强版prompt)
judge_result = judge_single(layer, context, result)

# 4. Consolidation前: Gate 3 去重
if layer == "fault":
    final = deduplicate_faults(final)
elif layer == "component":
    final = deduplicate_components(final)

# 5. 写入前: Gate 4 终检
passed, issues = struct_validate(layer, context, final, equip_registry)
if not passed:
    self.log(f"警告: 终检发现结构问题: {issues[:3]}...")
```

### 5.3 失败处理策略

| 场景 | 处理策略 |
|------|---------|
| StructValidator发现重复 | Deduplicator自动修复，不中断流程 |
| StructValidator发现层级冲突 | 记录问题，反馈给Collector，继续Judge |
| DomainGuard判定reject | 跳过Judge，将错误注入context，Collector下一轮重做 |
| Judge评分<7 | 常规处理：反馈missing_items，Collector补充 |
| 连续3轮未通过 | 保持现有终止机制：记录当前结果，向人类专家求助 |

---

## 六、实施优先级

| 优先级 | 模块 | 预计工作量 | 预期效果 | 实施建议 |
|--------|------|-----------|---------|---------|
| **P0** | **StructValidator** | 4小时 | 高 | 纯代码，零成本，立即解决重复和层级冲突 |
| **P0** | **Deduplicator** | 2小时 | 高 | 纯代码，配合StructValidator使用 |
| **P0** | **Collector Prompt增强** | 1小时 | 高 | 在源头预防分类维度混入、独立设备误归、机理张冠李戴 |
| **P1** | **DomainGuard** | 4小时 | 高 | 针对锅炉子设备、发电机轴承等高风险场景专项拦截 |
| **P1** | **Judge Prompt增强** | 1小时 | 中 | 让Judge也关注正确性和重复性 |
| **P2** | **Orchestrator流程改造** | 4小时 | 中 | 将上述模块串接到pipeline中，固化质量门 |
| **P3** | **领域规则库扩展** | 持续 | 中 | 随着构建推进，不断注入新的行业规则 |

### 建议的实施顺序

```
第1天: P0模块
  - 上午: 实现StructValidator + Deduplicator
  - 下午: 修改Collector Prompt
  - 测试: 用已有数据验证去重和层级检测效果

第2天: P1模块
  - 上午: 实现DomainGuard (先覆盖锅炉子设备、发电机轴承)
  - 下午: 修改Judge Prompt
  - 测试: 用历史错误数据验证拦截率

第3天: P2模块
  - 上午: 改造Orchestrator流程
  - 下午: 端到端测试整个pipeline
  - 晚上: 跑一轮火电行业数据，观察质量改善
```

---

## 七、关键设计原则

### 7.1 代码优先，LLM兜底

结构性问题（去重、层级冲突、格式检查）用代码解决，不要浪费LLM token。
只有涉及语义理解的问题（行业知识正确性、机理合理性）才使用LLM。

### 7.2 否定性约束比肯定性约束更有效

告诉Collector **"禁止做什么"** 比 **"请做好"** 更能防止错误。
因为LLM擅长生成内容，但不擅长自我审查生成内容的正确性。

### 7.3 分层审查，各尽其责

| 审查层 | 负责内容 | 成本 | 速度 |
|--------|---------|------|------|
| StructValidator | 重复、层级冲突、格式、关键词 | 零 | 毫秒级 |
| DomainGuard | 行业知识正确性（高风险场景） | 低(flash模型) | 秒级 |
| Judge | 覆盖度、分类、粒度、内容质量 | 高(主模型) | 秒级 |
| Deduplicator | 重复消除、版本选择 | 零 | 毫秒级 |

### 7.4 反馈闭环

Guard和Judge发现的问题必须**反馈给Collector的context**，让下一轮生成时带着修正指令，而不是简单打回重做。

```
Collector(Context) → 生成结果
    ↓
Guard发现问题: "发电机轴承不能是滚动轴承"
    ↓
Context += {domain_errors: ["必须是滑动轴承(轴瓦)"]}
    ↓
Collector(Context+错误反馈) → 修正后的结果
```

### 7.5 渐进式规则积累

`DOMAIN_RULES` 和 `DomainGuard` 不是一次性完善的。随着构建推进：
1. 每发现一个行业知识错误，就抽象成一条规则加入 `DOMAIN_RULES`
2. 每发现一个高风险场景，就增加一个 `_guard_xxx` 函数
3. 最终形成覆盖全行业的知识约束库

---

## 八、附录：与现有系统的兼容性

### 8.1 向后兼容

- 所有新增模块都是**可插拔**的，如果某个模块故障，可以跳过该质量门继续运行
- `StructValidator` 和 `Deduplicator` 不依赖外部API，不会因网络问题阻塞pipeline
- `DomainGuard` 使用现有的 `call_llm` 接口和 `AGENT_MODELS` 配置

### 8.2 配置项建议

建议在 `config.py` 中增加以下开关:

```python
# 质量门开关
ENABLE_STRUCT_VALIDATOR = True   # 自动化结构校验
ENABLE_DOMAIN_GUARD = True       # 领域守卫
ENABLE_DEDUPLICATOR = True       # 自动去重

# DomainGuard触发阈值
DOMAIN_GUARD_MIN_SCORE = 7       # 低于此分数则reject
```

---

> **文档结束**。本方案为可落地的工程化改进设计，所有模块均可直接融入现有pipeline代码库。
