# Pipeline 修复与优化执行总结

> 日期: 2026-05-19
> 基线: construct_guide v2.3，审查意见 `pipeline审查与优化建议（Claude）.md`

## P0 Bug 修复（4项，全部完成）

| # | 问题 | 文件 | 改动 |
|---|------|------|------|
| 1 | `accumulated` 拼接导致多表头 | orchestrator.py `_run_layer` | 第2轮起只追加数据行，去掉表头和分隔符 |
| 2 | `round_num > max_judge_rounds` 永远为 False | orchestrator.py L845 | `>` → `>=` |
| 3 | `is_leaf` 死代码（逻辑反转+未使用） | orchestrator.py `_rebuild_component_table` | 删除 4 行 |
| 4 | "9列"应为"10列" | collector.py + orchestrator.py `_consolidate` | 全部改为"10列" |

## 架构改进：故障生成扩展到所有部件

**用户决策**: 父部件存在叶节点无法覆盖的整体宏观故障（如筒体辐照脆化），故障生成范围从"仅叶节点"扩展为"全部部件"。

| 改动 | 文件 |
|------|------|
| `_read_component_list` 返回全部部件（叶节点优先） | orchestrator.py |
| 新增 `_get_children` / `_get_sub_equipment` 辅助方法 | orchestrator.py |
| `run_fault` context 传递 `children` + `sub_equipment` | orchestrator.py |
| fault prompt 增加子行业/子设备语境 + 父部件约束 | collector.py |
| fault 搜索查询增加 `sub_en` 上下文 | collector.py |
| "叶节点部件才有故障文件" → "所有部件均可生成" | construct_guide.md |
| 故障文件名对应检查放宽（父节点可选） | validate_kb.py |

## P1 质量修复（5项，全部完成）

| # | 问题 | 文件 | 改动 |
|---|------|------|------|
| 1 | Judge 缺 Schema 锚定 | judge.py | 新增 Schema 约束块 + D2/D3/D9 三项审查维度 |
| 2 | 搜索全英文 | collector.py | 每层增加 1-2 条中文查询 |
| 3 | base.py 无重试 | base.py | 添加指数退避重试（3次），`max_tokens` 参数化 |
| 4 | 非原子写入 | file_manager.py | 先写 `.tmp` 再 `os.replace` |
| 5 | 搜索缺子行业上下文 | collector.py | fault 层 `target` 拼入 `sub_en` |

## P2 清理（全部完成）

| 删除项 | 文件 |
|--------|------|
| `import hashlib`（未使用） | orchestrator.py |
| `import re`（未使用） | search.py |
| 3 个 `get_*_dir` 函数（从未被调用） | file_manager.py |
| `run_fault_enrich`（D14/D15 已废弃） | orchestrator.py |
| `run_schema_migrate`（历史迁移工具） | orchestrator.py |
| `_strip_d10_from_fault`（D10 已废弃） | orchestrator.py |
| key_map 中旧 D8_根本/D10-D15 映射 | orchestrator.py |
| "Phase 4.5" 注释段 | orchestrator.py |

## P3 Prompt 优化（全部完成）

| 问题 | 改动 |
|------|------|
| `_consolidate` 用英文 `layer` 名 | 改为中文（"故障知识"、"部件拆解"等）+ 传入行业/子行业/设备上下文 |

## 验证结果

- `python -c "from pipeline.orchestrator import Orchestrator"` — 通过
- `python -c "from pipeline.agents.base import call_llm"` — 通过
- `_read_component_list` 对核电 RPV 返回 16 个部件（12 叶 + 4 父），叶节点排在前面

## 未处理项（后续迭代）

- `run_validate`（阶段5）仍为空实现 → 待阶段4稳定后补
- `validate_kb.py` 未集成到 pipeline 自动调用 → 需设计调用时机
- Orchestrator 拆分 → 渐进重构，不急
- D5 阈值来源结构化标注 → 等来源标注机制成熟后再推
