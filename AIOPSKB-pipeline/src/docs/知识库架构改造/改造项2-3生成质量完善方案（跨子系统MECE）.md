# 改造项2-3 生成质量完善方案（跨子系统 MECE 去重）

> **背景**：改造项2-3（结构分解层）落地后，凝汽器测试数据出现**跨子系统重复件**（如"管板""密封垫"同时出现在多个子系统）。本方案在**生成阶段**（prompt + pipeline 结构）从源头保证质量，不依赖三AI评审兜底。
> **交付对象**：执行此方案的 AI 工程师（GLM）。
> **关联文档**：`改造项2-3实施记录.md`、`知识库架构改造方案（文华+生强）.md`

---

## 1. 问题与根因

### 1.1 现象（凝汽器实测数据）

同一物理件在多个子系统重复出现，且**层级、属性、描述各自漂移**：

| 物理件 | 在子系统A | 层级A | 易损A | 在子系统B | 层级B | 易损B |
|--------|----------|-------|-------|----------|-------|-------|
| 管板 | 冷凝换热管束系统 | 零件（挂"冷凝管束总成"下） | 是 | 冷却水流通与密封系统 | **部件** | 否 |
| 密封垫 | 冷凝换热管束系统（管板密封垫） | 零件 | 是 | 冷却水流通与密封系统 | **部件** | 是 |

这不是"多入口共享件"，而是**孤立生成撞名后各自分裂**的脏数据。

### 1.2 根因

`orchestrator.run_component` 的 Phase 3.2 **逐子系统独立调用 LLM 生成 `components.md`，子系统之间互不知情**（见 `orchestrator.py` 的 `for ss_name, ss_desc in sub_systems` 循环）。LLM 没有全局视野，必然在功能边界处撞名。

### 1.3 危害

1. **故障层双份且分叉**：`run_fault` 遍历子系统目录→部件/零件目录生成故障，重复件会被生成两遍，D5 阈值/置信/故障清单各不相同，稀释已有的 D5+Kimi 可靠性成果。
2. **编码 ID 不唯一**：按路径编码，重复件拿到两个 ID，破坏去重、统计、索引交叉引用。
3. **违反 MECE**：破坏结构分解层"互斥"前提。

---

## 2. 政策（已定）

**严格 MECE + 单一归属**：

- 每个物理部件/零件**只归属一个子系统**，归属依据 = "该件主要服务的功能"所在子系统。
- **禁止跨子系统重复**，不放引用行。
- 跨功能边界件的导航需求由 **index 检索**解决（搜名称即命中其唯一归属条目），不靠物理重复。
- 本轮**不处理**子系统间粒度不均衡问题（留给三AI评审模块）。

---

## 3. 改造方案

三道防线：**生成时避让（prompt）→ 生成后设备级仲裁去重（pipeline）→ 校验拦截（validate_kb）**。

### 3.1 Pipeline：兄弟上下文注入（生成时避让）

改 `orchestrator.run_component` 的 Phase 3.2 循环，让第 N 个子系统知道前 N-1 个已认领了哪些件：

```
claimed = []   # 累积已生成的 部件/零件 名称
for ss_name, ss_desc in sub_systems:
    # 断点续跑：若该子系统已有 components.md 且跳过生成，
    # 仍需解析其中的部件/零件名并入 claimed（否则后续子系统失去避让依据）
    if 已有数据:
        claimed.extend(_extract_part_names(existing_components_md))
        continue

    context = {**context_base,
               "sub_system": ss_name, "sub_system_desc": ss_desc,
               "all_sub_systems": sub_systems,   # 全部子系统名+描述（提供功能边界全景）
               "claimed_parts": claimed}          # 已被其他子系统认领的部件/零件名清单
    comp_result = self._run_layer("component", context, comp_path)
    comp_data = comp_result[0]
    write_kb_file(comp_path, comp_data)
    claimed.extend(_extract_part_names(comp_data))   # 累积本子系统认领的件
```

新增辅助函数 `_extract_part_names(md) -> list[str]`：解析新格式 components.md，返回所有非"—"的部件名 + 零件名（去重）。

> 注意顺序依赖：贪心"先到先得"可能让非最佳 owner 抢先认领；这一层只负责**降低撞名概率**，最终归属正确性由 3.2 的设备级仲裁兜底。

### 3.2 Pipeline：设备级去重仲裁（生成后兜底）

在 Phase 3.2 全部子系统生成完毕后，新增 `_dedup_cross_subsystem(base_dir, sub_systems)`：

