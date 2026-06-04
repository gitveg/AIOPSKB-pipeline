"""
D5 置信标注重跑脚本

对已有知识库的故障文件，仅刷新 D5 列的置信标注（标准值/经验值/经验值-未核实）。
不触碰其他列（D1-D4, D6-D10）。

用法：
    python -m scripts.rerun_d5 --industry wind
    python -m scripts.rerun_d5 --industry wind --equipment 箱式变压器
    python -m scripts.rerun_d5 --industry wind --equipment 箱式变压器 --component 分接开关
    python -m scripts.rerun_d5 --industry wind --dry-run
    python -m scripts.rerun_d5 --industry wind --skip-checker
"""

import argparse
import json
import os
import re
import sys
import time

# Ensure pipeline is importable
_pipeline_dir = os.path.join(os.path.dirname(__file__), '..', 'pipeline')
sys.path.insert(0, os.path.abspath(_pipeline_dir))
_src_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.abspath(_src_dir))

from pipeline.agents.base import call_llm
from pipeline.agents.standard_checker import run_standard_checker
from pipeline.config import D5_STANDARD_REFERENCE, select_relevant_domains
from pipeline.file_manager import read_kb_file, write_kb_file

INDUSTRY_MAP = {
    "wind": "风电", "thermal": "火电", "hydro": "水电", "nuclear": "核电",
    "pv": "光伏", "distribution": "配电", "transmission": "输电",
    "substation": "变电站", "energy_storage": "储能",
}

D5_RERUN_SYSTEM = """你是工业设备技术标准核查专家，专注于中国电力、石化、冶金等行业。

你的任务是对已有故障特征参数（D5字段）的置信标注进行重评。工作原则：
- 对已有参数的置信级别进行重新评估
- 如果你确知对应标准号且数值与标准一致，标注"标准值"
- 行业通用经验但无标准可引的参数，标注"经验值"
- 仅当同一参数出现来源冲突且无法裁断时才标"待核实"
- 不确定来源不是"待核实"的理由——找不到标准号就标"经验值"
- 宁可标"经验值"也绝不编造标准号

输出必须是合法JSON，不要在前后添加任何其他文字。"""


def _build_std_hint(equip: str, comp: str) -> str:
    relevant = select_relevant_domains(comp, equip, f"{equip} {comp}")
    lines = []
    for domain in relevant:
        info = D5_STANDARD_REFERENCE[domain]
        std_list = "、".join(std[0] for std in info["standards"])
        lines.append(f"  {domain} → {std_list}")
    return "\n".join(lines)


def _build_rerun_prompt(ctx_str: str, d5_rows: list[tuple[str, str]], std_hint: str) -> str:
    rows_text = "\n".join(
        f"| {name} | {d5} |" for name, d5 in d5_rows
    )
    return f"""请对以下【{ctx_str}】的故障特征参数（D5）进行置信标注重评。

现有D5参数：
| 故障名称 | D5特征参数 |
|---------|-----------|
{rows_text}

D5参数置信标注规则（收紧版）：
- 四级标注：标准值 / 经验值 / 经验值-未核实 / 待核实
- "标准值"：你能确定标准号且数值与标准一致，格式为：（适用：条件；标准号 条款，置信：标准值）
- "经验值"：行业通用经验但无标准可引，格式为：（置信：经验值）
- "待核实"：仅当同一参数在不同来源中出现矛盾数值且无法裁断时使用
- 不确定来源 ≠ 待核实，找不到标准号就标"经验值"
- 若参数已有正确标注则保留不动
- 若参数无标注（裸参数），则补充标注
- 若参数标注为"待核实"但你确知标准依据，则升级为"标准值"；否则降为"经验值"
- 保留所有现有参数条目和分隔符（；或<br>），仅修改/添加置信标注部分
- 若现有参数无"适用："条件但你能补充适用工况，则补充；不能则不加

标准速查表（按参数类型查找，非按设备）：
{std_hint}

以JSON格式返回（不加代码块标记）：
{{
  "updates": [
    {{
      "fault_name": "故障名称（与表格第一列完全一致）",
      "d5_revised": "完整修改后的D5单元格内容"
    }}
  ],
  "summary": "一句话总结"
}}

若某条故障的D5无需修改，不要列入updates。"""


# ── Table parsing ──────────────────────────────────────────────

