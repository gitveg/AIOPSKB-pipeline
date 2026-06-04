"""
将 Markdown 知识库大纲转化为结构化 JSON。

用法:
  python src/scripts/md_to_json.py [行业目录]
  python src/scripts/md_to_json.py src/data/power

默认输出到 stdout，可用 > 重定向到文件。
"""

import json
import os
import re
import sys
import hashlib

# ── 目录名映射（与 orchestrator._slug_sub / _slug_eq 对齐）──

SUB_SLUGS = {
    "火电": "thermal", "水电": "hydro", "风电": "wind", "光伏": "pv",
    "核电": "nuclear", "燃气轮机": "gas_turbine", "抽水蓄能": "pumped_storage",
    "输电": "transmission", "变电": "substation", "配电": "distribution",
    "储能": "energy_storage",
}

EQ_SLUGS = {
    "锅炉": "boiler", "汽轮机": "steam_turbine", "发电机": "generator",
    "主变压器": "main_transformer", "凝汽器": "condenser",
    "励磁系统": "excitation_system",
    "冷却塔": "湿冷塔", "空冷岛": "空冷岛",
    "水轮机": "hydro_turbine",
    "反应堆压力容器": "reactor_vessel", "光伏组件": "pv_module",
    "逆变器": "inverter", "燃气轮机": "gas_turbine",
    "蒸汽发生器": "steam_generator",
    "发电机出口断路器": "发电机出口断路器(GCB)",
    "箱式变压器（风电用）": "箱式变压器",
}

FAULT_COLUMNS = [
    "故障名称", "D1_故障类别", "D2_故障等级", "D3_故障描述与机理",
    "D4_故障征兆", "D5_故障特征参数", "D6_监测与检测手段",
    "D7_诊断方法", "D8_检修方法", "D9_预防措施", "D10_易混淆故障",
]


# ── Markdown 表格解析 ──

def parse_md_table(filepath: str) -> list[dict]:
    """解析 Markdown 表格，返回 dict 列表。"""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    rows = []
    headers = None
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        cells = [c.strip().strip("*") for c in line.split("|")[1:-1]]
        if not cells:
            continue
        if headers is None:
            # Normalize header names: strip D-prefix labels for fault tables
            headers = cells
            continue
        if headers is None or len(cells) != len(headers):
            continue
        row = {}
        for h, v in zip(headers, cells):
            row[h] = v if v not in ("—", "-", "") else None
        rows.append(row)
    return rows


def parse_fault_table(filepath: str) -> list[dict]:
    """解析故障表格，标准化列名。"""
    raw_rows = parse_md_table(filepath)
    results = []
    for row in raw_rows:
        # 取第一列作为故障名称（无论实际列名是什么）
        first_key = list(row.keys())[0] if row else None
        fault_name = row.pop(first_key, None) if first_key and first_key not in FAULT_COLUMNS else None

        fault = {}
        fault["故障名称"] = fault_name or row.get("故障名称", "")

        # 映射剩余列到标准化维度名（长前缀先匹配，避免D1匹配到D10）
        DIM_MAP = [
            ("D10", "D10_易混淆故障"),
            ("D9", "D9_预防措施"), ("D8", "D8_检修方法"),
            ("D7", "D7_诊断方法"), ("D6", "D6_监测与检测手段"),
            ("D5", "D5_故障特征参数"), ("D4", "D4_故障征兆"),
            ("D3", "D3_故障描述与机理"), ("D2", "D2_故障等级"),
            ("D1", "D1_故障类别"),
        ]
        key_map = {}
        for k in row:
            kl = k.strip()
            for prefix, std_name in DIM_MAP:
                if kl.startswith(prefix):
                    key_map[k] = std_name
                    break

        for orig, std in key_map.items():
            val = row.get(orig)
            fault[std] = val if val else None

        results.append(fault)
    return results


# ── 目录名反向查找 ──

def find_sub_dir(industry_dir: str, sub_name: str) -> str | None:
    """根据子行业名称查找目录。"""
    slug = SUB_SLUGS.get(sub_name)
    if slug and os.path.isdir(os.path.join(industry_dir, slug)):
        return os.path.join(industry_dir, slug)
    # fallback: 遍历子目录，读取 index 内容匹配
    return None