1. 读取所有子系统的 `components.md`，建立 `名称 → [(子系统, 层级, 行)]` 映射。
2. 找出出现在 **≥2 个子系统**的名称（撞名件）。
3. 对每个撞名件，调用 LLM（复用 `_consolidate` 框架或小型仲裁 agent）做**归属仲裁**：输入该件描述 + 所有候选子系统的描述，按"主要服务功能"判给唯一 owner 子系统。
4. 从非 owner 子系统的 `components.md` 删除该件对应行，重写文件；owner 保留。
5. 输出仲裁日志（`phase3.2_dedup_{设备}.md`），记录每个撞名件判给谁、理由，供审计。

> 与现有 `_consolidate` 的关系：去重仲裁可作为 consolidation 的一个子步骤，复用其 LLM 调用与文件重写逻辑。

### 3.3 Prompt：component 层约束（生成时避让）

改 `collector.py` 的 `_build_prompt` component 分支（当前 287-321 行），新增：

1. **归属规则**：
   > 部件/零件归属"主要服务功能"所在的子系统。横跨多个功能子系统的物理件（如管板、密封垫）只在其主功能 owner 子系统出现一次，禁止在本子系统重复列出已属于其他子系统的件。

2. **兄弟清单注入**（来自 `ctx["claimed_parts"]` 与 `ctx["all_sub_systems"]`）：
   > 本设备的全部子系统及功能边界如下：{all_sub_systems}
   > 以下部件/零件已被其他子系统认领，**不要重复列出**（除非本子系统确为其主功能 owner，此时请在输出中说明）：{claimed_parts}

3. **来源口径约束**（顺带修复"裸数字来源"退化）：
   > 来源必须标到可追溯粒度：标准号（如 DL/T 5000）、手册/文献名称或明确条目，**禁止只写裸数字**（如"（来源：7）"无效）。

子系统层 prompt（`sub_system` 分支，263-285 行）补一句强化边界互斥：
   > 各子系统功能边界互斥、不重叠，避免不同子系统出现职能交叉导致部件归属歧义。

### 3.4 Judge：跨子系统撞名感知（可选增强）

component 层 Judge 当前只看单个 `components.md`。增强：在 prompt 中附上 `claimed_parts`，让 Judge 把"列出了已被其他子系统认领的件"判为问题项（severity=严重），与生成侧形成闭环。

### 3.5 validate_kb：跨子系统重复校验（校验拦截）

`validate_kb.py` 新增 `check_cross_subsystem_dup(equipment_dir)`：

- 扫描某设备下所有子系统的 `components.md`，收集全部部件名 + 零件名。
- 任一名称出现在 **>1 个子系统** → 报 **ERROR**（含出现位置列表）。
- 在 Stage 3 校验中按设备维度调用。

这是廉价的程序化最后防线，与生成侧 prompt 互补。

---

## 4. 不受影响 / 需确认的点

- **编码与故障遍历**：MECE 后每件单源、ID 唯一，`run_fault` 与编码逻辑**无需改动**，重复问题从源头消除。
- **断点续跑**：3.1 中务必处理"跳过已有子系统时仍解析其 claimed 名称"，否则续跑会丢失避让上下文（已在方案中标注）。
- **已生成的凝汽器旧数据**：需用新流程**重新生成**或跑一次 `_dedup_cross_subsystem` 清洗，并归档旧版本。

---

## 5. 改造清单与优先级

| # | 任务 | 文件 | 优先级 |
|---|------|------|--------|
| 1 | component prompt 增加归属规则 + 兄弟清单 + 来源口径 | `collector.py` | P0 |
| 2 | `run_component` 注入 claimed_parts/all_sub_systems（含续跑解析） | `orchestrator.py` | P0 |
| 3 | `_extract_part_names()` 解析辅助函数 | `orchestrator.py` | P0 |
| 4 | `_dedup_cross_subsystem()` 设备级去重仲裁 + 审计日志 | `orchestrator.py` | P0 |
| 5 | `check_cross_subsystem_dup()` 校验 | `validate_kb.py` | P1 |
| 6 | sub_system prompt 强化边界互斥 | `collector.py` | P1 |
| 7 | Judge 注入 claimed_parts 感知撞名 | `judge.py` | P2 |
| 8 | 凝汽器数据重新生成/清洗对比 | 数据 | P1 |

**建议执行顺序**：1→2→3→4 打通"生成即去重"主链路，用凝汽器重跑验证管板/密封垫不再跨子系统重复；再补 5 校验、6 子系统边界、7 Judge 闭环。

---

## 6. 验证用例

1. 重新生成凝汽器结构树 → 校验"管板""密封垫"等只在唯一子系统出现。
2. `validate_kb.py --stage 3 --target .../condenser` → `check_cross_subsystem_dup` 零 ERROR。
3. 检查去重审计日志：撞名件归属判定合理（管板归"冷却水流通与密封系统"或"冷凝换热管束系统"二选一，理由清晰）。
4. 故障层抽查：管板的 `faults/管板.md` 全库唯一，无双份。
