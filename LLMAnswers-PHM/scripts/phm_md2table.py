"""
v10 第二部分 → CSV / JSON 转换脚本

解析 Merged_PHM_TOC_v10.md 的第二部分（行业-设备-特性知识体系），
将每个设备条目展开为扁平行，输出 CSV 和 JSON。
"""
import re
import json
import csv
from pathlib import Path

# 10 个标准维度（按模板顺序）
DIM_ORDER = [
    "基本信息", "设备作用与工作原理", "生命周期",
    "故障模式", "监测手段", "诊断与健康",
    "运维策略", "检修执行", "风险与标准", "智能化与前沿应用",
]

# CSV 列定义：行业信息 + 各维度子字段
CSV_COLUMNS = [
    "行业编号", "行业名称",
    "设备类别编号", "设备类别名称",
    "设备编号", "设备名称",
    "设备类型", "关键部件",
    "设备作用与工作原理",
    "设计选型", "安装调试", "运行看护", "维护检修", "退役报废",
    "故障模式",
    "监测手段",
    "诊断与健康",
    "运维策略",
    "检修执行",
    "风险与标准",
    "智能化与前沿应用",
]


def parse_part2(filepath: Path) -> list[dict]:
    """解析 v10 第二部分，返回设备条目列表。"""
    text = filepath.read_text(encoding="utf-8")
    lines = text.split("\n")

    # 定位第二部分范围
    part2_start = None
    part3_start = len(lines)
    for i, line in enumerate(lines):
        if "# 第二部分" in line:
            part2_start = i
        if "# 第三部分" in line:
            part3_start = i
            break

    if part2_start is None:
        raise ValueError("未找到第二部分")

    lines = lines[part2_start:part3_start]

    # 当前上下文
    industry_no = ""
    industry_name = ""
    category_no = ""
    category_name = ""
    equip_no = ""
    equip_name = ""

    # 当前设备的数据
    current = None
    current_dim = None
    records = []

    for line in lines:
        # ## 行业标题（如 "## 2. 电力行业"）
        m = re.match(r"^## (\d+)\.\s+(.+)$", line)
        if m:
            industry_no = m.group(1)
            industry_name = m.group(2).strip()
            continue

        # ### 设备类别（如 "### 2.1 风电"）
        m = re.match(r"^### (\d+\.\d+)\s+(.+)$", line)
        if m:
            category_no = m.group(1)
            category_name = m.group(2).strip()
            continue

        # #### 具体设备（如 "#### 2.1.1 齿轮箱"）
        m = re.match(r"^#### (\d+\.\d+\.\d+)\s+(.+)$", line)
        if m:
            # 保存上一个设备
            if current is not None:
                records.append(current)
            equip_no = m.group(1)
            equip_name = m.group(2).strip()
            current_dim = None
            current = {
                "行业编号": industry_no,
                "行业名称": industry_name,
                "设备类别编号": category_no,
                "设备类别名称": category_name,
                "设备编号": equip_no,
                "设备名称": equip_name,
            }
            # 初始化所有维度为空
            for dim in DIM_ORDER:
                current[dim] = ""
            continue

        if current is None:
            continue

        # 一级维度标题：- **维度名**
        m = re.match(r"^- \*\*(.+?)\*\*\s*$", line)
        if m:
            current_dim = m.group(1).strip()
            continue

        # 二级子 bullet：  - 内容
        if line.startswith("  - ") and current_dim:
            sub = line[4:].strip()
            if current[current_dim]:
                current[current_dim] += "\n" + sub
            else:
                current[current_dim] = sub
            continue

    # 保存最后一个设备
    if current is not None:
        records.append(current)

    return records