def parse_fault_table(content: str) -> dict:
    """Parse markdown table, return structured data for D5 re-annotation.

    Returns: {
        "lines": list[str],       # original lines
        "d5_col_idx": int|None,   # 0-indexed D5 column
        "d5_rows": [(fault_name, d5_content), ...],
        "header_idx": int,        # line index of header row
    }
    """
    lines = content.split("\n")
    d5_col_idx = None
    header_idx = -1
    d5_rows = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if not cells:
            continue

        # Detect header row
        if d5_col_idx is None and any("D5" in c or "特征参数" in c for c in cells):
            d5_col_idx = next(
                (j for j, c in enumerate(cells) if "D5" in c or "特征参数" in c), None
            )
            header_idx = i
            continue

        # Skip separator row
        if re.match(r'^\|[\s\-:|]+\|$', stripped):
            continue

        # Data row
        if d5_col_idx is not None and d5_col_idx < len(cells):
            fault_name = cells[0].strip("*").strip()
            if fault_name and fault_name not in ("故障名称",):
                d5_content = cells[d5_col_idx]
                d5_rows.append((fault_name, d5_content))

    return {
        "lines": lines,
        "d5_col_idx": d5_col_idx,
        "d5_rows": d5_rows,
        "header_idx": header_idx,
    }


def apply_d5_updates(content: str, updates: dict[str, str], d5_col_idx: int) -> str:
    """Replace D5 cells in original content. updates: {fault_name: new_d5}"""
    if not updates or d5_col_idx is None:
        return content

    lines = content.split("\n")
    result = []

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            result.append(line)
            continue

        cells = [c.strip() for c in stripped.split("|")[1:-1]]
        if not cells:
            result.append(line)
            continue

        # Skip separator row
        if re.match(r'^\|[\s\-:|]+\|$', stripped):
            result.append(line)
            continue

        # Skip header row (contains column title keywords)
        if any(c.strip() in ("故障名称", "D1 故障类别", "D2 故障等级", "D3 故障描述与机理",
                              "D4 故障征兆", "D5 故障特征参数", "D6 监测与检测手段",
                              "D7 诊断方法", "D8 检修方法", "D9 预防措施",
                              "D10 易混淆故障") for c in cells):
            result.append(line)
            continue

        # Data row
        fault_name = cells[0].strip("*").strip()
        if fault_name in updates and d5_col_idx < len(cells):
            cells[d5_col_idx] = updates[fault_name]
            result.append("| " + " | ".join(cells) + " |")
        else:
            result.append(line)

    return "\n".join(result)


# ── Context extraction ─────────────────────────────────────────

def extract_context(filepath: str) -> dict:
    """Derive context dict from file path.

    Supports two directory layouts patterns:
    1. Flat: data/power/wind/箱式变压器/faults/分接开关.md
       → {"industry": "电力", "sub_industry": "风电", "equipment": "箱式变压器", "component": "分接开关"}
    2. Sub-equipment: data/power/thermal/boiler/煤粉锅炉/faults/水冷壁.md
       → {"industry": "电力", "sub_industry": "火电", "equipment": "锅炉", "sub_equipment": "煤粉锅炉", "component": "水冷壁"}
    """
    parts = filepath.replace("\\", "/").split("/")
    equipment = comp = sub_equipment = ""
    for i, p in enumerate(parts):
        if p == "faults" and i > 0:
            parent_dir = parts[i - 1]
            grandparent_dir = parts[i - 2] if i >= 2 else ""

            # Check if grandparent has sub_equipment.md → parent is a sub-equipment directory
            if i >= 2:
                gp_path_parts = parts[:i - 1]
                gp_path = os.path.join(*gp_path_parts) if len(gp_path_parts) > 1 else gp_path_parts[0]
                if os.path.exists(os.path.join(gp_path, "sub_equipment.md")):
                    sub_equipment = parent_dir
                    equipment = grandparent_dir
                else:
                    equipment = parent_dir
            else:
                equipment = parent_dir

            comp = os.path.splitext(parts[i + 1])[0] if i + 1 < len(parts) else ""
            break
    return {
        "industry": "电力",
        "sub_industry": "风电",
        "equipment": equipment,
        "sub_equipment": sub_equipment,
        "component": comp,
    }


# ── D5 stats ──────────────────────────────────────────────────

