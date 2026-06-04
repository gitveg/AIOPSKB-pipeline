# Pipeline 审查与优化建议

> **作者**: Claude（AI 工程师 + 工业运维视角）
> **日期**: 2026-05-19
> **审查范围**: `src/pipeline/` 全部源码 + `src/scripts/validate_kb.py`
> **版本基线**: construct_guide v2.3，orchestrator 1003 行
>
> 本文不描述系统功能（详见 construct_guide），只给出**可操作的问题定位和改进建议**。问题按优先级排列，P0 = 会导致静默错误或数据损坏，P1 = 严重影响输出质量，P2 = 工程债务，P3 = 优化建议。

---

## 一、代码逻辑 Bug（P0，必须修复）

### 1.1 `_run_layer` 中的 `accumulated` 是多段原始表格拼接，不是合并表

**位置**: `orchestrator.py` L842

```python
accumulated += "\n\n" + result if accumulated else result
```

每轮 `collect_layer` 返回的是一张完整的 Markdown 表（含表头）。两轮拼接后，`accumulated` 变成：

```
| 故障名称 | D1 故障类别 | ... |
|---|---|...|
| 爆管 | 热 | ... |

| 故障名称 | D1 故障类别 | ... |   ← 第二个表头
|---|---|...|
| 腐蚀 | 化学 | ... |
```

Judge 收到的是这份格式混乱的数据，而 `_consolidate` 也在这份数据上执行"去重整合"。这会导致：
- Judge 无法按正常表格结构审查，评分失真
- Consolidation 可能输出双表头或跳过部分行

**修复方案**：扩充阶段每轮只收集**数据行**，不含表头；或第2轮起用 `existing` 把前一轮结果作为增量基底传入，让 LLM 在原表基础上追加（当前 fault 层已支持 `{existing_note}`，但 accumulated 的组织方式没有配合）。最简单的修复：整合阶段前，用 `_parse_*_table` 对 accumulated 去重后重建单一表格再提交 Judge。

---

### 1.2 `round_num > max_judge_rounds` 检查永远为 False

**位置**: `orchestrator.py` L845

```python
max_judge_rounds = 2
for i in range(2):          # i = 0, 1
    round_num += 1          # round_num = 1, 2
    ...
    if round_num > max_judge_rounds:   # 1>2? No. 2>2? No. ← 永远不触发
        break
```

注释说"已达 Judge 上限则跳过 Judge"，但 `>` 应改为 `>=`。当前等价于"每轮都执行 Judge"，含义虽然不错，但逻辑意图与代码不符，且如果将来有人改 `max_judge_rounds = 1` 或 `range(3)` 会产生意外行为。

**修复**：改为 `if round_num >= max_judge_rounds:` 并加注释说明语义。

---

### 1.3 `_rebuild_component_table` 中的 `is_leaf` 计算完全错误且从未使用

**位置**: `orchestrator.py` L649

```python
parent_cell = inner[1].strip() if len(inner) > 1 else ""
is_leaf = parent_cell and parent_cell not in ("—", "-", "")
# 注释: "Actually: leaf = name is NOT a parent of anyone else"
```

这段代码：
1. 把"有父部件的节点"误判为叶节点（逻辑反转）
2. 计算出的 `is_leaf` 变量在后续代码中**从未被使用**——函数直接信任 LLM 输出的 `maint_val/disposal_val`

这是写到一半的死代码，加上错误的注释，容易让后续维护者误信。**修复**：删除 L649-651 的 `is_leaf` 计算，或改为正确逻辑（通过 `_parse_component_table` 已有的 `is_leaf` 字段）。

---

### 1.4 故障 Prompt 中列数描述与实际格式矛盾

**位置**: `collector.py` L247 & L253-254

```
7. 输出严格为Markdown表格，9列
...
输出格式（严格9列，第一列必须是"故障名称"）：
| 故障名称 | D1 故障类别 | D2 故障等级 | D3 ... | D4 ... | D5 ... | D6 ... | D7 ... | D8 ... | D9 预防措施 |
```

实际列数是 **10 列**（故障名称 + D1-D9）。LLM 按 10 列输出没有问题，但"9列"的限定描述会让部分模型产生困惑（有时会省略最后一列）。`_consolidate` 里 `format_rules["fault"]` 同样写的是"9列"。

