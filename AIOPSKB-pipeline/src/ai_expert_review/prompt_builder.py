"""
prompt_builder.py — 按层级组装评审 prompt

根据 layer / expert_id / round_num 等参数，从模板文件和数据加载器
组装完整的评审 prompt。
"""

import json
import os
import sys

# 确保 import 路径
_BUILDER_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE_DIR = os.path.normpath(os.path.join(_BUILDER_DIR, os.pardir, "pipeline"))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

from config import SUB_INDUSTRY_CODING_ANCHORS

PROMPTS_DIR = os.path.join(_BUILDER_DIR, "prompts")

# 从同目录的 AI_Expert.py 导入
sys.path.insert(0, _BUILDER_DIR)
from AI_Expert import LAYER_EXPERT_ROLES


# ── JSON Schema 定义（写入 prompt 要求专家输出） ──

OUTPUT_JSON_SCHEMA = """你必须以如下 JSON 格式输出评审结果（不要添加其他文字，只输出 JSON）：

```json
{{
  "layer": "{layer}",
  "target": "{target}",
  "focus": "{focus}",
  "overall_score": <0-10的浮点数>,
  "verdict": "通过" | "需修订" | "需重做",
  "issues": [
    {{
      "level": "{level_hint}",
      "node": "节点名称",
      "dimension": "维度名称（如 分类合理性）",
      "severity": "致命" | "严重" | "一般",
      "problem": "问题描述",
      "suggestion": "具体修改建议"
    }}
  ],
  "missing": [
    {{
      "level": "{level_hint}",
      "parent": "应归属的父节点",
      "name": "遗漏的条目名称",
      "reason": "为什么应该包含"
    }}
  ],
  "redundant": [
    {{
      "level": "{level_hint}",
      "node": "冗余的节点名称",
      "reason": "为什么冗余"
    }}
  ]
}}
```

**输出要求**：
- `overall_score`：综合评分，0-10分
- `verdict`：≥8分→"通过"，5-7分→"需修订"，<5分→"需重做"
- `issues`：发现的所有问题，按 severity 从高到低排列
- `missing`：你认为被遗漏的条目
- `redundant`：你认为冗余的条目
- 如果没有 issues/missing/redundant，对应数组填空 `[]`
"""


# ── 模板加载 ──

