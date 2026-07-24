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
    # Phase 3 结构生成（sub_system/component）用 DeepSeek(structure)，其余层用 GLM(collector)
    agent = "structure" if layer in ("sub_system", "component") else "collector"
    result = call_llm(agent, COLLECTOR_SYSTEM, prompt, temperature=0.4)
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

    elif layer == "sub_system":
        sub_eq_cn = ctx.get("sub_equipment", "")
        sub_eq_en = _translate_name(sub_eq_cn) if sub_eq_cn else ""
        if sub_eq_cn:
            target_en = f"{sub_eq_en} {equip_en}".strip()
            target_cn = f"{sub_eq_cn}"
        else:
            target_en = equip_en
            target_cn = equip
        return [
            f"{target_en} functional decomposition subsystems block diagram",
            f"{target_en} subsystem structure ISO 14224 equipment breakdown",
            f"{target_en} main functional modules system architecture",
            f"{target_cn} 功能分解 子系统 结构",
            f"{target_cn} 设备组成 系统划分 技术手册",
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
2. 每台设备标注属性：主设备/辅助设备/公用系统
3. 包含设备功能描述
4. 设备边界明确，不重叠
5. 尽可能全面，宁多勿漏
6. 输出严格为Markdown表格，三列
7. 表格前后不允许添加任何解释性文字
8. 不允许添加"关键参数""所属子系统"等额外列
9. 每条信息末尾用括号注明来源，如：（来源：DL/T 5186）{existing_note}

输出格式（严格三列）：
| 设备类型名称 | 设备属性 | 描述 |"""

    elif layer == "sub_equipment":
        existing_note = f"\n\n当前已有子设备清单（请在已有基础上补充）：\n{existing}" if existing else ""
        return f"""请对【{equip}】的子设备/技术路线进行拆分调研。

该设备是一个大类，包含多种不同的技术路线或类型，需要进一步细分。

{search_text}

划分原则（严格执行）：
1. 单一维度：只按"技术路线/型式变体"切分，严禁混入功能模块（如齿轮箱、偏航系统——它们属于子系统层）或容量等级/用途维度
2. MECE：主流技术路线互斥且穷尽，合并起来覆盖该设备的主要型式
3. 按存量与可维护性裁剪（核心）：只列出覆盖该设备 95%+ 现场存量的**主流**技术路线；**市场份额极低、未规模化商用、试验性、已淘汰**的机型**不单列**（直接剔除，不列入正式库）。判断标准：现场存量占比、是否规模化商用、运维知识能否独立成体系
4. 数量克制：通常 2-4 个主流子设备即可，宁缺毋滥，不为凑数而罗列小众机型

锚点示例（仅列已实际验证的设备，供判断粒度参考；未验证的设备不列，避免把不确定的答案当标准误导）：
- 风电机组主流 = 双馈(DFIG)/直驱(PMSG)/半直驱（中速永磁）；高速永磁/液压传动/电励磁直驱(EESG)/无刷双馈/鼠笼异步(SCIG)等为小众或已淘汰，不列

其他要求：
1. 每个子设备给出一句简练描述，说明其技术特点与适用场景
2. 子设备之间边界清晰，不重叠
3. 子设备名称不得与上层设备同名
4. 输出严格为Markdown表格，两列
5. 表格前后不允许添加任何解释性文字{existing_note}

输出格式（严格两列）：
| 子设备名称 | 描述 |"""

    elif layer == "sub_system":
        sub_eq = ctx.get("sub_equipment", "")
        if sub_eq:
            ss_title = f"请对【{sub_eq}（{equip}的子设备）】进行功能子系统拆分。"
        else:
            ss_title = f"请对【{equip}】进行功能子系统拆分。"
        return f"""{ss_title}

{search_text}

要求：
1. 按功能独立性划分子系统，每个子系统完成一个相对独立的功能
2. 子系统是对设备的功能性分解（如传动系统、发电系统、控制系统），不是技术路线分类
3. 子系统≠子设备：子设备是技术路线变体（如双馈/直驱），子系统是功能模块（如传动/发电/偏航）
4. 各子系统功能边界互斥、不重叠，避免不同子系统出现职能交叉导致部件归属歧义
5. 粒度适中：通常3-8个子系统，覆盖设备全部功能
6. 参考ISO 14224设备分解结构
7. 每个子系统描述50-100字，说明功能范围和覆盖边界
8. 输出严格为Markdown表格，两列
9. 表格前后不允许添加任何解释性文字

输出格式（严格两列）：
| 子系统名称 | 描述 |"""

    elif layer == "component":
        existing_note = f"\n\n当前已有部件清单（请在已有基础上补充）：\n{existing}" if existing else ""
        sub_eq = ctx.get("sub_equipment", "")
        sub_system = ctx.get("sub_system", "")
        sub_system_desc = ctx.get("sub_system_desc", "")

        if sub_eq:
            comp_title = f"请对【{sub_eq}（{equip}的子设备）】的【{sub_system}】子系统进行部件+零件拆解。"
        else:
            comp_title = f"请对【{equip}】的【{sub_system}】子系统进行部件+零件拆解。"
        ss_note = f"\n子系统简介：{sub_system_desc}" if sub_system_desc else ""

        # MECE 去重：兄弟上下文注入
        claimed_parts = ctx.get("claimed_parts", [])
        all_sub_systems = ctx.get("all_sub_systems", [])
        mece_note = ""
        if all_sub_systems:
            ss_list = "\n".join(f"  - {name}：{desc[:50]}" for name, desc in all_sub_systems)
            mece_note += f"\n\n⚠ 跨子系统MECE约束（严格执行）："
            mece_note += f"\n本设备的全部子系统及功能边界如下：\n{ss_list}"
            mece_note += f"\n归属规则：部件/零件归属「主要服务功能」所在的子系统。横跨多个功能子系统的物理件（如管板、密封垫）只在其主功能owner子系统出现一次，禁止重复列出。"
        if claimed_parts:
            claimed_str = "、".join(claimed_parts[:30])
            mece_note += f"\n\n以下部件/零件已被其他子系统认领，**禁止在本子系统中重复列出**：{claimed_str}"

        return f"""{comp_title}
{ss_note}

{search_text}
{mece_note}

要求：
1. 拆解为两层：部件（Component，可独立更换/检修的总成）和零件（Part，更细粒度的可拆卸件）
2. 固定两层，不允许自由嵌套更多层级
3. "零件"列填"—"表示该部件无需进一步拆解为零件（短链允许，不强求拆到零件级）
4. 不可为凑满三行而编造不存在的零件——真实结构到哪层就到哪层
5. 每个部件必须有且仅有一行零件列="—"的行，用于填写该部件的整体描述、维护方法和报废方法
6. 若该部件包含可独立发生故障的零件，则额外为每个零件各写一行
7. 易损标识：零件行基于零件本身是否易损；部件行（零件=—）基于部件整体
8. 维护方法、报废方法：仅在零件列="—"的部件行填写（维护/报废是总成级动作，上挂到部件层），零件行填"—"
9. 必须包含易损件（轴承、密封、绝缘件、滤网等）
10. 部件描述30-60字（说明总成功能、结构特点），零件描述15-30字（点明材质、位置、作用）
11. 粒度适合故障诊断（部件级对应总成失效，零件级对应具体失效）
12. 参考ISO 14224设备分解结构
13. 输出严格为Markdown表格，六列
14. 表格前后不允许添加任何解释性文字
15. 来源必须标到可追溯粒度：标准号（如DL/T 5000）、手册/文献名称或明确条目，禁止只写裸数字（如"（来源：7）"无效）
16. 部件名、零件名禁止包含斜杠"/"——每个部件/零件是独立单元，用单一干净名称。如一个物理件有多个别名取最通用者（写"防冲导流板"而非"防冲/导流板"，"膨胀节"而非"膨胀节/补偿器"）；若是两个独立零件则分两行各自列出（不合并、不混写）{existing_note}
17. 部件/零件判定（三是否）：某件须同时满足"可独立拆卸+可独立故障+可独立更换/检修"才记录。不可独立拆（拆了母件报废，如轴承外圈/内圈/滚动体/保持架、绕组单匝、齿轮单齿）**禁止出现**。
18. 轴承归属：大型独立轴承（主轴承/偏航轴承/变桨轴承）作为**部件**（零件列填"—"短链，不拆外圈/内圈）；嵌入式小轴承（齿轮箱轴承/电机轴承/泵轴承）作为**零件**挂在所属部件下。
19. 命名规范：部件名**禁止带"总成"后缀**（写"主轴"非"主轴总成"、"齿轮箱"非"齿轮箱总成"）；**禁止"XX本体"作零件**（部件自身在部件行描述）；零件粒度止于可独立拆换件，禁止过度细化。

输出格式（严格六列）：
| 部件 | 零件 | 描述 | 易损标识 | 维护方法 | 报废方法 |"""

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
            parent_note = f"\n14. 该部件包含子部件（{'、'.join(children)}），请聚焦于该部件整体层面的故障模式（整体退化、系统级失效、多子部件耦合故障），避免与单一子部件故障重复"
        # Build pre-filtered standard reference hint for D5
        from config import D5_STANDARD_REFERENCE, select_relevant_domains, select_failure_categories
        relevant_domains = select_relevant_domains(comp, equip, search_text)
        std_hint_lines = []
        for domain in relevant_domains:
            info = D5_STANDARD_REFERENCE[domain]
            std_list = "、".join(std[0] for std in info["standards"])
            std_hint_lines.append(f"  {domain} → {std_list}")
        std_hint = "\n".join(std_hint_lines)

        # Build fault category enum hint (改造5)
        fault_cats, cat_group = select_failure_categories(comp, equip, search_text)
        cat_enum = "、".join(fault_cats)

        # 行业感知锚点（v3.1 根本治理：石化等非电力行业避免火电标准/工况词污染）
        industry = ctx.get("industry", "")
        if industry == "石化":
            industry_anchor = (
                "\n⚠ 石化行业专属要求（必须遵守，违反将导致整批返工）：\n"
                "- 标准优先级：石化/通用标准 > 火电标准。可用——API 610(离心泵)/API 682(机械密封)/GB/T 3215(离心泵技术条件)/GB 30871(化学品特殊作业安全)/SH/T 3501(石化焊接)/GB 150(压力容器)/ISO 10816-20816(振动)/ISO 1940(动平衡)\n"
                "- 禁用火电/电力标准（这些仅适用电站设备，出现在石化故障即为错误）：DL/T 869、DL/T 596、DL/T 722、DL/T 501、DL/T 438、GB/T 12145、GB/T 7595、GB/T 7596\n"
                "- 介质：石化工艺物料（腐蚀性/易挥发/有毒/高温/含固），D3/D4/D5 须用石化介质特征描述；禁用火电工况词：给水、锅炉、除氧器、凝结水、循环水、炉水、汽轮机驱动\n"
                "- D14 安全：严格执行 GB 30871 特殊作业（动火/受限空间/临时用电/盲板抽堵作业票）、LOTO 断电挂牌、泄压排空置换、防爆（禁非防爆工具/敲击火花）、防化服/防毒面具/护目镜\n"
            )
            d8_std = "SH/T 3501、GB 30871"
            d14_std = "GB 30871-2022"
            d15_std = "SH/T 3501、GB/T 3215"
        elif industry == "钢铁":
            industry_anchor = (
                "\n⚠ 钢铁行业专属要求（必须遵守，违反将导致整批返工）：\n"
                "- 标准优先级：通用工业标准 + 钢铁行业标准 > 火电标准 > 石化专用标准。可用——ISO 9908/GB/T 5656(离心泵技术条件)、ISO 10816/20816(旋转机械振动)、GB/T 11348(转轴振动)、ISO 1940(动平衡)；轧钢/冶炼设备用 YB/T 系列、GB 50431(高炉)、GB 50478(转炉)、GB 50579(连铸)\n"
                "- 禁用火电标准（仅适用电站设备，出现在钢铁故障即为错误）：DL/T 869、DL/T 596、DL/T 722、DL/T 501、DL/T 438、GB/T 12145、GB/T 7595、GB/T 7596\n"
                "- 禁用石化专用标准：API 610/682（石化工艺泵）、GB/T 3215（石油石化离心泵，等同API610）、SH/T 3501（石化焊接）、GB 30871（化学品特殊作业专项，钢铁水/油系统不套用其化学品专项）\n"
                "- 介质/工况：钢铁工况——冷却循环水、液压系统油液、除鳞高压水、消防/除尘供水、含尘烟气、高温氧化铁皮、轧制乳化液。D3/D4/D5 须用钢铁介质特征；禁用火电工况词（给水、锅炉、除氧器、凝结水、炉水、汽轮机驱动）和石化工况词（易燃易爆、有毒、腐蚀性工艺物料）\n"
                "- D14 安全：LOOTO 断电挂牌、泄压排液置换、动火/高处/临时用电作业票；起重作业按 GB 6067；不套用石化 GB 30871 化学品特殊作业专项\n"
            )
            d8_std = "ISO 9908、YB/T 系列"
            d14_std = "GB 6067.1、GB 30871(动火/临时用电通用要求)"
            d15_std = "ISO 9908、ISO 10816"
        elif industry == "水泥":
            industry_anchor = (
                "\n⚠ 水泥行业专属要求（必须遵守，违反将导致整批返工）：\n"
                "- 标准优先级：水泥行业标准 + 通用工业标准 > 火电标准 > 石化/钢铁专用标准。可用——JC/T 733(回转窑)、GB/T 26583(水泥回转窑)、JC/T 磨机系列(立磨/球磨/辊压机)、JC/T 333(管磨机)、GB/T 25738(水泥工业大气污染物)、ISO 10816/20816(旋转机械振动)、GB/T 11348(转轴振动)、ISO 1940(动平衡)\n"
                "- 禁用火电标准（仅适用电站设备，出现在水泥故障即为错误）：DL/T 869、DL/T 596、DL/T 722、DL/T 501、DL/T 438、GB/T 12145、GB/T 7595、GB/T 7596\n"
                "- 禁用石化专用标准：API 610/682（石化工艺泵）、GB/T 3215（石油石化离心泵，等同API610）、SH/T 3501（石化焊接）、GB 30871（化学品特殊作业专项，水泥非化学品工艺不套用其化学品专项）\n"
                "- 禁用钢铁专用标准：YB/T 系列、GB 50431(高炉)、GB 50478(转炉)、GB 50579(连铸)\n"
                "- 介质/工况：水泥工况——两磨一烧连续流程（生料磨→回转窑烧成→水泥磨），介质为生料/熟料/水泥粉（磨蚀性/含尘/高温）、高温烟气/窑尾废气（含CO/NOx/SOx）、磨机振动/篦冷/选粉。D3/D4/D5 须用水泥介质特征描述；禁用火电工况词（给水、锅炉、除氧器、凝结水、循环水、炉水、汽轮机驱动）、石化工况词（易燃易爆、有毒、腐蚀性工艺物料）和钢铁工况词（冷却循环水、除鳞高压水、轧制乳化液、高温氧化铁皮）\n"
                "- D14 安全：高温作业防烫伤/防辐射（窑体/熟料区）、水泥粉尘防护（防尘口罩/防尘服，长期吸入致尘肺）、动火/高处/临时用电作业票、LOTO 断电挂牌、有限空间作业（窑内/料仓检修，置换通风防CO中毒）、回转窑检修防筒体转动/塌陷；不套用石化 GB 30871 化学品特殊作业专项\n"
            )
            d8_std = "JC/T 系列、GB/T 26583"
            d14_std = "GB 30871(动火/临时用电通用要求)、GB/T 33000"
            d15_std = "JC/T 733、ISO 10816"
        else:
            industry_anchor = ""
            d8_std = "DL/T 869、GB/T 12243"
            d14_std = "DL/T 869-2012"
            d15_std = "DL/T 869-2012、GB/T 12145"

        return f"""{title}

{search_text}
{industry_anchor}
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
   ⚠️每条参数恰好一个置信标注，严禁重复：禁止出现"（置信：经验值）；置信：标准值"等同一条参数标两次置信的情况。整条参数（含适用工况括号内）只能出现一个"置信："。

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
   错误示例：[物理]振动速度>4.5mm/s（适用：机舱驱动端（置信：经验值）；置信：标准值，参考ISO 10816-3:2009）——重复标注（同一条参数出现两个"置信："），必须删除适用工况括号内的置信，只保留末尾一个
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
   - [规程级]：操作步骤来自国家/行业强制标准或厂商正式检修规程（如{d8_std}检修工艺导则），必须标注
   - [经验级]：操作步骤来自行业通用惯例或现场经验，无强制规程依据
   若无临时处理方案，填写"临时处理：无，须立即停机处理"
7. D10易混淆故障：列出与本故障症状相似、容易混淆的其他故障名称，并简述区分要点。格式：易混淆故障名：区分要点。若确实无易混淆故障，填"—"。禁止为凑数编造，少而准优于多而泛
8. 检维修5列定义（改造6新增，编号D11-D15，续接D1-D10）：
   - D11 用工需求：工种+人数+预计工时（如"钳工2名、管工1名；工时6-8h"），标"置信：经验值"作为参考
   - D12 工机具：通用工具类目（如"扭力扳手、涡流探伤仪、堵管工具"），标"置信：经验值"
   - D13 备件用料：备件/耗材通用名（如"冷凝管备件、堵头、密封胶"），标"置信：经验值"，具体型号现场补
   - D14 安全注意事项：HSE/特种作业规程要求，有标准依据标"置信：标准值"并引用（如{d14_std}），否则标"置信：经验值"
   - D15 验收标准：检验规范/量化验收指标，有标准依据标"置信：标准值"并引用（如{d15_std}），否则标"置信：经验值"
9. 检维修5列（D11-D15）置信标注：每列内容末尾必须标注置信级别（标准值/经验值/待核实），复用D5置信标注机制。
   D14 安全注意事项、D15 验收标准鼓励标"标准值"并带标准号。禁止伪造标准号——不确定来源就标"经验值"，不确定数值就标"待核实"。
10. 输出严格为Markdown表格，17列（含故障名称+故障类别+D1-D15）
11. 表格前后不允许添加任何解释性文字、前言、总结
12. 不允许使用###标题、列表等非表格格式
13. 不允许添加"故障代码"等额外列{parent_note}{existing_note}{critical_note}
14. 故障跨层归属：失效能定位到具体零件（太阳轮断齿、齿圈点蚀、轴承磨损）→ 属**零件级**，挂零件上；无法定位到单一零件的整体性/综合性失效（整体振动、油质劣化、接口泄漏、多点耦合退化）→ 属**部件级**，挂部件上。
15. 部件级故障边界：部件级故障**只描述**零件级无法表达的整体性失效（整体性能/振动/温度、油路油质、接口连接、多点耦合）。**禁止**在部件级登记可定位到具体零件的失效（"齿面剥落""太阳轮断齿""轴承磨损"应属零件级）。因果链只挂根因：零件失效导致的部件现象（太阳轮磨损→齿轮箱振动），只登记零件故障，振动作为该故障的D4征兆，不单独成部件故障。

输出格式（严格17列，第一列"故障名称"，第二列"故障类别"，第三列"D1物理属性"，第12列D10，第13-17列D11-D15检维修）：
| 故障名称 | 故障类别 | D1 物理属性 | D2 故障等级 | D3 故障描述与机理 | D4 故障征兆 | D5 故障特征参数 | D6 监测与检测手段 | D7 诊断方法 | D8 检修方法 | D9 预防措施 | D10 易混淆故障 | D11 用工需求 | D12 工机具 | D13 备件用料 | D14 安全注意事项 | D15 验收标准 |

D1物理属性取值（强制枚举，只允许以下7个值，禁止自创）：
机械、电气、绝缘、热、化学、控制、环境
- 可多选，用全角"；"分隔（如"机械；电气"），仅当确实跨多个物理类别时才多选，否则单值
- D1 填"故障所属的物理属性类别"，不是失效机理，也不是子系统/介质类别
- 禁止把失效机理填入D1：疲劳/磨损/老化/变形/腐蚀/断裂/泄漏/松动/振动 等属机理或现象，归D3，不得出现在D1
- 禁止把子系统类别或介质当D1：液压/润滑/密封/结构/流体→归"机械"；电子/电磁→归"电气"；生物→归"环境"；"物理"过泛，按D3机理重判到具体枚举
- 选择最直接的物理属性：密封泄漏→机械；绝缘击穿→绝缘；过热烧损→热；电化学腐蚀→化学
- 正确示例：机械、绝缘、机械；热、环境；化学
- 错误示例：机械；老化（老化是机理）、液压（非枚举，应机械）、结构（应机械）、疲劳（机理）、物理（过泛）

单元格格式约束（防止17列错位）：
- 每条故障占且仅占一个物理行（一行=一条故障），单元格内禁止换行
- 单元格内禁止使用竖线"|"（含转义"\\|"）和HTML标签"<br>"；单元格内并列项用全角"；"或顿号"、"分隔
- 多条D5参数、D6手段在单元格内用全角"；"串联，不换行、不分行
故障类别取值（必须从以下枚举中选择，禁止自创）：{cat_enum}
（当前部件「{comp}」匹配的故障类别分组为「{cat_group}」，如不适用可从其他分组选取，但禁止自创新类别）
"其他"为兜底类：仅当所有分组枚举确实无法精确描述失效模式时才用，且应极少使用；凡能用具体失效模式（磨损/断裂/泄漏/松动/腐蚀/绝缘老化/电腐蚀…）描述的，一律禁止用"其他"偷懒。
故障类别可多选（限1-3个），多值必须用全角"；"分隔（禁止半角";"、禁止逗号/换行），每个子项都必须是合法枚举值（含"其他"）。
D2取值及判定标准：
- 危急：须立即停机，继续运行有人身安全风险或设备失效风险
- 严重：应在72小时内安排处理，设备功能显著降级
- 一般：可在下次计划检修前处理，设备功能轻微降级
- 轻微：可在本检修周期内跟踪观察，不影响正常运行
"""
    return ""
