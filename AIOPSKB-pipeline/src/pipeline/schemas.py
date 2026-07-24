D1_D9_REQUIRED = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
D1_D9_ALL = D1_D9_REQUIRED

SCHEMA = {
    "D1": {"name": "物理属性", "type": "multi-enum",
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
#
# 属性挂载规则（改造3）：
#   子系统层：仅名称+描述，无扩展属性
#   部件行（零件列="—"）：填写维护方法、报废方法
#   零件行（零件列≠"—"）：维护方法、报废方法填"—"（上挂到部件层）
COMPONENT_EXT_ATTRS = ["维护方法", "报废方法"]


def validate_fault_entry(entry: dict) -> list[str]:
    issues = []
    for d in D1_D9_REQUIRED:
        if d not in entry or not entry[d]:
            issues.append(f"{d}({SCHEMA[d]['name']}) 缺失")
    if "故障类别" not in entry or not entry["故障类别"]:
        issues.append("故障类别 缺失")
    return issues


# 故障类别 schema（改造5新增）
# 值来自 failure_categories.yaml 静态白名单，LLM 不得自由生成
FAULT_CATEGORY_SCHEMA = {
    "name": "故障类别",
    "type": "yaml-enum",
    "source": "failure_categories.yaml",
    "description": "公司监测平台故障分类标签，从静态YAML枚举中选择",
}

# 检维修5列 schema（改造6新增）—— 运维工作流补充维度 D11-D15
# 把知识库从"故障诊断字典"升级为"完整运维工作流手册"。
# 这5列是选填的（允许"—"），但填写内容时必须带置信标注，复用 D5 置信机制（标准值/经验值/待核实）。
# 用工/备件与 OEM 强相关，准确率天然低于诊断列，RAG 输出时应注明"参考值，需对照现场实际"。
# 安全注意事项、验收标准鼓励标"标准值"并引用标准号（如 DL/T 869、GB/T 12145）。
# 做成独立维度列（便于工单系统单独提取"用工需求"等），不塞进 D8。
# 编号续接 D1-D10：D11 用工需求 / D12 工机具 / D13 备件用料 / D14 安全注意事项 / D15 验收标准
MAINTENANCE_SCHEMA = {
    "D11": {"name": "用工需求", "type": "text", "required": False,
             "desc": "工种+人数+预计工时，如'钳工2名、管工1名；工时6-8h'"},
    "D12": {"name": "工机具", "type": "text", "required": False,
             "desc": "通用工具类目，如'扭力扳手、涡流探伤仪、堵管工具'"},
    "D13": {"name": "备件用料", "type": "text", "required": False,
             "desc": "备件/耗材通用名，具体型号现场补"},
    "D14": {"name": "安全注意事项", "type": "text", "required": False,
             "desc": "HSE/特种作业规程要求，有标准依据标'标准值'"},
    "D15": {"name": "验收标准", "type": "text", "required": False,
             "desc": "检验规范/量化验收指标，有标准依据标'标准值'"},
}

# D11-D15 短编号（内部 key、validate headers 用，与 D1-D10 一致）
FAULT_MAINTENANCE_KEYS = list(MAINTENANCE_SCHEMA.keys())  # ["D11","D12","D13","D14","D15"]
# D11-D15 完整列名（JSON/CSV 列名用，格式 D编号_中文名，与 D1_物理属性 一致）
FAULT_MAINTENANCE_COLS = [f"{k}_{v['name']}" for k, v in MAINTENANCE_SCHEMA.items()]
# ["D11_用工需求","D12_工机具","D13_备件用料","D14_安全注意事项","D15_验收标准"]
# D11-D15 中文名（表头显示用，与"物理属性"等一致）
FAULT_MAINTENANCE_NAMES = [v["name"] for v in MAINTENANCE_SCHEMA.values()]
