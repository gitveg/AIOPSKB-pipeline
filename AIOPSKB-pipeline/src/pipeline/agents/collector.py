from agents.base import call_llm
from search import search_and_format

COLLECTOR_SYSTEM = """你是一个工业设备运维知识库的调研智能体。你的任务是通过联网搜索获取的信息，系统性地收集工业设备相关知识。

核心要求：
1. 所有信息必须基于搜索结果，不得凭空编造
2. 输出严格为Markdown表格，列名与要求完全一致
3. 表格前后不允许添加任何解释性文字、前言、总结
4. 内容精简、结构化，避免冗余论述
5. 不允许添加要求之外的额外列"""


# ── Name translation: static cache + LLM fallback ──

# Static cache for common names (avoids LLM call for known terms)
_NAME_CACHE = {
    # 子行业
    "火电": "thermal power", "水电": "hydropower", "风电": "wind power",
    "光伏": "solar PV", "核电": "nuclear power", "燃气轮机": "gas turbine power",
    "抽水蓄能": "pumped storage", "输电": "power transmission",
    "变电": "power substation", "配电": "power distribution",
    "储能": "energy storage",
    "石油炼制": "oil refining", "基础有机化工原料": "basic petrochemical feedstock",
    "合成树脂": "synthetic resin", "合成纤维": "synthetic fiber",
    "合成橡胶": "synthetic rubber", "化肥": "fertilizer",
    # 设备
    "锅炉": "power plant boiler", "汽轮机": "steam turbine", "发电机": "turbine generator",
    "主变压器": "power transformer", "凝汽器": "steam condenser",
    "励磁系统": "excitation system", "冷却塔": "cooling tower", "空冷岛": "air cooled condenser",
    "水轮机": "hydro turbine", "风力发电机组": "wind turbine generator",
    "反应堆压力容器": "reactor pressure vessel", "光伏组件": "PV module",
    "逆变器": "inverter", "燃气轮机": "gas turbine",
    "蒸汽发生器": "steam generator",
    # 常见部件（部分，其余由LLM翻译）
    "水冷壁": "water wall tube", "过热器": "superheater", "再热器": "reheater",
    "省煤器": "economizer", "汽包": "steam drum", "锅筒": "steam drum",
    "燃烧器": "burner", "空气预热器": "air preheater",
    "安全阀": "safety valve", "轴承": "bearing", "密封": "seal",
    "绕组": "winding", "铁芯": "iron core", "绝缘油": "insulating oil",
    "叶片": "turbine blade", "转子": "rotor", "定子": "stator",
}


def _translate_name(name: str) -> str:
    """Translate Chinese equipment/component name to English.
    Uses static cache first, falls back to Flash LLM with caching."""
    if not name:
        return ""

    # Exact match in cache
    if name in _NAME_CACHE:
        return _NAME_CACHE[name]

    # Substring match (e.g., "水冷壁管" matches "水冷壁")
    for cn, en in _NAME_CACHE.items():
        if cn in name:
            # Replace the matched part, keep the rest
            remaining = name.replace(cn, "").strip()
            if remaining:
                # Translate remaining part via LLM
                remaining_en = _llm_translate(remaining)
                result = f"{en} {remaining_en}".strip()
            else:
                result = en
            _NAME_CACHE[name] = result
            return result

    # No match — use LLM
    result = _llm_translate(name)
    _NAME_CACHE[name] = result
    return result


def _llm_translate(name: str) -> str:
    """Translate a Chinese industrial term to English using Flash model."""
    result = call_llm(
        "flash",
        "You translate Chinese industrial equipment/component names to standard English engineering terms. Output only the English term, nothing else.",
        f"Translate: {name}",
        temperature=0.0,
    )
    translated = result.strip().strip('"').strip("'").strip("`")
    return translated if translated else name


# ── Collection ──