def count_d5_labels(d5_rows: list[tuple[str, str]]) -> dict:
    """Count confidence label distribution across D5 content.

    Parses D5 params by finding [type] markers (e.g. [物理], [电气]),
    which are the canonical parameter boundaries. Avoids splitting on
    internal ； (U+FF1B) which separates 适用 clause from 置信 clause
    within a single parameter, not between parameters.
    """
    TYPE_TAG_RE = re.compile(
        r"\[(?:物理|化学|电气|状态量|热|机械|环境|绝缘|控制)\]"
    )
    stats = {"标准值": 0, "经验值": 0, "待核实": 0, "无标注": 0}
    for _, d5 in d5_rows:
        positions = list(TYPE_TAG_RE.finditer(d5))
        if not positions:
            continue
        for j, m in enumerate(positions):
            start = m.start()
            end = positions[j + 1].start() if j + 1 < len(positions) else len(d5)
            param_text = d5[start:end].strip()
            if "置信：标准值" in param_text:
                stats["标准值"] += 1
            elif "置信：经验值" in param_text:
                stats["经验值"] += 1
            elif "置信：待核实" in param_text:
                stats["待核实"] += 1
            elif "置信：unknown" in param_text:
                stats["待核实"] += 1
            else:
                stats["无标注"] += 1
    return stats


# ── Main logic ────────────────────────────────────────────────

def find_fault_files(data_root: str, industry: str,
                     equipment: str = None, component: str = None) -> list[str]:
    """Find fault files matching filters."""
    wind_dir = os.path.join(data_root, industry)
    if not os.path.isdir(wind_dir):
        print(f"目录不存在: {wind_dir}")
        return []

    files = []
    for root, dirs, fnames in os.walk(wind_dir):
        # Skip archive dirs
        if "_archive" in root:
            continue
        for fn in fnames:
            if not fn.endswith(".md"):
                continue
            if os.path.basename(root) != "faults":
                continue

            filepath = os.path.join(root, fn)
            rel = os.path.relpath(filepath, wind_dir)

            # Apply filters
            if equipment:
                eq_dir = os.path.basename(os.path.dirname(root))
                if eq_dir != equipment:
                    continue
            if component:
                comp_name = os.path.splitext(fn)[0]
                if comp_name != component:
                    continue

            files.append(filepath)

    return sorted(files)


def rerun_d5_file(filepath: str, skip_checker: bool = False) -> dict:
    """Re-annotate D5 for a single fault file.

    Returns: {
        "status": "updated"|"no_changes"|"error",
        "before": stats, "after": stats,
        "summary": str, "error": str|None,
    }
    """
    content = read_kb_file(filepath)
    if not content:
        return {"status": "error", "before": {}, "after": {}, "summary": "文件为空", "error": "empty"}

    parsed = parse_fault_table(content)
    if not parsed["d5_rows"]:
        return {"status": "error", "before": {}, "after": {}, "summary": "无D5数据行", "error": "no_data"}

    ctx = extract_context(filepath)
    ctx_str = " - ".join(filter(None, [
        ctx.get("sub_industry", ""),
        ctx.get("equipment", ""),
        ctx.get("component", ""),
    ]))

    before = count_d5_labels(parsed["d5_rows"])

    # Step 1: DeepSeek re-annotation
    std_hint = _build_std_hint(ctx["equipment"], ctx["component"])
    prompt = _build_rerun_prompt(ctx_str, parsed["d5_rows"], std_hint)

    raw = call_llm("collector", D5_RERUN_SYSTEM, prompt, temperature=0.1)
    cleaned = re.sub(r'```json\s*|```\s*', '', raw).strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # JSON parse failed — still apply regex fallback before giving up
        _residual = content.count("置信：待核实")
        _unknown = content.count("置信：unknown")
        fallback_content = content
        if _residual + _unknown > 0:
            fallback_content = content.replace("置信：待核实", "置信：经验值-未核实")
            fallback_content = fallback_content.replace("置信：unknown", "置信：经验值-未核实")
            write_kb_file(filepath, fallback_content)
            after_parsed = parse_fault_table(fallback_content)
            after = count_d5_labels(after_parsed["d5_rows"])
            return {"status": "fallback_only", "before": before, "after": after,
                    "summary": f"DeepSeek JSON解析失败，正则兜底转换{_residual+_unknown}条", "error": "parse_error"}
        return {
            "status": "error", "before": before, "after": before,
            "summary": f"DeepSeek返回JSON解析失败", "error": "parse_error",
        }

    updates_list = result.get("updates", [])
    update_map = {
        u["fault_name"].strip(): u["d5_revised"].strip()
        for u in updates_list
        if u.get("fault_name") and u.get("d5_revised")
    }

    if not update_map:
        if skip_checker:
            return {"status": "no_changes", "before": before, "after": before,
                    "summary": "D5无需修改", "error": None}
        updated = content
    else:
        updated = apply_d5_updates(content, update_map, parsed["d5_col_idx"])

    # Step 2: Kimi standard checker
    if not skip_checker:
        updated, checker_stats = run_standard_checker(ctx, updated)
        if checker_stats["status"] == "parse_error":
            print(f"  Kimi响应解析失败，跳过标准核查")

    # Step 3: Regex fallback
    _residual = updated.count("置信：待核实")
    _unknown = updated.count("置信：unknown")
    if _residual + _unknown > 0:
        updated = updated.replace("置信：待核实", "置信：经验值-未核实")
        updated = updated.replace("置信：unknown", "置信：经验值-未核实")

    # Step 4: Write back
    write_kb_file(filepath, updated)

    # Count after stats
    after_parsed = parse_fault_table(updated)
    after = count_d5_labels(after_parsed["d5_rows"])

    return {
        "status": "updated" if update_map else "checker_only",
        "before": before,
        "after": after,
        "summary": result.get("summary", ""),
        "error": None,
    }