def _load_template(name):
    """从 prompts/ 目录加载模板文件。"""
    path = os.path.join(PROMPTS_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ── 数据表格渲染 ──

def _render_equipment_table(items):
    """将设备列表渲染为 markdown 表格。"""
    lines = ["| 设备类型名称 | 设备属性 | 描述 |", "|---|---|---|"]
    for item in items:
        lines.append(f"| {item['name']} | {item['type']} | {item['desc']} |")
    return "\n".join(lines)


def _render_sub_equipment_table(items):
    """将子设备列表渲染为 markdown 表格。"""
    lines = ["| 子设备名称 | 描述 |", "|---|---|"]
    for item in items:
        lines.append(f"| {item['name']} | {item['desc']} |")
    return "\n".join(lines)


def _render_structure_data(tree, focus="all"):
    """将结构树渲染为 markdown 片段。"""
    sections = []

    for ss in tree["subsystems"]:
        section_lines = [f"### 子系统：{ss['name']}", f"> {ss['desc']}", ""]

        if focus in ("all", "component", "part"):
            if ss["components"]:
                section_lines.append("| 部件 | 零件 | 描述 | 易损标识 | 维护方法 | 报废方法 |")
                section_lines.append("|---|---|---|---|---|---|")
                for cname, cdata in ss["components"].items():
                    # 部件行
                    section_lines.append(
                        f"| {cname} | — | {cdata['desc']} | {cdata['consumable']} "
                        f"| {cdata['maint']} | {cdata['disposal']} |"
                    )
                    # 零件行
                    if focus in ("all", "part"):
                        for p in cdata["parts"]:
                            if isinstance(p, dict):
                                section_lines.append(
                                    f"| {cname} | {p['name']} | {p.get('desc', '')} "
                                    f"| {p.get('consumable', '—')} | — | — |"
                                )
                            else:
                                section_lines.append(f"| {cname} | {p} | | | — | — |")
            else:
                section_lines.append("*(该子系统下暂无部件数据)*")

        sections.append("\n".join(section_lines))

    return "\n\n".join(sections)


# ── 编码锚点渲染 ──

def _render_coding_anchor(sub_industry):
    """根据子行业生成编码锚点表格。"""
    anchor = SUB_INDUSTRY_CODING_ANCHORS.get(sub_industry)
    if not anchor:
        return "*(该子行业暂无编码锚点)*\n| — | — | — |"
    return (
        f"| {sub_industry} | {anchor['system']} | {anchor['standard']} |\n"
        f"| 范围 | {anchor['scope']} | |"
    )


def _get_coding_system(sub_industry):
    """获取编码体系名称。"""
    anchor = SUB_INDUSTRY_CODING_ANCHORS.get(sub_industry)
    return anchor["system"] if anchor else "标准编码体系"


# ── 维度块渲染（structure 层） ──

_DIMENSION_BLOCKS = {
    "subsystem": """#### 子系统维度

- **功能完备性**：是否覆盖该设备所有主要功能链/能量流环节，无关键功能缺失
- **划分逻辑一致**：是否统一按"功能/能量流"划分（不要一部分按功能、一部分按物理位置）
- **粒度一致性**：各子系统粒度相当，不要一个特别庞大、一个特别琐碎
- **边界清晰**：子系统间无功能重叠、无重复
- **符合真实工程结构**：与该设备真实的系统划分一致（对照行业认知）""",

    "component": """#### 部件维度

- **拆解充分性**：是否拆到了合理的可维护单元粒度，不过粗（如不能把整台齿轮箱当一个部件不再拆）
- **功能完备性**：覆盖所属子系统的全部关键部件，无遗漏
- **失效独立性**：每个部件应是独立的失效/维护单元（独立失效模式、可独立检修/更换）
- **粒度一致性**：同级部件粒度相当
- **维护/报废挂载合理性**：维护方法、报废方法应挂在部件层且内容合理、可操作""",

    "part": """#### 零件维度

- **聚焦易损/可更换件**：应聚焦易损件、可更换件、关键失效件；不罗列无运维意义的紧固件等
- **关键失效覆盖**：覆盖该部件下会导致部件功能丧失的关键零件
- **不过度细分**：避免把不可独立更换、无独立失效意义的最小结构都列出
- **归属正确**：每个零件挂在正确的父部件下
- **易损标识合理性**：易损标识列与零件实际属性一致""",
}


def _render_dimension_sections(focus="all"):
    """按 focus 渲染 structure 层的评审维度块。"""
    if focus == "all":
        blocks = [_DIMENSION_BLOCKS["subsystem"], _DIMENSION_BLOCKS["component"], _DIMENSION_BLOCKS["part"]]
    elif focus in _DIMENSION_BLOCKS:
        blocks = [_DIMENSION_BLOCKS[focus]]
    else:
        blocks = [_DIMENSION_BLOCKS["subsystem"], _DIMENSION_BLOCKS["component"], _DIMENSION_BLOCKS["part"]]
    return "\n\n".join(blocks)


def _render_focus_hint(focus):
    """生成 focus 模式提示文字。"""
    hints = {
        "subsystem": "> 📌 本次评审聚焦模式：**仅评审子系统层**",
        "component": "> 📌 本次评审聚焦模式：**仅评审部件层**",
        "part": "> 📌 本次评审聚焦模式：**仅评审零件层**",
    }
    return hints.get(focus, "")


# ── 主入口 ──

def build_review_prompt(layer, data, expert_id, context,
                         round_num=1, max_rounds=3,
                         other_expert_response=None, focus=None):
    """组装完整评审 prompt。

    Args:
        layer: equipment / sub_equipment / structure
        data: loader 返回的结构化数据
        expert_id: deepseek / kimi
        context: resolve_review_target 返回的上下文 dict
        round_num: 当前轮次（1-based）
        max_rounds: 最大轮次
        other_expert_response: 对方上轮回复 JSON（仅 round > 1 时有值）
        focus: structure 层聚焦模式

    Returns:
        str: 完整 prompt 文本
    """
    focus = focus or "all"
    sub_industry = context.get("sub_industry", "")
    equipment = context.get("equipment", "")
    industry = context.get("industry", "")

    # 1. 角色
    roles = LAYER_EXPERT_ROLES.get(layer, {})
    expert_role = roles.get(expert_id, "评审专家")

    # 2. 按 layer 选择模板和填充
    if layer == "equipment":
        template = _load_template("equipment_review.md")
        data_table = _render_equipment_table(data.get("items", []))
        coding_anchor = _render_coding_anchor(sub_industry)
        coding_system = _get_coding_system(sub_industry)
        level_hint = "equipment"
        target_desc = f"{sub_industry}设备清单"

        prompt = template.format(
            sub_industry=sub_industry,
            expert_role=expert_role,
            coding_anchor_table=coding_anchor,
            data_table=data_table,
            coding_system=coding_system,
        )

    elif layer == "sub_equipment":
        template = _load_template("sub_equipment_review.md")
        data_table = _render_sub_equipment_table(data.get("items", []))
        level_hint = "sub_equipment"
        target_desc = f"{equipment}子设备清单"

        prompt = template.format(
            equipment=equipment,
            expert_role=expert_role,
            industry=industry,
            sub_industry=sub_industry,
            data_table=data_table,
        )

    elif layer == "structure":
        template = _load_template("structure_review.md")
        data_sections = _render_structure_data(data, focus=focus)
        dimension_sections = _render_dimension_sections(focus)
        focus_hint = _render_focus_hint(focus)
        level_hint = "subsystem | component | part"
        target_desc = f"{equipment}结构树"

        prompt = template.format(
            equipment=equipment,
            expert_role=expert_role,
            industry=industry,
            sub_industry=sub_industry,
            data_sections=data_sections,
            dimension_sections=dimension_sections,
            focus_hint=focus_hint,
        )
    else:
        raise ValueError(f"未知层级: {layer}")

    # 3. 追加 JSON schema 输出要求
    schema_block = OUTPUT_JSON_SCHEMA.format(
        layer=layer,
        target=target_desc,
        focus=focus,
        level_hint=level_hint,
    )
    prompt += "\n\n" + schema_block

    # 4. 多轮辩论：追加对方上轮回复
    if round_num > 1 and other_expert_response:
        debate_template = _load_template("debate_round.md")
        other_json_str = json.dumps(other_expert_response, ensure_ascii=False, indent=2) \
            if isinstance(other_expert_response, dict) else str(other_expert_response)
        debate_block = debate_template.format(
            round_num=round_num,
            max_rounds=max_rounds,
            other_expert_response=other_json_str,
        )
        prompt += "\n\n" + debate_block

    return prompt