**修复**：将所有"9列"改为"10列（含故障名称）"，或改为"D1-D9共9个知识维度，加故障名称共10列"。

---

## 二、质量控制缺口（P1，严重影响输出质量）

### 2.1 `validate_kb.py` 与 pipeline 完全脱钩

`construct_guide` 章节3明确要求"每次生成新数据后、主智能体验证前调用校验脚本"，但 `orchestrator.py` 的阶段2/3/4执行完后**从不调用** `validate_kb.py`。当前该脚本只能手动运行，意味着格式错误、孤立节点等问题会无声地进入下一阶段。

**修复**：在 `run_component` 和 `run_fault` 中的 `write_kb_file` 之后，调用 `subprocess` 或直接 import 调用 `validate_stage3/4`，若返回错误则打印警告（不一定阻断，但必须记录日志）。

---

### 2.2 `run_validate`（阶段5）未实现

**位置**: `orchestrator.py` L427-430

```python
def run_validate(self, sub_filter: str = None):
    self.log(f"===== 阶段5: 验证 - {self.industry} =====")
    self.log("  (待实现)")
```

这是 construct_guide 中阶段5的核心：可用性测试 + 交叉索引构建。不实现就意味着知识库永远无法通过"最终质量门控"，无法得到行业完成标记。

**最小可行实现**（不需要完整可用性智能体）：
1. 调用 `validate_kb.py --target {行业目录}` 并汇总报告
2. 统计设备/部件/故障覆盖率（`track_progress.py` 已有基础）
3. 将结果写入 `reports/{行业}/final_validation.md`

完整可用性测试可以后续迭代，但阶段5空实现会让 pipeline 的流程闭环失效。

---

### 2.3 搜索结果对中文工业标准覆盖不足

**位置**: `collector.py` `_build_queries()`

当前所有搜索查询均为**英文**：
```python
f"{sub_en} main equipment list primary secondary auxiliary"
```

中国电力、石化行业的技术文档、故障案例、设备手册主要发布在中文网站和标准数据库（国家标准全文公开系统、DL/T 系列、GB/T 系列）。英文搜索对这些内容覆盖极弱，会导致：
- 阈值参数（D5）缺乏国标依据，更多是 LLM 凭记忆生成
- 故障案例缺乏真实事故数据支撑
- 设备型号与中国市场主流型号脱节

**建议**：每层搜索增加1-2条中文查询，例如：
```python
# fault 层增加
f"{equip}{comp} 故障诊断 DL GB 标准",
f"{equip}{comp} 常见故障 检修方法 电力行业",
```

同时考虑将 `MAX_SNIPPET_LENGTH` 从 300 适当提高到 500-600，避免技术数值被截断。

---

### 2.4 Judge 对故障层的 Prompt 缺乏 Schema 锚定

**位置**: `judge.py` L46-60

Judge 系统 Prompt 只有一句"你是工业设备知识库审查专家"，故障层审查 Prompt 里没有给出 D1-D9 的定义和 D2 的判定标准。这意味着：
- Judge 不知道 D5 和 D6 的区别，D5/D6 混填问题可能被放过
- D2 等级的判定没有统一基准，同一个故障在不同批次可能得到不同等级
- Judge 打分更多依赖 LLM 自身的工业知识，而非知识库的 Schema 要求

**建议**：在故障层 Judge Prompt 开头追加 D1-D9 Schema 说明（可以精简为 3-5 行的约束），以及 D2 等级判定标准（已在 construct_guide v2.3 定义）。Judge 的审查标准应该"锚定在本知识库的 Schema 上"，而不是泛化的行业标准。

---

### 2.5 故障层搜索查询缺少子行业上下文

**位置**: `collector.py` L136-143

```python
target = f"{equip_en} {comp_en}" if comp_en else equip_en
return [
    f"{target} common failure modes fault types characteristics",
    ...
]
```

锅炉（火电）的水冷壁和余热锅炉（燃气）的水冷壁，故障机理差异很大，但搜索时两者都用 `"water wall tube common failure modes"`。子行业语境丢失会让搜索结果混杂来自不同应用场景的内容。

**建议**：`target` 拼上 `sub_en`：
```python
target = f"{sub_en} {equip_en} {comp_en}".strip()
```

---