def main():
    parser = argparse.ArgumentParser(description="D5 置信标注重跑")
    parser.add_argument("--industry", required=True, help="行业目录名 (wind/thermal/hydro/...)")
    parser.add_argument("--equipment", default=None, help="设备名过滤")
    parser.add_argument("--component", default=None, help="部件名过滤")
    parser.add_argument("--skip-checker", action="store_true", help="跳过Kimi标准核查（加速但降低质量）")
    parser.add_argument("--dry-run", action="store_true", help="仅统计不修改")
    args = parser.parse_args()

    data_root = os.path.join(os.path.dirname(__file__), '..', 'data', 'power')
    files = find_fault_files(data_root, args.industry, args.equipment, args.component)

    if not files:
        print("未找到匹配的故障文件")
        return

    industry_cn = INDUSTRY_MAP.get(args.industry, args.industry)
    print(f"找到 {len(files)} 个故障文件（{industry_cn}）")

    if args.dry_run:
        total_before = {"标准值": 0, "经验值": 0, "待核实": 0, "无标注": 0}
        for fp in files:
            content = read_kb_file(fp)
            if not content:
                continue
            parsed = parse_fault_table(content)
            stats = count_d5_labels(parsed["d5_rows"])
            for k in total_before:
                total_before[k] += stats.get(k, 0)
            rel = os.path.relpath(fp, data_root)
            print(f"  {rel}: 标准值={stats['标准值']}, 经验值={stats['经验值']}, "
                  f"待核实={stats['待核实']}, 无标注={stats['无标注']}")
        print(f"\n=== 总计 ===")
        print(f"标准值={total_before['标准值']}, 经验值={total_before['经验值']}, "
              f"待核实={total_before['待核实']}, 无标注={total_before['无标注']}")
        return

    # Live run
    results = []
    total_before = {"标准值": 0, "经验值": 0, "待核实": 0, "无标注": 0}
    total_after = {"标准值": 0, "经验值": 0, "待核实": 0, "经验值-未核实": 0, "无标注": 0}

    for i, fp in enumerate(files):
        rel = os.path.relpath(fp, data_root)
        print(f"\n[{i+1}/{len(files)}] {rel}")

        try:
            r = rerun_d5_file(fp, skip_checker=args.skip_checker)
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"file": rel, "status": "error", "error": str(e)})
            continue

        results.append({"file": rel, **r})
        for k in total_before:
            total_before[k] += r["before"].get(k, 0)
        for k in total_after:
            total_after[k] += r["after"].get(k, 0)

        print(f"  {r['status']}: {r['summary']}")
        if r["before"] != r["after"]:
            print(f"  Before: {r['before']}")
            print(f"  After:  {r['after']}")

    # Write report
    report_dir = os.path.join(os.path.dirname(__file__), '..', 'reports')
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, "d5_rerun_stats.txt")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"D5 置信标注重跑报告 — {industry_cn}\n")
        f.write(f"{'='*60}\n\n")
        for r in results:
            f.write(f"文件: {r['file']}\n")
            f.write(f"  状态: {r['status']}\n")
            if r.get("summary"):
                f.write(f"  摘要: {r['summary']}\n")
            if r.get("error"):
                f.write(f"  错误: {r['error']}\n")
            f.write(f"  Before: {r.get('before', {})}\n")
            f.write(f"  After:  {r.get('after', {})}\n\n")
        f.write(f"{'='*60}\n")
        f.write(f"总计 ({len(files)} 文件)\n")
        f.write(f"Before: {total_before}\n")
        f.write(f"After:  {total_after}\n")

    print(f"\n{'='*60}")
    print(f"总计 ({len(files)} 文件)")
    print(f"Before: {total_before}")
    print(f"After:  {total_after}")
    print(f"\n报告已写入: {report_path}")


if __name__ == "__main__":
    main()