def find_eq_dir(sub_dir: str, eq_name: str) -> str | None:
    """根据设备名称查找目录。"""
    # 先查已知映射
    slug = EQ_SLUGS.get(eq_name)
    if slug and os.path.isdir(os.path.join(sub_dir, slug)):
        return os.path.join(sub_dir, slug)
    # 直接用设备名作为目录名
    direct_slug = eq_name.replace("/", "_").replace("／", "_").replace("（", "(").replace("）", ")")
    if os.path.isdir(os.path.join(sub_dir, direct_slug)):
        return os.path.join(sub_dir, direct_slug)
    return None


# ── 构建逻辑 ──

def build_component_tree(rows: list[dict]) -> list[dict]:
    """将扁平的部件表构建为树，返回所有部件（含子部件嵌套）。"""
    nodes = {}
    for row in rows:
        name = row.get("部件名称", "")
        parent = row.get("父部件")
        desc = row.get("描述", "")
        consumable = row.get("易损标识") == "是"
        nodes[name] = {
            "name": name,
            "parent": parent,
            "description": desc,
            "is_consumable": consumable,
            "维护方法": row.get("维护方法"),
            "报废方法": row.get("报废方法"),
            "children": [],
        }

    # 找出叶节点（没有子部件的部件）
    parent_set = {n["parent"] for n in nodes.values() if n["parent"]}
    for name, node in nodes.items():
        node["is_leaf"] = name not in parent_set

    # 构建树
    roots = []
    for name, node in nodes.items():
        parent = node["parent"]
        if parent and parent in nodes:
            nodes[parent]["children"].append(node)
        else:
            roots.append(node)
    return roots, nodes


def load_faults(eq_dir: str, comp_name: str) -> list[dict]:
    """加载某个部件的故障数据。"""
    faults_dir = os.path.join(eq_dir, "faults")
    if not os.path.isdir(faults_dir):
        return []
    if not comp_name:
        return []
    safe_comp = comp_name.replace("/", "／")
    fault_path = os.path.join(faults_dir, f"{safe_comp}.md")
    if not os.path.exists(fault_path):
        return []
    return parse_fault_table(fault_path)


def enrich_components_with_faults(eq_dir: str, nodes: dict):
    """为所有部件（含父部件）附加故障数据。"""
    for name, node in nodes.items():
        faults = load_faults(eq_dir, name)
        if faults:
            node["faults"] = faults


def _sanitize_dirname(name: str) -> str:
    """将子设备名称转为安全的目录名。"""
    return name.replace("/", "／").replace("\\", "＼").strip()


def build_equipment(sub_dir: str, eq_name: str, eq_type: str, eq_desc: str) -> dict:
    """构建单个设备的完整数据。"""
    eq_dir = find_eq_dir(sub_dir, eq_name)
    result = {
        "name": eq_name,
        "type": eq_type,
        "description": eq_desc,
    }

    if not eq_dir:
        return result

    # 子设备元数据
    sub_eq_path = os.path.join(eq_dir, "sub_equipment.md")
    sub_eq_names = []
    if os.path.exists(sub_eq_path):
        sub_eq_rows = parse_md_table(sub_eq_path)
        if sub_eq_rows:
            result["sub_equipment"] = [
                {"name": r.get("子设备名称", ""), "description": r.get("描述", "")}
                for r in sub_eq_rows
            ]
            sub_eq_names = [r.get("子设备名称", "") for r in sub_eq_rows if r.get("子设备名称")]

    if sub_eq_names:
        # 有子设备：从子设备子目录读取各自的 components.md 和 faults/
        all_components = []
        for se_name in sub_eq_names:
            se_dirname = _sanitize_dirname(se_name)
            se_dir = os.path.join(eq_dir, se_dirname)
            if not os.path.isdir(se_dir):
                continue
            comp_path = os.path.join(se_dir, "components.md")
            if not os.path.exists(comp_path):
                continue
            comp_rows = parse_md_table(comp_path)
            if not comp_rows:
                continue
            _, nodes = build_component_tree(comp_rows)
            enrich_components_with_faults(se_dir, nodes)
            for n in nodes.values():
                comp_dict = {
                    "name": n["name"],
                    "parent": n["parent"],
                    "description": n["description"],
                    "is_consumable": n["is_consumable"],
                    "维护方法": n.get("维护方法"),
                    "报废方法": n.get("报废方法"),
                    "faults": n.get("faults", []),
                    "sub_equipment": se_name,
                }
                all_components.append(comp_dict)
        if all_components:
            result["components"] = all_components
    else:
        # 无子设备：原逻辑，直接在设备目录下读取
        comp_path = os.path.join(eq_dir, "components.md")
        if os.path.exists(comp_path):
            comp_rows = parse_md_table(comp_path)
            if comp_rows:
                _, nodes = build_component_tree(comp_rows)
                enrich_components_with_faults(eq_dir, nodes)
                result["components"] = [
                    {
                        "name": n["name"],
                        "parent": n["parent"],
                        "description": n["description"],
                        "is_consumable": n["is_consumable"],
                        "维护方法": n.get("维护方法"),
                        "报废方法": n.get("报废方法"),
                        "faults": n.get("faults", []),
                    }
                    for n in nodes.values()
                ]

    return result