def flatten_record(rec: dict) -> dict:
    """将嵌套维度内容拆为 CSV 扁平行。"""
    row = {
        "行业编号": rec["行业编号"],
        "行业名称": rec["行业名称"],
        "设备类别编号": rec["设备类别编号"],
        "设备类别名称": rec["设备类别名称"],
        "设备编号": rec["设备编号"],
        "设备名称": rec["设备名称"],
    }

    # 基本信息 → 拆为 设备类型 / 关键部件
    basic = rec.get("基本信息", "")
    for sub in basic.split("\n"):
        sub = sub.strip()
        if sub.startswith("设备类型：") or sub.startswith("设备类型:"):
            row["设备类型"] = sub.split("：", 1)[-1].strip() if "：" in sub else sub.split(":", 1)[-1].strip()
        elif sub.startswith("关键部件：") or sub.startswith("关键部件:"):
            row["关键部件"] = sub.split("：", 1)[-1].strip() if "：" in sub else sub.split(":", 1)[-1].strip()
        elif sub:
            # 无标签的行，归入关键部件
            if not row.get("关键部件"):
                row["关键部件"] = sub

    # 生命周期 → 拆为 5 个子字段
    lifecycle_map = {"设计选型": "", "安装调试": "", "运行看护": "", "维护检修": "", "退役报废": ""}
    lifecycle = rec.get("生命周期", "")
    for sub in lifecycle.split("\n"):
        sub = sub.strip()
        for key in lifecycle_map:
            if sub.startswith(key + "：") or sub.startswith(key + ":"):
                lifecycle_map[key] = sub.split("：", 1)[-1].strip() if "：" in sub else sub.split(":", 1)[-1].strip()
                break
    row.update(lifecycle_map)

    # 其他维度直接填入（保持换行分隔的子条目）
    row["设备作用与工作原理"] = rec.get("设备作用与工作原理", "")
    row["故障模式"] = rec.get("故障模式", "")
    row["监测手段"] = rec.get("监测手段", "")
    row["诊断与健康"] = rec.get("诊断与健康", "")
    row["运维策略"] = rec.get("运维策略", "")
    row["检修执行"] = rec.get("检修执行", "")
    row["风险与标准"] = rec.get("风险与标准", "")
    row["智能化与前沿应用"] = rec.get("智能化与前沿应用", "")

    return row


def to_nested_json(rec: dict) -> dict:
    """将记录转为嵌套 JSON 结构。"""
    basic = rec.get("基本信息", "")
    basic_items = []
    for sub in basic.split("\n"):
        s = sub.strip()
        if s:
            basic_items.append(s)

    lifecycle_map = {"设计选型": "", "安装调试": "", "运行看护": "", "维护检修": "", "退役报废": ""}
    lifecycle = rec.get("生命周期", "")
    for sub in lifecycle.split("\n"):
        sub = sub.strip()
        for key in lifecycle_map:
            if sub.startswith(key + "：") or sub.startswith(key + ":"):
                lifecycle_map[key] = sub.split("：", 1)[-1].strip() if "：" in sub else sub.split(":", 1)[-1].strip()
                break

    def split_bullets(text: str) -> list[str]:
        return [s.strip() for s in text.split("\n") if s.strip()] if text else []

    return {
        "编号": rec["设备编号"],
        "设备名称": rec["设备名称"],
        "所属行业": {
            "编号": rec["行业编号"],
            "名称": rec["行业名称"],
        },
        "所属类别": {
            "编号": rec["设备类别编号"],
            "名称": rec["设备类别名称"],
        },
        "基本信息": {
            "设备类型": next(
                (s.split("：", 1)[1].strip() for s in basic_items if s.startswith("设备类型：")),
                ""
            ),
            "关键部件": next(
                (s.split("：", 1)[1].strip() for s in basic_items if s.startswith("关键部件：")),
                ""
            ),
        },
        "设备作用与工作原理": split_bullets(rec.get("设备作用与工作原理", "")),
        "生命周期": lifecycle_map,
        "故障模式": split_bullets(rec.get("故障模式", "")),
        "监测手段": split_bullets(rec.get("监测手段", "")),
        "诊断与健康": split_bullets(rec.get("诊断与健康", "")),
        "运维策略": split_bullets(rec.get("运维策略", "")),
        "检修执行": split_bullets(rec.get("检修执行", "")),
        "风险与标准": split_bullets(rec.get("风险与标准", "")),
        "智能化与前沿应用": split_bullets(rec.get("智能化与前沿应用", "")),
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="PHM 知识库大纲 Part2 → CSV/JSON 转换")
    parser.add_argument("input", help="输入 Markdown 文件路径")
    parser.add_argument("-o", "--output", help="输出文件前缀（默认从输入文件名推导）")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"文件不存在: {src}")
        return

    prefix = args.output or src.stem
    csv_path = Path(f"{prefix}_equipment.csv")
    json_path = Path(f"{prefix}_equipment.json")

    # 解析
    records = parse_part2(src)
    print(f"解析到 {len(records)} 个设备条目")

    # 输出设备列表
    for r in records:
        print(f"  {r['设备编号']} {r['设备名称']} ({r['行业名称']})")

    # ---- CSV ----
    rows = [flatten_record(r) for r in records]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nCSV 已生成: {csv_path} ({len(rows)} 行)")

    # ---- JSON（嵌套结构） ----
    nested = [to_nested_json(r) for r in records]
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(nested, f, ensure_ascii=False, indent=2)
    print(f"JSON 已生成: {json_path} ({len(nested)} 条)")

    # 统计各维度填充率
    print("\n--- 维度填充率 ---")
    for dim in DIM_ORDER:
        filled = sum(1 for r in records if r.get(dim, "").strip())
        print(f"  {dim}: {filled}/{len(records)} ({100*filled//len(records)}%)")


if __name__ == "__main__":
    main()