def collect_layer(layer: str, context: dict) -> tuple[str, str]:
    queries = _build_queries(layer, context)
    search_text = search_and_format(queries)
    prompt = _build_prompt(layer, context, search_text)
    result = call_llm("collector", COLLECTOR_SYSTEM, prompt, temperature=0.4)
    return result, search_text


def _build_queries(layer: str, ctx: dict) -> list[str]:
    industry = ctx.get("industry", "")
    sub = ctx.get("sub_industry", "")
    equip = ctx.get("equipment", "")
    comp = ctx.get("component", "")

    sub_en = _translate_name(sub) if sub else ""
    equip_en = _translate_name(equip) if equip else ""
    comp_en = _translate_name(comp) if comp else ""

    if layer == "sub_industry":
        return [
            f"{industry} industry sub-sectors equipment classification",
            f"{industry} industrial equipment categories production processes",
            f"{industry} equipment types national standard",
        ]

    elif layer == "equipment":
        sub_cn = sub  # 子行业中文名
        return [
            f"{sub_en} main equipment list primary secondary auxiliary",
            f"{sub_en} auxiliary equipment BOP utility systems",
            f"{sub_en} equipment specification complete list",
            f"{sub_en} balance of plant systems overview",
            f"{sub_cn} 主要设备 设备清单 设备种类",
        ]

    elif layer == "sub_equipment":
        return [
            f"{equip_en} types classification specification",
            f"{equip_en} technical routes structural differences",
            f"{equip_en} model specifications comparison",
        ]

    elif layer == "component":
        equip_cn = ctx.get("equipment", "")
        sub_eq_cn = ctx.get("sub_equipment", "")
        sub_eq_en = _translate_name(sub_eq_cn) if sub_eq_cn else ""
        if sub_eq_cn:
            target_en = f"{sub_eq_en} {equip_en}"
            target_cn = f"{sub_eq_cn}"
            return [
                f"{target_en} component breakdown parts list maintenance manual",
                f"{target_en} consumable parts wear items replacement interval",
                f"{target_en} structure assembly sub-components technical diagram",
                f"{target_cn} 结构组成 部件 技术手册",
            ]
        else:
            return [
                f"{equip_en} component breakdown parts list maintenance manual",
                f"{equip_en} consumable parts wear items replacement interval",
                f"{equip_en} structure assembly sub-components technical diagram",
                f"{equip_cn} 结构组成 部件 技术手册",
            ]

    elif layer == "fault":
        sub_eq_cn = ctx.get("sub_equipment", "")
        sub_eq_en = _translate_name(sub_eq_cn) if sub_eq_cn else ""
        if sub_eq_cn:
            target_en = f"{sub_eq_en} {equip_en} {comp_en}".strip()
            target_cn = f"{sub_eq_cn}"
        elif sub_en:
            target_en = f"{sub_en} {equip_en} {comp_en}".strip()
            target_cn = ""
        else:
            target_en = f"{equip_en} {comp_en}"
            target_cn = ""
        equip_cn = ctx.get("equipment", "")
        comp_cn = ctx.get("component", "")
        search_cn = f"{sub_eq_cn}{equip_cn}{comp_cn}" if sub_eq_cn else f"{equip_cn}{comp_cn}"
        return [
            f"{target_en} common failure modes fault types characteristics",
            f"{target_en} fault diagnosis monitoring parameters vibration temperature",
            f"{target_en} fault diagnosis standard inspection criteria",
            f"{target_en} repair methods preventive maintenance overhaul",
            f"{search_cn} 常见故障 检修方法",
            f"{search_cn} 故障诊断 DL GB 标准",
            f"{equip_en} condition monitoring threshold acceptance criteria standard",
            f"{search_cn} 预防性试验规程 限值 DL GB IEC ISO",
            f"industrial equipment standard threshold values {equip_en}",
        ]

    return []


