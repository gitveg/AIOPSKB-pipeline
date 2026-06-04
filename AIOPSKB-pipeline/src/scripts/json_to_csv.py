"""
将 knowledge_base.json 转化为 CSV 和 XLSX 格式。

用法:
  python src/scripts/json_to_csv.py [json路径] [输出路径前缀]
  python src/scripts/json_to_csv.py src/data/power/knowledge_base.json src/data/power/knowledge_base

默认使用 src/data/power/knowledge_base.json，输出同目录下的 .csv 和 .xlsx 文件。
"""

import csv
import json
import os
import sys

COLUMNS = [
    "行业", "子行业", "设备名称", "设备类型", "设备描述", "子设备",
    "部件名称", "父部件", "部件描述", "易损标识", "维护方法", "报废方法",
    "故障名称",
    "D1_故障类别", "D2_故障等级", "D3_故障描述与机理",
    "D4_故障征兆", "D5_故障特征参数", "D6_监测与检测手段",
    "D7_诊断方法", "D8_检修方法", "D9_预防措施", "D10_易混淆故障",
]

FAULT_DIMS = [c for c in COLUMNS if c.startswith("D")]


def flatten(data: dict) -> list[dict]:
    """将层级 JSON 展开为扁平行列表。"""
    rows = []
    industry = data.get("industry", "")

    for sub in data.get("sub_industries", []):
        sub_name = sub.get("name", "")
        for eq in sub.get("equipment", []):
            _flatten_equipment(rows, industry, sub_name, eq)

    for eq in data.get("equipment", []):
        _flatten_equipment(rows, industry, "", eq)

    return rows


def _flatten_component(rows, industry, sub_name, eq_name, eq_type, eq_desc, sub_eq_str, comp):
    comp_name = comp.get("name", "")
    comp_parent = comp.get("parent", "")
    comp_desc = comp.get("description", "")
    comp_consumable = "是" if comp.get("is_consumable") else "否"
    comp_maint = comp.get("维护方法", "") or ""
    comp_disposal = comp.get("报废方法", "") or ""

    faults = comp.get("faults", [])
    if faults:
        for fault in faults:
            row = {
                "行业": industry,
                "子行业": sub_name,
                "设备名称": eq_name,
                "设备类型": eq_type,
                "设备描述": eq_desc,
                "子设备": sub_eq_str,
                "部件名称": comp_name,
                "父部件": comp_parent,
                "部件描述": comp_desc,
                "易损标识": comp_consumable,
                "维护方法": comp_maint,
                "报废方法": comp_disposal,
                "故障名称": fault.get("故障名称", "") or "",
            }
            for dim in FAULT_DIMS:
                row[dim] = fault.get(dim, "") or ""
            rows.append(row)
    else:
        rows.append({
            "行业": industry,
            "子行业": sub_name,
            "设备名称": eq_name,
            "设备类型": eq_type,
            "设备描述": eq_desc,
            "子设备": sub_eq_str,
            "部件名称": comp_name,
            "父部件": comp_parent,
            "部件描述": comp_desc,
            "易损标识": comp_consumable,
            "维护方法": comp_maint,
            "报废方法": comp_disposal,
            "故障名称": "",
            **{dim: "" for dim in FAULT_DIMS},
        })


def _flatten_equipment(rows, industry, sub_name, eq):
    eq_name = eq.get("name", "")
    eq_type = eq.get("type", "")
    eq_desc = eq.get("description", "")

    # 子设备元数据（用于无 components 时的 fallback 显示）
    sub_eqs = eq.get("sub_equipment", [])
    sub_eq_str = "；".join(s.get("name", "") for s in sub_eqs) if sub_eqs else ""

    components = eq.get("components", [])
    if components:
        for comp in components:
            # 优先使用 component 自带的 sub_equipment 字段（来自子设备目录）
            specific_se = comp.get("sub_equipment", "")
            _flatten_component(rows, industry, sub_name, eq_name, eq_type, eq_desc,
                               specific_se or sub_eq_str, comp)
    else:
        rows.append({
            "行业": industry,
            "子行业": sub_name,
            "设备名称": eq_name,
            "设备类型": eq_type,
            "设备描述": eq_desc,
            "子设备": sub_eq_str,
            "部件名称": "",
            "父部件": "",
            "部件描述": "",
            "易损标识": "",
            "维护方法": "",
            "报废方法": "",
            "故障名称": "",
            **{dim: "" for dim in FAULT_DIMS},
        })


