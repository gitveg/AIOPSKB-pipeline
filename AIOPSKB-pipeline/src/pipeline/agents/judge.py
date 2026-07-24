import json
import re
from agents.base import call_llm

JUDGE_SYSTEM = """你是一个工业设备知识库的审查专家。你需要审查数据的完整性和准确性。

你必须以JSON格式返回审查结果。不要在JSON前后添加其他文字。"""


def judge_layer(agent_key: str, layer: str, context: dict, data: str) -> dict:
    prompt = _build_judge_prompt(layer, context, data)
    raw = call_llm(agent_key, JUDGE_SYSTEM, prompt, temperature=0.2)
    return _parse_judge_response(raw)


def judge_single(layer: str, context: dict, data: str) -> dict:
    """单Judge审查，使用DeepSeek V4"""
    return judge_layer("judge_b", layer, context, data)


def _build_judge_prompt(layer: str, ctx: dict, data: str) -> str:
    industry = ctx.get("industry", "")
    sub = ctx.get("sub_industry", "")
    equip = ctx.get("equipment", "")
    comp = ctx.get("component", "")
    sub_system = ctx.get("sub_system", "")

    if layer == "sub_industry":
        target = f"{industry}行业 - 子行业划分"
        item_type = "子行业/领域"
    elif layer == "equipment":
        target = f"{industry}-{sub} - 设备枚举"
        item_type = "设备种类"
    elif layer == "sub_equipment":
        target = f"{equip} - 子设备拆分"
        item_type = "子设备/技术路线"
    elif layer == "sub_system":
        target = f"{equip} - 子系统拆分"
        item_type = "子系统"
    elif layer == "component":
        if sub_system:
            target = f"{equip} - {sub_system} - 部件+零件拆解"
        else:
            target = f"{equip} - 部件拆解"
        item_type = "部件"
    elif layer == "fault":
        target = f"{equip}-{comp} - 故障知识"
        item_type = "故障"
    else:
        target = layer
        item_type = "条目"

    if layer == "fault":
        return f"""知识库Schema约束（审查时必须校验）：
- D1 物理属性：机械/电气/绝缘/热/化学/控制/环境（多选用;分隔，优先单选）
- 故障类别：必须从注入的枚举白名单中选择，禁止LLM自创不在枚举中的故障类别值
- D2 故障等级：危急(须立即停机)/严重(72h内处理)/一般(下次计划检修)/轻微(跟踪观察)
- D5 填写特征参数+阈值（如[物理]振动速度>7.1mm/s），不是传感器名称
- D6 填写监测手段+传感器（如[在线]振动加速度传感器），不是参数阈值
- D8 格式：根本处理：xxx；临时处理：xxx（无临时处理时填"须立即停机处理"）
- D10 易混淆故障：填写症状相似的故障名+区分要点，无则填"—"
- 检维修5列（改造6新增，D11-D15）：D11用工需求/D12工机具/D13备件用料/D14安全注意事项/D15验收标准。每列内容末尾必须标注置信级别（标准值/经验值/待核实）。D14安全注意事项、D15验收标准鼓励标"标准值"并带标准号；D11用工/D12工机具/D13备件通常标"经验值"（OEM强相关，准确率天然低于诊断列）

审查对象：{target}
审查数据：
{data}

审查标准：
1. 故障类型全面性：是否遗漏常见故障？
1a. 故障类别合规性：故障类别值是否全部来自注入的枚举白名单？是否存在LLM自创的故障类别值？若有则列为严重问题
2. 故障征兆实用性(D4)：是否对应现场可观测信号？
3. 特征参数准确性(D5)：阈值是否合理？
4. 诊断逻辑正确性(D7)：是否采用鉴别诊断逻辑？是否回答了"与相似故障如何区分"而非仅仅确认？
5. 检修方法实用性(D8)：是否可在现场执行？是否涵盖根本处理和临时处理？
6. D5/D6区分正确性：D5是否填写的是特征参数（含阈值），D6是否填写的是监测手段（含传感器类型），是否存在信息反向填写？
7. D2等级判定合理性：故障等级是否与Schema定义的判定标准一致？
8. D3因果关系完整性：故障描述是否包含现象+根本原因+诱发条件？
9. D9预防措施可操作性：预防措施是否具体可执行，而非泛泛描述？
10. D10易混淆故障有效性：列出的易混淆故障是否确实容易与本故障混淆？区分要点是否在工程上成立？是否存在填"—"但实际有明显易混淆故障的情况？

以下为对抗性审查——请以一位有25年工龄的挑剔资深工程师视角，主动质疑以下内容，而非礼貌地认可：
11. D5工况适用性：该阈值是否适用于{equip}的实际工况（压力/温度/材质）？同一参数在不同压力等级下差异极大，是否存在工况错配？D5中标注了"适用："条件的参数，其适用条件是否准确合理？
12. D5置信分布：是否所有D5参数都标注了置信级别？标注为"标准值"的参数标准号是否带年份？统计"待核实"占全部D5子参数的比例：≤10%正常不扣分，10%-20%扣1分并在suggestions中指出待核实集中区域，>20%则研究不充分、verdict直接返回revision_needed。零待核实是正常的——说明搜索研究充分，不是可疑信号。
13. D7鉴别诊断充分性：D7是否包含鉴别逻辑（而非仅确认逻辑）？是否明确回答了"与哪个相似故障如何区分"？鉴别要点是否在工程上成立？
14. D8操作安全性：检修步骤是否有安全隐患（如未先泄压就操作、需要特种资质的工序未标注）？操作顺序是否合理？
15. D8规程级标注真实性：标注为[规程级]的检修步骤，是否确实存在对应的强制标准或厂商检修规程？标注为[经验级]的是否真的缺乏规程依据？
16. D5假冒标准值核查：标注为"标准值"的参数，其引用的标准号是否真实存在？是否存在编造的标准号？是否存在标准号正确但阈值数值与该标准实际规定不一致的情况？此类问题按"严重"级别处理，列入critical_issues。
17. 检维修5列（D11-D15）完整性：D11用工需求是否含工种+人数+工时？D12工机具是否通用且必要（非冗余罗列）？D13备件用料是否用通用名（具体型号应注明"现场补"）？D15验收标准是否量化、可检验？D14安全注意事项是否与该故障检修操作匹配？
18. D14安全注意事项充分性：是否包含HSE/特种作业要求（停机隔离、泄压放水、通风含氧量、防爆照明、高处作业、动火/受限空间作业资质等）？是否遗漏了关键安全风险？
19. D15验收标准可操作性：验收指标是否量化（如水压试验保压时间+压力值、参数恢复至设计值±范围）？是否引用了检验标准（如DL/T 869、GB/T 12145）？
20. 检维修置信标注合规性：D11-D15每条内容是否都标注了置信级别？标注为"标准值"的D14/D15引用的标准号是否真实存在（防伪造）？不确定来源是否标"经验值"而非伪造标准号？
21. D2严重度分布均衡性：本部件所有故障的D2等级分布是否合理？若同一等级占比≥80%且这些故障的实际危害程度确有差异（如滤尘网堵塞、密封圈磨损等本应多属"一般"的故障被全标"严重"），判为偏置问题（severity=严重），要求按实际危害重新分级——危害差异大的故障应分散到不同等级，禁止偷懒全部标同一级。若该部件故障客观上确多属同一严重度（如叶片、高速轴等关键承载部件故障多为严重），则不判偏置。

重要规则：对抗审查（第11-21项）中发现的问题，按以下标准分级：
- "致命"：可能导致人身伤亡或设备重大损毁的错误（如D8操作顺序颠倒导致爆炸风险、D5阈值严重错配导致危急故障漏报）
- "严重"：技术逻辑错误但不直接危及安全（如D7诊断条件不充分、D5参数与工况明显不符、检维修5列伪造标准号、D14安全注意事项遗漏关键风险）
若发现"致命"或"严重"问题，必须列入 critical_issues 字段；若无此类问题，critical_issues 返回空数组，不要强行找问题。

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"verdict": "pass或revision_needed", "score": 评分1-10, "missing_items": ["缺失的故障类型"], "critical_issues": [{{"dimension": "D5/D7/D8/D14/D15", "fault_name": "故障名称", "issue": "具体问题描述", "severity": "致命/严重"}}], "issues": ["一般性格式或完整性问题"], "suggestions": ["建议"]}}"""

    # 子设备专项审查（改造4：子设备划分保障机制）
    if layer == "sub_equipment":
        return f"""审查对象：{target}
审查数据：
{data}

审查标准：
1. 维度单一性：是否只按"技术路线/型式变体"切分？有无混入功能模块（把"齿轮箱""偏航系统"等功能单元当子设备 = 严重问题）或容量等级/用途维度？互斥性自检：任意两个子设备不应可能同时存在于同一台设备上
2. MECE：主流技术路线是否互斥且穷尽？有无遗漏重要的技术分支？
3. 存量裁剪合理性（重点）：是否过度细分了小众/试验性/未规模化商用/已淘汰的机型？市场份额极低的机型是否应剔除或合并而非单列？清单中是否存在冗余或几乎无现场存量的子设备？【既不冗余、又覆盖主流】是核心判据
4. 主流覆盖：是否覆盖该设备的主流型式（现场存量 95%+）？有无漏掉主流技术路线
5. 子系统≠子设备：子设备是技术路线变体（如双馈/直驱），不得混入功能分解维度（如传动/发电）
6. 命名一致性：命名规范、口径统一（含括号缩写如 DFIG/PMSG 的一致性），不与上层设备同名

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"verdict": "pass或revision_needed", "score": 评分1-10, "missing_items": ["遗漏的主流技术路线"], "classification_issues": ["过度细分/维度混用/小众未裁剪等裁剪与分类问题"], "issues": ["其他问题"], "suggestions": ["建议"]}}"""

    # 子系统专项审查
    if layer == "sub_system":
        return f"""审查对象：{target}
审查数据：
{data}

审查标准：
1. 覆盖全面性：该设备/子设备的全部主要功能子系统是否覆盖（传动/发电/控制/液压/润滑/冷却/安全等）？
2. 分类合理性：子系统之间边界是否清晰？功能是否不重叠？
3. 子系统≠子设备：子系统中不得混入技术路线分类（如"双馈型""直驱型"），子系统是功能分解维度
4. 粒度适当性：通常3-8个子系统为宜，不可过粗（仅2个）或过细（超过10个）
5. 描述质量：每个子系统描述是否在50-100字，是否说明了功能范围和覆盖边界
6. 实际验证：是否符合真实工业环境中的设备功能分解？

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"verdict": "pass或revision_needed", "score": 评分1-10, "missing_items": ["具体缺失的子系统"], "classification_issues": ["重合/粒度/边界问题"], "issues": ["其他问题"], "suggestions": ["建议"]}}"""

    # 部件+零件审查（新格式含sub_system上下文时增强）
    if layer == "component" and sub_system:
        claimed_parts = ctx.get("claimed_parts", [])
        claimed_note = ""
        if claimed_parts:
            claimed_str = "、".join(claimed_parts[:30])
            claimed_note = f"""
13. 跨子系统MECE合规：以下部件/零件已被其他子系统认领，若本数据中包含这些名称则判为严重问题（severity=严重）：
   {claimed_str}"""

        return f"""审查对象：{target}
审查数据：
{data}

审查标准：
1. 覆盖全面性：该子系统的主要功能部件是否覆盖（机械+电气+控制+密封等）？
2. 分类合理性：部件之间边界是否清晰？是否存在表述重合或边界模糊？
3. 粒度适当性：部件和零件的粒度是否一致？同一子系统下的部件拆解深度是否统一？
4. 边界清晰性：部件/零件与上层（子系统、设备）不得同名
5. 实际验证：是否符合真实工业环境？
6. 命名规范性：部件和零件名称采用标准工程术语，不得与上层同名
7. 层级语义正确性：部件是可独立更换/检修的总成（如齿轮箱），零件是更细粒度的可拆卸件（如行星齿轮），不可串层
8. 粒度一致性：同一子系统下的所有部件拆解深度一致（不能"齿轮箱+行星齿轮"并列在同一列）
9. 拆解充分性：含明显易损件（轴承、密封、绝缘件等）的组件是否拆到了零件级？是否拆到了可维护项级别？
10. 功能完备性：该子系统的全部主要功能是否由部件集合覆盖？
11. 故障独立性：叶节点（部件或零件）的故障模式是否能清晰区分，不存在重叠？
12. 属性挂载正确性：维护方法和报废方法仅在零件列="—"的部件行填写，零件行这两列必须为"—"
14. 命名安全合规：部件名/零件名禁止包含斜杠"/"等路径分隔符（否则判severity=严重，要求改为单一干净名称，如"防冲导流板"而非"防冲/导流板"）{claimed_note}

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"verdict": "pass或revision_needed", "score": 评分1-10, "missing_items": ["具体缺失项"], "classification_issues": ["重合/粒度/边界/层级语义问题"], "issues": ["其他问题"], "suggestions": ["建议"]}}"""

    # 通用非故障层审查（旧格式 component 及其他非故障层）
    return f"""审查对象：{target}
审查数据：
{data}

审查标准：
1. 覆盖全面性：是否遗漏了重要的{item_type}？
2. 分类合理性：是否存在表述重合、边界模糊？是否需要更细拆分或合并？
3. 粒度适当性：{item_type}粒度是否一致？
4. 边界清晰性：有无重叠？
5. 实际验证：是否符合真实工业环境？

请严格以JSON格式返回（不要加markdown代码块标记）：
{{"verdict": "pass或revision_needed", "score": 评分1-10, "missing_items": ["具体缺失项"], "classification_issues": ["重合/粒度问题"], "issues": ["其他问题"], "suggestions": ["建议"]}}"""


def _parse_judge_response(raw: str) -> dict:
    cleaned = re.sub(r'```json\s*', '', raw)
    cleaned = re.sub(r'```\s*', '', cleaned)
    cleaned = cleaned.strip()
    try:
        result = json.loads(cleaned)
        if "score" not in result:
            result["score"] = 5
        if "verdict" not in result:
            result["verdict"] = "revision_needed"
        if "critical_issues" not in result:
            result["critical_issues"] = []
        return result
    except json.JSONDecodeError:
        score_match = re.search(r'[\'"]?score[\'"]?\s*[:=]\s*(\d+)', raw)
        score = int(score_match.group(1)) if score_match else 5
        return {"verdict": "revision_needed", "score": score, "raw_response": raw,
                "issues": ["Judge返回非JSON格式"], "missing_items": [], "critical_issues": [], "suggestions": []}
