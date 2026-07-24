"""
loader.py — 评审数据加载器

根据 --industry / --sub / --equip 参数解析数据目录路径，
读取对应 markdown 表格并转化为结构化 Python 对象。

仅支持 v3.0 新格式（structure 层需要 sub_system.md）。
"""

import os
import re
import sys

# 让 loader 能 import pipeline 模块
_LOADER_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE_DIR = os.path.join(_LOADER_DIR, os.pardir, "pipeline")
_PIPELINE_DIR = os.path.normpath(_PIPELINE_DIR)
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

from slug_utils import slug_industry, slug_sub, slug_eq
from config import DATA_DIR


# ── 路径解析 ──

def resolve_review_target(layer, industry, sub, equip=None):
    """将 CLI 参数解析为数据目录路径和上下文信息。

    Args:
        layer: equipment / sub_equipment / structure
        industry: 行业名（如 "电力"）
        sub: 子行业名（如 "火电"）
        equip: 设备名（如 "凝汽器"），sub_equipment/structure 层必填

    Returns:
        (base_dir, context_dict)
        base_dir: 数据目录的绝对路径
        context_dict: 评审上下文（行业、子行业、设备名等）

    Raises:
        FileNotFoundError: 目录不存在
        ValueError: structure 层检测到旧格式
    """
    industry_slug = slug_industry(industry)
    sub_slug = slug_sub(sub)

    context = {
        "industry": industry,
        "sub_industry": sub,
        "equipment": equip,
    }

    if layer == "equipment":
        # equipment 层：目标目录是子行业目录
        base_dir = os.path.join(DATA_DIR, industry_slug, sub_slug)
    else:
        # sub_equipment / structure 层：目标目录是设备目录
        if not equip:
            raise ValueError(f"--equip 参数在 {layer} 层评审中为必填")
        equip_slug = slug_eq(equip)
        base_dir = os.path.join(DATA_DIR, industry_slug, sub_slug, equip_slug)
        # fallback：无子设备的独立设备（如水泥回转窑），结构在设备级一层目录
        if not os.path.isdir(base_dir):
            _fb = os.path.join(DATA_DIR, industry_slug, sub_slug)
            if os.path.isdir(_fb) and os.path.exists(os.path.join(_fb, "sub_system.md")):
                base_dir = _fb

    if not os.path.isdir(base_dir):
        raise FileNotFoundError(f"数据目录不存在: {base_dir}")

    # structure 层检查 v3.0 格式
    if layer == "structure":
        sub_system_path = os.path.join(base_dir, "sub_system.md")
        if not os.path.exists(sub_system_path):
            raise ValueError(
                f"该设备使用旧格式（无 sub_system.md），结构评审仅支持 v3.0 格式。\n"
                f"目录: {base_dir}\n"
                f"请先完成该设备的 v3.0 目录结构改造。"
            )

    return base_dir, context


# ── Markdown 表格解析工具 ──

def _parse_md_table(filepath, expected_cols=None):
    """通用 markdown 表格解析器。

    Args:
        filepath: markdown 文件路径
        expected_cols: 期望列数（用于校验），None 表示不校验

    Returns:
        (headers, rows) - headers: 列名列表, rows: 每行为 cell 值列表
    """
    if not os.path.exists(filepath):
        return None, []

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        return None, []

    headers = []
    rows = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        # 跳过分隔行 (|---|---|)
        if re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        cells = [c.strip("*").strip() for c in line.split("|")[1:-1]]
        if not cells:
            continue

        # 第一行非分隔行是表头
        if not headers:
            headers = cells
            continue

        # 数据行
        if expected_cols and len(cells) != expected_cols:
            # 列数不符，跳过但继续
            continue
        rows.append(cells)

    return headers, rows


# ── 各层数据加载 ──

def load_equipment_registry(sub_dir):
    """加载设备清单。

    Args:
        sub_dir: 子行业目录（含 equipment_registry.md）

    Returns:
        list[dict]: [{"name": ..., "type": ..., "desc": ...}]

    Raises:
        FileNotFoundError: equipment_registry.md 不存在
        ValueError: 表为空
    """
    path = os.path.join(sub_dir, "equipment_registry.md")
    if not os.path.exists(path):
        raise FileNotFoundError(f"设备清单不存在: {path}")

    headers, rows = _parse_md_table(path, expected_cols=3)
    if headers is None:
        raise ValueError(f"数据表为空或格式错误: {path}")
    if not rows:
        raise ValueError(f"数据表为空（无数据行）: {path}")

    return [
        {"name": r[0], "type": r[1] if len(r) > 1 else "", "desc": r[2] if len(r) > 2 else ""}
        for r in rows
    ]