## 三、系统架构问题（P2，工程债务）

### 3.1 Orchestrator 是 1003 行的上帝类

`orchestrator.py` 混合了：磁盘 I/O、Markdown 解析、LLM 调用、业务流程控制、Schema 迁移、遗留代码清理，所有逻辑都在一个类里。这导致：
- 单个方法（如 `run_schema_migrate`）超 150 行
- 依赖关系隐式（`_consolidate` 内部 import `call_llm`）
- 难以独立测试任何一个功能

**建议拆分方向**（不要求立刻重构，但新增功能时按此方向扩展）：
```
Orchestrator（只做流程编排）
├── MarkdownParser（parse_md_table / parse_component_table 等）
├── KnowledgeStore（read/write KB files，路径解析）
└── QualityGate（调 validate_kb + Judge，统一质量门控入口）
```

---

### 3.2 遗留代码占据主类，干扰理解

以下方法/特性应归档或删除：

| 遗留内容 | 位置 | 建议 |
|---------|------|------|
| `run_fault_enrich` | orchestrator L289 | 注释已说明"D14/D15已移除"，整个方法可删除或移入 `_archive/` |
| `run_schema_migrate` | orchestrator L434 | 历史迁移工具，已无新数据需迁移，移入 `scripts/` |
| `_strip_d10_from_fault` | orchestrator L656 | 同上，D10 已废弃 |
| `"fault_enrich"/"schema_migrate"` | main.py PHASES | 从 CLI choices 移除或标记为 hidden |
| `key_map` 里的 D8_根本/D10_临时/D11-D15 | orchestrator L722-726 | 旧 schema 映射，会误导未来维护者 |
| `file_manager.get_*_dir` | file_manager.py | 三函数未被引用，删除 |
| `schemas.validate_fault_entry` | schemas.py | 从未调用，接入 validate_kb 或删除 |
| `hashlib` import | orchestrator.py L4 | 未使用 |
| `re` import | search.py L2 | 未使用 |

---

### 3.3 `base.py` 无重试机制，API 错误直接崩溃

**位置**: `agents/base.py` L14-25

单次 LLM 调用失败会抛出未捕获异常，终止整个阶段的执行。故障层一次运行可能调用数百次 LLM，网络抖动或速率限制会让整个阶段白跑。

**建议**：加指数退避重试（2-3次），失败后记录到日志并继续下一个部件（不要中断整个阶段）：
```python
for attempt in range(3):
    try:
        return resp.choices[0].message.content
    except Exception as e:
        if attempt == 2: raise
        time.sleep(2 ** attempt)
```

---

### 3.4 `max_tokens=8192` 对故障层可能不足

**位置**: `agents/base.py` L20

一个复杂部件（如汽轮机叶片）可能有 15+ 个故障，每个故障的 D3-D8 都是长文本，完整 10 列表格轻易超过 8192 token。截断会产生格式损坏的最后一行，但不会报错——`parse_fault_table` 会因列数不匹配跳过它（`L706: if len(cells) != len(headers): continue`），导致数据无声丢失。

**建议**：故障层调用时设 `max_tokens=16384`；或在 `collect_layer` 里按部件复杂度动态决定（复杂主设备部件用 16384，简单辅机部件用 8192）。

---

### 3.5 `validate_kb.py` 的故障层表头校验有隐患

**位置**: `validate_kb.py` L45 & L165-169

Schema 定义：
```python
"fault": ["故障名称", "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
```

实际表头是 `"D1 故障类别"`，校验逻辑用 `startswith("D1")` 通过——目前侥幸正确。但 `FAULT_REQUIRED_COLS` 里写的是 `"D1_故障类别"`（下划线），与实际表头（空格）完全不匹配，这个变量**定义了但从未被引用**。

更严重的问题：`check_required_fields_fault` 用位置（`row[1]` 到 `row[9]`）而非列名检查 D1-D9 是否为空。如果 LLM 偶尔多输出一列（曾发生过），位置偏移后会把 D1 值错误地映射到 D2 空检查。

**建议**：`check_required_fields_fault` 改为按列名索引（先找 header 中 "D1" "D2"... 的位置，再按该位置查 row 值）。

---

## 四、Prompt 质量优化（P3）

### 4.1 整合 Prompt 丢失了层级语境