def _build_prompt(layer: str, ctx: dict, search_text: str) -> str:
    industry = ctx.get("industry", "")
    sub = ctx.get("sub_industry", "")
    equip = ctx.get("equipment", "")
    comp = ctx.get("component", "")
    existing = ctx.get("existing", "")

    if layer == "sub_industry":
        return f"""请对【{industry}】行业进行系统调研，确定子行业/领域划分。

判断该行业是否需要子行业划分。如果该行业设备类型集中、无明显细分领域，可以建议不分子行业。

{search_text}

要求：
1. 子行业/领域划分必须符合该行业实际生产组织方式
2. 每个子行业给出一句简练的功能描述
3. 如果建议不分子行业，请说明理由
4. 输出严格为Markdown表格，两列
5. 表格前后不允许添加任何解释性文字
6. 不允许添加额外列
7. 每条信息末尾用括号注明来源，如：（来源：DL/T 5186）

输出格式（严格两列）：
| 子行业名称 | 描述 |"""

    elif layer == "equipment":
        existing_note = f"\n\n当前已有设备清单（请在已有基础上补充，标明新增条目）：\n{existing}" if existing else ""
        return f"""请对【{industry} - {sub}】的设备种类进行系统调研。

{search_text}

要求：
1. 覆盖主设备、辅助设备和公用系统(BOP)
2. 每台设备标注类型：主设备/辅助设备/公用系统
3. 包含设备功能描述
4. 设备边界明确，不重叠
5. 尽可能全面，宁多勿漏
6. 输出严格为Markdown表格，三列
7. 表格前后不允许添加任何解释性文字
8. 不允许添加"关键参数""所属子系统"等额外列
9. 每条信息末尾用括号注明来源，如：（来源：DL/T 5186）{existing_note}

输出格式（严格三列）：
| 设备名称 | 设备类型 | 描述 |"""

    elif layer == "sub_equipment":
        existing_note = f"\n\n当前已有子设备清单（请在已有基础上补充）：\n{existing}" if existing else ""
        return f"""请对【{equip}】的子设备/技术路线进行拆分调研。

该设备是一个大类，包含多种不同的技术路线或类型，需要进一步细分。

{search_text}

要求：
1. 列出该设备下的所有子设备/技术路线类型
2. 每个子设备给出一句简练描述，说明其技术特点
3. 子设备之间边界清晰，不重叠
4. 输出严格为Markdown表格，两列
5. 表格前后不允许添加任何解释性文字{existing_note}

输出格式（严格两列）：
| 子设备名称 | 描述 |"""

    elif layer == "component":
        existing_note = f"\n\n当前已有部件清单（请在已有基础上补充）：\n{existing}" if existing else ""
        sub_eq = ctx.get("sub_equipment", "")
        if sub_eq:
            comp_title = f"请对【{sub_eq}（{equip}的子设备）】进行部件拆解调研。"
        else:
            comp_title = f"请对【{equip}】进行部件拆解调研。"
        return f"""{comp_title}

{search_text}

要求：
1. 部件拆解1-3层，根据设备复杂度决定
2. 必须包含易损件（轴承、密封、绝缘件、滤网等）
3. 每个部件提供功能描述
4. 粒度适合故障诊断（不过粗也不过细）
5. 输出严格为Markdown表格，六列
6. 表格前后不允许添加任何解释性文字
7. 父部件列用"—"表示顶级部件
8. 易损标识取值为"是"或"否"
9. 维护方法：叶节点部件填写日常保养规程（巡检周期、维护操作要点），非叶节点填"—"
10. 报废方法：叶节点部件填写不可修复时的判定条件、拆除步骤、处置注意事项，非叶节点填"—"
11. 每条信息末尾用括号注明来源，如：（来源：DL/T 5186）{existing_note}

输出格式（严格六列）：
| 部件名称 | 父部件 | 描述 | 易损标识 | 维护方法 | 报废方法 |"""

    elif layer == "fault":
        existing_note = f"\n\n当前已有故障条目（请在已有基础上补充，不重复）：\n{existing}" if existing else ""
        # 上一轮 Judge 发现的致命/严重问题，要求本轮直接修正
        critical_note = ""
        critical_issues = ctx.get("critical_issues", [])
        if critical_issues:
            issues_text = "\n".join([
                f"   - [{c.get('severity', '')}][{c.get('dimension', '')}] {c.get('fault_name', '')}：{c.get('issue', '')}"
                for c in critical_issues
            ])
            critical_note = f"\n\n⚠ 上一轮审查发现以下致命/严重问题，本轮生成时必须修正（直接覆盖对应故障行）：\n{issues_text}"
        # 构建带上下文的标题
        sub_equip = ctx.get("sub_equipment", "")
        sub = ctx.get("sub_industry", "")
        if sub_equip:
            title = f"请对【{sub} - {sub_equip} - {comp}】进行故障知识调研。"
        elif sub:
            title = f"请对【{sub} - {equip} - {comp}】进行故障知识调研。"
        else:
            title = f"请对【{equip} - {comp}】进行故障知识调研。"
        # 父部件约束（如果有子部件）
        children = ctx.get("children", [])
        parent_note = ""
        if children:
            parent_note = f"\n12. 该部件包含子部件（{'、'.join(children)}），请聚焦于该部件整体层面的故障模式（整体退化、系统级失效、多子部件耦合故障），避免与单一子部件故障重复"
        # Build pre-filtered standard reference hint for D5
        from config import D5_STANDARD_REFERENCE, select_relevant_domains
        relevant_domains = select_relevant_domains(comp, equip, search_text)
        std_hint_lines = []
        for domain in relevant_domains:
            info = D5_STANDARD_REFERENCE[domain]
            std_list = "、".join(std[0] for std in info["standards"])
            std_hint_lines.append(f"  {domain} → {std_list}")
        std_hint = "\n".join(std_hint_lines)

        return f"""{title}

{search_text}

D5参数置信标注参考——以下标准速查表供判断"标准值"时参考（按参数类型查找，非按设备）：
{std_hint}

要求：
1. 按以下失效层级系统化枚举故障（参考IEC 60812 FMEA框架），每个层级若有真实故障则列出，无则跳过：
   ① 功能失效（设备/部件无法完成预期功能）
   ② 性能退化（功能可完成但参数偏移出允许范围）
   ③ 物理损伤（材料层面的磨损、腐蚀、疲劳、变形）
   ④ 结构失效（机械结构层面的断裂、松动、泄漏）
   ⑤ 接口失效（与其他设备/介质的连接异常）
   ⑥ 老化/劣化（长期运行导致的渐进性退化）
   注意：不为凑数而强制每个层级都产出故障，少而准优于多而泛
2. D4故障征兆必须列出可观测现象
3. D5特征参数（每条参数必须遵守）：
   每条D5参数必须以"置信：标准值""置信：经验值""置信：待核实"三者之一结尾，不允许遗漏。

   参数完整格式：{{类型标签}}{{参数名}}{{阈值}}（适用：{{工况条件}}，置信：{{置信等级}}）

   置信标注规则（每条参数末尾必须加，必须包含"置信："二字）：
   - 能确认来自具体标准：（标准号-年份 条款，置信：标准值），如（ISO 10816-3:2009 表1，置信：标准值）
   - 行业通用经验但无标准可引用：（置信：经验值）
   - 参数数值存疑（不同文献/资料数值矛盾，无法判断哪个正确）：（置信：待核实）
   标注优先级：尽量标"标准值"或"经验值"，避免依赖"待核实"。
   待核实仅用于一种情况：同一参数的阈值在多个来源中数值矛盾，无法确定哪个准确。
   不确定来源不是待核实的理由——找不到标准号就标经验值。
   每文件待核实占比超过10%视为不合格。
   标准号必须带年份：GB/T 7595-2017 而非 GB/T 7595；DL/T 722-2014 而非 DL/T 722

   禁止在不确定时伪造标准号。不确定来源就标"置信：经验值"（而非待核实）。不确定数值就标"置信：待核实"并注明矛盾的来源。
   正确示例：[物理]振动速度>7.1mm/s（适用：轴中心高≥315mm，刚性安装；ISO 10816-3:2009 表1 B/C级，置信：标准值）
   正确示例：[化学]油中水分>100ppm（置信：经验值）
   正确示例：[物理]磨损深度>0.2mm（某文献主张0.2mm，另一文献主张0.5mm，置信：待核实）
   错误示例：[状态量]密封面磨损深度>0.4mm（置信：待核实）——来源不确定但不是数值矛盾，应标经验值
   错误示例：[物理]振动速度>7.1mm/s（完全不加标注）
   错误示例：[物理]振动速度>7.1mm/s（经验值）（缺少"置信："前缀）
   错误示例：振动加速度传感器（这是监测手段，应填D6）
   错误示例：强行列出5条参数（其中2条是同一类别的重复或无意义的拼凑）
   错误示例：振动速度>7.1mm/s（未标注适用工况，不同轴高/安装方式下阈值完全不同）
4. D6监测手段标注类型标签[在线][离线][带电]。注意：D6填写的是传感器/检测方法，不是参数阈值。正确示例：[在线]振动加速度传感器；错误示例：振动速度>7.1mm/s（应填D5）
5. D7诊断方法必须采用鉴别诊断逻辑（而非简单确认逻辑）。必须回答"出现这些症状时，如何区分本故障与相似故障"，而非仅仅列出确认条件。格式要求：
   ① 先列出关键判据（基于D5参数阈值或D4征兆的组合判断）
   ② 然后给出至少一个鉴别要点：与哪个相似故障如何区分，或排除其他故障的依据
   正确示例：DGA分析H2升高时：H2+CH4同时升高→局部过热（非放电）；H2+C2H2出现→高能放电；仅H2升高→检查进水或受潮（与放电鉴别）
   错误示例：通过DGA分析气体组分，若H2>150μL/L判定为绝缘故障（仅确认，未鉴别）
   若无真实易混淆故障，允许写"无明显易混淆项"，但不得为凑数而编造
6. D8检修方法需包含根本处理和临时处理，含具体步骤和所需工具。格式如下：
   [规程级]根本处理：xxx；临时处理：xxx
   或：
   [经验级]根本处理：xxx；临时处理：xxx
   级别标签规则：
   - [规程级]：操作步骤来自国家/行业强制标准或厂商正式检修规程（如DL/T 869、GB/T 12243检修工艺导则），必须标注
   - [经验级]：操作步骤来自行业通用惯例或现场经验，无强制规程依据
   若无临时处理方案，填写"临时处理：无，须立即停机处理"
7. D10易混淆故障：列出与本故障症状相似、容易混淆的其他故障名称，并简述区分要点。格式：易混淆故障名：区分要点。若确实无易混淆故障，填"—"。禁止为凑数编造，少而准优于多而泛
8. 输出严格为Markdown表格，11列（含故障名称+D1-D9+D10）
9. 表格前后不允许添加任何解释性文字、前言、总结
10. 不允许使用###标题、列表等非表格格式
11. 不允许添加"故障代码"等额外列{parent_note}{existing_note}{critical_note}

输出格式（严格11列，第一列必须是"故障名称"，最后一列为D10）：
| 故障名称 | D1 故障类别 | D2 故障等级 | D3 故障描述与机理 | D4 故障征兆 | D5 故障特征参数 | D6 监测与检测手段 | D7 诊断方法 | D8 检修方法 | D9 预防措施 | D10 易混淆故障 |

D1取值：机械/电气/绝缘/热/化学/控制/环境（可多选，用;分隔；选择最直接的失效机制，仅当确实无法单一归类时才多选）
D2取值及判定标准：
- 危急：须立即停机，继续运行有人身安全风险或设备失效风险
- 严重：应在72小时内安排处理，设备功能显著降级
- 一般：可在下次计划检修前处理，设备功能轻微降级
- 轻微：可在本检修周期内跟踪观察，不影响正常运行
"""
    return ""
