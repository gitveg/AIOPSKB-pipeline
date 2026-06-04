"""
v9 → v10 结构化重构脚本

将每个设备条目的维度从单个长 bullet 拆为结构化子 bullet。
"""
import re
from pathlib import Path

INDENT = "  "

# 维度标签（按模板顺序）
DIM_LABELS = [
    "基本信息", "设备作用与工作原理", "生命周期",
    "故障模式", "监测手段", "诊断与健康",
    "运维策略", "检修执行", "风险与标准", "智能化与前沿应用",
]

def split_by_outer_brackets(text: str) -> list[tuple[str, str]]:
    """按中文括号外的顿号/逗号分割，保留括号内容。"""
    result = []
    depth = 0
    buf = ""
    for ch in text:
        if ch in "（(":
            depth += 1
            buf += ch
        elif ch in "）)":
            depth -= 1
            buf += ch
        elif ch in "、" and depth == 0:
            if buf.strip():
                result.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        result.append(buf.strip())
    return [(r, "") for r in result]


def restructure_basic_info(content: str) -> list[str]:
    """重构基本信息：拆为设备类型和关键部件。"""
    lines = []
    parts = content.split("|")
    for p in parts:
        p = p.strip()
        if p.startswith("关键部件：") or p.startswith("关键部件:"):
            lines.append(f"{INDENT}- 关键部件：{p[p.index('：')+1:].strip()}")
        elif p.startswith("关键部件"):
            lines.append(f"{INDENT}- {p}")
        else:
            lines.append(f"{INDENT}- 设备类型：{p}")
    return lines


def restructure_lifecycle(content: str) -> list[str]:
    """重构生命周期：拆为5个阶段子字段。"""
    lines = []
    # 先处理退役报废（可能在末尾用 ：引出）
    retirement = ""
    retirement_match = re.search(r"退役报废[：:]\s*(.+)", content)
    if retirement_match:
        retirement = retirement_match.group(1).strip()
        content = content[:retirement_match.start()].strip().rstrip("→").strip()

    # 按 → 分割阶段
    stages = [s.strip() for s in content.split("→") if s.strip()]

    stage_names = ["设计选型", "安装调试", "运行看护", "维护检修", "退役报废"]

    for stage in stages:
        # 提取阶段名和内容
        match = re.match(r"^([^（(：:]+?)[（(：:](.+)[)）]?$", stage)
        if match:
            name = match.group(1).strip().rstrip("：:")
            detail = match.group(2).strip().rstrip(")）")
            lines.append(f"{INDENT}- {name}：{detail}")
        else:
            # 没有括号的情况
            colon_match = re.match(r"^(.+?)[：:](.+)$", stage)
            if colon_match:
                lines.append(f"{INDENT}- {colon_match.group(1).strip()}：{colon_match.group(2).strip()}")
            else:
                lines.append(f"{INDENT}- {stage}")

    if retirement:
        lines.append(f"{INDENT}- 退役报废：{retirement}")

    return lines


def restructure_fault_modes(content: str) -> list[str]:
    """重构故障模式：每种故障一个 bullet。"""
    lines = []
    items = split_by_outer_brackets(content)
    for item_text, _ in items:
        item_text = item_text.strip()
        if item_text:
            # 检查是否包含 / 分隔的子类型
            lines.append(f"{INDENT}- {item_text}")
    return lines


def restructure_monitoring(content: str) -> list[str]:
    """重构监测手段：按模态分 bullet。"""
    lines = []
    items = split_by_outer_brackets(content)
    for item_text, _ in items:
        item_text = item_text.strip()
        if not item_text:
            continue
        # 检查是否有模态名+括号详情的格式
        match = re.match(r"^(.+?)[（(](.+)[)）]$", item_text)
        if match:
            lines.append(f"{INDENT}- {match.group(1).strip()}：{match.group(2).strip()}")
        else:
            lines.append(f"{INDENT}- {item_text}")
    return lines