def write_csv(rows: list[dict], csv_path: str):
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(rows: list[dict], xlsx_path: str):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()

    # ── Sheet1: 故障知识库（全部数据）──
    ws = wb.active
    ws.title = "故障知识库"

    header_font = Font(bold=True, size=11)
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font_white = Font(bold=True, size=11, color="FFFFFF")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )
    wrap_alignment = Alignment(wrap_text=True, vertical="top")

    # Header
    for col_idx, col_name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Data
    for row_idx, row_data in enumerate(rows, 2):
        for col_idx, col_name in enumerate(COLUMNS, 1):
            val = row_data.get(col_name, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = thin_border
            cell.alignment = wrap_alignment

    # Column widths
    col_widths = {
        "行业": 8, "子行业": 10, "设备名称": 18, "设备类型": 10, "设备描述": 25,
        "子设备": 20,
        "部件名称": 18, "父部件": 12, "部件描述": 20, "易损标识": 8,
        "故障名称": 22,
    }
    for col_idx, col_name in enumerate(COLUMNS, 1):
        width = col_widths.get(col_name, 30)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # Freeze top row
    ws.freeze_panes = "A2"
    # Auto-filter
    ws.auto_filter.ref = ws.dimensions

    # ── Sheet2: 统计概览 ──
    ws2 = wb.create_sheet("统计概览")

    # Aggregate stats
    sub_stats = {}
    for r in rows:
        sub = r.get("子行业", "(无子行业)")
        eq = r.get("设备名称", "")
        has_fault = bool(r.get("故障名称"))
        if sub not in sub_stats:
            sub_stats[sub] = {"设备": set(), "部件": 0, "故障": 0}
        sub_stats[sub]["设备"].add(eq)
        sub_stats[sub]["部件"] += 1
        if has_fault:
            sub_stats[sub]["故障"] += 1

    stats_headers = ["子行业", "设备数", "部件数", "含故障部件数"]
    for col_idx, h in enumerate(stats_headers, 1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = header_font_white
        cell.fill = header_fill
        cell.border = thin_border

    for row_idx, (sub, stats) in enumerate(sub_stats.items(), 2):
        ws2.cell(row=row_idx, column=1, value=sub).border = thin_border
        ws2.cell(row=row_idx, column=2, value=len(stats["设备"])).border = thin_border
        ws2.cell(row=row_idx, column=3, value=stats["部件"]).border = thin_border
        ws2.cell(row=row_idx, column=4, value=stats["故障"]).border = thin_border

    ws2.column_dimensions["A"].width = 15
    ws2.column_dimensions["B"].width = 10
    ws2.column_dimensions["C"].width = 10
    ws2.column_dimensions["D"].width = 14
    ws2.freeze_panes = "A2"

    wb.save(xlsx_path)


def main():
    sys.stdout.reconfigure(encoding='utf-8')

    if len(sys.argv) > 1:
        json_path = sys.argv[1]
    else:
        json_path = os.path.join(os.path.dirname(__file__), "..", "data", "power", "knowledge_base.json")

    json_path = os.path.normpath(json_path)

    if len(sys.argv) > 2:
        out_prefix = sys.argv[2]
    else:
        out_prefix = json_path.replace(".json", "")

    out_prefix = os.path.normpath(out_prefix)

    if not os.path.exists(json_path):
        print(f"文件不存在: {json_path}", file=sys.stderr)
        sys.exit(1)

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows = flatten(data)
    fault_count = sum(1 for r in rows if r.get("故障名称"))
    comp_count = len(rows)

    # CSV
    csv_path = out_prefix + ".csv"
    write_csv(rows, csv_path)
    print(f"CSV:  {csv_path}", file=sys.stderr)

    # XLSX
    xlsx_path = out_prefix + ".xlsx"
    write_xlsx(rows, xlsx_path)
    print(f"XLSX: {xlsx_path}", file=sys.stderr)

    print(f"  总行数: {comp_count} (含故障: {fault_count}, 无故障部件: {comp_count - fault_count})", file=sys.stderr)


if __name__ == "__main__":
    main()
