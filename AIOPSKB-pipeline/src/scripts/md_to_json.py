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

# ── 编码常量（改造7：优先从 pipeline.config 导入，失败则用内置 fallback）──
try:
    import sys as _sys, os as _os
    _SRC = _os.path.normpath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".."))
    if _SRC not in _sys.path:
        _sys.path.insert(0, _SRC)
    from pipeline.config import INDUSTRY_CODES, SUB_INDUSTRY_CODES
except Exception:
    INDUSTRY_CODES = {"电力": "PW", "石化": "PE", "冶金": "MT", "水泥": "CM",
                       "煤炭": "CL", "轨道交通": "RT", "制造业": "MF", "航空航天与船舶": "AS"}
    SUB_INDUSTRY_CODES = {"火电": "TH", "水电": "HY", "风电": "WI", "光伏": "PV",
                          "核电": "NU", "燃气轮机": "GT", "抽水蓄能": "PS",
                          "输电": "TM", "变电": "SS", "配电": "DS", "储能": "ES"}

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
    "风机": "风机", "离心泵": "离心泵", "压缩机": "压缩机",
}

FAULT_COLUMNS = [
    "故障名称", "故障类别", "D1_物理属性", "D2_故障等级", "D3_故障描述与机理",
    "D4_故障征兆", "D5_故障特征参数", "D6_监测与检测手段",
    "D7_诊断方法", "D8_检修方法", "D9_预防措施", "D10_易混淆故障",
    "D11_用工需求", "D12_工机具", "D13_备件用料", "D14_安全注意事项", "D15_验收标准",  # 改造6新增检维修5列（D11-D15）
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
    for lineno, line in enumerate(content.split("\n"), 1):
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
        if headers is None:
            continue
        if len(cells) != len(headers):
            print(f"⚠️ 告警: {filepath}:{lineno} 列数({len(cells)})≠表头({len(headers)})，该行将被跳过（可能数据丢失）", file=sys.stderr)
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
            ("故障类别", "故障类别"),  # 故障类别列（改造5新增，无D前缀，精确匹配）
            ("D11", "D11_用工需求"), ("D12", "D12_工机具"),
            ("D13", "D13_备件用料"), ("D14", "D14_安全注意事项"),
            ("D15", "D15_验收标准"),  # 改造6新增检维修5列（D11-D15，须在D10/D1前匹配避免D1误匹配D11）
            ("D10", "D10_易混淆故障"),
            ("D9", "D9_预防措施"), ("D8", "D8_检修方法"),
            ("D7", "D7_诊断方法"), ("D6", "D6_监测与检测手段"),
            ("D5", "D5_故障特征参数"), ("D4", "D4_故障征兆"),
            ("D3", "D3_故障描述与机理"), ("D2", "D2_故障等级"),
            ("D1", "D1_物理属性"),
            ("D1", "D1_故障类别")  # backward compat
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

def is_new_format(directory: str) -> bool:
    """检测目录是否使用新的三层结构。"""
    return os.path.exists(os.path.join(directory, "sub_system.md"))


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


def load_faults_from_dir(item_dir: str, item_name: str) -> list[dict]:
    """从 item_dir/faults/item_name.md 加载故障数据（新格式用）。"""
    faults_dir = os.path.join(item_dir, "faults")
    if not os.path.isdir(faults_dir):
        return []
    safe_name = item_name.replace("/", "／")
    fault_path = os.path.join(faults_dir, f"{safe_name}.md")
    if not os.path.exists(fault_path):
        return []
    return parse_fault_table(fault_path)


def build_component_tree_new(rows: list[dict]) -> list[dict]:
    """新格式：将部件+零件表构建为分组结构。
    返回: [{name, description, is_consumable, 维护方法, 报废方法, parts: [...], faults: []}]
    """
    components = {}
    for row in rows:
        comp_name = row.get("部件", "")
        part_name = row.get("零件", "")
        desc = row.get("描述", "")
        consumable = row.get("易损标识") == "是"
        maint = row.get("维护方法", "—")
        disposal = row.get("报废方法", "—")

        if part_name in ("—", "-", "", None):
            # Component standalone row
            if comp_name not in components:
                components[comp_name] = {
                    "name": comp_name,
                    "description": desc,
                    "is_consumable": consumable,
                    "维护方法": maint,
                    "报废方法": disposal,
                    "parts": [],
                    "faults": [],
                }
            else:
                components[comp_name]["description"] = desc
                components[comp_name]["is_consumable"] = consumable
                components[comp_name]["维护方法"] = maint
                components[comp_name]["报废方法"] = disposal
        else:
            # Part row
            if comp_name not in components:
                components[comp_name] = {
                    "name": comp_name,
                    "description": "",
                    "is_consumable": False,
                    "维护方法": "—",
                    "报废方法": "—",
                    "parts": [],
                    "faults": [],
                }
            components[comp_name]["parts"].append({
                "name": part_name,
                "description": desc,
                "is_consumable": consumable,
                "faults": [],
            })

    return list(components.values())


def enrich_components_with_faults(eq_dir: str, nodes: dict):
    """为所有部件（含父部件）附加故障数据。"""
    for name, node in nodes.items():
        faults = load_faults(eq_dir, name)
        if faults:
            node["faults"] = faults


def _sanitize_dirname(name: str) -> str:
    """将子设备名称转为安全的目录名。"""
    return name.replace("/", "／").replace("\\", "＼").strip()


def _build_sub_systems_new(base_dir: str, sub_eq_name: str) -> list[dict]:
    """构建新格式的子系统数据（含部件、零件、故障）。
    base_dir: 子设备目录（有子设备时）或设备目录（无子设备时）。
    sub_eq_name: 子设备名称（无子设备时为空字符串）。
    """
    sub_systems = []
    ss_path = os.path.join(base_dir, "sub_system.md")
    if not os.path.exists(ss_path):
        return sub_systems
    ss_rows = parse_md_table(ss_path)
    for ss_row in ss_rows:
        ss_name = ss_row.get("子系统名称", "")
        ss_desc = ss_row.get("描述", "")
        ss_dir = os.path.join(base_dir, ss_name)
        ss_data = {"name": ss_name, "description": ss_desc, "sub_equipment": sub_eq_name}

        comp_path = os.path.join(ss_dir, "components.md")
        if os.path.exists(comp_path):
            comp_rows = parse_md_table(comp_path)
            tree = build_component_tree_new(comp_rows)
            # 为每个部件和零件加载故障数据
            for comp in tree:
                comp_dir = os.path.join(ss_dir, comp["name"])
                comp["faults"] = load_faults_from_dir(comp_dir, comp["name"])
                for part in comp.get("parts", []):
                    part_dir = os.path.join(ss_dir, part["name"])
                    part["faults"] = load_faults_from_dir(part_dir, part["name"])
            ss_data["components"] = tree

        sub_systems.append(ss_data)
    return sub_systems


def build_equipment(sub_dir: str, eq_name: str, eq_type: str, eq_desc: str) -> dict:
    """构建单个设备的完整数据。"""
    eq_dir = find_eq_dir(sub_dir, eq_name)
    result = {
        "name": eq_name,
        "attribute": eq_type,
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
        # 有子设备：从子设备子目录读取
        all_components = []
        sub_systems_all = []
        for se_name in sub_eq_names:
            se_dirname = _sanitize_dirname(se_name)
            se_dir = os.path.join(eq_dir, se_dirname)
            if not os.path.isdir(se_dir):
                continue

            if is_new_format(se_dir):
                # 新格式：子系统目录结构
                ss_data = _build_sub_systems_new(se_dir, se_name)
                sub_systems_all.extend(ss_data)
            else:
                # 旧格式
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

        if sub_systems_all:
            result["sub_systems"] = sub_systems_all
        if all_components:
            result["components"] = all_components
    else:
        # 无子设备
        if is_new_format(eq_dir):
            result["sub_systems"] = _build_sub_systems_new(eq_dir, "")
        else:
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
        eq_name = eq_row.get("设备类型名称", "")
        eq_type = eq_row.get("设备属性", "")
        eq_desc = eq_row.get("描述", "")
        result["equipment"].append(build_equipment(sub_dir, eq_name, eq_type, eq_desc))

    return result


def build_industry(industry_dir: str) -> dict:
    """构建整个行业的完整 JSON 数据。"""
    industry_name = os.path.basename(industry_dir)
    # 从目录名还原中文名
    name_map = {
        "power": "电力", "petrochemical": "石化", "metallurgy": "冶金", "steel": "钢铁",
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
            build_equipment(industry_dir, r.get("设备类型名称", ""), r.get("设备属性", ""), r.get("描述", ""))
            for r in eq_rows
        ]

    return result


# ── 编码生成（改造7）──

def build_code(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, part_idx, fault_idx=None) -> str:
    """构造段式编码。

    格式: {行业2}-[子行业2]-{设备3}-[子设备3]-{子系统3}-{部件3}-{零件3}-[{故障3}]

    - sub_code / se_idx 为 None 时省略对应段（子行业、子设备按需存在）
    - ss_idx / part_idx 可为 "000" 字符串（旧格式子系统段 / 部件级故障的零件段占位）
    - fault_idx 为 None 时为结构节点（部件/零件），省略故障段
    - 零件段恒在（部件级故障填 000），保证尾部段数固定、解析无歧义
    """
    def _seg(v):
        if v is None:
            return None
        if isinstance(v, str):
            return v
        return f"{int(v):03d}"

    parts = [ind_code]
    if sub_code:
        parts.append(sub_code)
    parts.append(_seg(eq_idx))
    if se_idx is not None:
        parts.append(_seg(se_idx))
    parts.append(_seg(ss_idx))
    parts.append(_seg(comp_idx))
    parts.append(_seg(part_idx))
    if fault_idx is not None:
        parts.append(_seg(fault_idx))
    return "-".join(parts)


def assign_codes(data: dict):
    """后处理：为已建好的 JSON 树中所有故障/部件/零件挂「编码」字段。

    建树阶段已按目录与文件行顺序保序，故此处直接 enumerate 即可确定性编号，
    与目录遍历顺序一致。新格式走 sub_systems，旧格式走扁平 components（子系统段填 000）。
    """
    ind_code = INDUSTRY_CODES.get(data.get("industry", ""), "XX")
    subs = data.get("sub_industries", [])
    if subs:
        for sub in subs:
            sub_code = SUB_INDUSTRY_CODES.get(sub.get("name", ""), "XX")
            for eq_idx, eq in enumerate(sub.get("equipment", []), 1):
                _assign_eq_codes(eq, ind_code, sub_code, eq_idx)
    else:
        for eq_idx, eq in enumerate(data.get("equipment", []), 1):
            _assign_eq_codes(eq, ind_code, None, eq_idx)


def _assign_eq_codes(eq: dict, ind_code, sub_code, eq_idx: int):
    """单个设备的编码生成。"""
    sub_systems = eq.get("sub_systems", [])
    if sub_systems:
        # 子设备顺序以 sub_equipment 元数据为准（= sub_equipment.md 行顺序）
        se_order = [s.get("name", "") for s in eq.get("sub_equipment", [])]
        se_to_idx = {n: i for i, n in enumerate(se_order, 1)} if se_order else {}
        ss_counter: dict = {}  # 每个子设备内子系统从 001 重新计数
        for ss in sub_systems:
            se_name = ss.get("sub_equipment", "")
            if se_to_idx:
                se_idx = se_to_idx.get(se_name)
                key = se_name
            else:
                se_idx = None
                key = "__none__"
            ss_idx = ss_counter.get(key, 0) + 1
            ss_counter[key] = ss_idx
            _assign_ss_codes(ss, ind_code, sub_code, eq_idx, se_idx, ss_idx)
    else:
        # 旧格式：无子系统/零件层（子系统段=000、零件段=000）；按 sub_equipment 字段分组编号子设备段
        se_order = [s.get("name", "") for s in eq.get("sub_equipment", [])]
        se_to_idx = {n: i for i, n in enumerate(se_order, 1)} if se_order else {}
        comp_counter: dict = {}  # 每个子设备内部件从 001 重新计数
        for comp in eq.get("components", []):
            se_name = comp.get("sub_equipment", "")
            if se_to_idx:
                se_idx = se_to_idx.get(se_name)
                key = se_name
            else:
                se_idx = None
                key = "__none__"
            comp_idx = comp_counter.get(key, 0) + 1
            comp_counter[key] = comp_idx
            comp["编码"] = build_code(ind_code, sub_code, eq_idx, se_idx, "000", comp_idx, "000")
            for f_idx, fault in enumerate(comp.get("faults", []), 1):
                fault["编码"] = build_code(ind_code, sub_code, eq_idx, se_idx, "000", comp_idx, "000", f_idx)


def _assign_ss_codes(ss: dict, ind_code, sub_code, eq_idx, se_idx, ss_idx):
    """单个子系统下部件/零件/故障的编码生成。"""
    for comp_idx, comp in enumerate(ss.get("components", []), 1):
        # 部件独立行（总成级失效）：零件段占位 000
        comp["编码"] = build_code(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, "000")
        for f_idx, fault in enumerate(comp.get("faults", []), 1):
            fault["编码"] = build_code(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, "000", f_idx)
        for part_idx, part in enumerate(comp.get("parts", []), 1):
            part["编码"] = build_code(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, part_idx)
            for f_idx, fault in enumerate(part.get("faults", []), 1):
                fault["编码"] = build_code(ind_code, sub_code, eq_idx, se_idx, ss_idx, comp_idx, part_idx, f_idx)


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
    assign_codes(data)  # 改造7：为故障/部件/零件挂编码
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