**位置**: `orchestrator.py` `_consolidate()` L925

```python
prompt = f"""请对以下{layer}层级的调研数据进行整合精炼：
```

`layer` 变量是英文字符串 `"fault"`，对 LLM 而言不如直接用中文`"故障知识"`。另外，整合 Prompt 没有传入行业/子行业/设备名称——LLM 在整合时不知道当前是在处理哪台设备的故障，容易把通用设备的整合规则应用到专有场景（如把核反应堆压力容器的故障与通用压力容器混淆）。

**建议**：
```python
layer_cn = {"sub_industry": "子行业划分", "equipment": "设备清单",
            "component": "部件拆解", "fault": "故障知识"}.get(layer, layer)
context_str = f"行业:{context.get('industry')} 子行业:{context.get('sub_industry')} 设备:{context.get('equipment')}"
prompt = f"""请对【{context_str}】的{layer_cn}调研数据进行整合精炼：...
```

---

### 4.2 子行业种子模式下的 LLM 调用意义不大

**位置**: `orchestrator.py` `_build_sub_industry_index()` L892-909

当 `seed_subs` 已提供时（电力行业），系统调用 LLM "评估是否有遗漏并补充"，但这个调用：
- 没有任何搜索数据支撑，纯靠 LLM 记忆
- Prompt 说"尊重用户提供的，不要删除"，实际上 LLM 很难在这个约束下有意义地增补
- 输出结果直接写入 `index.md`，等于绕过了整个 `_run_layer` 的扩充/Judge/整合流程

**建议**：如果 `seed_subs` 质量可信（如用户自己提供），直接生成 index.md 的结构化表格（仅调 LLM 补描述），不需要让 LLM 判断"是否遗漏"。或者，至少补一次搜索验证，再让 Judge 做一轮完整审查。

---

### 4.3 部件层 Prompt 未体现子行业/子设备语境

**位置**: `collector.py` L212-232

```python
f"""请对【{equip}】进行部件拆解调研。"""
```

如果同一设备有子设备（如锅炉→煤粉炉），部件调研应该是针对"煤粉炉"的部件，而不是泛化的"锅炉"。但 Prompt 只传了 `equip`（"锅炉"），没有传子设备名。同理，"核电-蒸汽发生器"和"火电-余热锅炉"的换热管部件调研方向完全不同，但 Prompt 的搜索查询对两者相同。

**建议**：在 `context` 里增加 `sub_equipment` 字段的传递，并在 component layer 的 prompt 和搜索查询里体现：
```python
target = f"{ctx.get('sub_equipment', '')} {equip}".strip()
```

---

## 五、工业运维专业视角的补充建议

以下建议来自工业 O&M 场景的实际需求，不直接对应代码 bug，但影响知识库最终可用性。

### 5.1 故障层搜索策略应区分"高频故障"与"全面覆盖"

当前搜索查询偏向广泛覆盖（`common failure modes`），对于关键主设备（锅炉、汽轮机、变压器），漏掉任何一类故障的成本很高。建议为主设备部件增加一条定向查询，针对已知高危故障模式：
```python
# 对主设备叶节点部件，增加
f"{comp_en} catastrophic failure accident case study power plant"
f"{comp_en} FMEA failure mode effects analysis"
```

### 5.2 D5 阈值的来源标注应在生成时结构化，而不是嵌入文本

当前要求在 D3 末尾用括号注明来源（`（来源：DL/T 722）`）。对于 D5 中的每个阈值参数，来源同样重要但没有强制要求。实际 D5 中已有大量无来源的阈值（如 `[物理]振动速度>7.1mm/s`，来自 ISO 10816 还是 DL/T 501 没有区分）。

建议在 D5 的 Prompt 里加一行：`每个阈值参数标注来源标准，如[物理]振动速度>7.1mm/s（ISO 10816-3）`，并让 Judge 的故障审查标准里加一项"D5阈值来源可验证性"。

### 5.3 长运行任务需要进度持久化

当前 pipeline 没有运行状态文件。如果在处理第 60 个部件时崩溃，重启只能靠"已有文件则跳过"的增量逻辑。但如果崩溃发生在文件写入一半时（如 `write_kb_file` 中途断电），可能留下空文件或截断文件，下次运行会跳过（"已有数据"），导致这个部件的故障知识永远为空。