def restructure_diagnosis(content: str) -> list[str]:
    """重构诊断与健康：拆为诊断方法/健康评估/RUL预测。"""
    lines = []
    # 尝试按 、分割
    items = [i.strip() for i in content.split("、") if i.strip()]

    diag_items = []
    health_items = []
    rul_items = []

    for item in items:
        if "RUL" in item or "寿命预测" in item or "RUL预测" in item:
            rul_items.append(item)
        elif "健康" in item or "退化" in item or "HI" in item or "评估" in item:
            health_items.append(item)
        else:
            diag_items.append(item)

    if diag_items:
        lines.append(f"{INDENT}- 诊断方法：{'、'.join(diag_items)}")
    if health_items:
        lines.append(f"{INDENT}- 健康评估：{'、'.join(health_items)}")
    if rul_items:
        lines.append(f"{INDENT}- RUL预测：{'、'.join(rul_items)}")

    if not lines:
        lines.append(f"{INDENT}- {content}")
    return lines


def restructure_strategy(content: str) -> list[str]:
    """重构运维策略：拆为策略类型/检修计划/备件管理。"""
    lines = []
    items = [i.strip() for i in content.split("、") if i.strip()]

    strategy_items = []
    plan_items = []
    spare_items = []

    for item in items:
        if "备件" in item:
            spare_items.append(item)
        elif "检修" in item or "计划" in item or "换油" in item or "窗口" in item or "大修" in item:
            plan_items.append(item)
        else:
            strategy_items.append(item)

    if strategy_items:
        lines.append(f"{INDENT}- 策略类型：{'、'.join(strategy_items)}")
    if plan_items:
        lines.append(f"{INDENT}- 检修计划：{'、'.join(plan_items)}")
    if spare_items:
        lines.append(f"{INDENT}- 备件管理：{'、'.join(spare_items)}")

    if not lines:
        lines.append(f"{INDENT}- {content}")
    return lines


def restructure_maintenance(content: str) -> list[str]:
    """重构检修执行：每个SOP一个 bullet。"""
    lines = []
    items = split_by_outer_brackets(content)
    for item_text, _ in items:
        if item_text.strip():
            lines.append(f"{INDENT}- {item_text.strip()}")
    return lines


def restructure_risk(content: str) -> list[str]:
    """重构风险与标准：拆为关键性和标准。"""
    lines = []
    items = [i.strip() for i in content.split("、") if i.strip()]

    risk_items = []
    standard_items = []

    for item in items:
        if re.search(r"ISO|API|IEC|GB|DL|JB|MT|TB|EN|FAA|CCAR|TSG|ASME|TEMA|UL|IACS|AQ|NB|YB|SY|JC", item):
            standard_items.append(item)
        else:
            risk_items.append(item)

    if risk_items:
        lines.append(f"{INDENT}- 关键性：{'、'.join(risk_items)}")
    if standard_items:
        lines.append(f"{INDENT}- 标准：{'、'.join(standard_items)}")

    if not lines:
        lines.append(f"{INDENT}- {content}")
    return lines


def restructure_smart(content: str) -> list[str]:
    """重构智能化与前沿应用：每个应用一个 bullet。"""
    lines = []
    # 按 → 分割
    items = [i.strip() for i in content.split("→") if i.strip()]
    for item in items:
        if item:
            lines.append(f"{INDENT}- {item}")
    return lines


def restructure_description(content: str) -> list[str]:
    """重构设备作用与工作原理：长文本拆句。"""
    lines = []
    # 按句号分割
    sentences = re.split(r"[。；]", content)
    for s in sentences:
        s = s.strip()
        if s:
            lines.append(f"{INDENT}- {s}")
    return lines


