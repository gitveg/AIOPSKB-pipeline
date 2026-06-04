D1_D9_REQUIRED = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
D1_D9_ALL = D1_D9_REQUIRED

SCHEMA = {
    "D1": {"name": "故障类别", "type": "multi-enum",
            "options": ["机械", "电气", "绝缘", "热", "化学", "控制", "环境"]},
    "D2": {"name": "故障等级", "type": "enum",
            "options": ["轻微", "一般", "严重", "危急"]},
    "D3": {"name": "故障描述与机理", "type": "text"},
    "D4": {"name": "故障征兆", "type": "array"},
    "D5": {"name": "故障特征参数", "type": "array"},
    "D6": {"name": "监测与检测手段", "type": "array"},
    "D7": {"name": "诊断方法", "type": "text"},
    "D8": {"name": "检修方法", "type": "text"},
    "D9": {"name": "预防措施", "type": "array"},
}

# Component-level attributes (beyond name/parent/description/is_consumable)
COMPONENT_EXT_ATTRS = ["维护方法", "报废方法"]


def validate_fault_entry(entry: dict) -> list[str]:
    issues = []
    for d in D1_D9_REQUIRED:
        if d not in entry or not entry[d]:
            issues.append(f"{d}({SCHEMA[d]['name']}) 缺失")
    return issues
