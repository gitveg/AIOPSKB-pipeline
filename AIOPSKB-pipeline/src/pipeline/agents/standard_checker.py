"""
标准核查 Agent（Standard Checker）

使用异模型（verifier）作为第二专家，对生成模型产出的故障知识 D5 置信标注做二次审核：
- 消除所有"待核实"条目（升级为"标准值"或降级为"经验值"）
- 尝试将"经验值"升级为"标准值"（当核查模型知道对应标准时）
- 验证声称"标准值"的参数是否真实引用了正确标准（防止生成模型幻觉）

触发时机：fault 层整合（Phase B）完成后，写盘前（Phase C）。
受 config.ENABLE_PHASE_C 开关控制（当前关闭，未来启用时 verifier 即生效）。
"""

import json
import re
from agents.base import call_llm

STANDARD_CHECKER_SYSTEM = """你是一位精通国内外工业设备技术标准的知识专家，专注于中国电力、石化、冶金等行业。

你的任务是核查故障特征参数（D5字段）的置信标注，核查目标：
1. 对所有"待核实"条目给出结论（升级为"标准值"、降级为"经验值"、或标记为"unknown"）
2. 尝试将"经验值"升级为"标准值"（当你确实知道对应标准时）
3. 验证声称"标准值"的参数是否真实引用了正确标准（防止生成模型幻觉）

工作原则：
- 宁可标"经验值"也绝不保留虚假标准号
- 只有当你对标准号和数值都有把握时才用"标准值"
- 不确定时诚实降为"经验值"，不要因"看起来合理"就凭空标注标准号
- 如果你对该参数也完全没把握，可以返回"unknown"，由后续兜底处理
- 切勿在自己也不确定时强行二选一

输出必须是合法JSON，不要在前后添加任何其他文字。"""

# Build full standard reference for 核查 prompt (all 18 domains)
def _build_checker_reference() -> str:
    from config import D5_STANDARD_REFERENCE
    lines = []
    for domain, info in D5_STANDARD_REFERENCE.items():
        for std_num, scope in info["standards"]:
            lines.append(f"  - {std_num}: {scope}")
        lines.append("")
    return "\n".join(lines)

_STANDARD_CHECKER_REFERENCE = _build_checker_reference()

STANDARD_CHECKER_PROMPT = """请核查以下【{ctx_str}】部件故障知识表格中所有D5特征参数的置信标注。

---
{fault_content}
---

找出需要修改的故障行，给出修改后的完整D5单元格内容。

以JSON格式返回（不加代码块标记）：
{{
  "fault_updates": [
    {{
      "fault_name": "故障名称（与表格第一列完全一致）",
      "d5_revised": "修改后的完整D5单元格内容（保留所有参数条目，用<br>分隔，替换原置信标注：必须先删除该参数原有的'置信：X'再写新值，禁止保留旧置信导致同一参数出现两个置信）",
      "changes": [
        {{
          "param_hint": "参数关键词（3-5字）",
          "from": "待核实/经验值/标准值",
          "to": "标准值/经验值/unknown",
          "standard": "标准号（如 GB/T 12145-2016），或null",
          "reason": "一句话说明"
        }}
      ]
    }}
  ],
  "summary": "一句话总结（如：升级X条为标准值，消除Y条待核实，降级Z条虚假引用）"
}}

核查规则：
- 你必须对所有含"待核实"标注的D5参数给出结论，不得遗漏
- 三种合法结论：
  · "标准值"——你能确定标准号且数值与标准一致
  · "经验值"——你确认该参数是行业经验，但无标准可引
  · "unknown"——该参数你也无把握，将置信改为"置信：unknown"
- "待核实" → 你知道标准依据则升为"标准值"；否则改为"经验值"；若你也无法确定则标"unknown"
- "经验值" → 你确认有对应标准则升，否则保持；不强制升级
- "标准值" → 若标准号明显错误或你无法确认，改为"经验值"并去掉错误标准号
- 切勿在自己也不确定时强行二选一
- 若某条故障的D5无需任何修改（且不含"待核实"），不要列入fault_updates

中国工业设备常用标准参考（完整速查表）：
""" + _STANDARD_CHECKER_REFERENCE


def _apply_fault_d5_updates(fault_content: str, fault_updates: list[dict]) -> tuple[str, int]:
    """Apply D5 column updates (keyed by fault_name) to the fault Markdown table."""
    if not fault_updates:
        return fault_content, 0

    update_map = {
        upd["fault_name"].strip(): upd["d5_revised"].strip()
        for upd in fault_updates
        if upd.get("fault_name") and upd.get("d5_revised")
    }
    if not update_map:
        return fault_content, 0

    lines = fault_content.split("\n")
    result_lines = []
    d5_col_idx = None
    applied = 0

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            result_lines.append(line)
            continue

        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if not cells:
            result_lines.append(line)
            continue

        # Detect header row to locate D5 column
        if d5_col_idx is None and any("D5" in c or "特征参数" in c for c in cells):
            d5_col_idx = next(
                (i for i, c in enumerate(cells) if "D5" in c or "特征参数" in c), None
            )
            result_lines.append(line)
            continue

        # Separator row
        if re.match(r'^\|[\s\-:|]+\|$', stripped):
            result_lines.append(line)
            continue

        # Data row: apply update if fault_name matches
        if d5_col_idx is not None and 0 < d5_col_idx < len(cells):
            fault_name = cells[0]
            if fault_name in update_map:
                cells[d5_col_idx] = update_map[fault_name]
                result_lines.append("| " + " | ".join(cells) + " |")
                applied += 1
                continue

        result_lines.append(line)

    return "\n".join(result_lines), applied


def run_standard_checker(context: dict, fault_content: str) -> tuple[str, dict]:
    """Use verifier (异模型) to verify and upgrade D5 confidence annotations.

    Returns:
        (updated_fault_content, stats_dict)
        stats_dict keys: status, applied, summary
    """
    ctx_str = " - ".join(filter(None, [
        context.get("sub_industry", ""),
        context.get("equipment", ""),
        context.get("component", ""),
    ]))

    prompt = STANDARD_CHECKER_PROMPT.format(
        ctx_str=ctx_str,
        fault_content=fault_content,
    )

    raw = call_llm("verifier", STANDARD_CHECKER_SYSTEM, prompt, temperature=0.1)
    cleaned = re.sub(r'```json\s*|```\s*', '', raw).strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        return fault_content, {
            "status": "parse_error",
            "applied": 0,
            "summary": "核查响应解析失败，跳过标准核查",
        }

    fault_updates = result.get("fault_updates", [])
    updated_content, applied = _apply_fault_d5_updates(fault_content, fault_updates)

    return updated_content, {
        "status": "updated" if applied > 0 else "no_changes",
        "applied": applied,
        "summary": result.get("summary", f"核查完成，修改{applied}条故障的D5"),
    }
