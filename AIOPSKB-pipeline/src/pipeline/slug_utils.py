"""
slug_utils.py — 共享路径映射工具

从 orchestrator.py 提取的行业/子行业/设备名 → 目录名映射。
供 orchestrator.py 和 ai_expert_review/loader.py 共同使用。
"""

# ── 行业 → 目录名 ──
INDUSTRY_SLUG_MAP = {
    "电力": "power",
    "石化": "petrochemical",
    "冶金": "metallurgy",
    "钢铁": "steel",
    "水泥": "cement",
    "煤炭": "coal",
    "轨道交通": "rail_transit",
    "制造业": "manufacturing",
    "航空航天与船舶": "aerospace_marine",
}

# ── 子行业 → 目录名 ──
SUB_SLUG_MAP = {
    "火电": "thermal",
    "水电": "hydro",
    "风电": "wind",
    "光伏": "pv",
    "核电": "nuclear",
    "燃气轮机": "gas_turbine",
    "抽水蓄能": "pumped_storage",
    "输电": "transmission",
    "变电": "substation",
    "配电": "distribution",
    "储能": "energy_storage",
}

# ── 设备 → 目录名（已有英文目录的映射，其余直接用中文名） ──
EQUIP_SLUG_MAP = {
    "锅炉": "boiler",
    "汽轮机": "steam_turbine",
    "发电机": "generator",
    "主变压器": "main_transformer",
    "水轮机": "hydro_turbine",
    "凝汽器": "condenser",
    "励磁系统": "excitation_system",
    "冷却塔/空冷岛": "cooling_tower",
    "箱式变压器（风电用）": "箱式变压器",
    "发电机出口断路器": "发电机出口断路器(GCB)",
}


def slug_industry(name: str) -> str:
    """行业名 → 目录名"""
    return INDUSTRY_SLUG_MAP.get(name, name)


def slug_sub(name: str) -> str:
    """子行业名 → 目录名"""
    return SUB_SLUG_MAP.get(name, name)


def slug_eq(name: str) -> str:
    """设备名 → 目录名。未映射的设备做基本字符替换。"""
    mapped = EQUIP_SLUG_MAP.get(name)
    if mapped:
        return mapped
    return name.replace("/", "_").replace("／", "_").replace("（", "(").replace("）", ")")