def build_sub_industry(industry_dir: str, sub_name: str, sub_desc: str) -> dict:
    """构建单个子行业的完整数据。"""
    sub_dir = find_sub_dir(industry_dir, sub_name)
    result = {"name": sub_name, "description": sub_desc, "equipment": []}

    if not sub_dir:
        return result

    eq_registry = os.path.join(sub_dir, "equipment_registry.md")
    eq_rows = parse_md_table(eq_registry)
    for eq_row in eq_rows:
        eq_name = eq_row.get("设备名称", "")
        eq_type = eq_row.get("设备类型", "")
        eq_desc = eq_row.get("描述", "")
        result["equipment"].append(build_equipment(sub_dir, eq_name, eq_type, eq_desc))

    return result


def build_industry(industry_dir: str) -> dict:
    """构建整个行业的完整 JSON 数据。"""
    industry_name = os.path.basename(industry_dir)
    # 从目录名还原中文名
    name_map = {
        "power": "电力", "petrochemical": "石化", "metallurgy": "冶金",
        "cement": "水泥", "coal": "煤炭", "rail_transit": "轨道交通",
        "manufacturing": "制造业", "aerospace_marine": "航空航天与船舶",
    }
    industry_cn = name_map.get(industry_name, industry_name)

    result = {"industry": industry_cn}

    # 子行业
    index_path = os.path.join(industry_dir, "index.md")
    sub_rows = parse_md_table(index_path)
    if sub_rows:
        result["sub_industries"] = [
            build_sub_industry(industry_dir, r.get("子行业名称", ""), r.get("描述", ""))
            for r in sub_rows
        ]
    else:
        # 无子行业，直接读设备
        eq_registry = os.path.join(industry_dir, "equipment_registry.md")
        eq_rows = parse_md_table(eq_registry)
        result["equipment"] = [
            build_equipment(industry_dir, r.get("设备名称", ""), r.get("设备类型", ""), r.get("描述", ""))
            for r in eq_rows
        ]

    return result


# ── 统计 ──

def count_stats(data: dict) -> dict:
    stats = {"sub_industries": 0, "equipment": 0, "sub_equipment": 0,
             "components": 0, "faults": 0, "faults_with_details": 0}

    subs = data.get("sub_industries", [])
    if subs:
        stats["sub_industries"] = len(subs)
        for sub in subs:
            for eq in sub.get("equipment", []):
                stats["equipment"] += 1
                stats["sub_equipment"] += len(eq.get("sub_equipment", []))
                for comp in eq.get("components", []):
                    stats["components"] += 1
                    faults = comp.get("faults", [])
                    stats["faults"] += len(faults)
                    stats["faults_with_details"] += sum(
                        1 for f in faults if f.get("D3_故障描述与机理"))
    else:
        for eq in data.get("equipment", []):
            stats["equipment"] += 1
            stats["sub_equipment"] += len(eq.get("sub_equipment", []))
            for comp in eq.get("components", []):
                stats["components"] += 1
                faults = comp.get("faults", [])
                stats["faults"] += len(faults)
                stats["faults_with_details"] += sum(
                    1 for f in faults if f.get("D3_故障描述与机理"))

    return stats


# ── 入口 ──

def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    if len(sys.argv) > 1:
        industry_dir = sys.argv[1]
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        industry_dir = os.path.join(script_dir, "..", "data", "power")

    industry_dir = os.path.normpath(industry_dir)

    if not os.path.isdir(industry_dir):
        print(f"目录不存在: {industry_dir}", file=sys.stderr)
        sys.exit(1)

    data = build_industry(industry_dir)
    stats = count_stats(data)

    # 输出 JSON
    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    # 写入文件
    out_path = os.path.join(industry_dir, "knowledge_base.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(json_str)

    # 统计输出到 stderr
    print(f"\n── 转化统计 ──", file=sys.stderr)
    for k, v in stats.items():
        print(f"  {k}: {v}", file=sys.stderr)
    print(f"\n已输出: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