**建议**：用临时文件写入后 rename 替换（原子写入），防止截断问题：
```python
def write_kb_file(filepath, content):
    tmp = filepath + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, filepath)  # 原子替换
```

---

## 六、优先级汇总

| 优先级 | 问题 | 影响 | 工作量 |
|--------|------|------|--------|
| **P0** | `accumulated` 拼接多个表头 | 数据损坏，Judge 失真 | 小（修改积累逻辑） |
| **P0** | 故障列数描述"9列"应为"10列" | LLM 偶尔省列 | 极小 |
| **P0** | `is_leaf` 逻辑反转且未使用 | 当前静默，未来维护风险 | 极小 |
| **P1** | `validate_kb` 未集成到 pipeline | 格式错误静默入库 | 中 |
| **P1** | `run_validate` 空实现 | 无质量门控闭环 | 大 |
| **P1** | 搜索全英文，中文标准覆盖不足 | 阈值来源不可靠 | 小 |
| **P1** | Judge Prompt 缺 Schema 锚定 | 审查维度不一致 | 小 |
| **P1** | 无重试机制，API 失败崩溃全阶段 | 长任务风险高 | 小 |
| **P1** | `max_tokens=8192` 故障层可能截断 | 无声数据丢失 | 极小 |
| **P2** | 遗留代码（fault_enrich/schema_migrate/D10-D15 keymap） | 维护混乱 | 小 |
| **P2** | Orchestrator 上帝类 | 可测试性差 | 大（渐进重构） |
| **P2** | 原子写文件防截断 | 断电/崩溃保护 | 极小 |
| **P3** | 整合 Prompt 丢失上下文 | 整合质量略降 | 极小 |
| **P3** | 部件层 Prompt 缺子设备语境 | 专用设备部件调研偏差 | 小 |
| **P3** | D5 阈值来源结构化标注 | 知识可信度 | 小 |

---

> **总结**：pipeline 的主干流程（扩充→Judge→整合→写盘→增量跳过）是合理的，阶段1-4 的基本功能可以工作。当前最大的风险是两类：一是**无声的数据损坏**（accumulated 拼接多表头、8192 token 截断、增量跳过截断文件）；二是**质量门控失效**（validate_kb 与 pipeline 脱钩、阶段5空实现）。修复 P0 和 P1 问题后，pipeline 的输出可靠性会显著提升。

---

## 七、用户补充需求（2026-05-19）

### 7.1 故障生成范围扩展：从"仅叶节点"到"全部部件"

**来源**: 用户决策（经主智能体分析后确认）

**问题**: 当前 pipeline 仅对 components.md 中的**叶节点部件**（没有子部件的部件）生成故障文件。但父部件存在无法由单一子部件故障解释的**整体宏观故障**：

| 父部件 | 叶节点无法覆盖的故障示例 |
|--------|----------------------|
| 反应堆压力容器筒体 | 筒体整体辐照脆化（RTNDT升高）、内壁堆焊层剥离、法兰密封面腐蚀 |
| 容器顶盖 | 顶盖整体热变形导致密封失效 |
| 蒸汽发生器 | 一回路向二回路系统级泄漏（管束+管板综合失效） |
| 堆芯吊篮组件 | 吊篮整体下沉/倾斜导致堆芯几何畸变 |

**决策**: 故障生成扩展到所有部件（叶节点+父节点）。叶节点优先处理，父节点在后。对于有子部件的父节点，prompt 约束 LLM 聚焦整体层面故障模式。

**已执行改动**:

| 文件 | 改动 |
|------|------|
| `orchestrator.py` `_read_component_list` | 返回全部部件，叶节点优先排序 |
| `orchestrator.py` `run_fault` | context 增加 `children`（子部件列表）和 `sub_equipment` |
| `orchestrator.py` 新增 `_get_children` | 获取某部件的直接子部件列表 |
| `collector.py` fault prompt | 增加父部件约束："聚焦整体层面的故障模式" |
| `collector.py` fault prompt | 增加子行业/子设备语境（标题中体现完整路径） |
| `construct_guide.md` 1.3节 | "叶节点部件才有故障文件" → "所有部件均可生成故障文件" |
| `validate_kb.py` | 放宽故障文件名对应检查：叶节点必须有，父节点可选 |