def load_sub_equipment(equip_dir):
    """加载子设备清单。

    Args:
        equip_dir: 设备目录（含 sub_equipment.md）

    Returns:
        list[dict]: [{"name": ..., "desc": ...}]
        文件不存在时返回空列表（不是所有设备都有子设备）
    """
    path = os.path.join(equip_dir, "sub_equipment.md")
    if not os.path.exists(path):
        return []

    headers, rows = _parse_md_table(path, expected_cols=2)
    if not rows:
        return []

    return [{"name": r[0], "desc": r[1] if len(r) > 1 else ""} for r in rows]


def load_sub_systems(base_dir):
    """加载子系统清单（v3.0 格式）。

    Args:
        base_dir: 设备目录（含 sub_system.md）

    Returns:
        list[dict]: [{"name": ..., "desc": ...}]

    Raises:
        ValueError: sub_system.md 不存在（旧格式）
    """
    path = os.path.join(base_dir, "sub_system.md")
    if not os.path.exists(path):
        raise ValueError(
            f"sub_system.md 不存在，该设备使用旧格式，结构评审仅支持 v3.0。\n路径: {base_dir}"
        )

    headers, rows = _parse_md_table(path, expected_cols=2)
    if not rows:
        raise ValueError(f"子系统清单为空: {path}")

    return [{"name": r[0], "desc": r[1] if len(r) > 1 else ""} for r in rows]


def load_components(subsystem_dir):
    """加载单个子系统下的部件+零件表（v3.0 格式）。

    复用 orchestrator._parse_new_components 的解析逻辑。

    Args:
        subsystem_dir: 子系统目录

    Returns:
        dict: {comp_name: {"desc", "consumable", "maint", "disposal", "parts": [part_info]}}
        其中 parts 列表的每个元素为 {"name": ..., "desc": ..., "consumable": ...}
    """
    path = os.path.join(subsystem_dir, "components.md")
    if not os.path.exists(path):
        return {}

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        return {}

    components = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r'^\|[\s\-:|]+\|$', line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 6:
            continue
        comp_name = cells[0].strip("*").strip()
        part_name = cells[1].strip()
        if comp_name in ("部件", ""):
            continue
        desc = cells[2] if len(cells) > 2 else ""
        consumable = cells[3] if len(cells) > 3 else "否"
        maint = cells[4] if len(cells) > 4 else "—"
        disposal = cells[5] if len(cells) > 5 else "—"

        if comp_name not in components:
            components[comp_name] = {
                "desc": "", "consumable": "否",
                "maint": "—", "disposal": "—",
                "parts": [],
            }

        if part_name in ("—", "-", ""):
            # 部件独立行
            components[comp_name]["desc"] = desc
            components[comp_name]["consumable"] = consumable
            components[comp_name]["maint"] = maint
            components[comp_name]["disposal"] = disposal
        else:
            # 零件行
            components[comp_name]["parts"].append({
                "name": part_name,
                "desc": desc,
                "consumable": consumable,
            })

    return components


def load_structure_tree(base_dir, focus=None):
    """加载完整结构树（子系统 → 部件 → 零件）。

    Args:
        base_dir: 设备目录（含 sub_system.md 和子系统子目录）
        focus: "all" / "subsystem" / "component" / "part" 聚焦模式

    Returns:
        dict: {"subsystems": [{name, desc, components: {...}}]}
    """
    focus = focus or "all"
    sub_systems = load_sub_systems(base_dir)

    tree = {"subsystems": []}
    for ss in sub_systems:
        ss_name = ss["name"]
        ss_entry = {"name": ss_name, "desc": ss["desc"], "components": {}}

        if focus in ("all", "component", "part"):
            ss_dir = os.path.join(base_dir, ss_name)
            if os.path.isdir(ss_dir):
                comps = load_components(ss_dir)
                if focus == "part":
                    # 只保留零件信息，去掉部件级的维护/报废
                    comps_filtered = {}
                    for cname, cdata in comps.items():
                        if cdata["parts"]:
                            comps_filtered[cname] = {
                                "desc": cdata["desc"],
                                "parts": cdata["parts"],
                            }
                    ss_entry["components"] = comps_filtered
                else:
                    ss_entry["components"] = comps

        tree["subsystems"].append(ss_entry)

    return tree


def load_layer_data(layer, base_dir, focus=None):
    """按层级分发数据加载。

    Args:
        layer: equipment / sub_equipment / structure
        base_dir: resolve_review_target 返回的目录路径
        focus: structure 层的聚焦模式

    Returns:
        按 layer 返回对应结构化数据
    """
    if layer == "equipment":
        return {"items": load_equipment_registry(base_dir)}
    elif layer == "sub_equipment":
        return {"items": load_sub_equipment(base_dir)}
    elif layer == "structure":
        return load_structure_tree(base_dir, focus=focus)
    else:
        raise ValueError(f"未知层级: {layer}")