def restructure_dimension(label: str, content: str) -> list[str]:
    """根据维度标签选择对应的重构方法。"""
    content = content.strip()
    handlers = {
        "基本信息": restructure_basic_info,
        "设备作用与工作原理": restructure_description,
        "生命周期": restructure_lifecycle,
        "故障模式": restructure_fault_modes,
        "监测手段": restructure_monitoring,
        "诊断与健康": restructure_diagnosis,
        "运维策略": restructure_strategy,
        "检修执行": restructure_maintenance,
        "风险与标准": restructure_risk,
        "智能化与前沿应用": restructure_smart,
    }
    handler = handlers.get(label)
    if handler:
        return handler(content)
    else:
        return [f"{INDENT}- {content}"]


def process_equipment_block(lines: list[str], start_idx: int) -> tuple[list[str], int]:
    """处理一个设备条目块，返回重构后的行和结束索引。"""
    result = [lines[start_idx]]  # 保留标题行
    result.append("")  # 标题后空行

    idx = start_idx + 1
    while idx < len(lines):
        line = lines[idx]
        # 如果遇到下一个标题（#### 或 ### 或 ##），停止
        if re.match(r"^#{1,4}\s", line) or line.startswith("#"):
            break
        # 空行直接保留
        if not line.strip():
            idx += 1
            continue

        # 匹配维度 bullet：- **标签**：内容
        dim_match = re.match(r"^- \*\*(.+?)\*\*[：:]\s*(.*)", line)
        if dim_match:
            label = dim_match.group(1).strip()
            content = dim_match.group(2).strip()

            result.append(f"- **{label}**")
            sub_lines = restructure_dimension(label, content)
            result.extend(sub_lines)
            result.append("")  # 维度间空行
            idx += 1
        else:
            # 非 bullet 行（可能是普通文本），保留
            result.append(line)
            idx += 1

    return result, idx


def main():
    src = Path("outlines/Merged_PHM_TOC_v9.md")
    dst = Path("outlines/Merged_PHM_TOC_v10.md")

    text = src.read_text(encoding="utf-8")
    lines = text.split("\n")

    # 找到 Part 2 的起始位置
    part2_start = None
    part3_start = None
    for i, line in enumerate(lines):
        if "# 第二部分" in line:
            part2_start = i
        if "# 第三部分" in line:
            part3_start = i
            break

    # Part 1: 直接复制，但更新模板定义
    output_lines = []
    idx = 0

    # 处理 Part 1（到第二部分之前）
    while idx < (part2_start or len(lines)):
        output_lines.append(lines[idx])
        idx += 1

    # 处理 Part 2（设备条目）
    while idx < (part3_start or len(lines)):
        line = lines[idx]
        # 检查是否是设备条目标题（#### 或 ### 在 Part 2 中）
        if re.match(r"^#{3,4}\s", line) and idx >= (part2_start or 0):
            # 判断是否是设备条目（不是行业标题 ### 2.1 风电 这种）
            # 设备条目特征：有维度 bullet 在后面
            is_equipment = False
            for j in range(idx + 1, min(idx + 15, len(lines))):
                if re.match(r"^- \*\*(基本信息|设备类型)\*\*", lines[j]):
                    is_equipment = True
                    break
                if re.match(r"^#{2,4}\s", lines[j]):
                    break

            if is_equipment:
                block, new_idx = process_equipment_block(lines, idx)
                output_lines.extend(block)
                idx = new_idx
                continue

        output_lines.append(line)
        idx += 1

    # Part 3 + Part 4: 直接复制
    while idx < len(lines):
        output_lines.append(lines[idx])
        idx += 1

    # 写入 v10
    # 清理多余空行（连续3个以上空行压缩为2个）
    final_lines = []
    empty_count = 0
    for line in output_lines:
        if line.strip() == "":
            empty_count += 1
            if empty_count <= 2:
                final_lines.append(line)
        else:
            empty_count = 0
            final_lines.append(line)

    content = "\n".join(final_lines)
    dst.write_text(content, encoding="utf-8", newline="\n")
    print(f"v10 已生成: {dst} ({len(content)} 字符, {len(final_lines)} 行)")


if __name__ == "__main__":
    main()
